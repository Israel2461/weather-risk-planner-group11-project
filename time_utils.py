"""
time_utils.py — Helpers for the 12-hour time dropdown.

The user picks a time like "5:30 PM" from a dropdown. The rest of the app
(weather + risk logic) works with 24-hour numbers (17 and 30), so this file
is the one place that converts between the two.
"""

import re

DEFAULT_TIME_LABEL = "3:00 PM"


def to_24_hour(hour_12: int, minute: int, am_pm: str) -> tuple:
    """Convert 12-hour clock values to 24-hour values.

    Examples: (5, 30, "PM") -> (17, 30)   (12, 0, "AM") -> (0, 0)   (12, 0, "PM") -> (12, 0)
    Raises ValueError for impossible values.
    """
    am_pm = am_pm.strip().upper()
    if am_pm not in ("AM", "PM"):
        raise ValueError(f"AM/PM must be 'AM' or 'PM', got '{am_pm}'.")
    if not 1 <= hour_12 <= 12:
        raise ValueError(f"Hour must be between 1 and 12, got {hour_12}.")
    if not 0 <= minute <= 59:
        raise ValueError(f"Minute must be between 0 and 59, got {minute}.")

    hour_24 = hour_12 % 12          # 12 becomes 0, other hours stay the same
    if am_pm == "PM":
        hour_24 += 12               # 1 PM -> 13, 12 PM -> 12, 12 AM -> 0
    return hour_24, minute


def parse_time_label(label: str) -> tuple:
    """Turn a dropdown label such as "5:30 PM" into (17, 30).

    Uses a regular expression: 1-2 digits, a colon, 2 digits, then AM or PM.
    Raises ValueError if the text is not in that shape.
    """
    match = re.match(r"^\s*(\d{1,2}):(\d{2})\s*(AM|PM)\s*$", str(label), re.IGNORECASE)
    if not match:
        raise ValueError(f"'{label}' is not a valid time. Use a format like 5:30 PM.")
    hour_12, minute, am_pm = int(match.group(1)), int(match.group(2)), match.group(3)
    return to_24_hour(hour_12, minute, am_pm)


def format_time(hour_24: int, minute: int = 0) -> str:
    """Turn 24-hour values into a friendly label: (17, 30) -> "5:30 PM"."""
    if not 0 <= hour_24 <= 23:
        raise ValueError(f"Hour must be between 0 and 23, got {hour_24}.")
    if not 0 <= minute <= 59:
        raise ValueError(f"Minute must be between 0 and 59, got {minute}.")
    am_pm = "AM" if hour_24 < 12 else "PM"
    hour_12 = hour_24 % 12
    if hour_12 == 0:
        hour_12 = 12
    return f"{hour_12}:{minute:02d} {am_pm}"


def format_hour(hour_24: int) -> str:
    """Shortcut for whole hours: 17 -> "5:00 PM"."""
    return format_time(hour_24, 0)


def build_time_options(step_minutes: int = 30) -> list:
    """Build the list shown in the dropdown, from "12:00 AM" to "11:30 PM"."""
    if step_minutes <= 0 or 60 % step_minutes != 0:
        raise ValueError("step_minutes must divide 60 evenly (for example 15, 30 or 60).")
    options = []
    for hour in range(24):
        for minute in range(0, 60, step_minutes):
            options.append(format_time(hour, minute))
    return options
