import json
import logging
from typing import Iterable, List, Optional, Set, Tuple

from shiny import ui

from config import CHOICES, TOOLTIP_TEXT
from config import ONE_WAY_DASH
from data_processing import polyline_color
from config import MAP_COLORS


GRID_PAGE_SIZE = 10
logger = logging.getLogger("healthy_streets_shinypy")


def safe_guid(guid: object) -> str:
    return str(guid).replace("-", "_")


def grid_input_ids(guid: object) -> dict:
    sg = safe_guid(guid)
    return {
        "name": f"grid_name_{sg}",
        "designation": f"grid_designation_{sg}",
        "id": f"grid_id_{sg}",
        "oneway": f"grid_oneway_{sg}",
        "flow": f"grid_flow_{sg}",
        "protection": f"grid_protection_{sg}",
        "owner": f"grid_owner_{sg}",
        "audit_sv": f"grid_audit_sv_{sg}",
        "audit_ip": f"grid_audit_ip_{sg}",
        "rejected": f"grid_rejected_{sg}",
    }


def route_minimap(
    coords: Optional[List[Tuple[float, float]]],
    color: str,
    opacity: float,
    dash_array: Optional[str],
    guid: Optional[str] = None,
    width: int = 120,
    height: int = 80,
    weight: int = 2,
):
    if not coords:
        return ui.tags.div("No geometry", class_="hss-grid-map-empty")
    logger.info("Grid minimap attrs color=%s opacity=%s dash=%s coords=%s", color, opacity, dash_array, bool(coords))
    return ui.tags.div(
        class_="hss-grid-map",
        style=f"width:{width}px;height:{height}px;",
        **{
            "data-coords": json.dumps(coords),
            "data-color": color,
            "data-opacity": f"{opacity:.2f}",
            "data-dash": dash_array or "",
            "data-guid": guid or "",
            "data-weight": str(weight),
        },
    )

