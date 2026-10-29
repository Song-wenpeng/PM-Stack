"""Shared missing-value rules for field extraction and workbook writeback."""
import pandas as pd
import os


def normalization_enabled():
    """Legacy script callers opt in; the desktop UI enables this by default."""
    return os.getenv('EXTRACT_NORMALIZE', '0').strip().lower() in {'1', 'true', 'yes', 'y'}


def is_empty_extracted_field(value):
    # Explicit absence is an answer, not a request to guess a replacement.
    if normalization_enabled() and isinstance(value, str) and value.strip() == '无':
        return False
    return is_empty_field(value)


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
