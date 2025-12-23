from codemapper.processor.parser import Symbol

SYSTEM_PROMPT = """You are a code documentation assistant. Your task is to summarize code blocks concisely.

For each code block:
1. Write a 1-line explanation of what it does
2. Write 3-5 lines of pseudocode showing the logic flow

Output format (Markdown):
**Summary:** <one line explanation>
**Logic:**
1. <step>
2. <step>
3. <step>

Be precise. No fluff. Focus on what the code DOES, not what it IS."""


def build_summarize_prompt(symbol: Symbol) -> str:
    return f"""Analyze this {symbol.kind.value}:

```
{symbol.signature}

{symbol.code}
```

Provide a summary following the output format."""