def grid_assets():
    return ui.TagList(
        ui.tags.style(
            """
            .hss-grid-controls {
                display: flex;
                gap: 0.75rem;
                align-items: center;
                margin-bottom: 0.5rem;
            }
            .hss-grid-map {
                border: 1px solid #d7dbe0;
                border-radius: 6px;
                background: #f8f9fa;
                position: relative;
                z-index: 1;
            }
            .hss-grid-map-empty {
                width: 120px;
                height: 80px;
                border: 1px solid #d7dbe0;
                border-radius: 6px;
                background: #f8f9fa;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 12px;
                color: #666;
            }
            .hss-grid-table td, .hss-grid-table th {
                vertical-align: top;
                padding: 0.35rem;
            }
            .hss-grid-table .form-control,
            .hss-grid-table .form-select {
                font-size: 0.85rem;
                padding: 0.2rem 0.4rem;
            }
            .hss-grid-table th {
                font-size: 0.9rem;
            }
            .hss-grid-table .shiny-input-container {
                margin-bottom: 0.2rem !important;
            }
            .hss-grid-audit .shiny-input-container {
                margin-bottom: 0.1rem !important;
            }
            .hss-grid-audit label {
                font-size: 12px;
            }
            .hss-grid-stack {
                display: flex;
                flex-direction: column;
                gap: 0.25rem;
            }
            .hss-grid-action {
                display: flex;
                flex-direction: column;
                gap: 0.25rem;
                align-items: flex-start;
            }
            .hss-grid-map-wrap {
                position: relative;
                display: inline-block;
            }
            .hss-grid-goto {
                position: absolute;
                top: 4px;
                right: 4px;
                width: 24px;
                height: 24px;
                padding: 0;
                border-radius: 6px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                font-size: 12px;
                z-index: 5;
                background: #ffffff;
                box-shadow: 0 1px 2px rgba(0,0,0,0.15);
            }
            .hss-grid-badge {
                position: absolute;
                top: 4px;
                left: 4px;
                z-index: 6;
            }
            .hss-grid-action .btn {
                padding: 0.2rem 0.5rem;
                font-size: 12px;
            }
            .hss-grid-table-wrap {
                overflow-x: auto;
            }
            .hss-grid-table th:first-child,
            .hss-grid-table td:first-child {
                position: sticky;
                left: 0;
                background: #fff;
                z-index: 1;
            }
            .hss-grid-table th:first-child {
                z-index: 2;
            }
            .hss-grid-row-added td {
                background: #f0fdf4;
            }
            .hss-grid-row-changed td {
                background: #fff7ed;
            }
            .hss-grid-row-added td:first-child {
                background: #f0fdf4;
            }
            .hss-grid-row-changed td:first-child {
                background: #fff7ed;
            }
            .hss-change-badge {
                display: inline-block;
                padding: 0.1rem 0.5rem;
                border-radius: 999px;
                font-size: 12px;
                line-height: 1.4;
                align-self: flex-start;
            }
            .hss-change-badge-changed {
                background: #fde68a;
                color: #92400e;
            }
            .hss-change-badge-added {
                background: #bbf7d0;
                color: #166534;
            }
            """
        ),
        ui.tags.script(
            """
            function hssEnsureLeaflet(cb) {
                if (window.L) {
                    cb();
                    return;
                }
                if (window.__hssLeafletLoading) {
                    const timer = setInterval(function() {
                        if (window.L) {
                            clearInterval(timer);
                            cb();
                        }
                    }, 50);
                    return;
                }
                window.__hssLeafletLoading = true;
                const link = document.createElement('link');
                link.rel = 'stylesheet';
                link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
                document.head.appendChild(link);
                const script = document.createElement('script');
                script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
                script.onload = function() { cb(); };
                document.head.appendChild(script);
            }

            function hssInitMiniMaps(root) {
                hssEnsureLeaflet(function() {
                    const nodes = (root || document).querySelectorAll('.hss-grid-map');
                    nodes.forEach(function(node) {
                        const raw = node.dataset.coords;
                        if (!raw) return;
                        const coords = JSON.parse(raw);
                        if (!coords || !coords.length) return;
                        const strokeColor = node.dataset.color || '#1c42d7';
                        const strokeOpacity = node.dataset.opacity ? parseFloat(node.dataset.opacity) : 0.9;
                        const dash = node.dataset.dash || null;
                        const weight = node.dataset.weight ? parseFloat(node.dataset.weight) : 2;
                        console.log('HSS grid minimap style', { color: strokeColor, opacity: strokeOpacity, dash: dash });
                        const coordsKey = JSON.stringify(coords);
                        if (node.dataset.hssInit) {
                            if (node._hssPolyline) {
                                node._hssPolyline.setStyle({ color: strokeColor, opacity: strokeOpacity, dashArray: dash, weight: weight });
                                console.log('HSS grid minimap updated');
                            }
                            if (node._hssCoordsKey !== coordsKey && node._hssPolyline) {
                                node._hssPolyline.setLatLngs(coords);
                                if (node._hssMap) {
                                    const bounds = L.latLngBounds(coords);
                                    node._hssMap.fitBounds(bounds, { padding: [2, 2] });
                                    const maxZoom = 15;
                                    if (node._hssMap.getZoom() > maxZoom) {
                                        node._hssMap.setZoom(maxZoom);
                                    }
                                }
                                node._hssCoordsKey = coordsKey;
                            }
                            return;
                        }
                        node.dataset.hssInit = '1';
                        node._hssCoordsKey = coordsKey;
                        const map = L.map(node, {
                            attributionControl: false,
                            zoomControl: false,
                            dragging: false,
                            scrollWheelZoom: false,
                            doubleClickZoom: false,
                            boxZoom: false,
                            keyboard: false,
                            tap: false,
                        });
                        node._hssMap = map;
                        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
                            maxZoom: 19,
                            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
                        }).addTo(map);
                        const line = L.polyline(coords, { color: strokeColor, opacity: strokeOpacity, dashArray: dash, weight: weight }).addTo(map);
                        node._hssPolyline = line;
                        console.log('HSS grid minimap created');
                        const bounds = L.latLngBounds(coords);
                        map.fitBounds(bounds, { padding: [2, 2] });
                        const maxZoom = 15;
                        if (map.getZoom() > maxZoom) {
                            map.setZoom(maxZoom);
                        }
                    });
                });
            }

            function hssRefreshMiniMaps() {
                hssInitMiniMaps(document);
            }

            document.addEventListener('DOMContentLoaded', function() {
                hssInitMiniMaps(document);
                window.hssSetGridPage = function(page) {
                    if (!window.Shiny || !window.Shiny.setInputValue) return;
                    window.Shiny.setInputValue('grid_page', page, {priority: 'event'});
                };
                document.addEventListener('click', function(ev) {
                    const btn = ev.target.closest('.hss-grid-btn');
                    if (!btn) return;
                    if (!window.Shiny || !window.Shiny.setInputValue) return;
                    const guid = btn.dataset.guid;
                    const action = btn.dataset.action;
                    if (!guid || !action) return;
                    const payload = { guid: guid, ts: Date.now() };
                    if (action === 'goto') {
                        window.Shiny.setInputValue('grid_goto_click', payload, {priority: 'event'});
                    } else if (action === 'delete') {
                        window.Shiny.setInputValue('grid_delete_click', payload, {priority: 'event'});
                    } else if (action.startsWith('undo_')) {
                        payload.action = action;
                        window.Shiny.setInputValue('changes_undo_click', payload, {priority: 'event'});
                    }
                });
                if (window.Shiny && window.Shiny.addCustomMessageHandler) {
                    window.Shiny.addCustomMessageHandler('hss_refresh_minimaps', function(payload) {
                        console.log('HSS grid: refresh minimaps', payload);
                        hssRefreshMiniMaps();
                    });
                    window.Shiny.addCustomMessageHandler('hss_update_minimap', function(payload) {
                        console.log('HSS grid: update minimap', payload);
                        if (!payload || !payload.guid) return;
                        const node = document.querySelector('.hss-grid-map[data-guid=\"' + payload.guid + '\"]');
                        if (!node) return;
                        node.dataset.color = payload.color || node.dataset.color;
                        node.dataset.opacity = (payload.opacity !== undefined) ? payload.opacity : node.dataset.opacity;
                        node.dataset.dash = payload.dash || '';
                        if (node._hssPolyline) {
                            node._hssPolyline.setStyle({
                                color: node.dataset.color || '#1c42d7',
                                opacity: parseFloat(node.dataset.opacity || '0.9'),
                                dashArray: node.dataset.dash || null,
                                weight: 2,
                            });
                        } else {
                            hssInitMiniMaps(node);
                        }
                    });
                }
                const observer = new MutationObserver(function(mutations) {
                    mutations.forEach(function(m) {
                        m.addedNodes.forEach(function(node) {
                            if (node.nodeType !== 1) return;
                            hssInitMiniMaps(node);
                        });
                    });
                });
                observer.observe(document.body, { childList: true, subtree: true });
            });
            """
        ),
    )


