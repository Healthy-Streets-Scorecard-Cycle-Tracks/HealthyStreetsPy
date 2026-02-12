from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from datetime import date
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from data_processing import normalize_bool, line_length_m
from config import logger
from cycle_routes import get_cycle_route_index
from tfl_lookup import tfl_near_distance
from report_utils import (
    add_length_columns,
    build_geojson,
    compute_borough_colors,
    compute_borough_summary,
    format_report_metadata,
    geojson_feature,
    parse_date,
)


async def fetch_all_boroughs(
    *,
    boroughs: List[str],
    sheet_id: str,
    read_region_sheet: Callable[..., pd.DataFrame],
    prepare_routes_df: Callable[[pd.DataFrame], pd.DataFrame],
    on_progress: Optional[Callable[[str], None]] = None,
    on_retry: Optional[Callable[[int, float, float, Exception], None]] = None,
    concurrency: int = 4,
) -> Dict[str, pd.DataFrame]:
    semaphore = asyncio.Semaphore(concurrency)
    results: Dict[str, pd.DataFrame] = {}

    total = len(boroughs)
    completed = 0
    lock = asyncio.Lock()

    async def _fetch(name: str):
        nonlocal completed
        async with semaphore:
            if on_progress:
                async with lock:
                    on_progress(f"Downloading {name} ({completed}/{total} complete)")

            def _op():
                return read_region_sheet(sheet_id, name, on_retry=on_retry)

            df = await asyncio.to_thread(_op)
            df = prepare_routes_df(df)
            results[name] = df
            if on_progress:
                async with lock:
                    completed += 1
                if completed == total:
                    on_progress(f"Downloaded all boroughs ({completed}/{total})")

    await asyncio.gather(*[_fetch(b) for b in boroughs])
    return results


def filter_routes(
    df: pd.DataFrame,
    *,
    filter_mode: str,
    since_kind: Optional[str],
    since_date: Optional[date],
) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    if "Rejected" in df.columns:
        df = df.loc[~df["Rejected"].apply(normalize_bool)]
    if filter_mode == "TFL only":
        df = df.loc[df["Ownership"].fillna("").str.upper() == "TFL"]
    elif filter_mode == "Since date" and since_date:
        col = "WhenCreated" if since_kind == "Added since" else "LastEdited"
        if col in df.columns:
            ts = parse_date(since_date)
            col_ts = pd.to_datetime(df[col], errors="coerce")
            if ts is not None:
                df = df.loc[col_ts >= ts]
    return df


def build_report_zip(
    *,
    borough_dfs: Dict[str, pd.DataFrame],
    filter_label: str,
    borough_geoms: Optional[Dict[str, object]] = None,
    report_suffix: str = "",
    source_url: Optional[str] = None,
) -> Tuple[str, str]:
    tmp_root = tempfile.mkdtemp(prefix="hss-report-")
    report_root = f"healthy-streets-report{report_suffix}"
    report_dir = os.path.join(tmp_root, report_root)
    geojson_dir = os.path.join(report_dir, "geojson")
    os.makedirs(report_dir, exist_ok=True)
    os.makedirs(geojson_dir, exist_ok=True)
    borough_colors = None
    if borough_geoms:
        try:
            borough_colors = compute_borough_colors(borough_geoms)
        except Exception:
            borough_colors = None

    all_rows = []
    for borough, df in borough_dfs.items():
        if df.empty:
            continue
        df = df.copy()
        df["Borough"] = borough
        df = add_length_columns(df)
        all_rows.append(df)
        features = [
            geojson_feature(row, borough=borough, borough_colors=borough_colors)
            for _, row in df.iterrows()
        ]
        geojson = build_geojson(features)
        out_path = os.path.join(geojson_dir, f"{borough}{report_suffix}.geojson")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(geojson, f)

    if all_rows:
        combined = pd.concat(all_rows, ignore_index=True)
    else:
        combined = pd.DataFrame()

    excel_path = os.path.join(report_dir, f"report{report_suffix}.xlsx")
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        format_report_metadata(filter_label, source_url).to_excel(writer, sheet_name="Info", index=False)
        compute_borough_summary(combined).to_excel(writer, sheet_name="Summary", index=False)
        if not combined.empty:
            compute_tfl_mislabeled(combined).to_excel(writer, sheet_name="TFL mismatches", index=False)
        else:
            pd.DataFrame().to_excel(writer, sheet_name="TFL mismatches", index=False)
        if ENABLE_CYCLEWAY_COVERAGE:
            # Note: Cycleways coverage currently unreliable; keep behind a feature flag.
            if not combined.empty:
                cycle_by_designation = compute_cycleway_coverage(combined, mode="designation")
                cycle_by_auto = compute_cycleway_coverage(combined, mode="auto")
                cycle_by_designation.to_excel(writer, sheet_name="Cycleways cover (Des)", index=False)
                cycle_by_auto.to_excel(writer, sheet_name="Cycleways cover (Auto)", index=False)
            else:
                pd.DataFrame().to_excel(writer, sheet_name="Cycleways cover (Des)", index=False)
                pd.DataFrame().to_excel(writer, sheet_name="Cycleways cover (Auto)", index=False)
        if not combined.empty:
            drop_cols = [c for c in combined.columns if c.startswith("_") or c == "guid"]
            combined.drop(columns=drop_cols, errors="ignore").to_excel(writer, sheet_name="Routes", index=False)
        else:
            pd.DataFrame().to_excel(writer, sheet_name="Routes", index=False)

    zip_base = os.path.join(tmp_root, report_root)
    zip_path = shutil.make_archive(zip_base, "zip", report_dir)
    return tmp_root, zip_path


