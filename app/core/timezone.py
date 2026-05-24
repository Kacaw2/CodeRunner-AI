from datetime import datetime, timedelta, timezone


CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_china() -> datetime:
    """Return Beijing time as a naive datetime for existing DateTime columns."""
    return datetime.now(CHINA_TZ).replace(tzinfo=None)


def aware_now_china() -> datetime:
    return datetime.now(CHINA_TZ)


def today_china():
    return now_china().date()
