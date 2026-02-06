from datetime import date


def today_string() -> str:
    return date.today().isoformat()
