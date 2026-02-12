import json
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Tuple

from config import CYCLE_ROUTES_JSON, logger
from geo_utils import sample_lat

try:
    from shapely.geometry import LineString
    from shapely.strtree import STRtree
except Exception:  # pragma: no cover
    LineString = None
    STRtree = None

try:
    from pyproj import Transformer
except Exception:  # pragma: no cover
    Transformer = None


@dataclass
class CycleRouteFeature:
    geom: object
    label: str
    programme: str


_CACHE = None


def _iter_lines(coords: object) -> Iterable[List[Tuple[float, float]]]:
    if not coords:
        return []
    if isinstance(coords[0], (float, int)):
        return [[(coords[0], coords[1])]]
    if isinstance(coords[0], (list, tuple)) and coords and isinstance(coords[0][0], (float, int)):
        return [[(lon, lat) for lon, lat in coords]]
    lines = []
    for part in coords:
        if not part:
            continue
        if isinstance(part[0], (float, int)):
            lines.append([(lon, lat) for lon, lat in part])
        else:
            for sub in _iter_lines(part):
                lines.append(sub)
    return lines


def _fallback_projector(lat0: float) -> Callable[[float, float], Tuple[float, float]]:
    # Simple equirectangular approximation (meters) centered on lat0.
    import math

    r = 6371000.0
    cos_lat = math.cos(math.radians(lat0))

    def _project(lon: float, lat: float) -> Tuple[float, float]:
        x = math.radians(lon) * r * cos_lat
        y = math.radians(lat) * r
        return x, y

    return _project


