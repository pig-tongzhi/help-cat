import re
import unicodedata


_IGNORED_NAME_CHARACTERS = re.compile(r"[\s\-—_·，。！？、,.!?:：;；()（）]+")


def normalize_community_name(value: str) -> str:
    """Return a stable comparison key for a user-entered community name."""
    normalized = unicodedata.normalize("NFKC", value or "").strip().lower()
    normalized = _IGNORED_NAME_CHARACTERS.sub("", normalized)
    if not normalized:
        raise ValueError("invalid_community_name")
    return normalized
