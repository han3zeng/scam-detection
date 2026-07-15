"""Text embeddings via Vertex AI (gemini-embedding-001).

google-genai is imported lazily inside methods so that unit tests (which
inject a fake embedder) never pay the import cost — same convention as
app/model.py.

Auth: Application Default Credentials (the Cloud Run service account in
production, `gcloud auth application-default login` locally). No API key.
"""

import math

from app.config import Settings


class EmbeddingClient:
    def __init__(self, settings: Settings):
        self._project = settings.gcp_project
        self._location = settings.vertex_location
        self._model = settings.embedding_model
        self._dimensions = settings.embedding_dimensions
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=True, project=self._project, location=self._location
            )
        return self._client

    async def embed(self, text: str, task_type: str) -> list[float]:
        """
        Embed one text. task_type: RETRIEVAL_QUERY (serving) or RETRIEVAL_DOCUMENT (ingest).
        - stored corpus text uses RETRIEVAL_DOCUMENT;
        - the user's search text uses RETRIEVAL_QUERY.
        """
        from google.genai.types import EmbedContentConfig

        client = self._get_client()
        response = await client.aio.models.embed_content(
            model=self._model,
            contents=text,
            config=EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=self._dimensions,
            ),
        )
        return _l2_normalize(response.embeddings[0].values)


def _l2_normalize(vector: list[float]) -> list[float]:
    # Vectors truncated below the model's native dimensionality (MRL) are not
    # unit-length; cosine distance in Firestore expects normalized vectors.
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]
