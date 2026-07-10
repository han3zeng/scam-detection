"""Wrapper around the Chinese-Emotion-Small text-classification model.

torch/transformers are imported lazily inside load() so that unit tests (which
inject a fake classifier) never pay the import cost.
"""

# The model's config.json only has generic LABEL_0..7; this mapping comes from
# the model card (https://huggingface.co/Johnson8187/Chinese-Emotion-Small).
LABELS: list[tuple[str, str]] = [
    ("平淡語氣", "neutral"),
    ("關切語調", "concerned"),
    ("開心語調", "happy"),
    ("憤怒語調", "angry"),
    ("悲傷語調", "sad"),
    ("疑問語調", "questioning"),
    ("驚奇語調", "surprised"),
    ("厭惡語調", "disgusted"),
]


class EmotionClassifier:
    def __init__(
        self,
        model_name: str,
        revision: str,
        model_dir: str | None = None,
        max_tokens: int = 512,
    ):
        self._model_name = model_name
        self._revision = revision
        self._model_dir = model_dir
        self._max_tokens = max_tokens
        self._tokenizer = None
        self._model = None

    def load(self) -> None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        # In Dockerfile, then we should have the downloaded file -> nonone model_dir.

        # In local env, then we only have model name, AutoModelForSequenceClassification.from_pretrained load model from hugging face directly.
        source = self._model_dir or self._model_name
        # A local dir is already a snapshot of the pinned revision.
        kwargs = {} if self._model_dir else {"revision": self._revision}
        self._tokenizer = AutoTokenizer.from_pretrained(source, **kwargs)
        model = AutoModelForSequenceClassification.from_pretrained(source, **kwargs)
        model.eval()
        self._model = model

    def predict(self, text: str, top_k: int) -> list[dict]:
        import torch

        if self._model is None or self._tokenizer is None:
            raise RuntimeError("model is not loaded; call load() first")

        inputs = self._tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=self._max_tokens,
        )
        with torch.no_grad():
            logits = self._model(**inputs).logits[0]
        probs = torch.softmax(logits, dim=-1)
        k = min(top_k, probs.shape[-1])
        values, indices = torch.topk(probs, k)
        return [
            {
                "label": LABELS[i][0],
                "label_en": LABELS[i][1],
                "score": round(float(v), 4),
            }
            for v, i in zip(values.tolist(), indices.tolist(), strict=True)
        ]
