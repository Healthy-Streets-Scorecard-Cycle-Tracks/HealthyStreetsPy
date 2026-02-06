import asyncio
import json
import time

import pandas as pd
from shiny import reactive, ui
from uuid import uuid4
from cycle_routes import debug_cycle_probe, debug_cycle_suggestions, nearest_cycle_label, suggest_cycle_designation
from tfl_lookup import debug_tfl_probe, suggest_tfl_ownership


def register_geojson_handlers(
    *,
    input,
    session,
    data_state,
    boroughs_state,
    current_user,
    selected_guid,
    selected_snapshot,
    last_edit_payload,
    last_created_payload,
    last_created_guid,
    last_created_time,
    changes_made,
    set_map_state,
    update_edit_inputs,
    payload_from_row,
    clip_coords_to_borough,
    line_length_m,
    polyline_color,
    route_colors,
    route_weight,
    one_way_dash,
    update_history,
    reverse_geocode_name,
    generate_route_id,
    today_string,
    logger,
):
    @reactive.effect
    def _apply_edited_geojson():
        edited = input.edited_geojson()
        if not edited:
            logger.info("Edit geojson: no payload")
            return
        logger.info("Edited geojson payload keys=%s", list(edited.keys()))
        payload_key = json.dumps(edited, sort_keys=True)
        if payload_key == last_edit_payload.get():
            logger.info("Edit geojson: duplicate payload ignored")
            return
        features = edited.get("features", [])
        if not features:
            logger.info("Edit geojson: no features in payload")
            return
        df = data_state.get().copy()
        borough_name = input.region()
        borough_geom = boroughs_state.get().get(borough_name)
        logger.info("Edit geojson: borough=%s has_geom=%s", borough_name, borough_geom is not None)
        for feature in features:
            properties = feature.get("properties", {})
            guid = properties.get("guid")
            if not guid:
                logger.info("Edit geojson: missing guid in feature properties")
                continue
            coords = feature.get("geometry", {}).get("coordinates", [])
            if not coords:
                logger.info("Edit geojson: missing coords for guid=%s", guid)
                continue
            new_coords = [(coord[1], coord[0]) for coord in coords]
            logger.info("Edit geojson guid=%s coords=%d", guid, len(new_coords))
            clipped_coords, clipped = clip_coords_to_borough(new_coords, borough_geom)
            logger.info("Clip edit guid=%s clipped=%s coords=%d", guid, clipped, len(clipped_coords))
            if not clipped_coords:
                ui.notification_show("Edits must remain within the borough; changes were not applied.", type="warning")
                logger.info("Edit geojson: clipped to empty for guid=%s", guid)
                continue
            idx_list = df.index[df["guid"] == guid].tolist()
            if not idx_list:
                logger.info("Edit geojson: guid not found in dataframe %s", guid)
                continue
            df.at[idx_list[0], "_coords"] = clipped_coords
            df = update_history(df, guid, current_user.get())
            if clipped:
                ui.notification_show("Route was clipped to the borough boundary.", type="warning")
            row = df.loc[df["guid"] == guid].iloc[0]
            asyncio.create_task(
                session.send_custom_message(
                    "hss_replace_geometry",
                    {
                        "guid": guid,
                        "coords": clipped_coords,
                        "properties": {
                            "Length_m": int(round(line_length_m(clipped_coords))) if clipped_coords else 0,
                        },
                        "style": {
                            "color": polyline_color(row, route_colors()),
                            "dashArray": one_way_dash if row.get("OneWay") == "OneWay" else None,
                            "weight": route_weight(),
                        },
                    },
                )
            )
            logger.info("Sent hss_replace_geometry guid=%s coords=%d", guid, len(clipped_coords))
        logger.info("Edit geojson applied: updated %d feature(s)", len(features))
        data_state.set(df)
        changes_made.set(True)
        last_edit_payload.set(payload_key)

    @reactive.effect
    def _apply_created_geojson():
        created = input.created_geojson()
        if not created:
            return
        payload_key = json.dumps(created, sort_keys=True)
        if payload_key == last_created_payload.get():
            return
        geometry = created.get("geometry", {})
        if geometry.get("type") != "LineString":
            return
        coords = geometry.get("coordinates", [])
        if not coords:
            return
        temp_id = (created.get("properties") or {}).get("_temp_id")
        df = data_state.get().copy()
        if df.empty:
            return
        borough_name = input.region()
        borough_geom = boroughs_state.get().get(borough_name)
        logger.info("Create geojson: borough=%s has_geom=%s temp_id=%s", borough_name, borough_geom is not None, temp_id)
        new_guid = str(uuid4())
        new_row = {col: "" for col in df.columns if not col.startswith("_")}
        new_row.update(
            {
                "guid": new_guid,
                "name": "New Route",
                "id": generate_route_id(),
                "OneWay": "OneWay",
                "Ownership": "",
                "History": f"{today_string()}: created by {current_user.get() or 'unknown'}",
                "WhenCreated": today_string(),
                "LastEdited": today_string(),
            }
        )
        incoming_coords = [(lat, lon) for lon, lat in coords]
        logger.info("Create geojson temp_id=%s coords=%d", temp_id, len(incoming_coords))
        clipped_coords, clipped = clip_coords_to_borough(incoming_coords, borough_geom)
        logger.info("Clip create temp_id=%s clipped=%s coords=%d", temp_id, clipped, len(clipped_coords))
        if not clipped_coords:
            ui.notification_show("New routes must intersect the borough boundary; nothing was added.", type="warning")
            if temp_id:
                asyncio.create_task(session.send_custom_message("hss_discard_created", {"temp_id": temp_id}))
                logger.info("Sent hss_discard_created temp_id=%s", temp_id)
            return
        default_name = "New Route"
        try:
            default_name = reverse_geocode_name(clipped_coords[0][0], clipped_coords[0][1]) or default_name
        except Exception:
            logger.exception("Reverse geocode failed for new route.")
        new_row["name"] = default_name
        try:
            suggested = suggest_cycle_designation(clipped_coords)
            if not suggested:
                logger.info("CycleRoutes debug coords=%s", clipped_coords)
                debug_results = debug_cycle_suggestions(clipped_coords)
                logger.info("CycleRoutes debug results (buffer, ratio, overlap, label)=%s", debug_results)
                nearest = nearest_cycle_label(clipped_coords)
                if nearest:
                    logger.info("CycleRoutes nearest label=%s distance_m=%.1f programme=%s", nearest[0], nearest[1], nearest[2])
                probe = debug_cycle_probe(clipped_coords, buffer_m=200.0)
                if probe:
                    logger.info("CycleRoutes probe=%s", probe)
        except Exception:
            logger.exception("CycleRoutes lookup failed")
            suggested = None
        if suggested and not new_row.get("Designation"):
            new_row["Designation"] = suggested
        if not new_row.get("Ownership"):
            try:
                if suggest_tfl_ownership(clipped_coords):
                    new_row["Ownership"] = "TFL"
                    logger.info("CycleRoutes: assigned Ownership=TFL based on TFL proximity")
                else:
                    probe = debug_tfl_probe(clipped_coords, buffer_m=2000.0)
                    if probe:
                        logger.info("TFL lookup probe=%s", probe)
            except Exception:
                logger.exception("TFL ownership lookup failed")
        new_row["_coords"] = clipped_coords
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        data_state.set(df)
        selected_guid.set(new_guid)
        snapshot = payload_from_row(new_row)
        selected_snapshot.set(snapshot)
        update_edit_inputs(snapshot)
        last_created_guid.set(new_guid)
        last_created_time.set(time.monotonic())
        changes_made.set(True)
        if clipped:
            ui.notification_show("New route was clipped to the borough boundary.", type="warning")
        if temp_id:
            row = df.loc[df["guid"] == new_guid].iloc[0]
            asyncio.create_task(
                session.send_custom_message(
                    "hss_created_update",
                    {
                        "temp_id": temp_id,
                        "guid": new_guid,
                        "coords": clipped_coords,
                        "properties": {
                            "OneWay": row.get("OneWay"),
                            "Rejected": bool(row.get("Rejected", False)),
                            "AuditedStreetView": bool(row.get("AuditedStreetView", False)),
                            "AuditedInPerson": bool(row.get("AuditedInPerson", False)),
                            "name": row.get("name", ""),
                            "Length_m": int(round(line_length_m(clipped_coords))) if clipped_coords else 0,
                        },
                        "style": {
                            "color": polyline_color(row, route_colors()),
                            "dashArray": one_way_dash if row.get("OneWay") == "OneWay" else None,
                            "weight": route_weight(),
                        },
                    },
                )
            )
            logger.info("Sent hss_created_update temp_id=%s guid=%s coords=%d", temp_id, new_guid, len(clipped_coords))
            asyncio.create_task(session.send_custom_message("hss_select_route", {"guid": new_guid}))
        last_created_payload.set(payload_key)
