"""Schedule trigger parsing utilities.

Converts human-readable schedule expressions into APScheduler trigger
objects.  Supports standard 5-field cron expressions and convenient
interval shorthands.

Examples::

    trigger = parse_trigger("0 9 * * *")          # cron: daily at 09:00
    trigger = parse_trigger("every 30m")           # interval: every 30 min
    trigger = parse_trigger("every 2h")            # interval: every 2 hours
    trigger = parse_trigger("every 1d")            # interval: every 1 day
"""

from __future__ import annotations

import re

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

# Pattern for interval shorthands: "every <number><unit>"
_INTERVAL_PATTERN = re.compile(
    r"^every\s+(\d+)\s*(s|sec|second|seconds|m|min|minute|minutes|h|hr|hour|hours|d|day|days)$",
    re.IGNORECASE,
)

_UNIT_MAP: dict[str, str] = {
    "s": "seconds",
    "sec": "seconds",
    "second": "seconds",
    "seconds": "seconds",
    "m": "minutes",
    "min": "minutes",
    "minute": "minutes",
    "minutes": "minutes",
    "h": "hours",
    "hr": "hours",
    "hour": "hours",
    "hours": "hours",
    "d": "days",
    "day": "days",
    "days": "days",
}


def parse_trigger(expression: str) -> CronTrigger | IntervalTrigger:
    """Parse a schedule expression into an APScheduler trigger.

    Args:
        expression: Either a 5-field cron expression (e.g. ``"0 9 * * *"``)
                    or an interval shorthand (e.g. ``"every 30m"``).

    Returns:
        An APScheduler trigger object.

    Raises:
        ValueError: If the expression cannot be parsed.
    """
    expression = expression.strip()

    # Try interval shorthand first.
    match = _INTERVAL_PATTERN.match(expression)
    if match:
        amount = int(match.group(1))
        unit_raw = match.group(2).lower()
        unit = _UNIT_MAP.get(unit_raw)
        if unit is None:
            raise ValueError(f"Unknown interval unit: {unit_raw!r}")
        if amount <= 0:
            raise ValueError(f"Interval amount must be positive, got {amount}")
        return IntervalTrigger(**{unit: amount})

    # Try cron expression (5 fields: minute hour day month day_of_week).
    parts = expression.split()
    if len(parts) == 5:
        return CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

    raise ValueError(
        f"Cannot parse schedule expression: {expression!r}. "
        "Expected a 5-field cron expression (e.g. '0 9 * * *') "
        "or an interval shorthand (e.g. 'every 30m')."
    )


def describe_trigger(expression: str) -> str:
    """Return a human-readable description of a schedule expression.

    Args:
        expression: A cron or interval expression.

    Returns:
        A descriptive string.
    """
    expression = expression.strip()

    match = _INTERVAL_PATTERN.match(expression)
    if match:
        amount = int(match.group(1))
        unit_raw = match.group(2).lower()
        unit = _UNIT_MAP.get(unit_raw, unit_raw)
        return f"Every {amount} {unit}"

    parts = expression.split()
    if len(parts) == 5:
        return f"Cron: {expression}"

    return expression


def validate_expression(expression: str) -> bool:
    """Check whether a schedule expression is valid.

    Args:
        expression: A cron or interval expression.

    Returns:
        True if parseable, False otherwise.
    """
    try:
        parse_trigger(expression)
        return True
    except (ValueError, TypeError):
        return False
