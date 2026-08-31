# -*- coding: utf-8 -*-
"""
批量销量/销售额拆分脚本

自动扫描目录中的竞品数据文件 (Competitor-*.xlsx)，对每个文件的父体销量/
销售额按子体占比进行拆分，在原数据基础上新增 子体销量_矫正 和 子体销售额_矫正 两列。

用法:
    python batch_sales_split.py [directory] [--dry-run]

    directory   要处理的目录路径，默认 ./排插_US/
    --dry-run   预览模式，只列出待处理文件，不执行拆分
"""

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

# 含货币符号的列，运行时自动匹配
AMOUNT_PATTERNS = {
    '月销售额': re.compile(r'^月销售额\(.\)$'),
    '子体销售额': re.compile(r'^子体销售额\(.\)$'),
}

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
    """处理单个竞品数据文件，返回带矫正列的 DataFrame。"""
    df = pd.read_excel(filepath)

    # ---- 动态匹配含货币符号的列名 ----
    col_rename = {}
    for std_name, pattern in AMOUNT_PATTERNS.items():
        matches = [c for c in df.columns if pattern.match(c)]
        if matches:
            col_rename[matches[0]] = std_name

    if len(col_rename) != len(AMOUNT_PATTERNS):
        raise ValueError(
            f"数据源缺少销售额列。需要包含：月销售额(货币符号)、子体销售额(货币符号)。"
            f"\n实际列名: {list(df.columns)}"
        )

    # 校验必需列
    required_cols = BASE_REQUIRED + list(col_rename.keys())
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"数据源缺少以下列: {missing}")

    # 列名标准化
    df = df.rename(columns=col_rename)

    # ---- 数值清洗 ----
    df['月销量_num'] = clean_numeric(df['月销量'])
    df['月销售额_num'] = clean_numeric(df['月销售额'])
    df['子体销量_num'] = clean_numeric(df['子体销量']).fillna(0)
    df['子体销售额_num'] = clean_numeric(df['子体销售额']).fillna(0)

    # ---- 统一父体标准值（取子体销量最大行） ----
    idx = df.groupby('父ASIN')['子体销量_num'].idxmax()
    standards = df.loc[idx, ['父ASIN', '月销量_num', '月销售额_num']].copy()
    standards.columns = ['父ASIN', '标准父体销量', '标准父体销售额']
    df = df.merge(standards, on='父ASIN', how='left')

    df.reset_index(drop=True, inplace=True)

    # ---- 分组分配 ----
    def process_group(group):
        group = allocate_metric(
            group, '标准父体销量', '子体销量_num',
            '子体销量_矫正', '_tmp_sales_note', is_integer=True
        )
        group = allocate_metric(
            group, '标准父体销售额', '子体销售额_num',
            '子体销售额_矫正', '_tmp_revenue_note', is_integer=False
        )
        return group

    result = (
        df.groupby('父ASIN', group_keys=False)
          .apply(process_group)
          .reset_index(drop=True)
    )

    # 删除临时列
    temp_cols = ['月销量_num', '月销售额_num', '子体销量_num', '子体销售额_num',
                 '标准父体销量', '标准父体销售额', '_tmp_sales_note', '_tmp_revenue_note']
    result = result.drop(columns=[c for c in temp_cols if c in result.columns])

    # 将矫正列移到原列右侧
    cols = list(result.columns)
    for ref_col, new_col in [('子体销量', '子体销量_矫正'),
                             ('子体销售额', '子体销售额_矫正')]:
        if ref_col in cols and new_col in cols:
            cols.remove(new_col)
            insert_at = cols.index(ref_col) + 1
            cols.insert(insert_at, new_col)
    result = result[cols]

    return result


# ============================================================
# 文件扫描
# ============================================================

