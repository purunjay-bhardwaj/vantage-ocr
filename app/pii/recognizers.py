"""
Custom Presidio recognizers for Indian-context entities that the default
English model misses.
"""
from __future__ import annotations

import re
from presidio_analyzer import Pattern, PatternRecognizer


def get_custom_recognizers() -> list[PatternRecognizer]:
    """Return list of custom PatternRecognizer instances."""
    recognizers = []

    # Aadhaar: 12 digits, optionally space/hyphen separated in groups of 4
    aadhaar = PatternRecognizer(
        supported_entity="AADHAAR",
        patterns=[
            Pattern(
                name="aadhaar_grouped",
                regex=r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}\b",
                score=0.9,
            ),
            Pattern(
                name="aadhaar_plain",
                regex=r"\b\d{12}\b",
                score=0.6,
            ),
        ],
    )
    recognizers.append(aadhaar)

    # PAN: 5 uppercase letters + 4 digits + 1 uppercase letter
    pan = PatternRecognizer(
        supported_entity="PAN",
        patterns=[
            Pattern(
                name="pan_card",
                regex=r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
                score=0.95,
            )
        ],
    )
    recognizers.append(pan)

    # Indian mobile: +91 / 0 prefix optional, 10 digits starting with 6-9
    mobile = PatternRecognizer(
        supported_entity="IN_MOBILE",
        patterns=[
            Pattern(
                name="indian_mobile",
                regex=r"(?:\+91[\s\-]?|0)?[6-9]\d{9}\b",
                score=0.85,
            )
        ],
    )
    recognizers.append(mobile)

    # Indian bank account: 9–18 digits (NEFT/RTGS standard)
    bank_account = PatternRecognizer(
        supported_entity="BANK_ACCOUNT",
        patterns=[
            Pattern(
                name="bank_acc",
                regex=r"\b\d{9,18}\b",
                score=0.5,  # low score; context needed to avoid false positives
            ),
            # With common labels
            Pattern(
                name="bank_acc_labeled",
                regex=r"(?i)(?:a/?c|account\s*(?:no|number|#))[:\s]*(\d{9,18})\b",
                score=0.9,
            ),
        ],
    )
    recognizers.append(bank_account)

    # IFSC code: 4 letters + 0 + 6 alphanumeric
    ifsc = PatternRecognizer(
        supported_entity="IFSC",
        patterns=[
            Pattern(
                name="ifsc",
                regex=r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
                score=0.95,
            )
        ],
    )
    recognizers.append(ifsc)

    # Insurance policy number: typically 8–15 alphanumeric
    policy = PatternRecognizer(
        supported_entity="POLICY_NUMBER",
        patterns=[
            Pattern(
                name="policy_labeled",
                regex=r"(?i)policy\s*(?:no|number|#)[:\s]*([A-Z0-9\-]{6,15})\b",
                score=0.88,
            )
        ],
    )
    recognizers.append(policy)

    # Roll / registration number (colleges)
    roll = PatternRecognizer(
        supported_entity="ROLL_NUMBER",
        patterns=[
            Pattern(
                name="roll_labeled",
                regex=r"(?i)(?:roll|reg(?:istration)?|student\s+id)\s*(?:no|number|#)?[:\s]*([A-Z0-9\-\/]{4,15})\b",
                score=0.82,
            )
        ],
    )
    recognizers.append(roll)

    return recognizers
