# FastAPI uses standard Python type hints combined with Pydantic to automatically validate incoming data types and values

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

# Contract-level cap, enforced in characters (predictable for clients).
# The tokenizer additionally truncates to the model's 512-token limit as a
# safety net, since tokens != characters.
MAX_TEXT_CHARS = 512


class EmotionRequest(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT_CHARS)
    top_k: int = Field(3, ge=1, le=8)

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


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
