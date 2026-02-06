import json
import os
from typing import List

import pandas as pd

from config import ACCESS_SHEET_ID, ACCESS_SHEET_NAME, ACCESS_TABLE_CACHE, logger

try:
    import gspread
except Exception:  # pragma: no cover
    gspread = None


def get_gspread_client():
    if gspread is None:
        return None

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    creds_json = os.getenv("GSHEETS_SERVICE_ACCOUNT_JSON")

    if creds_path:
        return gspread.service_account(filename=creds_path)

    if creds_json:
        try:
            data = json.loads(creds_json)
        except json.JSONDecodeError:
            return None
        return gspread.service_account_from_dict(data)

    return None


def list_regions(sheet_id: str) -> List[str]:
    client = get_gspread_client()
    if not client:
        return []

    sheet = client.open_by_key(sheet_id)
    return [ws.title for ws in sheet.worksheets() if ws.title != "Sheet1"]


def read_region_sheet(sheet_id: str, region: str) -> pd.DataFrame:
    client = get_gspread_client()
    if client:
        worksheet = client.open_by_key(sheet_id).worksheet(region)
        records = worksheet.get_all_records()
        return pd.DataFrame(records)

    url = (
        "https://docs.google.com/spreadsheets/d/"
        f"{sheet_id}/gviz/tq?tqx=out:csv&sheet={region}"
    )
    return pd.read_csv(url)


def read_access_sheet() -> pd.DataFrame:
    client = get_gspread_client()
    if client:
        worksheet = client.open_by_key(ACCESS_SHEET_ID).worksheet(ACCESS_SHEET_NAME)
        records = worksheet.get_all_records()
        return pd.DataFrame(records)

    url = (
        "https://docs.google.com/spreadsheets/d/"
        f"{ACCESS_SHEET_ID}/gviz/tq?tqx=out:csv&sheet={ACCESS_SHEET_NAME}"
    )
    return pd.read_csv(url)


def get_access_table_once() -> pd.DataFrame:
    global ACCESS_TABLE_CACHE
    if ACCESS_TABLE_CACHE is None:
        logger.info("Loading access table...")
        ACCESS_TABLE_CACHE = read_access_sheet()
    return ACCESS_TABLE_CACHE.copy()
