from typing import Tuple

import pandas as pd


def _cell_equal(a: object, b: object) -> bool:
    try:
        if pd.isna(a) and pd.isna(b):
            return True
    except Exception:
        pass
    if a is None and b is None:
        return True
    return a == b


def compute_change_summary(base: pd.DataFrame, cur: pd.DataFrame) -> Tuple[int, int, int]:
    if base.empty or cur.empty:
        return 0, 0, 0
    if "guid" not in base.columns or "guid" not in cur.columns:
        return 0, 0, 0
    base_guids = set(base["guid"].astype(str))
    cur_guids = set(cur["guid"].astype(str))
    added = len(cur_guids - base_guids)
    removed = len(base_guids - cur_guids)
    common = list(cur_guids & base_guids)
    compare_cols = [
        c for c in cur.columns
        if c in base.columns and c not in {"History", "LastEdited", "WhenCreated"}
    ]
    changed = 0
    if common:
        base_idx = base.set_index(base["guid"].astype(str), drop=False)
        cur_idx = cur.set_index(cur["guid"].astype(str), drop=False)
        for guid in common:
            b_row = base_idx.loc[guid]
            c_row = cur_idx.loc[guid]
            for col in compare_cols:
                if not _cell_equal(b_row[col], c_row[col]):
                    changed += 1
                    break
    return added, removed, changed


__all__ = ["compute_change_summary"]
