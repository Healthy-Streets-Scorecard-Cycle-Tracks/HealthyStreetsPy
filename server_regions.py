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
    region_pref_ready,
    set_map_state,
    read_region_sheet,
    write_region_sheet,
    prepare_routes_df,
    get_gspread_client,
    coords_to_ewkt,
    default_sheet_id,
    logger,
):
    @reactive.effect
    def _toggle_controls():
        disabled = not changes_made.get()
        is_loading = loading_active.get()
        asyncio.create_task(
            session.send_custom_message(
                "hss_set_disabled",
                {"id": "region_fieldset", "disabled": changes_made.get() or is_loading},
            )
        )
        ui.update_action_button("save", disabled=disabled)
        ui.update_action_button("discard", disabled=disabled)

    async def _run_with_retry(label: str, func, *args, **kwargs):
        rate_notified = {"shown": False}

        def _on_retry(attempt: int, delay: float, elapsed: float, exc: Exception):
            logger.warning(
                "Google Sheets rate limit (429) during %s; attempt=%s wait=%.1fs elapsed=%.1fs",
                label,
                attempt,
                delay,
                elapsed,
            )
            loading_message.set(f"{label} (rate limited, retrying in {delay:.0f}s)...")
            if not rate_notified["shown"]:
                ui.notification_show(
                    "Google Sheets is rate limiting requests. Retrying with backoff...",
                    type="warning",
                )
                rate_notified["shown"] = True

        return await asyncio.to_thread(func, *args, on_retry=_on_retry, **kwargs)

    @reactive.effect
    async def _load_region():
        region = input.region()
        if not region:
            logger.info("Load region: no region selected")
            loading_active.set(False)
            return
        if not region_pref_ready.get():
            logger.info("Load region waiting for region_pref")
            return
        if loading_active.get():
            logger.info("Load region ignored while loading (requested=%s)", region)
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
                    logger.info(
                        "Region select reset: keep current=%s (pending=%s new=%s)",
                        current_region.get(),
                        pending_region.get(),
                        region,
                    )
                    ui.update_select("region", selected=current_region.get())
                return
        allow_region_change.set(False)
        loading_message.set(f"Loading {region} data...")
        loading_active.set(True)
        ensure_loading_modal()
        try:
            df = await _run_with_retry(f"Loading {region} data", read_region_sheet, default_sheet_id, region)
            prepared = await asyncio.to_thread(prepare_routes_df, df)
            data_state.set(prepared)
            baseline_state.set(prepared.copy())
            set_map_state(prepared, "load_region")
            selected_guid.set(None)
            selected_snapshot.set(None)
            changes_made.set(False)
            current_region.set(region)
        finally:
            loading_active.set(False)

    @reactive.effect
    @reactive.event(input.confirm_region_change)
    def _confirm_region_change():
        target = pending_region.get()
        if not target:
            return
        allow_region_change.set(True)
        ui.modal_remove()
        logger.info("Region select set: confirm discard -> %s", target)
        ui.update_select("region", selected=target)
        pending_region.set("")

    @reactive.effect
    @reactive.event(input.cancel_region_change)
    def _cancel_region_change():
        pending_region.set("")
        ui.modal_remove()

    @reactive.effect
    @reactive.event(input.reports)
    def _show_reports_modal():
        ui.modal_show(
            ui.modal(
                ui.p(
                    "TODO - we need to generate reports and geojson here, including TfL reports, "
                    "change reports and maybe Cycle Route reports too."
                ),
                title="Reports",
                easy_close=False,
                footer=ui.input_action_button("close_reports", "Close"),
            )
        )

    @reactive.effect
    @reactive.event(input.close_reports)
    def _close_reports_modal():
        ui.modal_remove()

    @reactive.effect
    @reactive.event(input.save)
    async def _save_sheet():
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
        loading_message.set("Saving changes to Google Sheets...")
        loading_active.set(True)
        ensure_loading_modal()
        try:
            await _run_with_retry("Saving changes", write_region_sheet, default_sheet_id, input.region(), df)
            changes_made.set(False)
            baseline_state.set(data_state.get().copy())
        finally:
            loading_active.set(False)

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
    async def _confirm_discard():
        ui.modal_remove()
        loading_message.set(f"Reloading {input.region()} data...")
        loading_active.set(True)
        ensure_loading_modal()
        try:
            df = await _run_with_retry(
                f"Reloading {input.region()} data",
                read_region_sheet,
                default_sheet_id,
                input.region(),
            )
            prepared = await asyncio.to_thread(prepare_routes_df, df)
            data_state.set(prepared)
            baseline_state.set(prepared.copy())
            set_map_state(prepared, "confirm_discard")
            selected_guid.set(None)
            selected_snapshot.set(None)
            changes_made.set(False)
        finally:
            loading_active.set(False)

    @reactive.effect
    @reactive.event(input.cancel_discard)
    def _cancel_discard():
        ui.modal_remove()
