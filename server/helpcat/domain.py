"""领域规则：日期、距离、排序。都是纯函数，路由只负责取数据。"""

import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .errors import error

FEEDING_SHIFT_MAX_DAYS = 14
FEEDING_SHIFT_LOOKAHEAD_DAYS = 13
EARTH_RADIUS_M = 6371000
FEEDING_STREAK_MILESTONES = (3, 7, 14, 30, 60)


def shanghai_today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def parse_shift_date(value):
    """A calendar date in the same YYYY-MM-DD shape stored on feeding shifts."""
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        error(422, "invalid_shift_date")


def haversine_distance_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in metres between two WGS84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def feeding_point_today_sort_key(point, fed_today, last_fed_at):
    """Points nobody fed today first, then never-fed points, then the oldest feed."""
    return (
        0 if fed_today == 0 else 1,
        0 if last_fed_at is None else 1,
        last_fed_at.isoformat() if last_fed_at is not None else "",
        point.name,
    )
