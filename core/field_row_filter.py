"""Optional row selection shared by serial and concurrent field extraction."""
from decimal import Decimal, InvalidOperation
import os

import pandas as pd


def normalize_label(value):
    if value is None or pd.isna(value):
        return ''
    text = str(value).strip()
    try:
        number = Decimal(text)
        if number.is_finite():
            return str(number.normalize())
    except InvalidOperation:
        pass
    return text


def select_field_rows(frame):
    """Return original indices and the effective filter for resume validation."""
    if os.getenv('EXTRACT_FILTER_ENABLED', '0') != '1':
        print('[提取范围] 所有行', flush=True)
        return list(frame.index), None
    column = os.getenv('EXTRACT_FILTER_COLUMN', '').strip()
    value = os.getenv('EXTRACT_FILTER_VALUE', '').strip()
    if not column or not value:
        raise ValueError('启用标签筛选后，请填写标签列和标签值。')
    candidates = [c for c in frame.columns if str(c).strip() == column]
    if len(candidates) != 1:
        raise ValueError(f'标签列“{column}”不存在或不唯一，请检查输入文件列名。')
    actual = candidates[0]
    normalized = normalize_label(value)
    indices = frame.index[frame[actual].map(normalize_label) == normalized].tolist()
    print(f'[提取范围] {column} = {value}：匹配 {len(indices)} 行，跳过 {len(frame) - len(indices)} 行', flush=True)
    return indices, {'column': str(actual), 'value': normalized}
