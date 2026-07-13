"""Grounded emotion explanation via the Anthropic API (claude-haiku-4-5).

The anthropic SDK is imported lazily so unit tests (which inject a fake
generator) never pay the import cost. The client reads ANTHROPIC_API_KEY from
the environment.

Privacy: only token-usage metadata is logged — never the user text or the
generated explanation, consistent with app/logging_utils.py.
"""

import logging

from app.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是繁體中文語氣分析助理。分類器將文本分為八種語氣："
    "平淡語氣、關切語調、開心語調、憤怒語調、悲傷語調、疑問語調、驚奇語調、厭惡語調。\n"
    "請用繁體中文，以 2–4 句話解釋輸入文本為何帶有預測的語氣："
    "引用文本中的具體語言線索（字詞、語尾助詞、標點、句式），"
    "並在有相似例句時以 [1]、[2] 編號援引作為佐證。\n"
    "只根據提供的資料回答，不要臆測、不要添加免責聲明、不要重複輸入全文。"
)


class ExplanationGenerator:
    def __init__(self, settings: Settings):
        self._model = settings.explain_model
        self._max_tokens = settings.explain_max_tokens
        self._timeout = settings.anthropic_timeout_seconds
        self._max_retries = settings.anthropic_max_retries
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic(
                timeout=self._timeout, max_retries=self._max_retries
            )
        return self._client

    async def generate(self, text: str, scores: list[dict], examples: list[dict]) -> str:
        client = self._get_client()
        response = await client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=0.2,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_content(text, scores, examples)}],
        )
        logger.info(
            "explanation generated",
            extra={"model": self._model},
        )
        logger.debug(
            "anthropic usage: input=%s output=%s",
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return next(block.text for block in response.content if block.type == "text")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


def _build_user_content(text: str, scores: list[dict], examples: list[dict]) -> str:
    lines = [f"輸入文本：「{text}」"]
    score_parts = [f"{s['label']}: {s['score']}" for s in scores]
    lines.append(f"分類結果（信心分數）：{', '.join(score_parts)}")
    if examples:
        lines.append("相似的已標註例句：")
        for i, ex in enumerate(examples, start=1):
            lines.append(f"[{i}]（{ex['label']}，相似度 {ex['similarity']}）「{ex['text']}」")
    else:
        lines.append("（無相似例句可供參考，請僅依文本本身的語言線索解釋。）")
    return "\n".join(lines)
