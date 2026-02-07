import logging
import os
from typing import Optional

APP_TITLE = "Healthy Streets (Shiny for Python)"
DEFAULT_SHEET_ID = "1x2SoDAUl8cgxiIhRgwz-74qLzt1xqxzCvorcHA3XGQE"
ACCESS_SHEET_ID = "1yir2yFrlCX614XVnVbKKX-DRhojOPtKP1YQv4luMu4s"
ACCESS_SHEET_NAME = "Access"
ACCESS_TABLE_CACHE: Optional[object] = None
HACK_QUICK_AUTO_LOGIN = False
LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}
AUTO_LOGIN_ENABLED = HACK_QUICK_AUTO_LOGIN and (os.environ.get("SHINY_SERVER_HOST", "localhost") in LOCAL_HOSTNAMES)
DEFAULT_REGION = "Richmond upon Thames"
DEFAULT_MAP_CENTER = (51.5074, -0.1278)
HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "Helpers"))
BOROUGHS_KML = os.path.join(HELPERS_DIR, "full_boroughs.kml")
LONDON_MASK_KML = os.path.join(HELPERS_DIR, "LondonMask.kml")
TFL_GEOJSON = os.path.join(HELPERS_DIR, "GLA_TLRN_HAB_wgs84.geojson")
LCC_TFL_GEOJSON = os.path.join(HELPERS_DIR, "lcc_special_tlrn.geojson")
CYCLE_ROUTES_JSON = os.path.join(HELPERS_DIR, "CycleRoutes.json")
NOMINATIM_ENABLED = os.environ.get("NOMINATIM_ENABLED", "").lower() in {"1", "true", "yes", "y"}
NOMINATIM_USER_AGENT = os.environ.get("NOMINATIM_USER_AGENT", "")
NOMINATIM_EMAIL = os.environ.get("NOMINATIM_EMAIL", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("healthy_streets_shinypy")

MAP_COLORS = {
    "polyline": "#E76D02",
    "polyline_approved": "#cd0002",
    "polyline_rejected": "#5c5555ff",
    "polyline_highlight": "#723FA6",
    "polyline_filter": "#2F9E44",
    "tfl_lines": "#1c42d7ff",
    "cycle_superhighway": "#7A1E1E",
    "cycleway": "#1F6F4A",
    "quietway": "#4B2A6A",
}

ROUTE_STYLE_DEFAULT = "Default"
ROUTE_STYLE_SCHEMES = {
    "Default": {
        **MAP_COLORS,
    },
    "Contrast": {
        "polyline": "#0050FF",
        "polyline_approved": "#FF2D55",
        "polyline_rejected": "#6B6B6B",
        "polyline_highlight": "#FFD400",
        "polyline_filter": "#00D084",
        "tfl_lines": "#3B82F6",
    },
    "Neon": {
        "polyline": "#00FFB3",
        "polyline_approved": "#FF5E00",
        "polyline_rejected": "#BDBDBD",
        "polyline_highlight": "#FF00FF",
        "polyline_filter": "#00E5FF",
        "tfl_lines": "#7C5CFF",
    },
    "OCM": {
        "polyline": "#F2A900",
        "polyline_approved": "#E6007A",
        "polyline_rejected": "#555555",
        "polyline_highlight": "#00C2FF",
        "polyline_filter": "#00D084",
        "tfl_lines": "#1c42d7ff",
    },
}


def get_route_style(name: Optional[str]) -> dict:
    if not name:
        name = ROUTE_STYLE_DEFAULT
    return ROUTE_STYLE_SCHEMES.get(name, ROUTE_STYLE_SCHEMES[ROUTE_STYLE_DEFAULT])
ONE_WAY_DASH = "3 6"

CHOICES = {
    "direction": {"Two Way": "TwoWay", "One Way": "OneWay"},
    "flow": {
        "Unknown": "",
        "With flow": "WithFlow",
        "Bi-directional": "BiDirectional",
        "Contraflow": "Contraflow",
    },
    "protection": {
        "Unknown": "",
        "Temporary/flexible": "TemporaryFlexible",
        "Floating parking": "FloatingParking",
        "Full kerb": "FullKerb",
        "Stepped/delineated": "SteppedDelineated",
        "Parallel path": "ParallelPath",
    },
    "ownership": {"Unknown": "", "TFL": "TFL", "Borough": "Borough", "Other": "Other"},
    "year_before": {"In": "In", "Before": "Before"},
}

TOOLTIP_TEXT = {
    "name": "The name of the street or area this segment is in?",
    "id": "A unique identifier to help identify this segment - made up of nonsense words - or choose something you like",
    "comment": "Comments/questions about this segment",
    "oneway": "Is this segment one way - or two way?",
    "flow": "Are lanes on one side of the street or both?",
    "protection": "What type of protection does this facility offer?",
    "designation": "What is the cycle route's designation, if there is one?",
    "ownership": "Ownership of the road (ie, is it TLRN)?",
    "year_before": "Do we know exactly when this facility was built?",
    "year_built": "Year this facility was built in (or before)",
    "audited_in_person": "Has this facility been audited in person?",
    "audited_online": "Has this facility been audited using online maps/streetview?",
    "rejected": "Had this facility been rejected? If yes, then put details in the comments",
}
