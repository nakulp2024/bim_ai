from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd


def read_schedule(path: Path) -> pd.DataFrame:
    """Read an Excel or CSV file into a DataFrame.

    All columns are read as strings so we don't lose precision on IDs that
    look numeric (e.g. Revit ElementIds, Speckle hashes).
    """
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)
    elif suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str, header=0)
    else:
        raise ValueError(f"Unsupported schedule file extension: {suffix}")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _safe_cell(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return str(v)


def summarise(df: pd.DataFrame, sample_n: int = 5) -> dict[str, Any]:
    headers = list(df.columns)
    sample = df.head(sample_n).to_dict(orient="records")
    sample = [{k: _safe_cell(v) for k, v in row.items()} for row in sample]
    return {
        "headers": headers,
        "sample_rows": sample,
        "row_count": int(len(df)),
    }
