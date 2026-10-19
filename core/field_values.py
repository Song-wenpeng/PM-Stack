"""Shared missing-value rules for field extraction and workbook writeback."""
import pandas as pd


def is_empty_field(value):
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return (not text or text.lower() in {'nan', 'none', 'null', 'n/a', 'na'}
            or text in {'未找到', '无', '空', '未知', '未说明'})
