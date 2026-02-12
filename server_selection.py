import time
import asyncio

from async_utils import send_custom

from shiny import reactive


def register_selection_handlers(
    *,
    input,
    data_state,
    selected_guid,
    selected_snapshot,
    payload_from_row,
    update_edit_inputs,
    last_created_guid,
    last_created_time,
    session,
    logger,
):
    @reactive.effect
    def _handle_selection():
        selected = input.selected_route()
        if not selected:
            return
        guid = selected.get("guid")
        if guid:
            recent_guid = last_created_guid.get()
            recent_time = last_created_time.get()
            if recent_guid and guid != recent_guid and (time.monotonic() - recent_time) < 1.0:
                logger.info("Selected route ignored (recent create=%s, got=%s)", recent_guid, guid)
                return
            logger.info("Selected route guid=%s", guid)
            selected_guid.set(guid)
            df = data_state.get()
            if not df.empty:
                rows = df.loc[df["guid"] == guid]
                if not rows.empty:
                    selected_snapshot.set(payload_from_row(rows.iloc[0]))

    @reactive.effect
    @reactive.event(selected_snapshot)
    def _sync_edit_inputs():
        guid = selected_guid.get()
        snapshot = selected_snapshot.get()
        if not guid or not snapshot:
            return
        update_edit_inputs(snapshot)

    @reactive.effect
    @reactive.event(input.map_click)
    def _clear_selection():
        try:
            payload = input.map_click()
        except Exception:
            payload = None
        logger.info("Map click received for clear_selection payload=%s", payload)
        guid = selected_guid.get()
        if not guid:
            logger.info("Map click: no selection to clear")
            return
        logger.info("Map background click: clearing selection guid=%s", guid)
        selected_guid.set(None)
        selected_snapshot.set(None)
        try:
            send_custom(session, "hss_clear_selection", {})
            logger.info("Map background click: sent hss_clear_selection")
        except Exception:
            logger.exception("Failed to send clear selection message")