def build_grid_panel():
    return ui.nav_panel(
        "Grid",
        grid_assets(),
        ui.tags.div(
            ui.output_ui("grid_pager"),
            ui.output_text("grid_page_info"),
            class_="hss-grid-controls",
        ),
        ui.tags.div(
            ui.input_numeric("grid_page", "Page", value=1, min=1, step=1),
            style="display:none;",
        ),
        ui.output_ui("grid_view"),
    )


def render_grid(
    rows,
    page: int,
    highlight_guids: Optional[Iterable[str]] = None,
    highlight_active: bool = False,
    dim_opacity: float = 0.3,
    change_status: Optional[dict] = None,
) -> ui.Tag:
    start = max(page - 1, 0) * GRID_PAGE_SIZE
    end = start + GRID_PAGE_SIZE
    slice_rows = rows.iloc[start:end]
    highlight_set: Set[str] = set(highlight_guids or [])

    rows_ui = []
    status_map = change_status or {}
    for _, row in slice_rows.iterrows():
        guid = row.get("guid", "")
        safe_guid_val = safe_guid(guid)
        status = status_map.get(str(guid))
        coords = row.get("_coords")
        base_color = polyline_color(row, MAP_COLORS)
        dash_array = ONE_WAY_DASH if row.get("OneWay") == "OneWay" else None
        opacity = 0.9
        if highlight_active and guid and guid not in highlight_set:
            opacity = dim_opacity
        row_class = ""
        badge = None
        if status == "created":
            row_class = "hss-grid-row-added"
            badge = ui.tags.span("Added", class_="hss-change-badge hss-change-badge-added hss-grid-badge")
        elif status == "edited":
            row_class = "hss-grid-row-changed"
            badge = ui.tags.span("Changed", class_="hss-change-badge hss-change-badge-changed hss-grid-badge")
        rows_ui.append(
            ui.tags.tr(
                ui.tags.td(
                    ui.tags.div(
                        ui.tags.div(
                            badge if badge else "",
                            route_minimap(coords, base_color, opacity, dash_array, str(guid)),
                            ui.tags.button(
                                "↗",
                                title="Go to map",
                                class_="btn btn-sm btn-outline-primary hss-grid-btn hss-grid-goto",
                                **{"data-guid": str(guid), "data-action": "goto"},
                            ),
                            class_="hss-grid-map-wrap",
                        ),
                        class_="hss-grid-action",
                    )
                ),
                ui.tags.td(
                    ui.tags.div(
                        ui.input_text(
                            f"grid_name_{safe_guid_val}", 
                            "", 
                            value=str(row.get("name", "")),
                            placeholder="Name",
                            update_on="blur",
                        ),
                        ui.input_text(
                            f"grid_designation_{safe_guid_val}",
                            "",
                            value=str(row.get("Designation", "")),
                            placeholder="Designation",
                            update_on="blur",
                        ),
                        ui.input_text(
                            f"grid_id_{safe_guid_val}", 
                            "", 
                            value=str(row.get("id", "")),
                            placeholder="Id",
                            update_on="blur",
                        ),
                        class_="hss-grid-stack",
                    )
                ),
                ui.tags.td(
                    ui.tags.div(
                        ui.input_select(
                            f"grid_oneway_{safe_guid_val}",
                            "",
                            choices=["TwoWay", "OneWay"],
                            selected=row.get("OneWay", "TwoWay") or "TwoWay",
                        ),
                        ui.input_select(
                            f"grid_flow_{safe_guid_val}",
                            "",
                            choices=list(CHOICES["flow"].values()),
                            selected=row.get("Flow", "") or "",
                        ),
                        class_="hss-grid-stack",
                    )
                ),
                ui.tags.td(
                    ui.tags.div(
                        ui.input_select(
                            f"grid_protection_{safe_guid_val}",
                            "",
                            choices=list(CHOICES["protection"].values()),
                            selected=row.get("Protection", "") or "",
                        ),
                        ui.input_select(
                            f"grid_owner_{safe_guid_val}",
                            "",
                            choices=list(CHOICES["ownership"].values()),
                            selected=row.get("Ownership", "") or "",
                        ),
                        class_="hss-grid-stack",
                    )
                ),
                ui.tags.td(
                    ui.tags.div(
                        ui.input_checkbox(
                            f"grid_audit_sv_{safe_guid_val}",
                            "Audited StreetView",
                            value=bool(row.get("AuditedStreetView", False)),
                        ),
                        ui.input_checkbox(
                            f"grid_audit_ip_{safe_guid_val}",
                            "Audited In Person",
                            value=bool(row.get("AuditedInPerson", False)),
                        ),
                        ui.input_checkbox(
                            f"grid_rejected_{safe_guid_val}",
                            "Rejected",
                            value=bool(row.get("Rejected", False)),
                        ),
                        class_="hss-grid-audit",
                    )
                ),
                ui.tags.td(
                    ui.tags.button(
                        "Delete",
                        class_="btn btn-sm btn-danger hss-grid-btn",
                        **{"data-guid": str(guid), "data-action": "delete"},
                    )
                ),
                class_=row_class,
            )
        )

    if not rows_ui:
        return ui.tags.div("No routes to display.")

    return ui.tags.div(
        ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(
                    ui.tags.th("Map"),
                    ui.tags.th(
                        ui.tooltip(
                            ui.tags.span("Name / Designation / Id"),
                            f"{TOOLTIP_TEXT['name']} / {TOOLTIP_TEXT['designation']} / {TOOLTIP_TEXT['id']}",
                            placement="bottom",
                        )
                    ),
                    ui.tags.th(
                        ui.tooltip(
                            ui.tags.span("Direction / Flow"),
                            f"{TOOLTIP_TEXT['oneway']} / {TOOLTIP_TEXT['flow']}",
                            placement="bottom",
                        )
                    ),
                    ui.tags.th(
                        ui.tooltip(
                            ui.tags.span("Protection / Ownership"),
                            f"{TOOLTIP_TEXT['protection']} / {TOOLTIP_TEXT['ownership']}",
                            placement="bottom",
                        )
                    ),
                    ui.tags.th(
                        ui.tooltip(
                            ui.tags.span("Audited / Rejected"),
                            f"{TOOLTIP_TEXT['audited_online']} / {TOOLTIP_TEXT['audited_in_person']} / {TOOLTIP_TEXT['rejected']}",
                            placement="bottom",
                        )
                    ),
                    ui.tags.th(ui.tooltip(ui.tags.span("Delete"), "Remove this route", placement="bottom")),
                )
            ),
            ui.tags.tbody(*rows_ui),
            class_="table table-sm table-striped hss-grid-table",
        ),
        class_="hss-grid-table-wrap",
    )
