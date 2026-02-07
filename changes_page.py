from typing import Iterable, List, Optional, Set, Tuple

from shiny import ui

from config import MAP_COLORS, ONE_WAY_DASH
from data_processing import line_length_m, polyline_color
from grid_page import grid_assets, route_minimap


CHANGE_FIELDS = [
    ("name", "Name"),
    ("description", "Comments"),
    ("id", "Id"),
    ("Designation", "Designation"),
    ("OneWay", "Direction"),
    ("Flow", "Flow"),
    ("Protection", "Protection"),
    ("Ownership", "Ownership"),
    ("YearBuildBeforeFlag", "Built"),
    ("YearBuilt", "Year"),
    ("AuditedStreetView", "Audited StreetView"),
    ("AuditedInPerson", "Audited In Person"),
    ("Rejected", "Rejected"),
]


def build_changes_panel():
    return ui.nav_panel(
        "Changes",
        grid_assets(),
        ui.tags.style(
            """
            .hss-changes-list {
                display: flex;
                flex-direction: column;
                gap: 1rem;
            }
            .hss-change-details > summary {
                list-style: none;
                cursor: pointer;
                display: flex;
                align-items: flex-start;
                gap: 0.5rem;
            }
            .hss-change-details > summary::-webkit-details-marker {
                display: none;
            }
            .hss-change-card {
                border: 1px solid #e1e4e8;
                border-radius: 12px;
                padding: 1rem;
                background: #fff;
            }
            .hss-change-title {
                font-weight: 600;
                margin-bottom: 0.5rem;
            }
            .hss-change-row {
                display: flex;
                gap: 1rem;
                flex-wrap: wrap;
            }
            .hss-change-maps {
                display: flex;
                gap: 0.75rem;
                align-items: flex-start;
            }
            .hss-change-maps .hss-grid-map {
                width: 160px;
                height: 100px;
            }
            .hss-change-label {
                font-size: 12px;
                color: #666;
                margin-bottom: 0.2rem;
            }
            .hss-change-field {
                display: flex;
                gap: 0.5rem;
                align-items: baseline;
                margin-bottom: 0.25rem;
            }
            .hss-change-field-name {
                min-width: 140px;
                font-weight: 600;
            }
            .hss-change-old {
                text-decoration: line-through;
                color: #6c757d;
            }
            .hss-change-new {
                font-weight: 700;
                color: #111827;
            }
            .hss-change-neutral {
                color: #111827;
            }
            .hss-change-badge {
                display: inline-block;
                padding: 0.1rem 0.5rem;
                border-radius: 999px;
                font-size: 12px;
                line-height: 1.4;
                align-self: flex-start;
                margin-left: 0;
                background: #f1f5f9;
            }
            .hss-change-badge-changed {
                background: #fde68a;
                color: #92400e;
            }
            .hss-change-badge-added {
                background: #bbf7d0;
                color: #166534;
            }
            .hss-change-badge-removed {
                background: #fecaca;
                color: #991b1b;
            }
            .hss-change-removed {
                opacity: 0.75;
            }
            .hss-change-card-changed {
                background: #fff7ed;
            }
            .hss-change-card-added {
                background: #f0fdf4;
            }
            .hss-change-card-removed {
                background: #fef2f2;
            }
            .hss-change-goto {
                margin-left: auto;
            }
            .hss-change-group {
                margin-bottom: 1rem;
            }
            """
        ),
        ui.tags.script(
            """
            (function() {
                function loadState() {
                    try {
                        return JSON.parse(localStorage.getItem('hss_changes_open_v1') || '{}');
                    } catch (e) {
                        return {};
                    }
                }
                function saveState(state) {
                    try {
                        localStorage.setItem('hss_changes_open_v1', JSON.stringify(state || {}));
                    } catch (e) {
                        return;
                    }
                }
                function applyState(root) {
                    const state = loadState();
                    const nodes = (root || document).querySelectorAll('details.hss-change-details[data-change-id]');
                    nodes.forEach(function(node) {
                        const id = node.dataset.changeId;
                        if (!id) return;
                        if (state[id] === undefined) return;
                        node.open = !!state[id];
                    });
                }
                document.addEventListener('DOMContentLoaded', function() {
                    applyState(document);
                    document.addEventListener('toggle', function(ev) {
                        const node = ev.target;
                        if (!node || !node.matches || !node.matches('details.hss-change-details[data-change-id]')) return;
                        const state = loadState();
                        state[node.dataset.changeId] = !!node.open;
                        saveState(state);
                    }, true);
                    const observer = new MutationObserver(function(mutations) {
                        mutations.forEach(function(m) {
                            m.addedNodes.forEach(function(node) {
                                if (node.nodeType !== 1) return;
                                applyState(node);
                            });
                        });
                    });
                    observer.observe(document.body, { childList: true, subtree: true });
                });
            })();
            """
        ),
        ui.output_ui("changes_view"),
    )


