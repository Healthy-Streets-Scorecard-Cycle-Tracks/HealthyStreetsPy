import json
import os
import time
from typing import Callable, List, Optional

import pandas as pd

from config import ACCESS_SHEET_ID, ACCESS_SHEET_NAME, ACCESS_TABLE_CACHE, logger

try:
    import gspread
    from gspread.exceptions import APIError
    try:
        from googleapiclient.errors import HttpError
    except Exception:  # pragma: no cover
        HttpError = None
except Exception:  # pragma: no cover
    gspread = None
    APIError = None
    HttpError = None


def _is_rate_limit_error(err: Exception) -> bool:
    status = None
    if APIError is not None and isinstance(err, APIError):
        try:
            status = err.response.status_code
        except Exception:
            status = None
    if status is None and HttpError is not None and isinstance(err, HttpError):
        try:
            status = err.resp.status
        except Exception:
            status = None
    if status is None:
        text = str(err).lower()
        if "429" in text or "rate limit" in text:
            status = 429
    return status == 429


def _call_with_retry(
    func: Callable[[], object],
    *,
    max_wait: float = 120.0,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    on_retry: Optional[Callable[[int, float, float, Exception], None]] = None,
):
    start = time.monotonic()
    attempt = 0
    while True:
        try:
            return func()
        except Exception as exc:
            if not _is_rate_limit_error(exc):
                raise
            elapsed = time.monotonic() - start
            if elapsed >= max_wait:
                raise
            attempt += 1
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            if on_retry:
                on_retry(attempt, delay, elapsed, exc)
            time.sleep(delay)


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


def list_regions(sheet_id: str, *, on_retry: Optional[Callable[[int, float, float, Exception], None]] = None) -> List[str]:
    client = get_gspread_client()
    if not client:
        return []

    def _op():
        sheet = client.open_by_key(sheet_id)
        return [ws.title for ws in sheet.worksheets() if ws.title != "Sheet1"]

    return _call_with_retry(_op, on_retry=on_retry)


def read_region_sheet(
    sheet_id: str,
    region: str,
    *,
    on_retry: Optional[Callable[[int, float, float, Exception], None]] = None,
) -> pd.DataFrame:
    client = get_gspread_client()
    if client:
        def _op():
            worksheet = client.open_by_key(sheet_id).worksheet(region)
            return worksheet.get_all_records()

        records = _call_with_retry(_op, on_retry=on_retry)
        return pd.DataFrame(records)

    url = (
        "https://docs.google.com/spreadsheets/d/"
        f"{sheet_id}/gviz/tq?tqx=out:csv&sheet={region}"
    )
    return pd.read_csv(url)


def read_access_sheet(*, on_retry: Optional[Callable[[int, float, float, Exception], None]] = None) -> pd.DataFrame:
    client = get_gspread_client()
    if client:
        def _op():
            worksheet = client.open_by_key(ACCESS_SHEET_ID).worksheet(ACCESS_SHEET_NAME)
            return worksheet.get_all_records()

        records = _call_with_retry(_op, on_retry=on_retry)
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


def write_region_sheet(
    sheet_id: str,
    region: str,
    df: pd.DataFrame,
    *,
    on_retry: Optional[Callable[[int, float, float, Exception], None]] = None,
) -> None:
    client = get_gspread_client()
    if not client:
        raise RuntimeError("Google Sheets client unavailable")

    def _op():
        worksheet = client.open_by_key(sheet_id).worksheet(region)
        worksheet.clear()
        worksheet.update([df.columns.values.tolist()] + df.astype(object).values.tolist())

    _call_with_retry(_op, on_retry=on_retry)
