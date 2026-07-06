"""Download a pinned model snapshot for baking into the Docker image.

Usage: python scripts/download_model.py <target_dir> <repo_id> <revision>
"""

import sys

from huggingface_hub import snapshot_download


def main() -> None:
    target_dir, repo_id, revision = sys.argv[1], sys.argv[2], sys.argv[3]
    snapshot_download(
        repo_id=repo_id,
        revision=revision,
        local_dir=target_dir,
        # Only what inference needs; training_args.bin etc. stay out of the image.
        allow_patterns=[
            "config.json",
            "model.safetensors",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "added_tokens.json",
            "spm.model",
        ],
    )
    print(f"downloaded {repo_id}@{revision} to {target_dir}")


if __name__ == "__main__":
    main()
