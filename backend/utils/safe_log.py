"""Shared safe formatting utilities — never crash on None."""


def safe_fmt(value, fmt=".1f", suffix="", missing="missing"):
    """Format a numeric value safely — returns 'missing' if value is None."""
    if value is None:
        return missing
    try:
        return f"{float(value):{fmt}}{suffix}"
    except (ValueError, TypeError):
        return missing


def safe_str(value, missing="missing"):
    """Return str(value) or 'missing' if value is None."""
    if value is None:
        return missing
    return str(value)


def safe_int(value, missing="missing"):
    """Return str(int(value)) or 'missing' if value is None."""
    if value is None:
        return missing
    try:
        return str(int(value))
    except (ValueError, TypeError):
        return missing
