import asyncio
import json
import time
from datetime import date
from typing import List

import pandas as pd
from shiny import App, reactive, render, ui
from shiny.types import SilentException

from config import (
    AUTO_LOGIN_ENABLED,
    BOROUGHS_KML,
    DEFAULT_MAP_CENTER,
    DEFAULT_REGION,
    DEFAULT_SHEET_ID,
    LONDON_MASK_KML,
    ONE_WAY_DASH,
    CHOICES,
    MAP_COLORS,
    TOOLTIP_TEXT,
    get_route_style,
    logger,
)
from data_io import get_access_table_once, get_gspread_client, list_regions, read_region_sheet, write_region_sheet
from data_processing import (
    coords_to_ewkt,
    generate_route_id,
    line_length_m,
    normalize_linebreaks,
    normalize_bool,
    polyline_color,
    prepare_routes_df,
    reverse_geocode_name,
    update_history,
)
from geo_utils import clip_coords_to_borough, load_kml_geometries
from map_folium import build_map
from time_utils import today_string
from ui_layout import build_app_ui
from grid_page import GRID_PAGE_SIZE, grid_input_ids, render_grid
from changes_page import render_changes
from server_grid import register_grid_actions
from server_highlight import compute_highlight, register_highlight_handlers
from change_tracking import compute_change_summary, compute_row_status
from server_map import register_map_outputs
from server_selection import register_selection_handlers
from server_regions import register_region_handlers
from server_geojson import register_geojson_handlers

app_ui = build_app_ui()