def scan_directory(directory):
    """扫描目录，返回待处理文件列表 (filename, year_month)。"""
    if not os.path.isdir(directory):
        raise FileNotFoundError(f"目录不存在: {directory}")

    all_files = sorted(os.listdir(directory))
    processed_ym = set()  # 已处理年月
    pending = []          # (filename, year_month)
    skipped = []

    # 第一遍：收集已处理年月
    for f in all_files:
        if not f.endswith('.xlsx') or f.startswith('~$'):
            continue
        if '_销量拆分' in f:
            ym = extract_year_month(f)
            if ym:
                processed_ym.add(ym)

    # 第二遍：识别待处理文件
    for f in all_files:
        if not f.endswith('.xlsx') or f.startswith('~$'):
            continue
        # 排除已有输出文件（_销量拆分 / _拆分结果 等）
        if '_销量拆分' in f or '_拆分' in f:
            continue
        if not f.startswith('Competitor-'):
            continue

        ym = extract_year_month(f)
        if not ym:
            skipped.append((f, '无法提取年月'))
            continue
        if ym in processed_ym:
            skipped.append((f, f'已有拆分结果 ({ym})'))
            continue

        pending.append((f, ym))

    return pending, skipped


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='批量销量/销售额拆分 — 自动检测并处理竞品数据文件'
    )
    parser.add_argument(
        'directory', nargs='?', default='./排插_DE/',
        help='要处理的目录路径 (默认: ./排插_DE/)'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='预览模式，只列出待处理文件，不执行拆分'
    )
    parser.add_argument(
        '--yes', action='store_true',
        help='跳过确认提示，直接执行处理'
    )
    args = parser.parse_args()

    directory = os.path.normpath(args.directory)
    parent_name = os.path.basename(directory)

    print("=" * 60)
    print(f"  Batch Sales Split")
    print(f"  Directory: {directory}")
    if args.dry_run:
        print(f"  Mode: DRY RUN (preview only)")
    print("=" * 60)

    pending, skipped = scan_directory(directory)

    all_files = sorted(os.listdir(directory))
    xlsx_files = [f for f in all_files if f.endswith('.xlsx') and not f.startswith('~$')]
    print(f"\n  目录内文件总数: {len(all_files)}")
    print(f"  .xlsx 文件数: {len(xlsx_files)}")
    print(f"  所有文件/文件夹:")
    for f in all_files:
        full = os.path.join(directory, f)
        tag = "[目录]" if os.path.isdir(full) else "[文件]"
        print(f"    {tag} {f}")
    print(f"  待处理: {len(pending)}")
    print(f"  已跳过: {len(skipped)}")

    if skipped:
        print(f"\n  跳过详情:")
        for fname, reason in skipped:
            print(f"    - {fname}  ({reason})")

    if not pending:
        print("\n  没有待处理的文件。")
        return

    print(f"\n  待处理文件:")
    for fname, ym in pending:
        out_name = f"{parent_name}_{ym}_销量拆分.xlsx"
        print(f"    {fname}  →  {out_name}")

    if args.dry_run:
        print(f"\n  [DRY RUN] 共 {len(pending)} 个文件待处理，未执行拆分。")
        return

    # 确认执行。GUI / EXE 模式没有可交互控制台，因此允许 --yes 直接执行。
    if not args.yes:
        confirm = input(f"\n  确认处理以上 {len(pending)} 个文件? [Y/n]: ").strip().lower()
        if confirm in ('n', 'no'):
            print("  已取消。")
            return

    # 逐个处理
    success = 0
    failed = 0
    for i, (fname, ym) in enumerate(pending, 1):
        filepath = os.path.join(directory, fname)
        out_name = f"{parent_name}_{ym}_销量拆分.xlsx"
        out_path = os.path.join(directory, out_name)

        print(f"\n{'─' * 60}")
        print(f"  [{i}/{len(pending)}] {fname}")
        print(f"  → {out_name}")

        try:
            result = process_file(filepath)
            result.to_excel(out_path, index=False)
            rows, cols = result.shape
            print(f"  ✓ 完成 ({rows} 行 × {cols} 列，含 子体销量_矫正 + 子体销售额_矫正)")
            success += 1
        except Exception as e:
            print(f"  ✗ 失败: {e}")
            failed += 1

    # 汇总
    print(f"\n{'=' * 60}")
    print(f"  处理完成: 成功 {success}, 失败 {failed}")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
