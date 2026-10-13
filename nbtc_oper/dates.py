"""The portal speaks Buddhist-era dd/mm/yyyy; callers speak ISO."""

import re
from datetime import date, datetime, timedelta, timezone

BE_OFFSET = 543
# The portal renders an unset date as 01/01/2443 (1900-01-01).
_NULL_YEAR = 1900
BANGKOK = timezone(timedelta(hours=7))


def to_portal_date(value) -> str:
    """'2026-01-01' or a date -> '01/01/2569'. Empty stays empty.

    A string already in dd/mm/yyyy form is passed through untouched.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
            return value
        value = date.fromisoformat(value)
    return f"{value.day:02d}/{value.month:02d}/{value.year + BE_OFFSET:04d}"


def from_portal_date(text) -> str | None:
    """'01/01/2569' -> '2026-01-01'. Blank, unset or unparseable -> None."""
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text or "")
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    year -= BE_OFFSET
    if year <= _NULL_YEAR:
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def from_dotnet_date(text) -> str | None:
    """'/Date(1595523600000)/' -> ISO-8601 timestamp in Thai time."""
    m = re.search(r"/Date\((-?\d+)", text or "")
    if not m:
        return None
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=BANGKOK).isoformat()
