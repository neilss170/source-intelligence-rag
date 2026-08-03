import re

EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])",
    flags=re.IGNORECASE,
)
PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\(?\d\)?[\s.-]?){9,14}\d(?!\w)"
)
LINKEDIN_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[a-z0-9_-]+/?",
    flags=re.IGNORECASE,
)


def redact_contact_details(text: str) -> str:
    redacted = EMAIL_PATTERN.sub("[EMAIL REDACTED]", text)
    redacted = LINKEDIN_PATTERN.sub("[LINKEDIN REDACTED]", redacted)
    redacted = PHONE_PATTERN.sub("[PHONE REDACTED]", redacted)
    return redacted
