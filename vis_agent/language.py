"""The language of a text, read from its script. The profiler and the analyst share one answer."""

import re

ARABIC = re.compile(r"[\u0600-\u06FF]")


def language_of(*texts: str | None) -> str:
    """The language of the first text that holds anything: "Arabic" when it holds Arabic script, else "English"."""
    for text in texts:
        if text and text.strip():
            return "Arabic" if ARABIC.search(text) else "English"
    return "English"
