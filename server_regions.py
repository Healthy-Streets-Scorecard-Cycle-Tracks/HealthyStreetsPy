import asyncio

from shiny import reactive, ui


def register_region_handlers(
    *,
    input,
    session,
    data_state,
    baseline_state,
    map_state,
    selected_guid,
    selected_snapshot,
    current_region,
    pending_region,
    allow_region_change,
    changes_made,
    last_save_click,
    last_discard_click,
    loading_message,
    loading_active,
    ensure_loading_modal,
    set_map_state,
    read_region_sheet,
    prepare_routes_df,
    get_gspread_client,
    coords_to_ewkt,
    default_sheet_id,
    logger,
):
    @reactive.effect
    def _toggle_controls():
        disabled = not changes_made.get()
        asyncio.create_task(
            session.send_custom_message(
                "hss_set_disabled",
                {"id": "region_fieldset", "disabled": changes_made.get()},
            )
        )
        ui.update_action_button("save", disabled=disabled)
        ui.update_action_button("discard", disabled=disabled)

    @reactive.effect
    async def _load_region():
        region = input.region()
        if not region:
            logger.info("Load region: no region selected")
            loading_active.set(False)
            return
        if region == current_region.get() and not map_state.get().empty:
            logger.info("Load region: unchanged (%s)", region)
            return
        if changes_made.get() and not allow_region_change.get():
            if region != current_region.get():
                logger.info(
                    "Load region blocked: current=%s pending=%s new=%s changes_made=%s",
                    current_region.get(),
                    pending_region.get(),
                    region,
                    changes_made.get(),
                )
                pending_region.set(region)
                ui.modal_show(
                    ui.modal(
                        ui.p("You have unsaved changes. Switching boroughs will discard them. Continue?"),
                        title="Discard unsaved changes?",
                        easy_close=False,
                        footer=ui.TagList(
                            ui.input_action_button("cancel_region_change", "Cancel"),
                            ui.input_action_button("confirm_region_change", "Discard and switch", class_="btn-danger"),
                        ),
                    )
                )
                if current_region.get():
                    ui.update_select("region", selected=current_region.get())
                return
        allow_region_change.set(False)
        loading_message.set(f"Loading {region} data...")
        loading_active.set(True)
        ensure_loading_modal()
        df = await asyncio.to_thread(read_region_sheet, default_sheet_id, region)
        prepared = await asyncio.to_thread(prepare_routes_df, df)
        data_state.set(prepared)
        baseline_state.set(prepared.copy())
        set_map_state(prepared, "load_region")
        selected_guid.set(None)
        selected_snapshot.set(None)
        changes_made.set(False)
        current_region.set(region)
        loading_active.set(False)

    @reactive.effect
    @reactive.event(input.confirm_region_change)
    def _confirm_region_change():
        target = pending_region.get()
        if not target:
            return
        allow_region_change.set(True)
        ui.modal_remove()
        ui.update_select("region", selected=target)
        pending_region.set("")

    @reactive.effect
    @reactive.event(input.cancel_region_change)
    def _cancel_region_change():
        pending_region.set("")
        ui.modal_remove()

    @reactive.effect
    @reactive.event(input.save)
    def _save_sheet():
        val = input.save() or 0
        if val <= last_save_click.get():
            return
        last_save_click.set(val)
        if not changes_made.get():
            return
        client = get_gspread_client()
        if not client:
            return
        df = data_state.get().copy()
        df["text_coords"] = df["_coords"].apply(lambda c: coords_to_ewkt(c) if c else "")
        df = df.drop(columns=[col for col in df.columns if col.startswith("_") or col == "guid"])
        worksheet = client.open_by_key(default_sheet_id).worksheet(input.region())
        worksheet.clear()
        worksheet.update([df.columns.values.tolist()] + df.astype(object).values.tolist())
        changes_made.set(False)
        baseline_state.set(data_state.get().copy())

    @reactive.effect
    @reactive.event(input.discard)
    def _discard_changes():
        val = input.discard() or 0
        if val <= last_discard_click.get():
            return
        last_discard_click.set(val)
        if not changes_made.get():
            return
        logger.info("Discard changes requested (region=%s)", input.region())
        ui.modal_show(
            ui.modal(
                ui.p("Discard all unsaved changes for this borough?"),
                title="Discard changes?",
                easy_close=False,
                footer=ui.TagList(
                    ui.input_action_button("cancel_discard", "Cancel"),
                    ui.input_action_button("confirm_discard", "Discard changes", class_="btn-danger"),
                ),
            )
        )

    @reactive.effect
    @reactive.event(input.confirm_discard)
    def _confirm_discard():
        ui.modal_remove()
        df = read_region_sheet(default_sheet_id, input.region())
        prepared = prepare_routes_df(df)
        data_state.set(prepared)
        baseline_state.set(prepared.copy())
        set_map_state(prepared, "confirm_discard")
        selected_guid.set(None)
        selected_snapshot.set(None)
        changes_made.set(False)

    @reactive.effect
    @reactive.event(input.cancel_discard)
    def _cancel_discard():
        ui.modal_remove()