def _load_cycle_routes_raw() -> Optional[dict]:
    try:
        with open(CYCLE_ROUTES_JSON, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        logger.exception("Failed to load CycleRoutes.json")
        return None


def _ensure_cache():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if LineString is None or STRtree is None:
        logger.warning("Cycle route lookup disabled: shapely unavailable")
        _CACHE = (None, [], {}, None)
        return _CACHE
    data = _load_cycle_routes_raw()
    if not data:
        _CACHE = (None, [], {}, None)
        return _CACHE
    # Use lightweight equirectangular projection to avoid pyproj issues on Python 3.14
    # (pyproj CRS parsing currently throws "expected bytes, str found" in this env).
    sample_lat_value = None
    for feat in data.get("features", []):
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        sample_lat_value = sample_lat(coords)
        if sample_lat_value is not None:
            break
    if sample_lat_value is None:
        sample_lat_value = 51.5074
    project = _fallback_projector(sample_lat_value)

    features: List[CycleRouteFeature] = []
    geoms = []
    geom_to_feature = {}
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        label = (props.get("Label") or "").strip()
        programme = (props.get("Programme") or "").strip()
        geom = (feat.get("geometry") or {}).get("coordinates")
        if not geom:
            continue
        for coords in _iter_lines(geom):
            try:
                proj = [project(lon, lat) for lon, lat in coords]
                line = LineString(proj)
            except Exception:
                continue
            if line.is_empty:
                continue
            feature = CycleRouteFeature(geom=line, label=label, programme=programme)
            features.append(feature)
            geoms.append(line)
            geom_to_feature[id(line)] = feature

    tree = STRtree(geoms)
    _CACHE = (tree, features, geom_to_feature, geoms, project)
    logger.info("Cycle route lookup cache ready: %s features", len(features))
    return _CACHE


def get_cycle_route_index(programmes: Optional[Iterable[str]] = None):
    if LineString is None or STRtree is None:
        return None, [], {}, None
    tree, features, _, _, project = _ensure_cache()
    if tree is None:
        return None, [], {}, None
    programme_set = {p.strip() for p in (programmes or [])}
    filtered = []
    for feature in features:
        if programme_set and feature.programme not in programme_set:
            continue
        if not feature.label:
            continue
        filtered.append(feature)
    geoms = [f.geom for f in filtered]
    if not geoms:
        return None, [], {}, project
    filtered_tree = STRtree(geoms)
    geom_to_feature = {id(f.geom): f for f in filtered}
    logger.info(
        "Cycle route index: programmes=%s features=%s",
        list(programme_set) if programme_set else "all",
        len(filtered),
    )
    return filtered_tree, geoms, geom_to_feature, project


def suggest_cycle_designation(
    coords: List[Tuple[float, float]],
    buffer_m: float = 25.0,
    min_overlap_ratio: float = 0.3,
    min_overlap_m: float = 150.0,
    max_distance_m: float = 40.0,
) -> Optional[str]:
    """Return a CycleRoutes Label if the route overlaps a known cycle route.

    Uses a buffered intersection in Web Mercator for speed. Returns the first
    label with the best overlap ratio.
    """
    if not coords or LineString is None:
        return None
    tree, _, geom_to_feature, geoms, project = _ensure_cache()
    if tree is None:
        return None
    try:
        proj = [project(lon, lat) for lat, lon in coords]
        route = LineString(proj)
    except Exception:
        return None
    if route.is_empty or route.length == 0:
        return None

    buffered = route.buffer(buffer_m)
    candidates = tree.query(buffered)
    best_label = None
    best_ratio = 0.0
    best_distance = None
    for geom in candidates:
        if not hasattr(geom, "intersection"):
            try:
                geom = geoms[int(geom)]
            except Exception:
                continue
        try:
            overlap = route.intersection(geom)
        except Exception:
            continue
        overlap_len = 0.0 if overlap.is_empty else overlap.length
        ratio = overlap_len / route.length if route.length else 0.0
        try:
            distance = route.distance(geom)
        except Exception:
            distance = None
        passes_overlap = overlap_len >= min_overlap_m or ratio >= min_overlap_ratio
        passes_distance = distance is not None and distance <= max_distance_m
        if not (passes_overlap or passes_distance):
            continue
        feature = geom_to_feature.get(id(geom))
        if not feature or not feature.label:
            continue
        if passes_overlap:
            if ratio > best_ratio:
                best_ratio = ratio
                best_label = feature.label
                best_distance = distance
        elif passes_distance and best_label is None:
            best_label = feature.label
            best_distance = distance
        elif passes_distance and best_distance is not None and distance is not None:
            if distance < best_distance:
                best_label = feature.label
                best_distance = distance
    return best_label


def debug_cycle_suggestions(
    coords: List[Tuple[float, float]],
) -> List[Tuple[float, float, float, float, Optional[str]]]:
    tests = [
        (15.0, 0.2, 50.0, 20.0),
        (15.0, 0.1, 30.0, 20.0),
        (25.0, 0.2, 50.0, 25.0),
        (25.0, 0.3, 150.0, 30.0),
        (35.0, 0.2, 100.0, 30.0),
        (50.0, 0.2, 100.0, 40.0),
        (50.0, 0.1, 50.0, 40.0),
        (75.0, 0.1, 50.0, 50.0),
        (75.0, 0.05, 30.0, 60.0),
        (100.0, 0.05, 30.0, 80.0),
    ]
    results = []
    for buffer_m, ratio, overlap_m, max_dist in tests:
        label = suggest_cycle_designation(
            coords,
            buffer_m=buffer_m,
            min_overlap_ratio=ratio,
            min_overlap_m=overlap_m,
            max_distance_m=max_dist,
        )
        results.append((buffer_m, ratio, overlap_m, max_dist, label))
    return results


def nearest_cycle_label(coords: List[Tuple[float, float]]) -> Optional[Tuple[str, float, str]]:
    if not coords or LineString is None:
        return None
    tree, _, geom_to_feature, geoms, project = _ensure_cache()
    if tree is None:
        return None
    try:
        proj = [project(lon, lat) for lat, lon in coords]
        route = LineString(proj)
    except Exception:
        return None
    if route.is_empty or route.length == 0:
        return None
    try:
        nearest_geom = tree.nearest(route)
    except Exception:
        return None
    if nearest_geom is None:
        return None
    if not hasattr(nearest_geom, "distance"):
        # Shapely 2 STRtree may return integer indices
        try:
            nearest_geom = geoms[int(nearest_geom)]
        except Exception:
            logger.warning("CycleRoutes nearest geom has no distance(): %s", type(nearest_geom))
            return None
    feature = geom_to_feature.get(id(nearest_geom))
    if not feature:
        return None
    try:
        distance = route.distance(nearest_geom)
    except Exception:
        logger.exception("CycleRoutes nearest distance failed for geom type=%s", type(nearest_geom))
        distance = None
    if distance is None:
        return None
    return feature.label, distance, feature.programme


def debug_cycle_probe(coords: List[Tuple[float, float]], buffer_m: float = 200.0) -> Optional[dict]:
    if not coords or LineString is None:
        return None
    tree, _, geom_to_feature, geoms, project = _ensure_cache()
    if tree is None:
        return None
    try:
        proj = [project(lon, lat) for lat, lon in coords]
        route = LineString(proj)
    except Exception:
        return None
    if route.is_empty or route.length == 0:
        return None
    buffered = route.buffer(buffer_m)
    candidates = tree.query(buffered)
    min_dist = None
    min_label = None
    min_programme = None
    for geom in candidates:
        if not hasattr(geom, "distance"):
            try:
                geom = geoms[int(geom)]
            except Exception:
                logger.warning("CycleRoutes probe candidate has no distance(): %s", type(geom))
                continue
        try:
            dist = route.distance(geom)
        except Exception:
            logger.exception("CycleRoutes probe distance failed for geom type=%s", type(geom))
            continue
        if min_dist is None or dist < min_dist:
            min_dist = dist
            feature = geom_to_feature.get(id(geom))
            if feature:
                min_label = feature.label
                min_programme = feature.programme
    return {
        "buffer_m": buffer_m,
        "candidate_count": len(candidates),
        "min_distance_m": min_dist,
        "min_label": min_label,
        "min_programme": min_programme,
    }
