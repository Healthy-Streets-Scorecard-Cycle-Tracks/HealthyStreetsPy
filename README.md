# HealthyStreetsShinyPy

Python Shiny rewrite of the Healthy Streets editor, modeled after the original R Shiny app.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
shiny run --reload app.py
```

## Setup Tips

- Activate the venv: `source .venv/bin/activate`
- Check Python: `python --version` (3.12+ recommended; 3.14 works with numpy>=2.4)
- Upgrade pip if installs fail: `python -m pip install -U pip setuptools wheel`
- If Thunderforest tiles don’t appear, ensure `THUNDER_FOREST_KEY` is exported in the same shell before starting Shiny.
- If Sheets access fails, confirm the service account email is shared on the sheet and that one of the Google credential env vars is set.
- Local-only env files (gitignored):
  - `HealthyStreetsShinyPy/.envrc` (for direnv)
  - `HealthyStreetsShinyPy/.local_env.sh` (source manually)

## Configuration

Set environment variables before running (no secrets in README):

- `THUNDER_FOREST_KEY`: Thunderforest API key (for OpenCycleMap tiles).
- `NOMINATIM_ENABLED`: Set to `1` to enable reverse-geocoding new route names.
- `NOMINATIM_USER_AGENT`: User agent string for Nominatim (required when enabled).
- `NOMINATIM_EMAIL`: Optional contact email appended to the user agent.
- `GOOGLE_APPLICATION_CREDENTIALS`: Path to a Google service account JSON file, or
- `GSHEETS_SERVICE_ACCOUNT_JSON`: The JSON content of the service account key.
- `SHINY_SERVER_HOST`: Optional host value used by the local auto-login guard (defaults to `localhost`).

If no credentials are supplied, the app attempts to read the sheet via public CSV export.

Edits are written back by replacing the entire worksheet, matching the behavior of the R app.

## Notes

- Click a route on the map to load its metadata into the right-hand editor panel.
- Route edits are applied in-memory; use "Save current borough" to write the full sheet back.
- Inline geometry editing uses Leaflet Geoman and will update the selected route when edits are made.
- New routes are clipped to the current borough on save; if a line crosses the boundary the out-of-borough segments are removed.
- New routes get a default ID (three-word slug). When Nominatim is enabled, the route name is reverse-geocoded from the first point.
- Grid actions ("Go to" / "Delete") are handled via custom Shiny messages to avoid reactive loops.
- Highlighting supports: Created since, Edited since, Owned by, Audited status. Non-highlighted routes are dimmed.
- The main map supports multiple route color schemes (Default, Neon, Contrast, OCM) and a route width slider; minimaps always use the default palette.
- The app stores lightweight UI preferences in local browser storage (route style, width, basemap, highlight options, last borough) and restores them on reload.
- Cycle Routes reference data is loaded once at startup from `Helpers/CycleRoutes.json` (source: https://cycling.data.tfl.gov.uk/CycleRoutes/CycleRoutes.json, downloaded 2026-02-06).
- When creating a new route, the app checks CycleRoutes for overlap and suggests the `Label` as the designation when a close match is found.
- When creating a new route, the app checks TFL reference layers; if the route is close to a TFL asset it auto-sets `Ownership` to `TFL`.
- TfL polygon handling avoids Shapely's `MultiPolygon` constructor on Python 3.14 (it errors with Shapely 2.0.4); polygons are built ring-by-ring instead. The lookup logs the matched geometry index for debugging.

### CycleRoutes Debug Harness

If CycleRoutes matching needs investigation, use `test_cycle_lookup.py`:

1. Copy the log line that looks like:
   `CycleRoutes debug coords=[(lat, lon), ...]`
2. Paste it into `LOG_LINE` in `test_cycle_lookup.py`.
3. Run: `python test_cycle_lookup.py`

This prints the suggested designation, nearest label, and a parameter sweep.

### TfL Lookup Debug Harness

If TfL ownership matching needs investigation, use `test_tfl_lookup.py`:

1. Copy the log line that looks like:
   `CycleRoutes debug coords=[(lat, lon), ...]`
2. Paste it into `LOG_LINE` in `test_tfl_lookup.py`.
3. Run: `python test_tfl_lookup.py`

This prints whether TfL ownership is detected and a proximity probe summary.

## Project Structure

The Python Shiny app is split into a small set of focused modules:

- `app.py`: Entry point. Wires `app_ui` and `server`, and hosts reactive logic.
- `config.py`: App constants, paths, map colors, logging config, and choice lists.
- `ui_layout.py`: All layout, sidebar controls, and the parent-page JS/CSS used for the map bridge.
- `ui_assets.py`: Shared JS/CSS snippets used by the layout.
- `map_folium.py`: Folium map construction, Geoman control, and the `ShinyBridge` (iframe <-> Shiny message bridge).
- `data_io.py`: Google Sheets access and the access-table cache.
- `data_processing.py`: Dataframe preparation, route parsing, history updates, line length, date parsing.
- `geo_utils.py`: KML/GeoJSON helpers, EWKT conversion, and borough clipping.
- `time_utils.py`: Small date helpers (e.g., `today_string()`).
- `grid_page.py`: Grid view layout + mini-map rendering and grid action wiring.
- `change_tracking.py`: Helpers for summarising added/removed/changed rows.
- `server_grid.py`: Grid actions (Go to/Delete) and related handlers.
- `server_highlight.py`: Highlight filtering logic + UI controls.
- `server_geojson.py`: GeoJSON edit/create handlers for the map.
- `server_map.py`: Map rendering to iframe.
- `server_selection.py`: Map selection handling + edit-panel sync.
- `server_regions.py`: Region load/save/discard and change tracking hooks.

This split keeps map/JS concerns isolated from data logic and UI layout, and makes it easier to debug without scrolling a single giant file.

## Google Auth

This app uses a Google **service account** for Sheets access. You have two ways to supply credentials:

1. File path (recommended):
   - Set `GOOGLE_APPLICATION_CREDENTIALS` to the absolute path of a downloaded service account JSON file.
2. JSON content:
   - Set `GSHEETS_SERVICE_ACCOUNT_JSON` to the raw JSON contents of the service account key.

The service account email must be **shared on the Google Sheets** you want to read/write.

If no credentials are provided, the app falls back to **public CSV export** (read-only).

## Access Control (Passwords)

The login modal validates passwords against the `Access` sheet in:

- `1yir2yFrlCX614XVnVbKKX-DRhojOPtKP1YQv4luMu4s`

Rules:
- Password with `Region = All` can edit all regions.
- Password with a single region can only edit that region.
- Invalid password keeps the modal open.

## Map Embedding + Shiny Bridge

The map is rendered with Folium and embedded as an **iframe** using `srcdoc`.
This isolates Leaflet/JS from Shiny's own DOM bindings (avoids jQuery/selector errors).

Because the map runs inside an iframe, it cannot call `Shiny.setInputValue` directly.
Instead, the map uses `window.parent.postMessage(...)` to send events to the parent page.
The parent listens for these messages and forwards them into Shiny inputs:

- `selected_route`: fired when a route line is clicked
- `edited_geojson`: fired when a line is edited via Leaflet.draw
- `created_geojson`: fired when a new line is drawn

This bridge is implemented in `ShinyBridge` inside `map_folium.py`.

## Thorny / Fragile Issues

- **Selection after creating a route**: the map may emit a stale `selected_route` event after a create. We ignore selection events for ~1s after a create and explicitly select the new route from the server.
- **KML geometry conversion**: fastkml geometries sometimes fail `__geo_interface__` conversion; we fall back to WKT parsing in `geo_utils.to_shapely_geom`.

## Notes on Dependencies

`fastkml` currently depends on `pkg_resources`, which is slated for removal in a future `setuptools` release.
To keep the app stable, `setuptools` is pinned to `<81` in `requirements.txt`.
