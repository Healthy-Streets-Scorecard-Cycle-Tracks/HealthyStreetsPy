# Codex Notes (HealthyStreetsShinyPy)

## Collaboration Rules

- Keep a high level of logging to help debug issues.
- Record significant design decisions in the README.
- Add setup and run instructions to the README as they come up.
- If we spend a long time resolving a tricky issue, add a note about it in the README under a "thorny/fragile issues" section.
- Minimize full map re-renders; prefer targeted layer updates for metadata edits.
- When adding/changing map bridge messages, log them on both client and server.
- Prefer clipping routes to the borough boundary on commit rather than hard blocking during edits.
- If we change editing tools (e.g., Geoman vs Leaflet.draw), note it in README and CODEX.
- For Shiny UI controls and layouts, consult https://shiny.posit.co/py/ first, especially:
  - https://shiny.posit.co/py/components/ for components
  - https://shiny.posit.co/py/layouts/ for layouts
- Prefer vanilla Shiny components over custom CSS where possible; keep CSS minimal.
- Prefer clean reactive flows over ad-hoc flags; avoid hacks unless necessary and document them.
- Keep grid actions (GoTo/Delete) wired via custom messages rather than per-row reactive inputs to avoid loops.
- Keep README updated with user-facing behavior changes and fragile issues.
- Be careful not to delete core files (especially `app.py`); before any major refactor, create a timestamped backup folder in `_backups/`.
- Route styling schemes/width are main-map only; minimap styling should remain stable unless explicitly requested.
- Keep preference persistence lightweight (localStorage + minimal JS), and restore only when inputs exist.
- CycleRoutes lookup uses a cached spatial index (STRtree) to suggest a designation for new routes; keep it fast and read-only.
- Preferred wording in UI/docs: use “Added / Removed / Changed” (not Created/Deleted/Edited).
- Always await or `asyncio.create_task()` any `session.send_custom_message(...)` calls to avoid dropped messages and runtime warnings. Prefer a shared helper when adding new message paths.
- Any callbacks invoked from worker threads (e.g., retry hooks inside `asyncio.to_thread`) must schedule UI updates or new tasks using `loop.call_soon_threadsafe(...)` to avoid “no running event loop” errors.
- Do not wrap `send_custom(...)` in `asyncio.create_task(...)` since it already handles scheduling; wrapping it can raise “coroutine expected” errors.
- Suggestions tab is intentionally a placeholder for future QA tooling (naming gaps, TfL mismatches, designation checks).
- Deployment target uses PROJ 8.2.1; keep pyproj pinned to 3.4.x and Python at 3.11.

## Project Structure

- Keep `app.py` as a thin entry point with `app_ui` wiring and server logic.
- Place layout/JS/CSS in `ui_layout.py`.
- Keep shared UI JS/CSS snippets in `ui_assets.py`.
- Keep Folium + Leaflet bridge code in `map_folium.py`.
- Keep Google Sheets and access-table logic in `data_io.py`.
- Keep data prep, history updates, and parsing utilities in `data_processing.py`.
- Keep geo helpers (KML/GeoJSON/EWKT/clipping) in `geo_utils.py`.
- Keep region load/save/discard logic in `server_regions.py`.
- Keep highlight logic in `server_highlight.py`.
- Keep grid actions in `server_grid.py`.
- Keep geojson edit/create handlers in `server_geojson.py`.
- Keep map rendering in `server_map.py`.
- Keep selection + edit sync in `server_selection.py`.
- Keep report generation in `reports.py` and helpers (geojson/excel/coloring) in `report_utils.py`.
- Add other modules to keep logic together - but always update this file (and the README) when you do.
