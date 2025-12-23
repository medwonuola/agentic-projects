from codemapper.processor.parser import Symbol

SYSTEM_PROMPT = """You are a terse code summarizer. Output ONE line explaining what the code does.

Rules:
- Max 15 words
- No fluff like "This function..." or "This class..."
- Just say what it DOES
- For data classes/models: list the key fields
- For functions: describe the action

Examples:
- "Fetches user by ID from database, returns None if not found"
- "Config for API rate limits: requests/period, timeout, retry count"
- "Validates email format, raises ValueError on invalid"
- "Pydantic model: name, credentials, rate limits, asset classes"
"""


def build_summarize_prompt(symbol: Symbol) -> str:
    return f"""Summarize this {symbol.kind.value} in ONE LINE (max 15 words):

```
{symbol.signature}
```

Just the purpose, no boilerplate."""
