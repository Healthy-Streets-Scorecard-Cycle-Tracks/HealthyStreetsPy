"""Manual test harness for CycleRoutes designation lookup."""
from cycle_routes import debug_cycle_suggestions, nearest_cycle_label, suggest_cycle_designation

"""
Paste the log line here to run a quick lookup test.
Example:
    LOG_LINE = \"CycleRoutes debug coords=[(51.466823, -0.300153), (51.466455, -0.300147), (51.465993, -0.300151)]\"
"""
LOG_LINE = ""


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


COORDS = _coords_from_log(LOG_LINE)


def main() -> None:
    if not COORDS:
        print("No coords found. Paste the log line into LOG_LINE first.")
        return
    print("Suggest:", suggest_cycle_designation(COORDS))
    print("Nearest:", nearest_cycle_label(COORDS))
    print("Debug sweep:")
    for buffer_m, ratio, overlap_m, max_dist, label in debug_cycle_suggestions(COORDS):
        print(f"  buffer={buffer_m} ratio={ratio} overlap={overlap_m} max_dist={max_dist} -> {label}")


if __name__ == "__main__":
    main()
