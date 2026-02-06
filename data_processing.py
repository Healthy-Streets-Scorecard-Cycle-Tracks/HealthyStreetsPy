import json
import random
import urllib.parse
import urllib.request
from datetime import date
from typing import List, Optional, Tuple
from uuid import uuid4

import pandas as pd

from config import MAP_COLORS, NOMINATIM_EMAIL, NOMINATIM_ENABLED, NOMINATIM_USER_AGENT
from geo_utils import coords_to_ewkt, wkt_to_latlon

try:
    from pyproj import Geod
except Exception:  # pragma: no cover
    Geod = None

GEOD = Geod(ellps="WGS84") if Geod else None


def row_to_coords(row: pd.Series) -> Optional[List[Tuple[float, float]]]:
    for col in ("text_coords", "geometry", "Geometry"):
        if col in row and isinstance(row[col], str) and row[col].strip():
            return wkt_to_latlon(row[col].strip())
    return None


def polyline_color(row: pd.Series, colors: Optional[dict] = None) -> str:
    colors = colors or MAP_COLORS
    if bool(row.get("Rejected", False)):
        return colors["polyline_rejected"]
    if bool(row.get("AuditedStreetView", False)) or bool(row.get("AuditedInPerson", False)):
        return colors["polyline_approved"]
    return colors["polyline"]


def generate_route_id() -> str:
    words = [
        "apple", "banana", "cherry", "date", "elder", "fig", "grape", "honey",
        "kiwi", "lemon", "mango", "nectar", "olive", "peach", "quince", "rasp",
        "straw", "tangerine", "ugli", "vanilla", "water", "xigua", "yam", "zucchini",
    ]
    colors = ["red", "blue", "green", "yellow", "purple"]
    nouns = ["apple", "banana", "cherry", "date", "elder"]
    return f"{random.choice(words)}-{random.choice(colors)}-{random.choice(nouns)}"


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    defaults = {
        "name": "",
        "id": "",
        "description": "",
        "Designation": "",
        "OneWay": "TwoWay",
        "Flow": "",
        "Protection": "",
        "Ownership": "",
        "YearBuildBeforeFlag": False,
        "YearBuilt": "",
        "AuditedStreetView": False,
        "AuditedInPerson": False,
        "Rejected": False,
        "History": "",
        "LastEdited": "",
        "WhenCreated": "",
        "text_coords": "",
    }
    for key, value in defaults.items():
        if key not in df.columns:
            df[key] = value
    return df


def normalize_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "t", "yes", "y", "1"}:
        return True
    if text in {"false", "f", "no", "n", "0", ""}:
        return False
    return False


def prepare_routes_df(df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_columns(df.copy())
    if "guid" not in df.columns:
        df["guid"] = [str(uuid4()) for _ in range(len(df))]
    df.loc[:, "_coords"] = df.apply(row_to_coords, axis=1)
    df.loc[:, "YearBuildBeforeFlag"] = df["YearBuildBeforeFlag"].apply(normalize_bool)
    df.loc[:, "AuditedStreetView"] = df["AuditedStreetView"].apply(normalize_bool)
    df.loc[:, "AuditedInPerson"] = df["AuditedInPerson"].apply(normalize_bool)
    df.loc[:, "Rejected"] = df["Rejected"].apply(normalize_bool)
    return df


def update_history(df: pd.DataFrame, guid: str, user: str, today: Optional[str] = None) -> pd.DataFrame:
    from time_utils import today_string

    today_val = today or today_string()
    line = f"{today_val}: edited by {user or 'unknown'}"
    current = df.loc[df["guid"] == guid, "History"].fillna("").astype(str).values
    new_history = line if len(current) == 0 or current[0] == "" else f"{line}\n{current[0]}"
    df.loc[df["guid"] == guid, "History"] = new_history
    df.loc[df["guid"] == guid, "LastEdited"] = today_val
    existing_created = df.loc[df["guid"] == guid, "WhenCreated"].values
    if len(existing_created) == 0 or pd.isna(existing_created[0]) or str(existing_created[0]) == "":
        df.loc[df["guid"] == guid, "WhenCreated"] = today_val
    return df


def normalize_linebreaks(text: str) -> str:
    if text is None:
        return ""
    text = str(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    return text


def parse_date_value(value: object) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = pd.to_datetime(text, errors="coerce", dayfirst=False)
        if pd.isna(parsed):
            parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
        if pd.isna(parsed):
            return None
        return parsed.date()
    except Exception:
        return None


def reverse_geocode_name(lat: float, lon: float, timeout: float = 2.0) -> Optional[str]:
    if not NOMINATIM_ENABLED:
        return None
    user_agent = NOMINATIM_USER_AGENT or "HealthyStreetsShinyPy"
    if NOMINATIM_EMAIL:
        user_agent = f"{user_agent} ({NOMINATIM_EMAIL})"
    params = {
        "format": "jsonv2",
        "lat": str(lat),
        "lon": str(lon),
        "zoom": "18",
        "addressdetails": "1",
    }
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    address = data.get("address", {})
    for key in ("road", "pedestrian", "footway", "cycleway", "path", "street"):
        name = address.get(key)
        if name:
            return str(name)
    return data.get("name") or data.get("display_name")


def line_length_m(coords: List[Tuple[float, float]]) -> float:
    if not coords:
        return 0.0
    geod = GEOD
    if geod is None:
        try:
            from pyproj import Geod as _Geod

            geod = _Geod(ellps="WGS84")
        except Exception:
            return 0.0
    lons = [lon for _, lon in coords]
    lats = [lat for lat, _ in coords]
    length = 0.0
    for i in range(len(coords) - 1):
        _, _, dist = geod.inv(lons[i], lats[i], lons[i + 1], lats[i + 1])
        length += dist
    return length


__all__ = [
    "row_to_coords",
    "polyline_color",
    "generate_route_id",
    "ensure_columns",
    "normalize_bool",
    "prepare_routes_df",
    "update_history",
    "normalize_linebreaks",
    "parse_date_value",
    "reverse_geocode_name",
    "line_length_m",
    "coords_to_ewkt",
]
