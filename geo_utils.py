import json
from typing import List, Optional, Tuple

from config import logger

try:
    from fastkml import kml as fastkml
except Exception:  # pragma: no cover
    fastkml = None

try:
    from shapely import wkt as shapely_wkt
    from shapely.geometry import LineString, shape as shapely_shape
    from shapely.geometry.base import BaseGeometry
except Exception:  # pragma: no cover
    shapely_wkt = None
    LineString = None
    shapely_shape = None
    BaseGeometry = None

try:
    from pyproj import Transformer
except Exception:  # pragma: no cover
    Transformer = None


def to_shapely_geom(geom: object) -> Optional[object]:
    if geom is None:
        return None
    if shapely_shape is None:
        return None
    if BaseGeometry is not None and isinstance(geom, BaseGeometry):
        return geom
    if shapely_wkt is not None and hasattr(geom, "wkt"):
        try:
            return shapely_wkt.loads(geom.wkt)
        except Exception:
            logger.exception("Failed to convert WKT to shapely geometry")
    try:
        return shapely_shape(geom.__geo_interface__)
    except Exception:
        try:
            return shapely_shape(geom)
        except Exception:
            logger.exception("Failed to convert geo interface to shapely geometry")
            return None


def load_kml_geometries(path: str) -> List[Tuple[str, object]]:
    if fastkml is None:
        raise RuntimeError("fastkml not available")

    with open(path, "rb") as fh:
        kml_doc = fastkml.KML()
        kml_doc.from_string(fh.read())

    results: List[Tuple[str, object]] = []

    def _walk(features):
        for feat in features:
            if hasattr(feat, "features"):
                _walk(feat.features())
            if hasattr(feat, "geometry") and feat.geometry:
                geom = to_shapely_geom(feat.geometry)
                if geom is not None:
                    results.append((getattr(feat, "name", "") or "", geom))

    _walk(kml_doc.features())
    return results


def _sample_coord(coords):
    if not coords:
        return None
    if isinstance(coords[0], (float, int)):
        return coords
    return _sample_coord(coords[0])


def sample_lat(coords: object) -> Optional[float]:
    if not coords:
        return None
    if isinstance(coords[0], (float, int)):
        return coords[1] if len(coords) > 1 else None
    try:
        return sample_lat(coords[0])
    except Exception:
        return None


def load_geojson(path: str, source_epsg: Optional[int] = None) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not source_epsg:
            return data
        if Transformer is None:
            logger.warning("GeoJSON %s expects EPSG:%s but pyproj is unavailable", path, source_epsg)
            return data
        try:
            transformer = Transformer.from_crs(f"EPSG:{source_epsg}", "EPSG:4326", always_xy=True)
        except Exception:
            transformer = None
        if transformer is None:
            logger.warning("GeoJSON %s expects EPSG:%s but no transformer available", path, source_epsg)
            return data

        def _reproject_coords(coords):
            if isinstance(coords[0], (float, int)):
                x, y = coords
                lon, lat = transformer.transform(x, y)
                return [lon, lat]
            return [_reproject_coords(c) for c in coords]

        for feature in data.get("features", []):
            geom = feature.get("geometry") or {}
            coords = geom.get("coordinates")
            if coords:
                geom["coordinates"] = _reproject_coords(coords)
        return data
    except Exception:
        logger.exception("Failed to load geojson %s", path)
        return None


def geojson_geom_types(data: Optional[dict]) -> dict:
    if not data:
        return {}
    counts: dict = {}
    for feat in data.get("features", []):
        gtype = (feat.get("geometry") or {}).get("type") or "unknown"
        counts[gtype] = counts.get(gtype, 0) + 1
    return counts


def strip_ewkt(value: str) -> str:
    if value.startswith("SRID="):
        return value.split(";", 1)[1]
    return value


def wkt_to_latlon(wkt_text: str) -> List[Tuple[float, float]]:
    if shapely_wkt is None:
        raise RuntimeError("shapely not available")
    geom = shapely_wkt.loads(strip_ewkt(wkt_text))
    if geom.geom_type == "LineString":
        return [(lat, lon) for lon, lat in geom.coords]
    if geom.geom_type == "MultiLineString":
        coords: List[Tuple[float, float]] = []
        for line in geom.geoms:
            coords.extend([(lat, lon) for lon, lat in line.coords])
        return coords
    return []


def coords_to_ewkt(coords: List[Tuple[float, float]]) -> str:
    if LineString is None:
        raise RuntimeError("shapely not available")
    line = LineString([(lon, lat) for lat, lon in coords])
    wkt = line.wkt
    return f"SRID=4326;{wkt}"


def clip_coords_to_borough(
    coords: List[Tuple[float, float]],
    borough_geom: Optional[object],
) -> Tuple[List[Tuple[float, float]], bool]:
    if not coords:
        logger.info("clip_coords_to_borough: no coords")
        return coords, False
    if borough_geom is None:
        logger.info("clip_coords_to_borough: no borough geometry loaded")
        return coords, False
    if LineString is None:
        logger.info("clip_coords_to_borough: shapely not available")
        return coords, False
    try:
        line = LineString([(lon, lat) for lat, lon in coords])
        clipped = line.intersection(borough_geom)
        if clipped.is_empty:
            logger.info("clip_coords_to_borough: empty after clip")
            return [], True
        if clipped.geom_type == "LineString":
            result = clipped
        else:
            from shapely.ops import linemerge

            merged = linemerge(clipped)
            if merged.geom_type == "LineString":
                result = merged
            else:
                parts = list(merged.geoms) if hasattr(merged, "geoms") else []
                if not parts:
                    logger.info("clip_coords_to_borough: no parts after merge")
                    return [], True
                result = max(parts, key=lambda g: g.length)
        out = [(coord[1], coord[0]) for coord in result.coords]
        return out, True if out != coords else False
    except Exception:
        logger.exception("Failed to clip line to borough")
        return coords, False
