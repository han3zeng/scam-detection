"""KNN retrieval of labeled emotion examples from Firestore vector search.

google-cloud-firestore is imported lazily so unit tests (which inject a fake
retriever) never pay the import cost. Requires the composite vector index
documented in docs/gcp-setup.md.
"""

from app.config import Settings


class ExampleRetriever:
    def __init__(self, settings: Settings):
        self._project = settings.gcp_project
        self._database = settings.firestore_database
        self._collection = settings.examples_collection
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.AsyncClient(project=self._project, database=self._database)
        return self._client

    async def find_similar(self, vector: list[float], k: int) -> list[dict]:
        """Return the k nearest labeled examples as {text, label, label_en, similarity}."""
        from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
        from google.cloud.firestore_v1.vector import Vector

        client = self._get_client()
        query = client.collection(self._collection).find_nearest(
            vector_field="embedding",
            query_vector=Vector(vector),
            distance_measure=DistanceMeasure.COSINE,
            limit=k,
            distance_result_field="distance",
        )
        results = []
        async for doc in query.stream():
            data = doc.to_dict()
            results.append(
                {
                    "text": data["text"],
                    "label": data["label"],
                    "label_en": data["label_en"],
                    # COSINE distance is 1 - cosine similarity.
                    "similarity": round(1 - data["distance"], 4),
                }
            )
        return results

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