# Feature flag: Cycleways coverage tabs are enabled by default.
ENABLE_CYCLEWAY_COVERAGE = True


def compute_cycleway_coverage(
    df: pd.DataFrame,
    *,
    mode: str,
    buffer_m: float = 50.0,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=["Label", "Programme", "Cycleway_len_m", "OneWay_m", "TwoWay_m", "Coverage_pct"]
        )
    allowed_programmes = {"Cycleways", "Cycle Superhighways"}
    tree, geoms, geom_to_feature, project = get_cycle_route_index(allowed_programmes)
    if tree is None or not geoms or project is None:
        return pd.DataFrame(
            columns=["Label", "Programme", "Cycleway_len_m", "OneWay_m", "TwoWay_m", "Coverage_pct"]
        )

    from shapely.geometry import LineString

    totals: Dict[str, Dict[str, float]] = {}
    for geom in geoms:
        feature = geom_to_feature.get(id(geom))
        if not feature:
            continue
        entry = totals.setdefault(
            feature.label,
            {"Programme": feature.programme, "Cycleway_len_m": 0.0, "OneWay_m": 0.0, "TwoWay_m": 0.0},
        )
        entry["Cycleway_len_m"] += float(getattr(geom, "length", 0.0) or 0.0)

    routes_considered = 0
    matched_candidates = 0
    overlap_total = 0.0
    for _, row in df.iterrows():
        coords = row.get("_coords") or []
        if not coords:
            continue
        routes_considered += 1
        try:
            proj = [project(lon, lat) for lat, lon in coords]
            route = LineString(proj)
        except Exception:
            continue
        if route.is_empty or route.length == 0:
            continue
        is_oneway = row.get("OneWay") == "OneWay"
        if mode == "designation":
            label = str(row.get("Designation") or "").strip()
            if not label or label not in totals:
                continue
            if is_oneway:
                totals[label]["OneWay_m"] += float(route.length)
            else:
                totals[label]["TwoWay_m"] += float(route.length)
            continue

        buffered = route.buffer(buffer_m)
        candidates = tree.query(buffered)
        if len(candidates) == 0:
            continue
        matched_candidates += 1
        for geom in candidates:
            if not hasattr(geom, "intersection"):
                try:
                    geom = geoms[int(geom)]
                except Exception:
                    continue
            feature = geom_to_feature.get(id(geom))
            if not feature:
                continue
            try:
                # Use a buffer to capture near-overlaps (line-line intersections
                # are often empty due to tiny geometric offsets).
                overlap = route.intersection(geom.buffer(buffer_m))
            except Exception:
                continue
            overlap_len = 0.0 if overlap.is_empty else float(overlap.length)
            if overlap_len <= 0:
                continue
            overlap_total += overlap_len
            entry = totals.get(feature.label)
            if not entry:
                continue
            if is_oneway:
                entry["OneWay_m"] += overlap_len
            else:
                entry["TwoWay_m"] += overlap_len

    rows: List[Dict[str, object]] = []
    for label, entry in sorted(totals.items()):
        cycle_len = float(entry.get("Cycleway_len_m", 0.0))
        one_len = float(entry.get("OneWay_m", 0.0))
        two_len = float(entry.get("TwoWay_m", 0.0))
        coverage = (100.0 * (one_len + 2.0 * two_len) / (2.0 * cycle_len)) if cycle_len > 0 else 0.0
        rows.append(
            {
                "Label": label,
                "Programme": entry.get("Programme", ""),
                "Cycleway_len_m": round(cycle_len, 2),
                "OneWay_m": round(one_len, 2),
                "TwoWay_m": round(two_len, 2),
                "Coverage_pct": round(coverage, 2),
            }
        )
    def _sort_key(label: str):
        import re

        match = re.match(r"([A-Za-z]+)(\d+)", label.strip())
        if not match:
            safe = label.strip()
            return (3, safe, float("inf"), safe)
        prefix, num = match.groups()
        prefix = prefix.upper()
        order = 0 if prefix == "CS" else 1 if prefix == "C" else 2
        return (order, prefix, int(num), label.strip())

    rows = sorted(rows, key=lambda r: _sort_key(str(r.get("Label", ""))))
    logger.info(
        "Cycleways coverage (%s): routes=%s candidates=%s overlap_total=%.1f",
        mode,
        routes_considered,
        matched_candidates,
        overlap_total,
    )
    return pd.DataFrame(rows)


def compute_tfl_mislabeled(
    df: pd.DataFrame,
    *,
    threshold_m: float = 60.0,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "Issue",
                "Borough",
                "Name",
                "Id",
                "Ownership",
                "OneWay",
                "LengthInM",
                "DistanceToTFL_m",
            ]
        )
    rows: List[Dict[str, object]] = []
    for _, row in df.iterrows():
        coords = row.get("_coords") or []
        if not coords:
            continue
        near, distance = tfl_near_distance(coords, buffer_m=threshold_m, max_distance_m=threshold_m)
        owner = str(row.get("Ownership") or "").strip()
        owner_is_tfl = owner.upper() == "TFL"
        issue = None
        if near and not owner_is_tfl:
            issue = "Near TFL but Ownership != TFL"
        elif owner_is_tfl and not near:
            issue = "Ownership=TFL but not near TFL"
        if not issue:
            continue
        rows.append(
            {
                "Issue": issue,
                "Borough": row.get("Borough", ""),
                "Name": row.get("name", ""),
                "Id": row.get("id", ""),
                "Ownership": owner,
                "OneWay": row.get("OneWay", ""),
                "LengthInM": int(round(line_length_m(coords))) if coords else 0,
                "DistanceToTFL_m": round(distance, 2) if distance is not None else None,
            }
        )
    return pd.DataFrame(rows)
