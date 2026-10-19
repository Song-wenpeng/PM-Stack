# -*- coding: utf-8 -*-
"""统一销量拆分：保留销量规则，子体矫正销额按当月售价计算。"""

import os
import re
import sys
import argparse
import numpy as np
import pandas as pd

# ============================================================
# 配置
# ============================================================
BASE_REQUIRED = ['ASIN', '父ASIN', '月销量', '子体销量']

# ============================================================
# 辅助函数
# ============================================================

def extract_year_month(filename):
    """从文件名提取年月。

    Competitor-US-2024.04-437681.xlsx → '2024-04'
    Competitor-DE-202512.xlsx → '2025-12'
    排插_US_2024-04_销量拆分.xlsx → '2024-04'
    """
    # YYYY.MM（US 源文件）
    m = re.search(r'(\d{4})\.(\d{2})', filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    # YYYY-MM（输出文件命名）
    m = re.search(r'(\d{4})-(\d{2})', filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    # YYYYMM（DE 格式，如 202512）
    m = re.search(r'(\d{4})(\d{2})(?:\D|$)', filename)
    if m:
        year, month = m.group(1), m.group(2)
        if 1 <= int(month) <= 12:
            return f"{year}-{month}"
    return None


def clean_numeric(series):
    """清洗数值列：去掉逗号、货币符号，转成数值。"""
    return pd.to_numeric(
        series.astype(str)
              .str.replace(',', '', regex=False)
              .str.replace(r'[€$£¥元]', '', regex=True)
              .str.strip()
              .replace({'nan': np.nan, 'None': np.nan, '': np.nan}),
        errors='coerce'
    )


# ============================================================
# 核心拆分逻辑（与 sales_number.py 一致）
# ============================================================

def allocate_metric(group, standard_parent_col, child_col, new_col,
                    note_col, is_integer=True):
    """通用分配逻辑：按子体占比重分配父体值。"""
    target_total = group[standard_parent_col].iloc[0]
    original_child_total = group[child_col].sum()

    def fmt(s):
        return s.round().astype(int) if is_integer else s.round(2)

    # 情况1：父体值为空
    if pd.isna(target_total):
        group[new_col] = fmt(group[child_col])
        group[note_col] = '父体值缺失，保留原子体值'
        return group

    # 情况2：父体值 = 0
    if target_total == 0:
        group[new_col] = fmt(group[child_col])
        group[note_col] = '父体值为0，保留原子体值'
        return group

    # 情况3：子体合计超过父体值 → 父体值疑似错误，保留原子体值
    #   （子体值均为非负，任一子体>父体 等价于 合计>父体，一个判断即可）
    if original_child_total > target_total:
        group[new_col] = fmt(group[child_col])
        group[note_col] = '子体合计超过父体，父体值疑似错误，保留原子体值'
        return group

    # 情况4：子体合计 = 0 → 平均分配
    if original_child_total == 0:
        equal_share = target_total / len(group)
        if is_integer:
            group[new_col] = np.round(equal_share).astype(int)
        else:
            group[new_col] = round(equal_share, 2)
        group[note_col] = '子体合计为0，平均分配'
    else:
        # 情况5：正常按占比分配
        ratios = group[child_col] / original_child_total
        raw_alloc = ratios * target_total
        group[new_col] = fmt(raw_alloc)
        group[note_col] = '按原子体占比重分配'

    # 误差修正：差额补到第一行
    current_sum = group[new_col].sum()
    if is_integer:
        diff = int(round(target_total - current_sum))
        if diff != 0:
            group.iloc[0, group.columns.get_loc(new_col)] += diff
    else:
        diff = round(float(target_total) - float(current_sum), 2)
        if diff != 0:
            idx = group.columns.get_loc(new_col)
            group.iloc[0, idx] = round(group.iloc[0, idx] + diff, 2)

    return group


def process_file(filepath):
    """保留销量分配规则；矫正销额 = 矫正销量 × 本文件子体售价。"""
    df = pd.read_excel(filepath)
    missing = [c for c in BASE_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"数据源缺少以下列: {missing}")
    if df.empty:
        raise ValueError("数据源没有商品行")
    price_columns = [c for c in df.columns if re.fullmatch(
        r'(?:子体当月售价|当月售价|子体售价|售价|价格)(?:[（(][^()（）]+[)）])?', str(c).strip())]
    if len(price_columns) != 1:
        raise ValueError("请保留唯一的价格/售价列（支持价格($)、价格(€)等）；"
                         f"当前识别到：{price_columns or '无'}")
    price_col = price_columns[0]
    price = clean_numeric(df[price_col])
    invalid = price.isna() | ~np.isfinite(price) | (price < 0)
    if invalid.any():
        rows = ', '.join(str(i + 2) for i in df.index[invalid][:10])
        raise ValueError(f"{price_col} 缺失或无效，Excel 行：{rows}。请补齐当月售价后重试")
    invalid_ids = df[['ASIN', '父ASIN']].isna().any(axis=1)
    if invalid_ids.any():
        raise ValueError("ASIN 或父ASIN 缺失，请补齐后重试")
    original_columns = list(df.columns)
    # 临时数据独立保存，避免覆盖源文件同名列。
    work = pd.DataFrame({'parent': df['父ASIN'],
                         'volume': clean_numeric(df['月销量']),
                         'child': clean_numeric(df['子体销量']).fillna(0)})
    idx = work.groupby('parent')['child'].idxmax()
    standards = work.loc[idx].set_index('parent')['volume']
    work['standard'] = work['parent'].map(standards)
    allocated = []
    for _, group in work.groupby('parent', sort=False):
        allocated.append(allocate_metric(group.copy(), 'standard', 'child',
                                         'corrected', 'note', is_integer=True))
    quantities = pd.concat(allocated)['corrected'].reindex(df.index)
    df['子体销量_矫正'] = quantities
    df['子体销售额_矫正'] = (quantities * price).round(2)
    # 保留原列（包括货币符号）、商品属性与行顺序。
    columns = [c for c in original_columns if c not in ('子体销量_矫正', '子体销售额_矫正')]
    columns.insert(columns.index('子体销量') + 1, '子体销量_矫正')
    revenue = next((c for c in columns if str(c) == '子体销售额' or
                    re.fullmatch(r'子体销售额[（(].+[)）]', str(c))), None)
    columns.insert(columns.index(revenue) + 1 if revenue else len(columns), '子体销售额_矫正')
    return df[columns]


def scan_directory(directory):
    """处理当前层级 Excel；排除临时文件、结果和备份。"""
    if not os.path.isdir(directory):
        raise FileNotFoundError(f"目录不存在: {directory}")
    pending, skipped = [], []
    for name in sorted(os.listdir(directory)):
        if not os.path.isfile(os.path.join(directory, name)):
            continue
        if not name.lower().endswith(('.xlsx', '.xls')) or name.startswith('~$'):
            continue
        if any(tag in name for tag in ('_销量拆分', '_拆分结果', '_备份', '.backup')):
            skipped.append((name, '结果或备份文件'))
            continue
        pending.append((name, extract_year_month(name)))
    return pending, skipped


def output_path(filepath, output_dir=None):
    from pathlib import Path
    source = Path(filepath)
    # 年月紧邻后缀，兼容后续历史数据提取；源文件名避免同月覆盖。
    month = extract_year_month(source.name)
    suffix = f'_{month}' if month and not source.stem.endswith(month) else ''
    return str(Path(output_dir or source.parent) / f'{source.stem}{suffix}_销量拆分.xlsx')


def write_result(filepath, destination):
    """先完整计算再原子写入；重跑保留上一版结果备份。"""
    import tempfile
    import shutil
    from datetime import datetime
    result = process_file(filepath)
    if os.path.normcase(os.path.abspath(filepath)) == os.path.normcase(os.path.abspath(destination)):
        raise ValueError('输出文件不能覆盖源文件')
    folder = os.path.dirname(os.path.abspath(destination))
    os.makedirs(folder, exist_ok=True)
    fd, temp = tempfile.mkstemp(suffix='.xlsx', dir=folder)
    os.close(fd)
    try:
        result.to_excel(temp, index=False)
        if os.path.exists(destination):
            backup = destination + '.' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.backup'
            shutil.copy2(destination, backup)
            print(f'已备份上一版结果：{backup}')
        os.replace(temp, destination)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print(f'已保存：{destination}')


def main():
    parser = argparse.ArgumentParser(description='销量拆分：文件或文件夹使用同一计算规则')
    parser.add_argument('source', help='Excel 文件或文件夹')
    parser.add_argument('--output-dir', default='')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--yes', action='store_true', help='兼容旧批量调用')
    args = parser.parse_args()
    source = os.path.abspath(args.source)
    if os.path.isdir(source):
        pending, skipped = scan_directory(source)
        paths = [os.path.join(source, name) for name, _ in pending]
        for name, reason in skipped:
            print(f'跳过：{name}（{reason}）')
    elif os.path.isfile(source) and source.lower().endswith(('.xlsx', '.xls')):
        paths = [source]
    else:
        print('[错误] 请提供有效的 Excel 文件或文件夹')
        return 1
    if not paths:
        print('[错误] 没有可处理的源文件（已排除拆分结果、临时文件和备份）')
        return 1
    print(f'待处理 {len(paths)} 个文件；子体销售额_矫正 = 子体销量_矫正 × 当月售价')
    failed = 0
    for i, path in enumerate(paths, 1):
        destination = output_path(path, args.output_dir)
        if args.dry_run:
            print(f'预览：{path} → {destination}')
            continue
        try:
            write_result(path, destination)
        except Exception as exc:
            failed += 1
            print(f'[错误] {os.path.basename(path)}：{exc}')
        print(f'进度：{i}/{len(paths)}')
    print(f'处理结束：成功 {len(paths) - failed if not args.dry_run else 0}，失败 {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
