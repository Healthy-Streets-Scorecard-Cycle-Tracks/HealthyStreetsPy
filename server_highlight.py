import asyncio
import json
from typing import List, Optional, Tuple

import pandas as pd
from shiny import reactive, render, ui
from shiny.types import SilentException

from data_processing import parse_date_value


def _cell_equal(a: object, b: object) -> bool:
    try:
        if pd.isna(a) and pd.isna(b):
            return True
    except Exception:
        pass
    if a is None and b is None:
        return True
    return a == b


def compute_highlight(
    *,
    df: pd.DataFrame,
    mode: str,
    since_value: object,
    owner_value: str,
    audit_value: str,
    dim_percent: int,
) -> Tuple[List[str], float, str, Optional[object], Optional[str], bool]:
    if not mode:
        mode = "None"
    since_date = None
    owner_filter = None
    if mode in ("Created since", "Edited since"):
        since_date = parse_date_value(since_value)
    elif mode == "Owned by":
        owner_filter = (owner_value or "").strip()
    elif mode == "Audited status":
        owner_filter = (audit_value or "").strip()

    highlight_guids = set()
    if mode == "Created since" and since_date:
        for _, row in df.iterrows():
            created = row.get("WhenCreated", "") or ""
            created_date = parse_date_value(created)
            if created_date and created_date >= since_date:
                highlight_guids.add(row.get("guid"))
    elif mode == "Edited since" and since_date:
        for _, row in df.iterrows():
            last_edit = row.get("LastEdited", "") or ""
            edited_date = parse_date_value(last_edit)
            if edited_date and edited_date >= since_date:
                highlight_guids.add(row.get("guid"))
    elif mode == "Owned by" and owner_filter:
        for _, row in df.iterrows():
            owner = str(row.get("Ownership", "") or "").strip()
            owner_lower = owner.lower()
            if owner_filter == "Unknown":
                if not owner or owner_lower == "unknown":
                    highlight_guids.add(row.get("guid"))
            elif owner_filter == "TfL":
                if owner_lower == "tfl":
                    highlight_guids.add(row.get("guid"))
            elif owner_filter == "Borough":
                if owner_lower == "borough":
                    highlight_guids.add(row.get("guid"))
            elif owner_filter == "Other":
                if owner_lower == "other":
                    highlight_guids.add(row.get("guid"))
    elif mode == "Audited status" and owner_filter:
        for _, row in df.iterrows():
            audited = bool(row.get("AuditedStreetView", False)) or bool(row.get("AuditedInPerson", False))
            if owner_filter == "Audited" and audited:
                highlight_guids.add(row.get("guid"))
            elif owner_filter == "Not audited" and not audited:
                highlight_guids.add(row.get("guid"))

    if mode in ("Created since", "Edited since") and since_date is None:
        highlight_guids = set()
    try:
        dim_percent = int(dim_percent)
    except Exception:
        dim_percent = 30
    dim_percent = max(0, min(dim_percent, 80))
    dim_opacity = round(dim_percent / 100.0, 2)
    guids = sorted([g for g in highlight_guids if g])
    highlight_active = mode != "None"
    return guids, dim_opacity, mode, since_date, owner_filter, highlight_active


