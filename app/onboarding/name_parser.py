"""Extract (owner_name, shop_name) from a free-form introduction message."""
from __future__ import annotations

import re


def parse_name(text: str) -> tuple[str, str]:
    """Return (owner_name, shop_name).

    Handles patterns like:
      "I'm Amina, Amina's Mini-Mart"
      "My name is John, John's Pharmacy"
      "Kofi, Kofi Mart"
      "Amina"   → shop defaults to "Amina's Shop"
    """
    text = text.strip().strip("!.?")

    # Strip intro phrases
    intro_re = re.compile(
        r"^(i(?:'m| am)|my name is)\s+", re.IGNORECASE
    )
    text = intro_re.sub("", text).strip()

    # Split on first comma or newline to separate name from shop
    if "," in text or "\n" in text:
        # Explicit delimiter exists
        parts = re.split(r"[,\n]+", text, maxsplit=1)
        owner = parts[0].strip().strip("!.?")
        shop = parts[1].strip().strip("!.?") if len(parts) > 1 else None
    else:
        # No delimiter: check if the text has multiple words that might include shop name
        # Take only the first word as the owner name (or first two if they form a typical name pattern)
        words = text.split()

        # Remove punctuation from each word
        cleaned_words = []
        for word in words:
            cleaned_word = re.sub(r'[!.?]+', '', word)
            if cleaned_word:
                cleaned_words.append(cleaned_word)

        # If multiple words exist and second word is a shop descriptor (Shop, Mart, Stores, etc.)
        # or if first word appears multiple times, take just the first name word
        if len(cleaned_words) > 1:
            # Check if this looks like "Name ... Shop" pattern
            second_word_lower = cleaned_words[1].lower() if len(cleaned_words) > 1 else ""
            shop_keywords = {"shop", "mart", "stores", "store", "market", "market", "pharmacy", "cafe", "mini-mart"}

            if (second_word_lower in shop_keywords or
                cleaned_words[0] == cleaned_words[1]):  # repeated name like "Fatima Fatima"
                owner = cleaned_words[0]
                shop = " ".join(cleaned_words[1:]) if len(cleaned_words) > 1 else None
            else:
                # Take first two words as owner name
                owner = " ".join(cleaned_words[:2])
                shop = None
        else:
            owner = cleaned_words[0] if cleaned_words else text
            shop = None

    # Apply final cleanup
    owner = owner.strip().strip("!.?")

    if not shop:
        shop = f"{owner}'s Shop"
    else:
        shop = shop or f"{owner}'s Shop"

    return owner, shop
