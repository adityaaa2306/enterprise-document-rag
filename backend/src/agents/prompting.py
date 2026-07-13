"""Shared Markdown formatting instructions for user-facing LLM answers."""

MARKDOWN_OUTPUT_RULES = """
Format your entire answer in clean GitHub-Flavored Markdown.

Rules:
- Use headings (## / ###) when they improve scannability; skip a top-level # unless the answer is a full report.
- Use short paragraphs, bullet lists, and numbered lists where helpful.
- Use **bold** sparingly for emphasis.
- Use Markdown tables when comparing metrics or structured values.
- Use fenced code blocks only for actual code or commands.
- Never output HTML tags.
- Never wrap the entire answer in a single triple-backtick code fence.
- Do not escape Markdown (do not write \\*\\*bold\\*\\*).
- Cite evidence with bracket markers like [1] when context provides them.
- Prefer clarity over decoration; avoid excessive formatting.
""".strip()
