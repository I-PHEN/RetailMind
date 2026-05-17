"""WhatsApp text formatting — shared by narrator and agent.

Free models ignore formatting instructions, so we enforce valid WhatsApp markup
deterministically instead of trusting the prompt.
"""
from __future__ import annotations

import re


def to_whatsapp(text: str) -> str:
    """Coerce LLM output into valid WhatsApp formatting."""
    # **bold** / __bold__  ->  *bold*  (WhatsApp uses a single asterisk)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text, flags=re.S)
    text = re.sub(r"__(.+?)__", r"*\1*", text, flags=re.S)
    # Markdown headings "### Title" -> "*Title*"
    text = re.sub(r"(?m)^\s*#{1,6}\s*(.+?)\s*$", r"*\1*", text)
    # Horizontal rules / stray table pipes
    text = re.sub(r"(?m)^\s*([-*_]\s*){3,}$", "", text)
    text = re.sub(r"(?m)^\s*\|.*\|\s*$", "", text)
    # Tidy trailing spaces, collapse 3+ blank lines
    text = re.sub(r"[ \t]+(\n)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
