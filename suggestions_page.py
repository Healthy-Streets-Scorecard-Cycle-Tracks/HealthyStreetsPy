import json
from typing import Iterable, List, Optional, Set

from shiny import ui

from config import MAP_COLORS, ONE_WAY_DASH
from data_processing import line_length_m, polyline_color
from grid_page import grid_assets, route_minimap


def build_suggestions_panel() -> ui.Tag:
    return ui.nav_panel(
        "Suggestions",
        grid_assets(),
        ui.tags.style(
            """
            .hss-suggestions-wrap {
                display: flex;
                flex-direction: column;
                gap: 1rem;
            }
            .hss-suggestion-card {
                border: 1px solid #e1e4e8;
                border-radius: 12px;
                padding: 1rem;
                background: #fff;
            }
            .hss-suggestion-title {
                font-weight: 600;
                margin-bottom: 0.5rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }
            .hss-suggestion-list {
                display: flex;
                flex-direction: column;
                gap: 0.4rem;
            }
            .hss-suggestion-item {
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }
            .hss-suggestion-item.accepted {
                opacity: 0.55;
            }
            .hss-suggestion-tick {
                color: #16a34a;
                font-weight: 700;
            }
            .hss-suggestions-actions {
                margin-bottom: 1rem;
            }
            """
        ),
        ui.tags.script(
            """
            (function() {
                document.addEventListener('click', function(ev) {
                    const btn = ev.target.closest('.hss-suggestion-accept');
                    if (!btn) return;
                    const payloadText = btn.getAttribute('data-payload');
                    if (!payloadText) return;
                    try {
                        const payload = JSON.parse(payloadText);
                        if (window.Shiny && window.Shiny.setInputValue) {
                            window.Shiny.setInputValue('suggestions_accept', payload, {priority: 'event'});
                        }
                    } catch (e) {
                        console.warn('Failed to parse suggestion payload', e);
                    }
                });
            })();
            """
        ),
        ui.div(
            ui.input_action_button("suggestions_run", "Generate suggestions", class_="btn btn-primary"),
            class_="hss-suggestions-actions",
        ),
        ui.output_ui("suggestions_view"),
    )


def _route_title(row: dict) -> str:
    name = str(row.get("name") or "").strip() or "Unnamed"
    coords = row.get("_coords") or []
    length_m = int(round(line_length_m(coords))) if coords else 0
    direction = row.get("OneWay") or "TwoWay"
    return f'{length_m}m of {direction} on "{name}"'


def render_suggestions_view(
    suggestions: Optional[List[dict]],
    accepted_ids: Set[str],
) -> ui.Tag:
    if suggestions is None:
        return ui.p("Click “Generate suggestions” to scan the current borough.")
    if not suggestions:
        return ui.p("No suggestions found — everything looks good.")
    cards = []
    for entry in suggestions:
        row = entry["row"]
        coords = row.get("_coords") or []
        card_title = _route_title(row)
        minimap = route_minimap(
            coords,
            polyline_color(row, MAP_COLORS),
            0.9,
            ONE_WAY_DASH if row.get("OneWay") == "OneWay" else "",
            guid=row.get("guid"),
            width=160,
            height=100,
            weight=2,
        )
        items = []
        for suggestion in entry["suggestions"]:
            sid = suggestion["id"]
            accepted = sid in accepted_ids
            payload = {
                "id": sid,
                "guid": row.get("guid"),
                "field": suggestion["field"],
                "value": suggestion["value"],
                "label": suggestion["label"],
            }
            items.append(
                ui.tags.div(
                    ui.tags.span("✓", class_="hss-suggestion-tick") if accepted else "",
                    ui.tags.span(suggestion["label"]),
                    ui.tags.button(
                        "Accepted" if accepted else "Accept",
                        class_="btn btn-sm btn-outline-primary hss-suggestion-accept",
                        disabled=accepted,
                        **{"data-payload": json.dumps(payload)},
                    ),
                    class_="hss-suggestion-item accepted" if accepted else "hss-suggestion-item",
                )
            )
        cards.append(
            ui.div(
                ui.tags.div(card_title, class_="hss-suggestion-title"),
                ui.div(
                    ui.div(minimap, class_="hss-grid-map-wrap"),
                    ui.div(ui.TagList(*items), class_="hss-suggestion-list"),
                    class_="hss-change-row",
                ),
                class_="hss-suggestion-card",
            )
        )
    return ui.div(*cards, class_="hss-suggestions-wrap")
