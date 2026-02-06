import json
from typing import Callable, List, Optional, Tuple

from config import LCC_TFL_GEOJSON, TFL_GEOJSON, logger
from geo_utils import sample_lat

try:
    from shapely.geometry import shape
    from shapely.geometry import LineString, Point, Polygon
    from shapely.strtree import STRtree
    from shapely.ops import transform as shapely_transform
except Exception:  # pragma: no cover
    shape = None
    LineString = None
    Point = None
    Polygon = None
    STRtree = None
    shapely_transform = None


_CACHE = None


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


def _load_geojson(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        logger.exception("Failed to load geojson %s", path)
        return None


def _iter_coords(coords):
    if not coords:
        return []
    if isinstance(coords[0], (float, int)):
        return [coords]
    out = []
    for part in coords:
        out.extend(_iter_coords(part))
    return out


def _bbox_from_coords(coords) -> Optional[Tuple[float, float, float, float]]:
    flat = _iter_coords(coords)
    if not flat:
        return None
    xs = [pt[0] for pt in flat if len(pt) > 1]
    ys = [pt[1] for pt in flat if len(pt) > 1]
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _ensure_cache():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if shape is None or STRtree is None or shapely_transform is None or LineString is None or Polygon is None:
        logger.warning("TFL lookup disabled: shapely unavailable")
        _CACHE = (None, [], None, {})
        return _CACHE

    data = []
    counts = {}
    for path in (TFL_GEOJSON, LCC_TFL_GEOJSON):
        geo = _load_geojson(path)
        if geo:
            feats = geo.get("features", [])
            counts[path] = len(feats)
            data.extend(feats)
    if counts:
        logger.info("TFL lookup source counts: %s", counts)

    # Use lightweight equirectangular projection to avoid pyproj on Python 3.14.
    sample_lat_value = 51.5074
    for feat in data:
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        sample = sample_lat(coords)
        if sample is not None:
            sample_lat_value = sample
            break

    project = _fallback_projector(sample_lat_value)

    geoms: List[object] = []
    geom_type_counts = {}
    for feat in data:
        geom = feat.get("geometry")
        if not geom:
            continue
        gtype = (geom or {}).get("type")
        if gtype not in ("LineString", "MultiLineString", "Polygon", "MultiPolygon"):
            continue
        geom_type_counts[gtype] = geom_type_counts.get(gtype, 0) + 1
        try:
            def _proj(x, y, z=None):
                return project(x, y)
            if gtype == "MultiPolygon":
                # Avoid shapely MultiPolygon constructor (fails on Py3.14 + shapely 2.0.4).
                for poly_coords in geom.get("coordinates") or []:
                    if not poly_coords:
                        continue
                    shell = poly_coords[0]
                    holes = poly_coords[1:] if len(poly_coords) > 1 else []
                    shp = Polygon(shell, holes)
                    if shp.is_empty:
                        continue
                    shp_proj = shapely_transform(_proj, shp)
                    if shp_proj.is_empty:
                        continue
                    geoms.append(shp_proj)
            elif gtype == "Polygon":
                poly_coords = geom.get("coordinates") or []
                if not poly_coords:
                    continue
                shell = poly_coords[0]
                holes = poly_coords[1:] if len(poly_coords) > 1 else []
                shp = Polygon(shell, holes)
                if shp.is_empty:
                    continue
                shp_proj = shapely_transform(_proj, shp)
                if shp_proj.is_empty:
                    continue
                geoms.append(shp_proj)
            else:
                shp = shape(geom)
                if shp.is_empty:
                    continue
                shp_proj = shapely_transform(_proj, shp)
                if shp_proj.is_empty:
                    continue
                geoms.append(shp_proj)
        except Exception:
            continue

    if not geoms:
        logger.warning("TFL lookup cache empty")
        _CACHE = (None, [], None, {})
        return _CACHE

    tree = STRtree(geoms)
    logger.info("TFL lookup cache ready: %s features (types=%s)", len(geoms), geom_type_counts)
    geom_index = {id(geom): idx for idx, geom in enumerate(geoms)}
    _CACHE = (tree, geoms, project, geom_index)
    return _CACHE


def suggest_tfl_ownership(
    coords: List[Tuple[float, float]],
    buffer_m: float = 60.0,
    max_distance_m: float = 50.0,
) -> bool:
    if not coords or LineString is None or Point is None:
        return False
    tree, geoms, project, geom_index = _ensure_cache()
    if tree is None:
        return False


    try:
        proj = [project(lon, lat) for lat, lon in coords]
        if len(proj) < 2:
            route = Point(proj[0])
        else:
            route = LineString(proj)
    except Exception:
        return False
    if route.is_empty:
        return False

    buffered = route.buffer(buffer_m)
    candidates = tree.query(buffered)
    logger.info("TFL lookup candidates=%s buffer_m=%.1f", len(candidates), buffer_m)
    nearest = None
    for geom in candidates:
        if not hasattr(geom, "distance"):
            try:
                geom = geoms[int(geom)]
            except Exception:
                continue
        geom_idx = geom_index.get(id(geom))
        try:
            distance = route.distance(geom)
        except Exception:
            continue
        if nearest is None or distance < nearest:
            nearest = distance
        if distance <= max_distance_m:
            logger.info(
                "TFL lookup matched distance_m=%.1f (<= %.1f) geom_idx=%s",
                distance,
                max_distance_m,
                geom_idx,
            )
            return True
    if nearest is not None:
        logger.info("TFL lookup nearest distance_m=%.1f (threshold %.1f)", nearest, max_distance_m)
    if nearest is None:
        try:
            nearest_geom = tree.nearest(route)
            if not hasattr(nearest_geom, "distance"):
                nearest_geom = geoms[int(nearest_geom)]
            geom_idx = geom_index.get(id(nearest_geom))
            nearest = route.distance(nearest_geom)
            logger.info(
                "TFL lookup nearest (tree.nearest) distance_m=%.1f (threshold %.1f) geom_idx=%s",
                nearest,
                max_distance_m,
                geom_idx,
            )
            if nearest <= max_distance_m:
                logger.info("TFL lookup matched via nearest distance_m=%.1f (<= %.1f)", nearest, max_distance_m)
                return True
        except Exception:
            logger.exception("TFL lookup nearest failed")
    return False


def debug_tfl_bbox(coords: List[Tuple[float, float]]) -> Optional[dict]:
    if not coords:
        return None
    # route bbox in lon/lat
    xs = [lon for lat, lon in coords]
    ys = [lat for lat, lon in coords]
    if not xs or not ys:
        return None
    route_bbox = (min(xs), min(ys), max(xs), max(ys))

    data = []
    for path in (TFL_GEOJSON, LCC_TFL_GEOJSON):
        geo = _load_geojson(path)
        if geo:
            data.extend(geo.get("features", []))

    def bbox_distance(a, b) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        dx = max(bx1 - ax2, ax1 - bx2, 0)
        dy = max(by1 - ay2, ay1 - by2, 0)
        return (dx * dx + dy * dy) ** 0.5

    nearest_bbox = None
    nearest_dist = None
    for feat in data:
        geom = feat.get("geometry") or {}
        coords_raw = geom.get("coordinates")
        if not coords_raw:
            continue
        bbox = _bbox_from_coords(coords_raw)
        if not bbox:
            continue
        dist = bbox_distance(route_bbox, bbox)
        if nearest_dist is None or dist < nearest_dist:
            nearest_dist = dist
            nearest_bbox = bbox
    return {
        "route_bbox": route_bbox,
        "nearest_bbox": nearest_bbox,
        "nearest_dist_deg": nearest_dist,
    }


def debug_tfl_probe(coords: List[Tuple[float, float]], buffer_m: float = 2000.0) -> Optional[dict]:
    if not coords or LineString is None or Point is None:
        return None
    tree, geoms, project = _ensure_cache()
    if tree is None:
        return None
    try:
        proj = [project(lon, lat) for lat, lon in coords]
        if len(proj) < 2:
            route = Point(proj[0])
        else:
            route = LineString(proj)
    except Exception:
        return None
    if route.is_empty or route.length == 0:
        if route.is_empty:
            return None
    buffered = route.buffer(buffer_m)
    candidates = tree.query(buffered)
    nearest = None
    for geom in candidates:
        if not hasattr(geom, "distance"):
            try:
                geom = geoms[int(geom)]
            except Exception:
                continue
        try:
            dist = route.distance(geom)
        except Exception:
            continue
        if nearest is None or dist < nearest:
            nearest = dist
    return {
        "buffer_m": buffer_m,
        "candidate_count": len(candidates),
        "nearest_distance_m": nearest,
    }