def server(input, output, session):
    data_state = reactive.Value(pd.DataFrame())
    baseline_state = reactive.Value(pd.DataFrame())
    map_state = reactive.Value(pd.DataFrame())
    map_html_state = reactive.Value(None)
    selected_guid = reactive.Value(None)
    selected_snapshot = reactive.Value(None)
    changes_made = reactive.Value(False)
    current_region = reactive.Value("")
    pending_region = reactive.Value("")
    allow_region_change = reactive.Value(False)
    last_save_click = reactive.Value(0)
    last_discard_click = reactive.Value(0)
    current_user = reactive.Value("")
    authenticated = reactive.Value(False)
    allowed_regions = reactive.Value([])
    access_table = reactive.Value(pd.DataFrame())
    boroughs_state = reactive.Value({})
    london_mask_state = reactive.Value(None)
    last_edit_payload = reactive.Value("")
    last_created_payload = reactive.Value("")
    last_metadata_payload = reactive.Value("")
    last_highlight_payload = reactive.Value("")
    last_created_guid = reactive.Value("")
    last_created_time = reactive.Value(0.0)
    highlight_date_state = reactive.Value(date(2024, 1, 1))
    highlight_dim_state = reactive.Value(40)
    loading_message = reactive.Value("Loading...")
    loading_active = reactive.Value(True)
    loading_modal_visible = reactive.Value(False)
    region_pref = reactive.Value(None)
    region_pref_ready = reactive.Value(False)
    region_pref_timeout_started = reactive.Value(False)
    region_select_synced = reactive.Value(False)
    changes_open_state = reactive.Value(["changed", "added", "removed"])

    @reactive.effect
    def _show_loading_modal():
        if not AUTO_LOGIN_ENABLED and not authenticated.get():
            if loading_modal_visible.get():
                ui.modal_remove()
                loading_modal_visible.set(False)
            return
        if loading_active.get():
            if not loading_modal_visible.get():
                ui.modal_show(
                    ui.modal(
                        ui.p(loading_message.get()),
                        title="Loading...",
                        easy_close=False,
                        footer=None,
                    )
                )
                loading_modal_visible.set(True)
        else:
            if loading_modal_visible.get():
                ui.modal_remove()
                loading_modal_visible.set(False)

    def _ensure_loading_modal():
        if loading_modal_visible.get():
            return
        ui.modal_show(
            ui.modal(
                ui.p(loading_message.get()),
                title="Loading...",
                easy_close=False,
                footer=None,
            )
        )
        loading_modal_visible.set(True)

    def _input_value(input_obj, input_id: str):
        try:
            return input_obj[input_id]()
        except Exception:
            return None

    def set_map_state(df: pd.DataFrame, reason: str) -> None:
        try:
            import inspect

            caller = inspect.stack()[1]
            logger.info(
                "map_state.set reason=%s caller=%s:%s",
                reason,
                caller.filename,
                caller.lineno,
            )
        except Exception:
            logger.info("map_state.set reason=%s", reason)
        map_state.set(df)

    @reactive.effect
    def _init_access_table():
        if AUTO_LOGIN_ENABLED and not authenticated.get():
            try:
                all_regions = list_regions(DEFAULT_SHEET_ID)
            except Exception:
                all_regions = []
            allowed_regions.set(all_regions)
            current_user.set("AutoLogin")
            authenticated.set(True)
            logger.info("Auto-login enabled (debugger detected).")
            return
        loading_message.set("Loading access table...")
        access_table.set(get_access_table_once())
        loading_active.set(False)

    @reactive.effect
    def _load_borough_shapes():
        if boroughs_state.get():
            return
        loading_message.set("Loading borough boundaries...")
        try:
            logger.info("Loading borough shapes from %s", BOROUGHS_KML)
            borough_geoms = {name: geom for name, geom in load_kml_geometries(BOROUGHS_KML) if name}
            logger.info("Loaded %d borough geometries", len(borough_geoms))
            loading_message.set("Loading London mask...")
            logger.info("Loading London mask from %s", LONDON_MASK_KML)
            london_shapes = load_kml_geometries(LONDON_MASK_KML)
            london_geom = london_shapes[0][1] if london_shapes else None
            boroughs_state.set(borough_geoms)
            london_mask_state.set(london_geom)
            logger.info("Loaded London mask: %s", "yes" if london_geom is not None else "no")
        except Exception:
            logger.exception("Failed to load borough shapes.")
            boroughs_state.set({})
            london_mask_state.set(None)

    @reactive.effect
    def _show_login_modal():
        if AUTO_LOGIN_ENABLED:
            return
        if authenticated.get():
            return
        ui.modal_show(
            ui.modal(
                ui.h3("Hello"),
                ui.input_text("login_name", "Please enter your name", placeholder="Your Name"),
                ui.input_password("login_password", "Please enter your password", placeholder="Password"),
                ui.input_action_button("login_ok", "OK"),
                easy_close=False,
            )
        )

    @reactive.effect
    @reactive.event(input.login_ok)
    def _handle_login():
        if AUTO_LOGIN_ENABLED:
            return
        name = (input.login_name() or "").strip()
        password = (input.login_password() or "").strip()
        logger.info("Login attempt for name=%s", name)
        if not name:
            ui.notification_show("Please provide a name", type="error")
            return
        if not password:
            ui.notification_show("Please provide a password", type="error")
            return
        access_df = access_table.get()
        if access_df.empty:
            try:
                logger.info("Access table empty. Reloading access table.")
                access_df = get_access_table_once()
                access_table.set(access_df)
            except Exception:
                logger.exception("Failed to reload access table.")
                access_df = pd.DataFrame()
        if access_df.empty or "Password" not in access_df.columns or "Region" not in access_df.columns:
            logger.warning("Access table invalid or missing columns.")
            ui.notification_show("Password list unavailable", type="error")
            return
        access_df = access_df.copy()
        access_df["Password"] = access_df["Password"].astype(str).str.strip()
        access_df["Region"] = access_df["Region"].astype(str).str.strip()
        matched = access_df.loc[access_df["Password"] == password]
        if len(matched) != 1:
            logger.warning("Password not recognised for name=%s", name)
            ui.notification_show("Password not recognised", type="error")
            return
        region = matched.iloc[0]["Region"]
        if region == "All":
            regions_list = sorted([r for r in access_df["Region"].unique() if r != "All"])
        else:
            regions_list = [region]
        allowed_regions.set(regions_list)
        current_user.set(name)
        authenticated.set(True)
        ui.modal_remove()
        ui.notification_show(f"Welcome {name}", type="message")

    @reactive.calc
    def regions() -> List[str]:
        if not authenticated.get():
            return []
        sheet_regions = list_regions(DEFAULT_SHEET_ID)
        allowed = allowed_regions.get()
        if not allowed:
            return []
        return [r for r in sheet_regions if r in allowed]

    @reactive.effect
    @reactive.event(input.region_pref)
    def _capture_region_pref():
        try:
            pref = input.region_pref()
        except Exception:
            pref = None
        region_pref.set(pref)
        region_pref_ready.set(True)
        logger.info("Region pref received: %s", pref)

    @reactive.effect
    def _region_pref_timeout():
        if region_pref_ready.get() or region_pref_timeout_started.get():
            return
        region_pref_timeout_started.set(True)
        async def _wait():
            await asyncio.sleep(1.0)
            if not region_pref_ready.get():
                region_pref_ready.set(True)
                logger.info("Region pref timeout: proceeding without client pref")
        asyncio.create_task(_wait())

    @reactive.effect
    def _sync_region_select():
        values = regions()
        if not values:
            return
        if not region_pref_ready.get():
            return
        current_input = None
        try:
            current_input = input.region()
        except Exception:
            current_input = None
        current = current_region.get()
        if current and current in values and region_select_synced.get():
            logger.info(
                "Region select sync skipped: already synced current=%s (values=%s)",
                current,
                len(values),
            )
            return
        selected = current if current in values else None
        if not selected:
            pref = region_pref.get()
            if pref and pref in values:
                selected = pref
            else:
                selected = DEFAULT_REGION if DEFAULT_REGION in values else values[0]
        if current_input and current_input == selected and len(values) > 0:
            logger.info(
                "Region select sync skipped: input already %s (values=%s)",
                current_input,
                len(values),
            )
            region_select_synced.set(True)
            return
        logger.info(
            "Region select sync: values=%s selected=%s current=%s",
            len(values),
            selected,
            current_region.get(),
        )
        ui.update_select("region", choices=values, selected=selected)
        region_select_synced.set(True)

    register_highlight_handlers(
        input=input,
        session=session,
        output=output,
        data_state=data_state,
        last_highlight_payload=last_highlight_payload,
        highlight_date_state=highlight_date_state,
        highlight_dim_state=highlight_dim_state,
        map_html_state=map_html_state,
        logger=logger,
    )
    def _normalize_optional(value) -> str:
        try:
            if pd.isna(value):
                return ""
        except Exception:
            pass
        if value is None:
            return ""
        return str(value)

    def _payload_from_row(row: pd.Series) -> dict:
        return {
            "name": _normalize_optional(row.get("name", "")),
            "designation": _normalize_optional(row.get("Designation", "")),
            "id": _normalize_optional(row.get("id", "")),
            "description": normalize_linebreaks(row.get("description", "")),
            "oneway": _normalize_optional(row.get("OneWay", "TwoWay")) or "TwoWay",
            "flow": _normalize_optional(row.get("Flow", "")),
            "protection": _normalize_optional(row.get("Protection", "")),
            "ownership": _normalize_optional(row.get("Ownership", "")),
            "year_before": "Before" if row.get("YearBuildBeforeFlag", False) else "In",
            "year_built": _normalize_optional(row.get("YearBuilt", "")),
            "audited_sv": bool(row.get("AuditedStreetView", False)),
            "audited_in_person": bool(row.get("AuditedInPerson", False)),
            "rejected": bool(row.get("Rejected", False)),
        }

    def _payload_from_inputs() -> dict:
        return {
            "name": str(input.edit_name() or ""),
            "designation": str(input.edit_designation() or ""),
            "id": str(input.edit_id() or ""),
            "description": normalize_linebreaks(input.edit_description() or ""),
            "oneway": input.edit_oneway() or "TwoWay",
            "flow": input.edit_flow() or "",
            "protection": input.edit_protection() or "",
            "ownership": input.edit_ownership() or "",
            "year_before": input.edit_year_before() or "In",
            "year_built": str(input.edit_year_built() or ""),
            "audited_sv": bool(input.edit_audited_sv()),
            "audited_in_person": bool(input.edit_audited_in_person()),
            "rejected": bool(input.edit_rejected()),
        }

    def _current_route_scheme():
        try:
            return input.route_scheme()
        except SilentException:
            return None

    def _current_route_colors():
        return get_route_style(_current_route_scheme())

    def _current_route_weight():
        try:
            value = input.route_width()
        except SilentException:
            value = None
        try:
            weight = int(value) if value is not None else 3
        except Exception:
            weight = 3
        return max(1, min(weight, 12))

    def _update_edit_inputs(snapshot: dict) -> None:
        if not snapshot:
            return
        ui.update_text("edit_name", value=snapshot.get("name", ""))
        ui.update_text("edit_designation", value=snapshot.get("designation", ""))
        ui.update_text("edit_id", value=snapshot.get("id", ""))
        ui.update_text_area("edit_description", value=snapshot.get("description", ""))
        ui.update_select("edit_oneway", selected=snapshot.get("oneway", "TwoWay"))
        ui.update_select("edit_flow", selected=snapshot.get("flow", ""))
        ui.update_select("edit_protection", selected=snapshot.get("protection", ""))
        ui.update_select("edit_ownership", selected=snapshot.get("ownership", ""))
        ui.update_select("edit_year_before", selected=snapshot.get("year_before", "In"))
        ui.update_text("edit_year_built", value=snapshot.get("year_built", ""))
        ui.update_checkbox("edit_audited_sv", value=bool(snapshot.get("audited_sv", False)))
        ui.update_checkbox("edit_audited_in_person", value=bool(snapshot.get("audited_in_person", False)))
        ui.update_checkbox("edit_rejected", value=bool(snapshot.get("rejected", False)))

    register_selection_handlers(
        input=input,
        data_state=data_state,
        selected_guid=selected_guid,
        selected_snapshot=selected_snapshot,
        payload_from_row=_payload_from_row,
        update_edit_inputs=_update_edit_inputs,
        last_created_guid=last_created_guid,
        last_created_time=last_created_time,
        session=session,
        logger=logger,
    )

    register_region_handlers(
        input=input,
        session=session,
        data_state=data_state,
        baseline_state=baseline_state,
        map_state=map_state,
        selected_guid=selected_guid,
        selected_snapshot=selected_snapshot,
        current_region=current_region,
        pending_region=pending_region,
        allow_region_change=allow_region_change,
        changes_made=changes_made,
        last_save_click=last_save_click,
        last_discard_click=last_discard_click,
        loading_message=loading_message,
        loading_active=loading_active,
        ensure_loading_modal=_ensure_loading_modal,
        set_map_state=set_map_state,
        read_region_sheet=read_region_sheet,
        write_region_sheet=write_region_sheet,
        prepare_routes_df=prepare_routes_df,
        get_gspread_client=get_gspread_client,
        coords_to_ewkt=coords_to_ewkt,
        default_sheet_id=DEFAULT_SHEET_ID,
        logger=logger,
        region_pref_ready=region_pref_ready,
        authenticated=authenticated,
    )

    register_grid_actions(
        input=input,
        session=session,
        data_state=data_state,
        selected_guid=selected_guid,
        selected_snapshot=selected_snapshot,
        changes_made=changes_made,
        set_map_state=set_map_state,
        payload_from_row=_payload_from_row,
        logger=logger,
    )

    register_geojson_handlers(
        input=input,
        session=session,
        data_state=data_state,
        boroughs_state=boroughs_state,
        current_user=current_user,
        selected_guid=selected_guid,
        selected_snapshot=selected_snapshot,
        last_edit_payload=last_edit_payload,
        last_created_payload=last_created_payload,
        last_created_guid=last_created_guid,
        last_created_time=last_created_time,
        changes_made=changes_made,
        set_map_state=set_map_state,
        update_edit_inputs=_update_edit_inputs,
        payload_from_row=_payload_from_row,
        clip_coords_to_borough=clip_coords_to_borough,
        line_length_m=line_length_m,
        polyline_color=polyline_color,
        route_colors=_current_route_colors,
        route_weight=_current_route_weight,
        one_way_dash=ONE_WAY_DASH,
        update_history=update_history,
        reverse_geocode_name=reverse_geocode_name,
        generate_route_id=generate_route_id,
        today_string=today_string,
        logger=logger,
    )

    @reactive.effect
    def _apply_grid_edits():
        df_current = data_state.get()
        if df_current.empty:
            return
        df = df_current.copy()
        page = input.grid_page() or 1
        try:
            page = int(page)
        except Exception:
            page = 1
        start = max(page - 1, 0) * GRID_PAGE_SIZE
        end = start + GRID_PAGE_SIZE
        slice_rows = df_current.iloc[start:end]
        changed = False
        for _, row in slice_rows.iterrows():
            guid = row.get("guid")
            if not guid:
                continue
            ids = grid_input_ids(guid)
            name = _input_value(input, ids["name"])
            designation = _input_value(input, ids["designation"])
            rid = _input_value(input, ids["id"])
            oneway = _input_value(input, ids["oneway"])
            flow = _input_value(input, ids["flow"])
            protection = _input_value(input, ids["protection"])
            owner = _input_value(input, ids["owner"])
            audit_sv = _input_value(input, ids["audit_sv"])
            audit_ip = _input_value(input, ids["audit_ip"])
            rejected = _input_value(input, ids["rejected"])

            row_changed = False
            if name is not None and str(row.get("name", "")) != str(name):
                df.loc[df["guid"] == guid, "name"] = str(name)
                row_changed = True
            if designation is not None and str(row.get("Designation", "")) != str(designation):
                df.loc[df["guid"] == guid, "Designation"] = str(designation)
                row_changed = True
            if rid is not None and str(row.get("id", "")) != str(rid):
                df.loc[df["guid"] == guid, "id"] = str(rid)
                row_changed = True
            if oneway is not None and str(row.get("OneWay", "")) != str(oneway):
                df.loc[df["guid"] == guid, "OneWay"] = str(oneway)
                row_changed = True
                logger.info("Grid edit OneWay guid=%s value=%s", guid, oneway)
            if flow is not None and str(row.get("Flow", "")) != str(flow):
                df.loc[df["guid"] == guid, "Flow"] = str(flow)
                row_changed = True
            if protection is not None and str(row.get("Protection", "")) != str(protection):
                df.loc[df["guid"] == guid, "Protection"] = str(protection)
                row_changed = True
            if owner is not None and str(row.get("Ownership", "")) != str(owner):
                df.loc[df["guid"] == guid, "Ownership"] = str(owner)
                row_changed = True
            if audit_sv is not None and bool(row.get("AuditedStreetView", False)) != bool(audit_sv):
                df.loc[df["guid"] == guid, "AuditedStreetView"] = bool(audit_sv)
                row_changed = True
            if audit_ip is not None and bool(row.get("AuditedInPerson", False)) != bool(audit_ip):
                df.loc[df["guid"] == guid, "AuditedInPerson"] = bool(audit_ip)
                row_changed = True
            if rejected is not None and bool(row.get("Rejected", False)) != bool(rejected):
                df.loc[df["guid"] == guid, "Rejected"] = bool(rejected)
                row_changed = True

            if row_changed:
                df = update_history(df, guid, current_user.get())
                changed = True
                try:
                    updated_row = df.loc[df["guid"] == guid].iloc[0]
                    style_payload = {
                        "guid": guid,
                        "style": {
                            "color": polyline_color(updated_row, _current_route_colors()),
                            "dashArray": ONE_WAY_DASH if updated_row.get("OneWay") == "OneWay" else None,
                            "weight": _current_route_weight(),
                        },
                        "properties": {
                            "OneWay": updated_row.get("OneWay"),
                            "Rejected": bool(updated_row.get("Rejected", False)),
                            "AuditedStreetView": bool(updated_row.get("AuditedStreetView", False)),
                            "AuditedInPerson": bool(updated_row.get("AuditedInPerson", False)),
                            "name": updated_row.get("name", ""),
                            "Length_m": int(round(line_length_m(updated_row.get("_coords") or []))),
                        },
                    }
                    asyncio.create_task(session.send_custom_message("hss_update_style", style_payload))
                    with reactive.isolate():
                        try:
                            highlight_date = input.highlight_date()
                        except SilentException:
                            highlight_date = None
                        try:
                            highlight_owner = input.highlight_owner()
                        except SilentException:
                            highlight_owner = None
                        try:
                            highlight_audit = input.highlight_audit()
                        except SilentException:
                            highlight_audit = None
                    grid_guids, dim_opacity, _, _, _, highlight_active = compute_highlight(
                        df=df,
                        mode=input.highlight_mode(),
                        since_value=highlight_date,
                        owner_value=highlight_owner,
                        audit_value=highlight_audit,
                        dim_percent=highlight_dim_state.get(),
                    )
                    grid_opacity = 0.9
                    if highlight_active and guid not in set(grid_guids):
                        grid_opacity = dim_opacity
                    asyncio.create_task(
                        session.send_custom_message(
                            "hss_update_minimap",
                            {
                                "guid": guid,
                                "color": polyline_color(updated_row, MAP_COLORS),
                                "dash": ONE_WAY_DASH if updated_row.get("OneWay") == "OneWay" else "",
                                "opacity": grid_opacity,
                            },
                        )
                    )
                    logger.info("Grid edit: sent hss_update_minimap guid=%s dash=%s opacity=%s", guid, ONE_WAY_DASH if updated_row.get("OneWay") == "OneWay" else "", grid_opacity)
                except Exception:
                    logger.exception("Failed to send style update for grid edit guid=%s", guid)

                if selected_guid.get() == guid:
                    selected_snapshot.set(_payload_from_row(updated_row))

        if changed:
            data_state.set(df)
            _sync_changes_flag(df)
            logger.info("Grid edits applied: sending hss_refresh_minimaps")
            asyncio.create_task(session.send_custom_message("hss_refresh_minimaps", {"changed": True}))

    register_map_outputs(
        input=input,
        output=output,
        session=session,
        data_state=data_state,
        map_state=map_state,
        map_html_state=map_html_state,
        boroughs_state=boroughs_state,
        london_mask_state=london_mask_state,
        build_map=build_map,
        default_center=DEFAULT_MAP_CENTER,
        logger=logger,
    )

    @output
    @render.ui
    def edit_panel():
        df = data_state.get()
        guid = selected_guid.get()
        if df.empty or not guid:
            return ui.p("Click a route on the map to edit.")
        if df.loc[df["guid"] == guid].empty:
            selected_guid.set(None)
            selected_snapshot.set(None)
            return ui.p("Click a route on the map to edit.")
        logger.info("Render edit_panel for guid=%s", guid)
        row = df.loc[df["guid"] == guid].iloc[0]

        def _label(text: str, key: str):
            tooltip = TOOLTIP_TEXT.get(key, "")
            if not tooltip:
                return text
            return ui.tooltip(ui.tags.span(text), tooltip, placement="right")

        return ui.TagList(
            ui.input_text(
                "edit_name",
                _label("Name", "name"),
                value=str(row.get("name", "")),
                update_on="blur",
            ),
            ui.input_text(
                "edit_designation",
                _label("Designation", "designation"),
                value=str(row.get("Designation", "")),
                update_on="blur",
            ),
            ui.input_text(
                "edit_id",
                _label("Id", "id"),
                value=str(row.get("id", "")),
                update_on="blur",
            ),
            ui.input_text_area(
                "edit_description",
                _label("Comments", "comment"),
                value=normalize_linebreaks(row.get("description", "")),
                rows=5,
            ),
            ui.input_select(
                "edit_oneway",
                _label("Direction", "oneway"),
                choices=list(CHOICES["direction"].values()),
                selected=row.get("OneWay", "TwoWay"),
            ),
            ui.input_select(
                "edit_flow",
                _label("Flow", "flow"),
                choices=list(CHOICES["flow"].values()),
                selected=row.get("Flow", ""),
            ),
            ui.input_select(
                "edit_protection",
                _label("Protection", "protection"),
                choices=list(CHOICES["protection"].values()),
                selected=row.get("Protection", ""),
            ),
            ui.input_select(
                "edit_ownership",
                _label("Ownership", "ownership"),
                choices=list(CHOICES["ownership"].values()),
                selected=row.get("Ownership", ""),
            ),
            ui.input_select(
                "edit_year_before",
                _label("Built", "year_before"),
                choices=list(CHOICES["year_before"].values()),
                selected="Before" if row.get("YearBuildBeforeFlag", False) else "In",
            ),
            ui.input_text(
                "edit_year_built",
                _label("Year", "year_built"),
                value=str(row.get("YearBuilt", "")),
                update_on="blur",
            ),
            ui.input_checkbox(
                "edit_audited_sv",
                _label("Audited Streetview", "audited_online"),
                value=bool(row.get("AuditedStreetView", False)),
            ),
            ui.input_checkbox(
                "edit_audited_in_person",
                _label("Audited In Person", "audited_in_person"),
                value=bool(row.get("AuditedInPerson", False)),
            ),
            ui.input_checkbox("edit_rejected", _label("Rejected", "rejected"), value=bool(row.get("Rejected", False))),
            ui.input_action_button("delete_route", "Delete selected route", class_="btn-danger"),
        )

    @reactive.effect
    @reactive.event(
        input.edit_name,
        input.edit_designation,
        input.edit_id,
        input.edit_description,
        input.edit_oneway,
        input.edit_flow,
        input.edit_protection,
        input.edit_ownership,
        input.edit_year_before,
        input.edit_year_built,
        input.edit_audited_sv,
        input.edit_audited_in_person,
        input.edit_rejected,
    )
    def _apply_metadata():
        guid = selected_guid.get()
        if not guid:
            return
        payload = _payload_from_inputs()
        snapshot = selected_snapshot.get()
        if snapshot is not None and payload == snapshot:
            return
        payload_key = json.dumps(payload, sort_keys=True)
        if payload_key == last_metadata_payload.get():
            return
        logger.info("Apply metadata guid=%s", guid)
        df = data_state.get().copy()
        df.loc[df["guid"] == guid, "name"] = payload["name"]
        df.loc[df["guid"] == guid, "Designation"] = payload["designation"]
        df.loc[df["guid"] == guid, "id"] = payload["id"]
        df.loc[df["guid"] == guid, "description"] = payload["description"]
        df.loc[df["guid"] == guid, "OneWay"] = payload["oneway"]
        df.loc[df["guid"] == guid, "Flow"] = payload["flow"]
        df.loc[df["guid"] == guid, "Protection"] = payload["protection"]
        df.loc[df["guid"] == guid, "Ownership"] = payload["ownership"]
        df.loc[df["guid"] == guid, "YearBuildBeforeFlag"] = payload["year_before"] == "Before"
        df.loc[df["guid"] == guid, "YearBuilt"] = payload["year_built"]
        df.loc[df["guid"] == guid, "AuditedStreetView"] = payload["audited_sv"]
        df.loc[df["guid"] == guid, "AuditedInPerson"] = payload["audited_in_person"]
        df.loc[df["guid"] == guid, "Rejected"] = payload["rejected"]
        df = update_history(df, guid, current_user.get())
        data_state.set(df)
        changes_made.set(True)
        last_metadata_payload.set(payload_key)
        selected_snapshot.set(payload)
        try:
            row = df.loc[df["guid"] == guid].iloc[0]
            style_payload = {
                "guid": guid,
                "style": {
                    "color": polyline_color(row, _current_route_colors()),
                    "dashArray": ONE_WAY_DASH if row.get("OneWay") == "OneWay" else None,
                    "weight": _current_route_weight(),
                },
                "properties": {
                    "OneWay": row.get("OneWay"),
                    "Rejected": bool(row.get("Rejected", False)),
                    "AuditedStreetView": bool(row.get("AuditedStreetView", False)),
                    "AuditedInPerson": bool(row.get("AuditedInPerson", False)),
                    "name": row.get("name", ""),
                    "Length_m": int(round(line_length_m(row.get("_coords") or []))),
                },
            }
            logger.info("Send style update guid=%s payload=%s", guid, style_payload)
            asyncio.create_task(session.send_custom_message("hss_update_style", style_payload))
        except Exception:
            logger.exception("Failed to send style update for guid=%s", guid)

    @reactive.effect
    @reactive.event(input.delete_route)
    def _delete_route():
        guid = selected_guid.get()
        logger.info("Delete requested (guid=%s)", guid)
        if not guid:
            ui.notification_show("Select a route to delete first.", type="warning")
            return
        df = data_state.get().copy()
        df = df.loc[df["guid"] != guid].reset_index(drop=True)
        data_state.set(df)
        set_map_state(df, "delete_route")
        selected_guid.set(None)
        changes_made.set(True)
        ui.notification_show("Route deleted.", type="message")

    @output
    @render.ui
    def distance_boxes():
        df = data_state.get()
        if df.empty:
            return ui.TagList()
        if "Rejected" in df.columns:
            df = df.loc[~df["Rejected"].apply(normalize_bool)]
        one_way = 0.0
        two_way = 0.0
        total_rows = len(df.index)
        rows_with_coords = 0
        for _, row in df.iterrows():
            coords = row.get("_coords")
            if coords:
                rows_with_coords += 1
            length = line_length_m(coords) if coords else 0.0
            if row.get("OneWay") == "TwoWay":
                two_way += length
            else:
                one_way += length
        total = one_way + 2 * two_way
        one_km = round(one_way / 1000, 2)
        two_km = round(two_way / 1000, 2)
        total_km = round(total / 1000, 2)
        return ui.tags.ul(
            ui.tags.li(
                ui.tags.span("One-way", class_="metric-label"),
                ui.tags.span(f"{one_km} km", class_="metric-value"),
            ),
            ui.tags.li(
                ui.tags.span("Two-way", class_="metric-label"),
                ui.tags.span(f"{two_km} km", class_="metric-value"),
            ),
            ui.tags.li(
                ui.tags.span("Total", class_="metric-label"),
                ui.tags.span(f"{total_km} km", class_="metric-value"),
            ),
            class_="hss-metrics-list",
        )

    def _cell_equal(a: object, b: object) -> bool:
        try:
            if pd.isna(a) and pd.isna(b):
                return True
        except Exception:
            pass
        if a is None and b is None:
            return True
        return a == b

    @output
    @render.text
    def change_summary():
        base = baseline_state.get()
        cur = data_state.get()
        added, removed, changed = compute_change_summary(base, cur)
        logger.info("Change summary render: added=%s removed=%s changed=%s", added, removed, changed)
        if added == 0 and removed == 0 and changed == 0:
            return ""
        return f"{added} added / {removed} removed / {changed} changed"

    def _sync_changes_flag(df: pd.DataFrame) -> None:
        added, removed, changed = compute_change_summary(baseline_state.get(), df)
        changes_made.set((added + removed + changed) > 0)

    @output
    @render.text
    def grid_page_info():
        try:
            df = data_state.get()
            if df.empty:
                return "0 routes"
            total = len(df.index)
            total_pages = max(1, (total + GRID_PAGE_SIZE - 1) // GRID_PAGE_SIZE)
            page = input.grid_page() or 1
            return f"Page {page} of {total_pages} ({total} routes)"
        except Exception:
            logger.exception("Grid page info failed")
            return "Grid info failed to render"

    @output
    @render.ui
    def grid_pager():
        try:
            df = data_state.get()
            if df.empty:
                return ui.tags.div()
            total = len(df.index)
            total_pages = max(1, (total + GRID_PAGE_SIZE - 1) // GRID_PAGE_SIZE)
            page = input.grid_page() or 1
            try:
                page = int(page)
            except Exception:
                page = 1
            page = max(1, min(page, total_pages))

            window = 2
            start = max(1, page - window)
            end = min(total_pages, page + window)
            pages = list(range(start, end + 1))

            def page_item(label, target=None, active=False, disabled=False):
                cls = "page-item"
                if active:
                    cls += " active"
                if disabled:
                    cls += " disabled"
                if target is None or disabled:
                    return ui.tags.li(ui.tags.span(label, class_="page-link"), class_=cls)
                return ui.tags.li(
                    ui.tags.a(label, class_="page-link", href="#", onclick=f"hssSetGridPage({target}); return false;"),
                    class_=cls,
                )

            items = [
                page_item("«", 1, disabled=(page == 1)),
                page_item("‹", page - 1, disabled=(page == 1)),
            ]
            for p in pages:
                items.append(page_item(str(p), p, active=(p == page)))
            items.extend(
                [
                    page_item("›", page + 1, disabled=(page == total_pages)),
                    page_item("»", total_pages, disabled=(page == total_pages)),
                ]
            )
            return ui.tags.nav(ui.tags.ul(*items, class_="pagination pagination-sm mb-0"))
        except Exception:
            logger.exception("Grid pager failed")
            return ui.tags.div()

    @output
    @render.ui
    def grid_view():
        try:
            df = data_state.get()
            if df.empty:
                return ui.tags.div("No routes loaded yet.")
            base = baseline_state.get()
            page = input.grid_page() or 1
            with reactive.isolate():
                try:
                    highlight_date = input.highlight_date()
                except SilentException:
                    highlight_date = None
                try:
                    highlight_owner = input.highlight_owner()
                except SilentException:
                    highlight_owner = None
                try:
                    highlight_audit = input.highlight_audit()
                except SilentException:
                    highlight_audit = None
            guids, dim_opacity, mode, _, _, highlight_active = compute_highlight(
                df=df,
                mode=input.highlight_mode(),
                since_value=highlight_date,
                owner_value=highlight_owner,
                audit_value=highlight_audit,
                dim_percent=highlight_dim_state.get(),
            )
            change_status = compute_row_status(base, df)
            logger.info("Render grid_view page=%s mode=%s dim=%s", page, mode, dim_opacity)
            return render_grid(df, int(page), guids, highlight_active, dim_opacity, change_status)
        except Exception:
            logger.exception("Grid view failed")
            return ui.tags.div("Grid failed to render")

    @output
    @render.ui
    def changes_view():
        df = data_state.get()
        baseline = baseline_state.get()
        logger.info(
            "Changes view render: rows=%s baseline_rows=%s",
            len(df.index) if not df.empty else 0,
            len(baseline.index) if not baseline.empty else 0,
        )
        if df.empty and baseline.empty:
            return ui.tags.div("No changes yet.")
        current_ids = set(df["guid"].astype(str)) if not df.empty else set()
        baseline_ids = set(baseline["guid"].astype(str)) if not baseline.empty else set()

        created_rows = []
        removed_rows = []
        edited_pairs = []

        created_ids = current_ids - baseline_ids
        removed_ids = baseline_ids - current_ids
        shared_ids = current_ids & baseline_ids

        for guid in created_ids:
            row = df.loc[df["guid"].astype(str) == guid].iloc[0]
            created_rows.append(row)

        for guid in removed_ids:
            row = baseline.loc[baseline["guid"].astype(str) == guid].iloc[0]
            removed_rows.append(row)

        def _cell_equal(a, b) -> bool:
            try:
                if pd.isna(a) and pd.isna(b):
                    return True
            except Exception:
                pass
            if a is None and b is None:
                return True
            return a == b

        compare_cols = [
            c for c in df.columns
            if c in baseline.columns and c not in {"History", "LastEdited", "WhenCreated"}
        ]

        def _row_changed(a, b):
            for key in compare_cols:
                if not _cell_equal(a.get(key), b.get(key)):
                    return True
            return False

        for guid in shared_ids:
            before_row = baseline.loc[baseline["guid"].astype(str) == guid].iloc[0]
            after_row = df.loc[df["guid"].astype(str) == guid].iloc[0]
            if _row_changed(before_row, after_row):
                edited_pairs.append((before_row, after_row))
        logger.info(
            "Changes view counts: created=%s removed=%s edited=%s",
            len(created_rows),
            len(removed_rows),
            len(edited_pairs),
        )

        with reactive.isolate():
            try:
                highlight_date = input.highlight_date()
            except SilentException:
                highlight_date = None
            try:
                highlight_owner = input.highlight_owner()
            except SilentException:
                highlight_owner = None
            try:
                highlight_audit = input.highlight_audit()
            except SilentException:
                highlight_audit = None

        guids, dim_opacity, _, _, _, highlight_active = compute_highlight(
            df=df,
            mode=input.highlight_mode(),
            since_value=highlight_date,
            owner_value=highlight_owner,
            audit_value=highlight_audit,
            dim_percent=highlight_dim_state.get(),
        )

        return render_changes(
            edited=edited_pairs,
            created=created_rows,
            removed=removed_rows,
            highlight_guids=guids,
            highlight_active=highlight_active,
            dim_opacity=dim_opacity,
            route_colors=_current_route_colors(),
            route_weight=_current_route_weight(),
            open_panels=changes_open_state.get(),
        )

    @reactive.effect
    @reactive.event(input.hss_changes_accordion)
    def _capture_changes_open_state():
        try:
            value = input.hss_changes_accordion()
        except Exception:
            value = None
        if value is None:
            return
        if isinstance(value, str):
            changes_open_state.set([value])
        else:
            try:
                changes_open_state.set(list(value))
            except Exception:
                return

    @reactive.effect
    @reactive.event(input.changes_undo_click)
    def _undo_change():
        payload = input.changes_undo_click()
        if not payload:
            return
        guid = payload.get("guid")
        action = payload.get("action")
        if not guid or not action:
            return
        df = data_state.get().copy()
        base = baseline_state.get().copy()
        guid_str = str(guid)

        if action == "undo_create":
            if guid_str in set(df["guid"].astype(str)):
                df = df.loc[df["guid"].astype(str) != guid_str].reset_index(drop=True)
                if selected_guid.get() == guid:
                    selected_guid.set(None)
                    selected_snapshot.set(None)
        elif action == "undo_remove":
            if guid_str in set(base["guid"].astype(str)) and guid_str not in set(df["guid"].astype(str)):
                row = base.loc[base["guid"].astype(str) == guid_str].iloc[0]
                insert_at = len(df)
                try:
                    insert_at = int(base.index[base["guid"].astype(str) == guid_str][0])
                except Exception:
                    pass
                upper = df.iloc[:insert_at]
                lower = df.iloc[insert_at:]
                df = pd.concat([upper, pd.DataFrame([row]), lower], ignore_index=True)
        elif action == "undo_edit":
            if guid_str in set(base["guid"].astype(str)) and guid_str in set(df["guid"].astype(str)):
                row = base.loc[base["guid"].astype(str) == guid_str].iloc[0]
                idx = df.index[df["guid"].astype(str) == guid_str][0]
                for col in df.columns:
                    if col in row.index:
                        df.at[idx, col] = row[col]
                if selected_guid.get() == guid:
                    selected_snapshot.set(_payload_from_row(row))
        else:
            return

        data_state.set(df)
        set_map_state(df, f"undo_{action}")
        _sync_changes_flag(df)
        asyncio.create_task(session.send_custom_message("hss_refresh_minimaps", {"changed": True}))

app = App(app_ui, server)