def format_value(key: str, value) -> str:
    if value is None:
        return "—"
    if key in {"AuditedStreetView", "AuditedInPerson", "Rejected"}:
        return "Yes" if bool(value) else "No"
    if key == "YearBuildBeforeFlag":
        return "Before" if bool(value) else "In"
    text = str(value).strip()
    return text if text else "—"


def diff_fields(before_row, after_row) -> List[Tuple[str, str, str, bool]]:
    diffs = []
    for key, label in CHANGE_FIELDS:
        before_val = before_row.get(key) if before_row is not None else None
        after_val = after_row.get(key) if after_row is not None else None
        before_fmt = format_value(key, before_val)
        after_fmt = format_value(key, after_val)
        def _norm(val):
            try:
                import pandas as pd

                if pd.isna(val):
                    return None
            except Exception:
                pass
            if isinstance(val, str):
                return val.strip()
            return val

        before_norm = _norm(before_val)
        after_norm = _norm(after_val)
        changed = before_norm != after_norm
        diffs.append((label, before_fmt, after_fmt, changed))
    return diffs


def _route_style(row, colors, weight: int, highlight_active: bool, highlight_set: Set[str], dim_opacity: float):
    guid = row.get("guid") if row is not None else ""
    opacity = 0.9
    if highlight_active and guid and guid not in highlight_set:
        opacity = dim_opacity
    dash = ONE_WAY_DASH if row.get("OneWay") == "OneWay" else None
    color = polyline_color(row, colors) if row is not None else MAP_COLORS["polyline"]
    return color, opacity, dash


def _route_summary(row, prefix: str, *, direction: Optional[str] = None) -> str:
    name = str(row.get("name", "")).strip() if row is not None else ""
    if not name:
        name = "Unnamed"
    coords = row.get("_coords") or []
    length_m = int(round(line_length_m(coords))) if coords else 0
    dir_val = direction or (row.get("OneWay") if row is not None else None) or ""
    dir_text = dir_val or "TwoWay"
    return f"\"{name}\" - {length_m}m of {dir_text} - {prefix}"


def _route_summary_updated(after_row, changed_labels: Optional[List[str]] = None) -> str:
    name = str(after_row.get("name", "")).strip() if after_row is not None else ""
    if not name:
        name = "Unnamed"
    coords = after_row.get("_coords") or []
    length_m = int(round(line_length_m(coords))) if coords else 0
    dir_val = after_row.get("OneWay") or ""
    dir_text = dir_val or "TwoWay"
    changes = ""
    if changed_labels:
        if len(changed_labels) <= 3:
            trimmed = changed_labels
        else:
            trimmed = changed_labels[:2]
            trimmed.append(f"+{len(changed_labels) - 2} more")
        if len(trimmed) == 1:
            changes = " - " + trimmed[0] + " Changed"
        elif len(trimmed) == 2:
            changes = " - " + " and ".join(trimmed) + " Changed"
        else:
            changes = " - " + " / ".join(trimmed) + " Changed"
    return f"\"{name}\" - {length_m}m of {dir_text}{changes}"


