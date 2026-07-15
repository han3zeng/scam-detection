"""Ingest the labeled emotion corpus into Firestore for vector search.

Downloads Johnson8187/Chinese_Multi-Emotion_Dialogue_Dataset (MIT license, same
author as the classifier model), embeds each sentence with Vertex AI, and
upserts into the Firestore collection used by /v1/emotion/explain.

The dataset uses exactly the model's 8-label taxonomy (verified 2026-07);
rows with any other label are skipped defensively and reported.

Idempotent: document IDs are derived from the text hash, so re-running
overwrites rather than duplicates.

Usage:
    python scripts/ingest_corpus.py <gcp_project> [--database "(default)"]
        [--collection emotion_examples] [--location us-central1] [--dry-run]

Auth: Application Default Credentials (gcloud auth application-default login).
The Firestore vector index must exist first — see docs/gcp-setup.md.
"""

import argparse
import asyncio
import csv
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

# Set the root for the process for app.etc importing
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ignore the “module import not at top of file” warning for this line.
# For Ruff
from app.config import Settings  # noqa: E402 
from app.embeddings import EmbeddingClient  # noqa: E402
from app.model import LABELS  # noqa: E402

DATASET_REPO = "Johnson8187/Chinese_Multi-Emotion_Dialogue_Dataset"
MAX_TEXT_CHARS = 512
EMBED_CONCURRENCY = 8
EMBED_RETRIES = 5



"""
each row unit:
{
    "text": "我今天真的很開心",
    "label": "喜悅",
    "label_en": "joy",
}
"""
def load_rows() -> list[dict]:
    """Download the dataset CSV and return cleaned {text, label, label_en} rows."""
    from huggingface_hub import hf_hub_download, list_repo_files

    csv_files = [
        f for f in list_repo_files(DATASET_REPO, repo_type="dataset") if f.endswith(".csv")
    ]
    if not csv_files:
        raise SystemExit(f"no CSV file found in dataset repo {DATASET_REPO}")
    # The repo actually only has 1 csv file
    # path: a local cached file path
    path = hf_hub_download(DATASET_REPO, csv_files[0], repo_type="dataset")

    zh_to_en = dict(LABELS)
    # accepted records
    rows: list[dict] = []
    # sentences have appeared
    seen: set[str] = set()
    # invalid rows
    dropped = 0
    with open(path, newline="", encoding="utf-8") as f:
        # DictReader: Converse csv format to dictionary format in code
        for record in csv.DictReader(f):
            text = (record.get("text") or "").strip()
            label = (record.get("emotion") or "").strip()
            if not text or len(text) > MAX_TEXT_CHARS or label not in zh_to_en:
                dropped += 1
                continue
            if text in seen:
                continue
            seen.add(text)
            rows.append({"text": text, "label": label, "label_en": zh_to_en[label]})
    print(f"loaded {len(rows)} rows (skipped {dropped} invalid/unknown-label rows)")
    return rows

"""
from {
    "text": "我很開心",
    "label": "喜悅",
    "label_en": "joy",
}
to {
    "text": "我很開心",
    "label": "喜悅",
    "label_en": "joy",
    "embedding": [0.12, -0.08, 0.44, ...],
}
"""
async def embed_rows(rows: list[dict], settings: Settings) -> None:
    """Attach an 'embedding' vector to each row, in place."""
    embedder = EmbeddingClient(settings)
    # Limits the number of concurrent tasks accessing a shared resource.
    # The number is 8 here, at most we send 9 requests to Vertex AI
    semaphore = asyncio.Semaphore(EMBED_CONCURRENCY)
    # number of embeddings have completed successfully
    done = 0

    async def embed_one(row: dict) -> None:
        nonlocal done
        # limits the number of coroutines executing inside the semaphore block to 8
        async with semaphore:
            for attempt in range(EMBED_RETRIES):
                try:
                    row["embedding"] = await embedder.embed(row["text"], "RETRIEVAL_DOCUMENT")
                    break
                except Exception:
                    if attempt == EMBED_RETRIES - 1:
                        raise
                    await asyncio.sleep(2**attempt)
            done += 1
            if done % 200 == 0:
                print(f"embedded {done}/{len(rows)}")

    # *(embed_one(row) for row in rows): Creates or schedules one coroutine for every row. So with 10,000 rows, there are conceptually 10,000 embed_one() coroutine tasks.
    # asyncio.gather(): runs multiple tasks at the same time
    await asyncio.gather(*(embed_one(row) for row in rows))


def write_rows(rows: list[dict], settings: Settings) -> None:
    from google.cloud import firestore
    # The class is a native Firestore data type that explicitly wraps an array of floating-point numbers
    # to store vector embeddings for AI and semantic search
    from google.cloud.firestore_v1.vector import Vector

    client = firestore.Client(project=settings.gcp_project, database=settings.firestore_database)
    collection = client.collection(settings.examples_collection)
    ingested_at = datetime.now(UTC).isoformat()
    writer = client.bulk_writer()
    for row in rows:
        # If the doc_id has been used the new record will overwrite the old one

        # Store model meta embedding_model and embedding_dimension for future change of model
        # We generally don't mix indexing data from different model together
        doc_id = hashlib.sha256(row["text"].encode("utf-8")).hexdigest()[:24]
        writer.set(
            collection.document(doc_id),
            {
                "text": row["text"],
                "label": row["label"],
                "label_en": row["label_en"],
                "embedding": Vector(row["embedding"]),
                "embedding_model": settings.embedding_model,
                "embedding_dimensions": settings.embedding_dimensions,
                "source": DATASET_REPO,
                "ingested_at": ingested_at,
            },
        )
    writer.close()
    print(f"upserted {len(rows)} documents into '{settings.examples_collection}'")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="GCP project ID")
    parser.add_argument("--database", default="(default)")
    parser.add_argument("--collection", default="emotion_examples")
    parser.add_argument("--location", default="us-central1")
    parser.add_argument(
        "--dry-run", action="store_true", help="parse and report only; no embedding or writes"
    )
    args = parser.parse_args()

    settings = Settings(
        preload_model=False,
        gcp_project=args.project,
        vertex_location=args.location,
        firestore_database=args.database,
        examples_collection=args.collection,
    )

    rows = load_rows()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["label"]] = counts.get(row["label"], 0) + 1
    print("label distribution:", counts)
    if args.dry_run:
        return
    # Create a new event loop to handle multiple embedding process in parallel
    # Block the rest of the code
    asyncio.run(embed_rows(rows, settings))
    write_rows(rows, settings)


if __name__ == "__main__":
    main()
