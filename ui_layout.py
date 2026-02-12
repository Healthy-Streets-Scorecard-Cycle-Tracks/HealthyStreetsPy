from shiny import ui

from ui_assets import app_styles, map_bridge_script

from grid_page import build_grid_panel
from changes_page import build_changes_panel
from suggestions_page import build_suggestions_panel


def build_app_ui():
    return ui.page_navbar(
        ui.nav_panel(
            "Map",
            map_bridge_script(),
            app_styles(),
            ui.layout_columns(
                ui.card(
                    ui.tags.div(
                        ui.tags.button("✏", title="Add new line", onclick="hssStartDraw()", class_="hss-map-add"),
                        ui.tags.div(
                            ui.input_select(
                                "route_scheme",
                                "",
                                choices=["Default", "Neon", "Contrast", "OCM"],
                                selected="Default",
                            ),
                            ui.input_slider(
                                "route_width",
                                "",
                                min=1,
                                max=12,
                                value=3,
                            ),
                            class_="hss-map-style-controls",
                        ),
                        ui.output_ui("map_view"),
                        class_="hss-map-wrap",
                    ),
                    height="100%",
                ),
                ui.card(
                    ui.output_ui("edit_panel"),
                    height="100%",
                ),
                col_widths=(8, 4),
                fill=True,
                fillable=True,
                gap="1rem",
                height="100%",
            ),
        ),
        build_grid_panel(),
        build_changes_panel(),
        build_suggestions_panel(),
        ui.nav_spacer(),
        ui.nav_control(ui.tags.div(ui.download_button("reports_download", "Download"), class_="hss-hidden-download")),
        ui.nav_control(
            ui.input_action_button(
                "reports",
                "Reports",
                class_="btn btn-outline-secondary btn-sm",
                title="Reports are disabled while there are unsaved changes.",
            )
        ),
        ui.nav_control(ui.output_ui("welcome_banner")),
        title="Healthy Streets",
        sidebar=ui.sidebar(
            ui.tags.fieldset(
                ui.input_select("region", "Borough", choices=[], selected=None),
                id="region_fieldset",
            ),
            ui.tags.div(
                ui.input_action_button("save", "Save changes"),
                ui.input_action_button("discard", "Discard changes", class_="btn-danger"),
                class_="hss-save-discard",
            ),
            ui.tags.div(ui.output_text("change_summary"), class_="hss-change-summary"),
            ui.output_ui("distance_boxes"),
            ui.input_select(
                "highlight_mode",
                "Focus on",
                choices=["None", "Created since", "Edited since", "Owned by", "Audited status"],
                selected="None",
            ),
            ui.output_ui("highlight_controls"),
            open="always",
            width=280,
            padding="1rem",
        ),
        fillable=True,
        fillable_mobile=True,
        selected="Map",
    )