def render_changes(
    *,
    edited: Iterable[Tuple[object, object]],
    created: Iterable[object],
    removed: Iterable[object],
    highlight_guids: Optional[Iterable[str]] = None,
    highlight_active: bool = False,
    dim_opacity: float = 0.3,
    route_colors: Optional[dict] = None,
    route_weight: int = 3,
    open_panels: Optional[Iterable[str]] = None,
):
    highlight_set = set(highlight_guids or [])
    colors = route_colors or MAP_COLORS
    edited_cards = []
    created_cards = []
    removed_cards = []

    def _field_list(diffs, only_changed: bool = False):
        items = []
        for label, before_val, after_val, changed in diffs:
            if only_changed and not changed:
                continue
            if changed:
                items.append(
                    ui.tags.div(
                        ui.tags.span(label, class_="hss-change-field-name"),
                        ui.tags.span(before_val, class_="hss-change-old"),
                        ui.tags.span("→"),
                        ui.tags.span(after_val, class_="hss-change-new"),
                        class_="hss-change-field",
                    )
                )
            else:
                items.append(
                    ui.tags.div(
                        ui.tags.span(label, class_="hss-change-field-name"),
                        ui.tags.span(after_val, class_="hss-change-neutral"),
                        class_="hss-change-field",
                    )
                )
        return ui.tags.div(*items)

    for before_row, after_row in edited:
        guid = after_row.get("guid")
        before_coords = before_row.get("_coords")
        after_coords = after_row.get("_coords")
        before_color, before_opacity, before_dash = _route_style(
            before_row, colors, route_weight, highlight_active, highlight_set, dim_opacity
        )
        after_color, after_opacity, after_dash = _route_style(
            after_row, colors, route_weight, highlight_active, highlight_set, dim_opacity
        )
        diffs = diff_fields(before_row, after_row)
        changed_labels = [label for label, _, _, changed in diffs if changed]
        if (before_coords or []) != (after_coords or []):
            changed_labels = ["Route"] + [label for label in changed_labels if label != "Route"]
        summary_title = _route_summary_updated(after_row, changed_labels)
        map_changed = False
        if (before_coords or []) != (after_coords or []):
            map_changed = True
        if before_row.get("OneWay") != after_row.get("OneWay"):
            map_changed = True
        if bool(before_row.get("Rejected", False)) != bool(after_row.get("Rejected", False)):
            map_changed = True
        edited_cards.append(
            ui.tags.details(
                ui.tags.summary(
                    ui.tags.span("Changed", class_="hss-change-badge hss-change-badge-changed"),
                    ui.tags.span(summary_title, class_="hss-change-title"),
                    ui.tags.button(
                        "Undo",
                        title="Undo all edits for this route",
                        class_="btn btn-sm btn-outline-secondary hss-grid-btn hss-change-undo",
                        **{"data-guid": str(guid), "data-action": "undo_edit"},
                    ),
                    ui.tags.button(
                        "↗",
                        title="Go to map",
                        class_="btn btn-sm btn-outline-primary hss-grid-btn hss-change-goto",
                        **{"data-guid": str(guid), "data-action": "goto"},
                    ),
                ),
                ui.tags.div(
                    ui.tags.div(
                        ui.tags.div("Before", class_="hss-change-label"),
                        route_minimap(
                            before_coords,
                            before_color,
                            before_opacity,
                            before_dash,
                            str(guid),
                            width=160,
                            height=100,
                            weight=route_weight,
                        ),
                    ),
                    ui.tags.div(
                        ui.tags.div("After", class_="hss-change-label"),
                        route_minimap(
                            after_coords,
                            after_color,
                            after_opacity,
                            after_dash,
                            str(guid),
                            width=160,
                            height=100,
                            weight=route_weight,
                        ),
                    ),
                    class_="hss-change-maps",
                ) if map_changed else ui.tags.div(),
                _field_list(diffs, only_changed=True),
                class_="hss-change-card hss-change-card-changed hss-change-details",
                open=True,
                **{"data-change-id": f"changed-{guid}"},
            )
        )

    for row in created:
        guid = row.get("guid")
        coords = row.get("_coords")
        color, opacity, dash = _route_style(row, colors, route_weight, highlight_active, highlight_set, dim_opacity)
        diffs = diff_fields(None, row)
        summary_title = _route_summary(row, "Added")
        created_cards.append(
            ui.tags.details(
                ui.tags.summary(
                    ui.tags.span("Added", class_="hss-change-badge hss-change-badge-added"),
                    ui.tags.span(summary_title, class_="hss-change-title"),
                    ui.tags.button(
                        "Undo",
                        title="Undo create (remove this route)",
                        class_="btn btn-sm btn-outline-secondary hss-grid-btn hss-change-undo",
                        **{"data-guid": str(guid), "data-action": "undo_create"},
                    ),
                    ui.tags.button(
                        "↗",
                        title="Go to map",
                        class_="btn btn-sm btn-outline-primary hss-grid-btn hss-change-goto",
                        **{"data-guid": str(guid), "data-action": "goto"},
                    ),
                ),
                ui.tags.div(
                    ui.tags.div("Added", class_="hss-change-label"),
                    route_minimap(
                        coords,
                        color,
                        opacity,
                        dash,
                        str(guid),
                        width=160,
                        height=100,
                        weight=route_weight,
                    ),
                    class_="hss-change-maps",
                ),
                _field_list(diffs),
                class_="hss-change-card hss-change-card-added hss-change-details",
                open=True,
                **{"data-change-id": f"added-{guid}"},
            )
        )

    for row in removed:
        guid = row.get("guid")
        coords = row.get("_coords")
        color, opacity, dash = _route_style(row, colors, route_weight, highlight_active, highlight_set, dim_opacity)
        diffs = diff_fields(row, None)
        summary_title = _route_summary(row, "Removed")
        removed_cards.append(
            ui.tags.details(
                ui.tags.summary(
                    ui.tags.span("Removed", class_="hss-change-badge hss-change-badge-removed"),
                    ui.tags.span(summary_title, class_="hss-change-title"),
                    ui.tags.button(
                        "Undo",
                        title="Undo delete (restore this route)",
                        class_="btn btn-sm btn-outline-secondary hss-grid-btn hss-change-undo",
                        **{"data-guid": str(guid), "data-action": "undo_remove"},
                    ),
                ),
                ui.tags.div(
                    ui.tags.div("Removed", class_="hss-change-label"),
                    route_minimap(
                        coords,
                        color,
                        opacity,
                        dash,
                        str(guid),
                        width=160,
                        height=100,
                        weight=route_weight,
                    ),
                    class_="hss-change-maps",
                ),
                _field_list(diffs),
                class_="hss-change-card hss-change-card-removed hss-change-removed hss-change-details",
                open=True,
                **{"data-change-id": f"removed-{guid}"},
            )
        )

    if not (edited_cards or created_cards or removed_cards):
        return ui.tags.div("No changes yet.")

    return ui.accordion(
        ui.accordion_panel(
            f"Changed ({len(edited_cards)})",
            ui.tags.div(*edited_cards, class_="hss-changes-list") if edited_cards else ui.tags.div("No changes."),
            class_="hss-change-group",
            value="changed",
        ),
        ui.accordion_panel(
            f"Added ({len(created_cards)})",
            ui.tags.div(*created_cards, class_="hss-changes-list") if created_cards else ui.tags.div("No additions."),
            class_="hss-change-group",
            value="added",
        ),
        ui.accordion_panel(
            f"Removed ({len(removed_cards)})",
            ui.tags.div(*removed_cards, class_="hss-changes-list") if removed_cards else ui.tags.div("No removals."),
            class_="hss-change-group",
            value="removed",
        ),
        id="hss_changes_accordion",
        open=list(open_panels) if open_panels is not None else True,
    )
