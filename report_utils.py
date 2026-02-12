from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from shapely.geometry.base import BaseGeometry

import pandas as pd

from data_processing import line_length_m


# High-contrast palette tuned for light basemaps (Mapbox/OSM-style) with
# good separation between adjacent boroughs.
FOUR_COLOR_PALETTE: List[str] = [
    "#ff3366",  # bright magenta
    "#00aeff",  # bright cyan
    "#ffb000",  # bright amber
    "#7c4dff",  # bright purple
]


def compute_borough_colors(borough_geoms: Dict[str, BaseGeometry]) -> Dict[str, str]:
    names = sorted(borough_geoms.keys())
    adjacency: Dict[str, set] = {name: set() for name in names}
    for i, name in enumerate(names):
        geom = borough_geoms.get(name)
        if geom is None:
            continue
        for other in names[i + 1 :]:
            other_geom = borough_geoms.get(other)
            if other_geom is None:
                continue
            try:
                if geom.touches(other_geom) or geom.intersects(other_geom):
                    adjacency[name].add(other)
                    adjacency[other].add(name)
            except Exception:
                continue

    colors: Dict[str, str] = {}
    order = sorted(names, key=lambda n: len(adjacency[n]), reverse=True)
    for name in order:
        used = {colors.get(n) for n in adjacency[name] if n in colors}
        for color in FOUR_COLOR_PALETTE:
            if color not in used:
                colors[name] = color
                break
        if name not in colors:
            colors[name] = FOUR_COLOR_PALETTE[len(colors) % len(FOUR_COLOR_PALETTE)]
    return colors


def borough_color(name: str, borough_colors: Optional[Dict[str, str]] = None) -> str:
    if borough_colors and name in borough_colors:
        return borough_colors[name]
    return FOUR_COLOR_PALETTE[0]


def parse_date(value) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    try:
        ts = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return ts


def format_report_metadata(filter_label: str, source_url: Optional[str] = None) -> pd.DataFrame:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        {"Key": "Generated", "Value": now},
        {"Key": "Filter", "Value": filter_label},
    ]
    if source_url:
        rows.append({"Key": "Source Sheet", "Value": source_url})
    return pd.DataFrame(rows)


def add_length_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["LengthInM"] = df["_coords"].apply(lambda coords: int(round(line_length_m(coords or []))))
    return df


def compute_borough_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Borough", "OneWay_m", "TwoWay_m", "Total_m"])
    one_way = df[df["OneWay"] == "OneWay"].groupby("Borough")["LengthInM"].sum()
    two_way = df[df["OneWay"] != "OneWay"].groupby("Borough")["LengthInM"].sum()
    boroughs = sorted(set(df["Borough"].unique()))
    rows: List[Dict[str, object]] = []
    for borough in boroughs:
        one = float(one_way.get(borough, 0.0))
        two = float(two_way.get(borough, 0.0))
        total = one + (2 * two)
        rows.append(
            {
                "Borough": borough,
                "OneWay_m": round(one, 2),
                "TwoWay_m": round(two, 2),
                "Total_m": round(total, 2),
            }
        )
    return pd.DataFrame(rows)


def geojson_feature(
    row: pd.Series,
    *,
    borough: str,
    borough_colors: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    coords = row.get("_coords") or []
    lonlat = [(lon, lat) for lat, lon in coords]
    weight = 2 if row.get("OneWay") == "OneWay" else 4
    return {
        "type": "Feature",
        "properties": {
            "name": row.get("name", ""),
            "id": row.get("id", ""),
            "Designation": row.get("Designation", ""),
            "OneWay": row.get("OneWay", ""),
            "Borough": borough,
            "LengthInM": int(round(line_length_m(coords))) if coords else 0,
            "stroke": borough_color(borough, borough_colors),
            "stroke-width": weight,
        },
        "geometry": {"type": "LineString", "coordinates": lonlat},
    }


def build_geojson(features: Iterable[Dict[str, object]]) -> Dict[str, object]:
    return {"type": "FeatureCollection", "features": list(features)}
