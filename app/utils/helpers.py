from datetime import datetime, timezone


def format_date(dt: datetime) -> str:
    return dt.astimezone().strftime("%d.%m.%Y %H:%M")


def format_days_left(days: int) -> str:
    if days <= 0:
        return "истекла"
    if days == 1:
        return "1 день"
    if days < 5:
        return f"{days} дня"
    if days < 21:
        return f"{days} дней"
    return f"{days} дней"


def truncate_text(text: str, max_length: int = 100) -> str:
    return text[:max_length] + "..." if len(text) > max_length else text


def is_expired(end_date: datetime) -> bool:
    return datetime.now(timezone.utc) >= end_date
