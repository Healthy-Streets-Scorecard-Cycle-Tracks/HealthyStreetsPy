import os
import asyncio

from shiny import reactive, render, ui
from async_utils import send_custom
from shiny.types import SilentException
from config import get_route_style


def register_map_outputs(
    *,
    input,
    output,
    session,
    data_state,
    map_state,
    map_html_state,
    boroughs_state,
    london_mask_state,
    build_map,
    default_center,
    logger,
):
    @reactive.effect
    @reactive.event(map_state)
    def _render_map_html():
        df = map_state.get()
        logger.info("Render map_view trigger (rows=%d)", len(df.index))
        if df.empty:
            logger.info("Render map_view aborted: empty data")
            map_html_state.set(None)
            return
        with reactive.isolate():
            region = input.region()
            try:
                route_scheme = input.route_scheme()
            except SilentException:
                route_scheme = None
            try:
                route_width = input.route_width()
            except SilentException:
                route_width = None
            boroughs = boroughs_state.get()
            london_mask = london_mask_state.get()
        logger.info(
            "Render map_view details: region=%s boroughs=%d london_mask=%s",
            region,
            len(boroughs or {}),
            "yes" if london_mask is not None else "no",
        )
        center = default_center
        if "lat" in df.columns and "lon" in df.columns:
            center = (df["lat"].mean(), df["lon"].mean())
        folium_map = build_map(
            df,
            center,
            12,
            os.getenv("THUNDER_FOREST_KEY", ""),
            boroughs,
            london_mask,
            region,
            route_scheme,
            route_width,
        )
        map_html_state.set(folium_map.get_root().render())
        logger.info("Render map_view done")

    @reactive.effect
    @reactive.event(input.route_scheme, input.route_width)
    def _send_route_style_update():
        try:
            scheme_name = input.route_scheme()
        except SilentException:
            scheme_name = None
        try:
            width_value = input.route_width()
        except SilentException:
            width_value = None
        colors = get_route_style(scheme_name)
        try:
            weight = int(width_value) if width_value is not None else 3
        except Exception:
            weight = 3
        weight = max(1, min(weight, 12))
        logger.info("Send route style update scheme=%s weight=%s", scheme_name, weight)
        send_custom(
            session,
            "hss_set_route_style",
            {
                "colors": colors,
                "weight": weight,
            },
        )

    @output
    @render.ui
    def map_view():
        html = map_html_state.get()
        if not html:
            return ui.p("Please wait.")
        return ui.tags.iframe(
            srcdoc=html,
            style="width: 100%; height: 100%; border: 0;",
            sandbox="allow-scripts allow-same-origin",
        )
