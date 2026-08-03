from app.services.redaction import redact_contact_details


def test_redacts_email_phone_and_linkedin() -> None:
    source = (
        "Candidate\n"
        "candidate@example.com | +91 98765 43210 | "
        "linkedin.com/in/sample-candidate\n"
        "Python developer"
    )

    redacted = redact_contact_details(source)

    assert "candidate@example.com" not in redacted
    assert "98765 43210" not in redacted
    assert "linkedin.com/in/sample-candidate" not in redacted
    assert "Python developer" in redacted
    assert "[EMAIL REDACTED]" in redacted
    assert "[PHONE REDACTED]" in redacted
    assert "[LINKEDIN REDACTED]" in redacted
