"""Manual test harness for TfL ownership lookup."""
from tfl_lookup import suggest_tfl_ownership, debug_tfl_probe, debug_tfl_bbox

# Paste log line here, e.g.:
LOG_LINE = "CycleRoutes debug coords=[(51.46497, -0.298262), (51.465986, -0.293541)]"
#LOG_LINE = ""


def _coords_from_log(line: str):
    if not line:
        return []
    if "coords=" in line:
        line = line.split("coords=", 1)[1]
    line = line.strip()
    try:
        return eval(line, {"__builtins__": {}}, {})
    except Exception:
        return []


def main() -> None:
    coords = _coords_from_log(LOG_LINE)
    if not coords:
        print("No coords found. Paste the log line into LOG_LINE first.")
        return
    print("Suggest TFL:", suggest_tfl_ownership(coords))
    print("Probe:", debug_tfl_probe(coords))
    bbox_info = debug_tfl_bbox(coords)
    if bbox_info:
        print("BBoxes:", bbox_info)
        _print_bbox_ascii(bbox_info)
    _point_probe()


def _print_bbox_ascii(info: dict, width: int = 40, height: int = 12) -> None:
    route_bbox = info.get("route_bbox")
    nearest_bbox = info.get("nearest_bbox")
    if not route_bbox or not nearest_bbox:
        return
    rx1, ry1, rx2, ry2 = route_bbox
    tx1, ty1, tx2, ty2 = nearest_bbox
    minx = min(rx1, tx1)
    maxx = max(rx2, tx2)
    miny = min(ry1, ty1)
    maxy = max(ry2, ty2)
    if maxx == minx or maxy == miny:
        return
    def _scale(x, y):
        cx = int((x - minx) / (maxx - minx) * (width - 1))
        cy = int((y - miny) / (maxy - miny) * (height - 1))
        return cx, (height - 1 - cy)
    grid = [[" " for _ in range(width)] for _ in range(height)]
    def _draw_box(bbox, ch):
        x1, y1, x2, y2 = bbox
        x1i, y1i = _scale(x1, y1)
        x2i, y2i = _scale(x2, y2)
        for x in range(min(x1i, x2i), max(x1i, x2i) + 1):
            if 0 <= y1i < height: grid[y1i][x] = ch
            if 0 <= y2i < height: grid[y2i][x] = ch
        for y in range(min(y1i, y2i), max(y1i, y2i) + 1):
            if 0 <= y < height: grid[y][x1i] = ch
            if 0 <= y < height: grid[y][x2i] = ch
    _draw_box(route_bbox, "R")
    _draw_box(nearest_bbox, "T")
    print("ASCII bbox sketch (R=route, T=TFL):")
    for row in grid:
        print("".join(row))


def _point_probe() -> None:
    # Known point expected inside a TFL polygon
    point_coords = [(51.461208761245835, -0.3131919107576756)]
    print("Point probe (expected inside TfL polygon):")
    print("  Suggest TFL:", suggest_tfl_ownership(point_coords))
    print("  Probe:", debug_tfl_probe(point_coords))
    bbox_info = debug_tfl_bbox(point_coords)
    if bbox_info:
        print("  BBoxes:", bbox_info)


if __name__ == "__main__":
    main()
