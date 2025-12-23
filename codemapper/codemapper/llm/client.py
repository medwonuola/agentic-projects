from dataclasses import dataclass

import ollama

from codemapper.llm.prompts import SYSTEM_PROMPT, build_summarize_prompt
from codemapper.processor.parser import Symbol


@dataclass
class ModelConfig:
    name: str = "qwen2.5-coder:14b"
    context_window: int = 8192
    temperature: float = 0.1


class OllamaClient:
    def __init__(self, config: ModelConfig | None = None) -> None:
        self._config = config or ModelConfig()
        self._client = ollama.Client()

    def summarize(self, symbol: Symbol) -> str:
        prompt = build_summarize_prompt(symbol)
        response = self._client.chat(
            model=self._config.name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            options={
                "num_ctx": self._config.context_window,
                "temperature": self._config.temperature,
            },
        )
        return response.message.content or ""

    async def summarize_async(self, symbol: Symbol) -> str:
        prompt = build_summarize_prompt(symbol)
        async_client = ollama.AsyncClient()
        response = await async_client.chat(
            model=self._config.name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            options={
                "num_ctx": self._config.context_window,
                "temperature": self._config.temperature,
            },
        )
        return response.message.content or ""

    def is_available(self) -> bool:
        try:
            self._client.list()
            return True
        except Exception:
            return False
