from datetime import datetime
from typing import List


def generate_group_title(
    account_index: int,
    group_number: int,
    dt: datetime,
) -> str:
    date_str = dt.strftime("%Y-%m-%d")
    return f"ACC{account_index:02d} • G{group_number:03d} • {date_str}"


def generate_datetime_messages(dt: datetime) -> List[str]:
    year = dt.year
    month = dt.month
    day = dt.day
    weekday = dt.strftime("%A")
    hour = dt.hour
    minute = dt.minute
    second = dt.second
    iso = dt.isoformat()
    unix_ts = int(dt.timestamp())
    summary = dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    return [
        f"Year: {year}",
        f"Month: {month} ({dt.strftime('%B')})",
        f"Day: {day}",
        f"Weekday: {weekday}",
        f"Hour: {hour}",
        f"Minute: {minute}",
        f"Second: {second}",
        f"ISO: {iso}",
        f"Unix: {unix_ts}",
        f"Summary: {summary}",
    ]
