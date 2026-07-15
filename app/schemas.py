# FastAPI uses standard Python type hints combined with Pydantic to automatically validate incoming data types and values

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

# Contract-level cap, enforced in characters (predictable for clients).
# The tokenizer additionally truncates to the model's 512-token limit as a
# safety net, since tokens != characters.
MAX_TEXT_CHARS = 512


class EmotionRequest(BaseModel):
    # json_schema_extra examples pre-fill the "Try it out" form in /docs.
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"text": "你最近過得好嗎？", "top_k": 3}]}
    )

    text: str = Field(
        ...,
        max_length=MAX_TEXT_CHARS,
        description="Traditional Chinese text to classify (1–512 characters).",
    )
    top_k: int = Field(3, ge=1, le=8, description="How many top-scoring labels to return.")

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise PydanticCustomError("empty_text", "text must not be empty or whitespace-only")
        return value


class LabelScore(BaseModel):
    label: str
    label_en: str
    score: float


class EmotionResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    text: str
    # Intentionally duplicates top_k[0] as a convenience field.
    prediction: LabelScore
    top_k: list[LabelScore]
    model: str
    model_revision: str


class ExplainRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"text": "你怎麼可以這樣對我！", "top_k": 3, "examples_k": 4}]
        }
    )

    text: str = Field(
        ...,
        max_length=MAX_TEXT_CHARS,
        description="Traditional Chinese text to classify and explain (1–512 characters).",
    )
    top_k: int = Field(3, ge=1, le=8, description="How many top-scoring labels to return.")
    examples_k: int = Field(
        4,
        ge=1,
        le=8,
        description="How many similar labeled example sentences to retrieve for grounding.",
    )

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise PydanticCustomError("empty_text", "text must not be empty or whitespace-only")
        return value


class SimilarExample(BaseModel):
    text: str
    label: str
    label_en: str
    similarity: float


class WarningDetail(BaseModel):
    code: str
    message: str


class ExplainResponse(BaseModel):
    model_config = ConfigDict(
        protected_namespaces=(),
        json_schema_extra={
            "examples": [
                {
                    "text": "你怎麼可以這樣對我！",
                    "prediction": {"label": "憤怒語調", "label_en": "angry", "score": 0.93},
                    "top_k": [
                        {"label": "憤怒語調", "label_en": "angry", "score": 0.93},
                        {"label": "悲傷語調", "label_en": "sad", "score": 0.04},
                        {"label": "疑問語調", "label_en": "questioning", "score": 0.02},
                    ],
                    "similar_examples": [
                        {
                            "text": "你憑什麼這樣說！",
                            "label": "憤怒語調",
                            "label_en": "angry",
                            "similarity": 0.87,
                        }
                    ],
                    "explanation": "此句以質問句式「怎麼可以」直接指責對方，並以感嘆號收尾，"
                    "情緒強烈，與例句 [1] 的質問語氣相似，故判定為憤怒語調。",
                    "model": "Johnson8187/Chinese-Emotion-Small",
                    "model_revision": "2c04ce86de44d232f0fbe31413868eb31d791aea",
                    "explain_model": "claude-haiku-4-5",
                    "warnings": [],
                }
            ]
        },
    )

    text: str
    prediction: LabelScore
    top_k: list[LabelScore]
    similar_examples: list[SimilarExample]
    # None when explanation generation was degraded — see warnings.
    explanation: str | None
    model: str
    model_revision: str
    explain_model: str
    warnings: list[WarningDetail] = []


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
