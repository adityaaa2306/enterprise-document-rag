"""Shared Markdown formatting instructions for user-facing LLM answers."""

# Compressed (~half the previous token cost) while keeping critical constraints.
MARKDOWN_OUTPUT_RULES = """
Reply in GitHub-Flavored Markdown. Use ## headings only when useful; prefer short paragraphs and bullets. Cite context with [n]. Never wrap the whole answer in a code fence. No HTML.
""".strip()
