from shiny import ui


def build_suggestions_panel() -> ui.Tag:
    return ui.nav_panel(
        "Suggestions",
        ui.card(
            ui.tags.p(
                "TODO - we could add suggestions here, including naming unnamed routes, "
                "identifying TfL mismatches, and identifying Designation candidates (and mismatches)."
            ),
            class_="hss-suggestions-card",
        ),
    )
