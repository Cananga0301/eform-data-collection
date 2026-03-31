import re
import unicodedata


def normalize(s: str) -> str:
    """
    Normalize a string for matching:
      1. Trim whitespace and lowercase
      2. Collapse internal whitespace to a single space
      3. Strip diacritics (NFD decomposition + remove combining chars)

    Originals are preserved for display; use this only for _norm columns and comparisons.
    """
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r'\s+', ' ', s)
    # Decompose to NFD, then drop combining (diacritic) characters.
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return s
