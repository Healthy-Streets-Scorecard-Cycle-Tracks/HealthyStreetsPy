import asyncio

from shiny import reactive, ui


def register_grid_actions(
    *,
    input,
    session,
    data_state,
    selected_guid,
    selected_snapshot,
    changes_made,
    set_map_state,
    payload_from_row,
    logger,
):
    @reactive.effect
    @reactive.event(input.grid_delete_click)
    def _handle_grid_delete():
        payload = input.grid_delete_click()
        guid = payload.get("guid") if payload else None
        if not guid:
            return
        df = data_state.get()
        if df.empty:
            return
        if guid not in set(df["guid"].astype(str)):
            return
        logger.info("Grid delete requested guid=%s", guid)
        logger.info("Grid delete pre rows=%s", len(df))
        df = df.loc[df["guid"].astype(str) != str(guid)].reset_index(drop=True)
        data_state.set(df)
        set_map_state(df, "grid_delete")
        changes_made.set(True)
        if selected_guid.get() == guid:
            selected_guid.set(None)
            selected_snapshot.set(None)
        ui.notification_show("Deleted 1 route.", type="message")
        logger.info("Grid delete post rows=%s", len(df))

    @reactive.effect
    @reactive.event(input.grid_goto_click)
    def _handle_grid_goto():
        payload = input.grid_goto_click()
        guid = payload.get("guid") if payload else None
        if not guid:
            return
        df = data_state.get()
        if df.empty:
            return
        rows = df.loc[df["guid"].astype(str) == str(guid)]
        if rows.empty:
            return
        selected_guid.set(guid)
        selected_snapshot.set(payload_from_row(rows.iloc[0]))
        asyncio.create_task(session.send_custom_message("hss_nav_to_map", {"guid": guid, "zoom": True}))
