"""Normalize documented approval/retry explanations after whitespace removal."""
from pydantic import field_validator


def meaningful_reason(value: str, *, minimum: int = 12) -> str:
    normalized = value.strip()
    if len(normalized) < minimum:
        raise ValueError(f"Documented reason must contain at least {minimum} non-whitespace characters.")
    return normalized