def register_highlight_handlers(
    *,
    input,
    session,
    output,
    data_state,
    last_highlight_payload,
    highlight_date_state,
    highlight_dim_state,
    map_html_state,
    logger,
):
    def _safe_input(getter):
        try:
            return getter()
        except SilentException:
            return None

    @reactive.effect
    @reactive.event(input.highlight_mode)
    def _log_highlight_mode():
        mode = _safe_input(input.highlight_mode)
        logger.info("Highlight mode changed to %s", mode)

    @reactive.effect
    @reactive.event(input.highlight_owner)
    def _log_highlight_owner():
        owner = _safe_input(input.highlight_owner)
        logger.info("Highlight owner changed to %s", owner)

    @reactive.effect
    @reactive.event(input.highlight_audit)
    def _log_highlight_audit():
        audit = _safe_input(input.highlight_audit)
        logger.info("Highlight audit changed to %s", audit)

    @reactive.effect
    def _update_highlight_filters():
        df = data_state.get()
        if df.empty:
            payload_key = json.dumps({"guids": [], "active": False})
            if payload_key != last_highlight_payload.get():
                asyncio.create_task(
                    session.send_custom_message("hss_set_highlight", {"guids": [], "active": False})
                )
                last_highlight_payload.set(payload_key)
            return
        highlight_date = _safe_input(input.highlight_date)
        highlight_owner = _safe_input(input.highlight_owner)
        highlight_audit = _safe_input(input.highlight_audit)

        guids, dim_opacity, mode, since_date, owner_filter, highlight_active = compute_highlight(
            df=df,
            mode=input.highlight_mode(),
            since_value=highlight_date,
            owner_value=highlight_owner,
            audit_value=highlight_audit,
            dim_percent=highlight_dim_state.get(),
        )
        payload_key = json.dumps({"guids": guids, "dim": dim_opacity, "active": highlight_active})
        if payload_key == last_highlight_payload.get():
            return
        logger.info(
            "Highlight update mode=%s since=%s owner=%s matches=%d dim=%s",
            mode,
            since_date,
            owner_filter,
            len(guids),
            dim_opacity,
        )
        asyncio.create_task(
            session.send_custom_message(
                "hss_set_highlight",
                {"guids": guids, "dim_opacity": dim_opacity, "active": highlight_active},
            )
        )
        last_highlight_payload.set(payload_key)

    @reactive.effect
    @reactive.event(map_html_state)
    def _reapply_highlight_after_map():
        if map_html_state.get() is None:
            return
        df = data_state.get()
        if df.empty:
            return
        with reactive.isolate():
            highlight_date = _safe_input(input.highlight_date)
            highlight_owner = _safe_input(input.highlight_owner)
            highlight_audit = _safe_input(input.highlight_audit)
        guids, dim_opacity, mode, _, _, highlight_active = compute_highlight(
            df=df,
            mode=input.highlight_mode(),
            since_value=highlight_date,
            owner_value=highlight_owner,
            audit_value=highlight_audit,
            dim_percent=highlight_dim_state.get(),
        )
        logger.info("Reapply highlight after map render mode=%s matches=%d dim=%s", mode, len(guids), dim_opacity)
        asyncio.create_task(
            session.send_custom_message(
                "hss_set_highlight",
                {"guids": guids, "dim_opacity": dim_opacity, "active": highlight_active},
            )
        )

    @output
    @render.ui
    def highlight_controls():
        mode = input.highlight_mode()
        if mode in ("Created since", "Edited since"):
            return ui.TagList(
                ui.input_date("highlight_date", "Since date", value=highlight_date_state.get()),
                ui.input_slider(
                    "highlight_dim",
                    "Dim non-highlighted (%)",
                    min=0,
                    max=80,
                    value=highlight_dim_state.get(),
                ),
            )
        if mode == "Owned by":
            return ui.TagList(
                ui.input_select(
                    "highlight_owner",
                    "Owner",
                    choices=["Unknown", "TfL", "Borough", "Other"],
                    selected="TfL",
                ),
                ui.input_slider(
                    "highlight_dim",
                    "Dim non-highlighted (%)",
                    min=0,
                    max=80,
                    value=highlight_dim_state.get(),
                ),
            )
        if mode == "Audited status":
            return ui.TagList(
                ui.input_select(
                    "highlight_audit",
                    "Status",
                    choices=["Audited", "Not audited"],
                    selected="Audited",
                ),
                ui.input_slider(
                    "highlight_dim",
                    "Dim non-highlighted (%)",
                    min=0,
                    max=80,
                    value=highlight_dim_state.get(),
                ),
            )
        return ui.tags.div("")

    @reactive.effect
    @reactive.event(input.highlight_date)
    def _sync_highlight_date_state():
        value = input.highlight_date()
        if value:
            highlight_date_state.set(value)

    @reactive.effect
    @reactive.event(input.highlight_dim)
    def _sync_highlight_dim_state():
        value = input.highlight_dim()
        if value is None:
            return
        try:
            highlight_dim_state.set(int(value))
        except Exception:
            return


__all__ = [
    "register_highlight_handlers",
    "compute_highlight",
    "_cell_equal",
]
