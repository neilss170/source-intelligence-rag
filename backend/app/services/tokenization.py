import re

TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[+#.-][a-z0-9]+)*", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)]
