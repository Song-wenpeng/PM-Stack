# -*- coding: utf-8 -*-
"""
产品路线矩阵（销额数据版）

从 Excel 数据中按两个维度交叉分析，生成产品路线矩阵。
每个单元格显示：销额总和、ASIN数量、平均销额。

用法:
    # 方式一：从元数据 Sheet 指定列取值（原有逻辑）
    python product_matrix2.py --file data.xlsx --sheet "元数据" --row-col "三级分类" --col-col "插孔布局" --value-col "月销额"

    # 方式二：从子表格的指定月份列取值（新逻辑）
    python product_matrix2.py --file data.xlsx --sheet "元数据" \\
        --data-sheet "子体销额" --month-col "2025-12" \\
        --row-col "三级分类" --col-col "插孔布局"

    # 带筛选条件
    python product_matrix2.py --file data.xlsx --sheet "元数据" --filter "排插类型=条形" \\
        --data-sheet "子体销额" --month-col "2025-12" \\
        --row-col "三级分类" --col-col "插孔布局"
"""

import os
import sys
import argparse
import datetime as dt
import math

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import pandas as pd
import numpy as np
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.report_io import normalized_path, require_distinct, write_excel, SafeWriteError


# ============================================================
# 金额解析
# ============================================================

CURRENCY_SYMBOLS = '€$£¥￥₹'
BLANK_TEXT = {'', '-', '--', 'nan', 'none', 'nat'}
SAMPLE_LIMIT = 5


def parse_amount(value):
    """解析混合格式金额，返回 (数值或 nan, 原因)。

    原因只有三种：'' 表示可用数值，'空值' 表示本来就没有数据，
    '不可解析' 表示有内容但不是金额。区分两者是为了让缺失被明确报告，
    而不是像 pd.to_numeric(errors='coerce') 那样静默变成 NaN 后从合计里消失。
    """
    if value is None:
        return math.nan, '空值'
    if isinstance(value, bool):
        return math.nan, '不可解析'
    if isinstance(value, (dt.date, dt.datetime, pd.Timestamp)):
        return math.nan, '不可解析'
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        if math.isnan(number):
            return math.nan, '空值'
        if not math.isfinite(number):
            return math.nan, '不可解析'
        return number, ''

    text = str(value).strip()
    if text.lower() in BLANK_TEXT:
        return math.nan, '空值'
    negative = text.startswith('(') and text.endswith(')')
    if negative:
        text = text[1:-1].strip()
    cleaned = ''.join(ch for ch in text if not ch.isspace() and ch not in CURRENCY_SYMBOLS)
    if cleaned.lower() in BLANK_TEXT:
        return math.nan, '空值'
    if ',' in cleaned and '.' in cleaned:
        # "1.234,56"（欧式）与 "1,234.56"（英美）靠最后一个分隔符区分
        if cleaned.rfind(',') > cleaned.rfind('.'):
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    else:
        cleaned = cleaned.replace(',', '')
    try:
        number = float(cleaned)
    except ValueError:
        return math.nan, '不可解析'
    if not math.isfinite(number):
        return math.nan, '不可解析'
    return (-number if negative else number), ''


def parse_amount_column(series):
    parsed = [parse_amount(value) for value in series]
    values = pd.Series([item[0] for item in parsed], index=series.index, dtype='float64')
    reasons = pd.Series([item[1] for item in parsed], index=series.index, dtype=object)
    return values, reasons


def report_amount_quality(column_name, series, values, reasons):
    """打印并返回金额质量统计；不可解析的值给出样例，便于用户回查源数据。"""
    bad_mask = reasons == '不可解析'
    samples = [str(v).strip() for v in series[bad_mask].head(SAMPLE_LIMIT)]
    stats = {
        '有效金额行数': int(values.notna().sum()),
        '空金额行数': int((reasons == '空值').sum()),
        '不可解析金额行数': int(bad_mask.sum()),
        '不可解析金额样例': '、'.join(samples) if samples else '无',
    }
    print(f"  金额解析（{column_name}）: 共{len(reasons)}行，有效{stats['有效金额行数']}行，"
          f"空值{stats['空金额行数']}行，不可解析{stats['不可解析金额行数']}行")
    if stats['不可解析金额行数']:
        print(f"  [警告] 有 {stats['不可解析金额行数']} 行金额无法解析，已按缺失处理，"
              f"不计入合计与均值。样例: {stats['不可解析金额样例']}")
    if stats['空金额行数']:
        print(f"  [提示] 有 {stats['空金额行数']} 行金额为空，单元格会单独标出缺失行数，"
              f"不会当成销额为 0。")
    return stats


# ============================================================
# 参数解析
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description='产品路线矩阵 — 按两个维度交叉分析，生成销额数据矩阵'
    )
    parser.add_argument('--file', required=True,
                        help='Excel 文件路径')
    parser.add_argument('--sheet', required=True,
                        help='Sheet 名称')
    parser.add_argument('--filter', action='append', default=[],
                        help='筛选条件，格式: 列名=值 (如 --filter 排插类型=条形)，可多次指定')
    parser.add_argument('--row-col', required=True,
                        help='纵向维度列名（如 三级分类）')
    parser.add_argument('--row-values', default='',
                        help='纵向维度的具体值，逗号分隔 (如 "普通排插,家用增强,工具排插"，留空=全部)')
    parser.add_argument('--col-col', required=True,
                        help='横向维度列名（如 插孔布局）')
    parser.add_argument('--col-values', default='',
                        help='横向维度的具体值，逗号分隔 (如 "条形-单列,条形-双列,条形-三列,条形-四列"，留空=全部)')
    parser.add_argument('--value-col', default='',
                        help='销额列名（如 月销额）。与 --data-sheet 互斥，二选一')
    parser.add_argument('--data-sheet', default='',
                        help='子数据表格 Sheet 名（行=ASIN，列=月份）。指定后通过 --month-col 取值')
    parser.add_argument('--month-col', default='',
                        help='子数据表格中的月份列名（如 2025-12）。需配合 --data-sheet 使用')
    parser.add_argument('--output', default='',
                        help='输出文件路径 (默认: product_matrix.xlsx)')
    return parser.parse_args()


# ============================================================
# 数据读取
# ============================================================

def load_data(file_path, sheet_name):
    """读取 Excel 数据。"""
    if not os.path.isfile(file_path):
        if os.path.isdir(file_path):
            print(f"错误: 输入的是文件夹，需要选择具体的 Excel 文件。路径: {file_path}")
        else:
            print(f"错误: 文件不存在。路径: {file_path}")
        sys.exit(1)

    print(f"读取: {file_path} / {sheet_name}")
    df = pd.read_excel(file_path, sheet_name=sheet_name)
    df.columns = df.columns.astype(str).str.strip()
    return df


def filter_data(df, filter_exprs):
    """应用筛选条件。"""
    if not filter_exprs:
        return df

    for expr in filter_exprs:
        if '=' not in expr:
            print(f"错误: --filter 格式应为 列名=值，收到: {expr}")
            sys.exit(1)
        col, val = expr.split('=', 1)
        col, val = col.strip(), val.strip()

        if col not in df.columns:
            print(f"错误: 筛选列「{col}」不在数据中。可用列: {', '.join(df.columns)}")
            sys.exit(1)

        before = len(df)
        # 先尝试字符串比较
        mask = df[col].astype(str).str.strip() == val
        # 如果结果为空，尝试数值比较
        if mask.sum() == 0:
            try:
                val_num = float(val)
                mask = df[col] == val_num
            except (ValueError, TypeError):
                pass

        df = df[mask]
        print(f"  筛选: {col}={val}  ({before} → {len(df)} 条)")

    return df


# ============================================================
# 矩阵构建
# ============================================================

def build_matrix(df, row_col, col_col, value_col, row_values_specified=None, col_values_specified=None):
    """构建矩阵数据。

    Args:
        df: DataFrame
        row_col: 纵向维度列名
        col_col: 横向维度列名
        value_col: 销额列名
        row_values_specified: 用户指定的纵向维度值列表（可选）
        col_values_specified: 用户指定的横向维度值列表（可选）

    Returns:
        matrix: {row_val: {col_val: {'sales': float, 'count': int, 'avg': float,
                                     'missing': int, 'rows': int} 或 None}}
        row_values: 纵向维度值列表（排序后）
        col_values: 横向维度值列表（排序后）
        stats: 金额解析质量统计，用于写入「参数信息」并在日志中说明
    """
    # 验证列是否存在
    for col in [row_col, col_col, value_col]:
        if col not in df.columns:
            print(f"错误: 列「{col}」不在数据中。可用列: {', '.join(df.columns)}")
            sys.exit(1)

    # 转换销列为数值：兼容千分位与货币符号，不可解析的单独计数而不是静默丢弃
    raw_values = df[value_col]
    df[value_col], reasons = parse_amount_column(raw_values)
    stats = report_amount_quality(value_col, raw_values, df[value_col], reasons)

    # 获取纵向和横向的值
    if row_values_specified:
        row_values = row_values_specified
    else:
        row_values = sorted(df[row_col].dropna().astype(str).str.strip().unique().tolist())

    if col_values_specified:
        col_values = col_values_specified
    else:
        col_values = sorted(df[col_col].dropna().astype(str).str.strip().unique().tolist())

    print(f"\n  纵向维度 ({row_col}): {len(row_values)} 个值")
    print(f"  横向维度 ({col_col}): {len(col_values)} 个值")

    # 初始化矩阵
    matrix = {}
    for row_val in row_values:
        matrix[row_val] = {}
        for col_val in col_values:
            # 筛选符合条件的数据
            mask = (df[row_col].astype(str).str.strip() == row_val) & \
                   (df[col_col].astype(str).str.strip() == col_val)
            subset = df[mask]
            rows = len(subset)

            if rows == 0:
                matrix[row_val][col_val] = None
                continue

            # 计数与均值只基于有有效金额的行；缺失行数单独保留，
            # 避免把「没有数据」显示成「销额为 0」。
            valid = subset[value_col].notna()
            count = int(valid.sum())
            missing = rows - count
            if count == 0:
                matrix[row_val][col_val] = {'sales': math.nan, 'count': 0, 'avg': math.nan,
                                            'missing': missing, 'rows': rows}
            else:
                total_sales = float(subset.loc[valid, value_col].sum())
                matrix[row_val][col_val] = {
                    'sales': total_sales,
                    'count': count,
                    'avg': total_sales / count,
                    'missing': missing,
                    'rows': rows,
                }

    return matrix, row_values, col_values, stats


# ============================================================
# Excel 输出
# ============================================================

def format_cell(cell):
    """单元格文本：销额 (有效个数, 均值均[, 另N行无有效金额])。

    没有任何有效金额时明确写「无有效金额（N行）」，不显示 0，
    因为 0 会被读成「这些 ASIN 卖得为零」而不是「源数据缺金额」。
    """
    if not cell:
        return ''
    count = cell.get('count', 0)
    sales = cell.get('sales', math.nan)
    missing = cell.get('missing', 0)
    if count <= 0 or not math.isfinite(sales):
        rows = cell.get('rows', missing)
        return f'无有效金额（{rows}行）'
    text = f"{sales:,.0f} ({count}个, {cell.get('avg', 0):,.1f}均"
    if missing:
        text += f", 另{missing}行无有效金额"
    return text + ')'


def export_excel(matrix, row_values, col_values, row_col, col_col, output_path,
                 source_path=None, diagnostics=None):
    """校验临时工作簿后原子另存，不直接打开输出目标写入。"""
    if source_path is not None:
        require_distinct(source_path, output_path)
    # 构建数据
    data = []
    for row_val in row_values:
        row_data = [row_val]
        for col_val in col_values:
            row_data.append(format_cell(matrix[row_val].get(col_val)))
        data.append(row_data)

    # 创建 DataFrame
    columns = [row_col] + col_values
    df_matrix = pd.DataFrame(data, columns=columns)

    # 计算汇总行和列
    summary_row = ["合计"]
    for col_val in col_values:
        total_sales = 0.0
        total_count = 0
        total_missing = 0
        total_rows = 0
        for row_val in row_values:
            cell = matrix[row_val].get(col_val)
            if not cell:
                continue
            total_missing += cell.get('missing', 0)
            total_rows += cell.get('rows', cell.get('count', 0) + cell.get('missing', 0))
            if cell.get('count', 0) > 0 and math.isfinite(cell.get('sales', math.nan)):
                total_sales += cell['sales']
                total_count += cell['count']
        if total_count > 0:
            text = f"{total_sales:,.0f} ({total_count}个, {total_sales / total_count:,.1f}均"
            if total_missing:
                text += f", 另{total_missing}行无有效金额"
            summary_row.append(text + ')')
        elif total_rows > 0:
            summary_row.append(f'无有效金额（{total_rows}行）')
        else:
            summary_row.append('')

    # 添加汇总行
    df_summary = pd.DataFrame([summary_row], columns=columns)
    df_final = pd.concat([df_matrix, df_summary], ignore_index=True)

    parameters = [('纵向维度', row_col), ('横向维度', col_col), ('销额列', '已聚合')]
    for key, value in (diagnostics or {}).items():
        parameters.append((key, '' if value is None else str(value)))
    info_df = pd.DataFrame({'参数': [item[0] for item in parameters],
                            '值': [item[1] for item in parameters]})
    write_excel(output_path, {'产品矩阵': df_final, '参数信息': info_df},
                protected_paths=(source_path,) if source_path is not None else ())
    print(f"\n  矩阵已保存: {output_path}")


# ============================================================
# 主入口
# ============================================================

def main():
    args = parse_args()
    output_path = normalized_path(args.output.strip() or 'product_matrix.xlsx')
    try:
        require_distinct(args.file, output_path)
        if output_path.suffix.lower() != '.xlsx':
            raise ValueError('矩阵输出必须为.xlsx文件')
    except ValueError as exc:
        print(f'错误: {exc}')
        sys.exit(1)

    # 验证取值方式
    use_data_sheet = bool(args.data_sheet and args.month_col)
    use_value_col = bool(args.value_col)
    if not use_data_sheet and not use_value_col:
        print("错误: 必须指定 --value-col（从元数据Sheet取值）或 --data-sheet + --month-col（从子表格取值）")
        sys.exit(1)
    if use_data_sheet and use_value_col:
        print("提示: --data-sheet 和 --value-col 同时指定，优先使用 --data-sheet")

    print("=" * 60)
    print("  产品路线矩阵")
    print("=" * 60)
    print(f"  文件:     {args.file}")
    print(f"  Sheet:    {args.sheet}")
    print(f"  纵向维度: {args.row_col}")
    print(f"  横向维度: {args.col_col}")
    if use_data_sheet:
        print(f"  取值方式: 子表格「{args.data_sheet}」→ 月份列「{args.month_col}」")
    else:
        print(f"  取值方式: 元数据列「{args.value_col}」")
    if args.filter:
        print(f"  筛选条件: {' & '.join(args.filter)}")

    # 1. 读取元数据
    df = load_data(args.file, args.sheet)

    # 1.5 如果指定了子表格，加载并合并月份值
    if use_data_sheet:
        df_data = load_data(args.file, args.data_sheet)
        if args.month_col not in df_data.columns:
            print(f"错误: 数据 Sheet「{args.data_sheet}」中无月份列「{args.month_col}」。可用列: {', '.join(df_data.columns)}")
            sys.exit(1)
        if 'ASIN' not in df_data.columns:
            first_col = df_data.columns[0]
            print(f"  提示: 数据 Sheet 无 ASIN 列，将第一列「{first_col}」作为 ASIN")
            df_data = df_data.rename(columns={first_col: 'ASIN'})
        df_data['ASIN'] = df_data['ASIN'].astype(str).str.strip()
        # 取 ASIN + 指定月份列，合并到元数据
        df_merge = df_data[['ASIN', args.month_col]].copy()
        df_merge = df_merge.rename(columns={args.month_col: '_month_value'})
        # 保留原始月份值到关联/筛选之后，由 build_matrix 统一解析并记录原因。
        # 提前转成 NaN 会丢失不可解析文本与样例，使坏金额被误报为普通空值。
        # merge via ASIN (元数据左连接)
        if 'ASIN' not in df.columns:
            print(f"错误: 元数据 Sheet「{args.sheet}」中无 ASIN 列。可用列: {', '.join(df.columns)}")
            sys.exit(1)
        df['ASIN'] = df['ASIN'].astype(str).str.strip()
        # 子表 ASIN 重复会让左连接按倍数复制元数据行，从而放大金额与数量；
        # 这里先去重并明确告警，不静默膨胀。
        repeated = df_merge['ASIN'][df_merge['ASIN'].duplicated(keep=False)]
        duplicate_data_asins = int(repeated.nunique())
        if duplicate_data_asins:
            examples = '、'.join(sorted(set(repeated))[:SAMPLE_LIMIT])
            print(f"  [警告] 数据 Sheet「{args.data_sheet}」存在重复 ASIN，共 {duplicate_data_asins} 个"
                  f"（如 {examples}）；已按首次出现的月份值保留，避免金额与数量被放大。")
            df_merge = df_merge.drop_duplicates(subset='ASIN', keep='first')
        before = len(df)
        df = df.merge(df_merge, on='ASIN', how='left')
        after = len(df)
        if after != before:
            print(f"  [警告] 合并后行数由 {before} 变为 {after}，结果可能不可靠。")
        print(f"  合并月份数据: {before} 条 → {df['_month_value'].notna().sum()} 条非空，金额有效性将在统计时校验")
        value_col = '_month_value'
    else:
        value_col = args.value_col
        duplicate_data_asins = 0

    # 2. 应用筛选条件
    df = filter_data(df, args.filter)

    if df.empty:
        print("\n筛选后没有数据，请检查筛选条件。")
        sys.exit(1)

    print(f"\n  有效数据: {len(df)} 条")

    # 元数据重复 ASIN 会让同一产品被计入多次。这里只告警并登记，
    # 不自动删除，因为是否重复录入需要用户按源数据判断。
    duplicate_meta_rows = 0
    if 'ASIN' in df.columns:
        meta_asin = df['ASIN'].astype(str).str.strip()
        duplicate_meta_rows = int(meta_asin.duplicated().sum())
        if duplicate_meta_rows:
            examples = '、'.join(sorted(set(meta_asin[meta_asin.duplicated(keep=False)]))[:SAMPLE_LIMIT])
            print(f"  [警告] 元数据存在重复 ASIN，多出 {duplicate_meta_rows} 行（如 {examples}）；"
                  f"未自动删除，合计与个数按现有行数计算，请确认源数据是否重复录入。")

    # 3. 解析用户指定的值
    row_values_specified = None
    if args.row_values:
        row_values_specified = [v.strip() for v in args.row_values.split(',') if v.strip()]
        print(f"  纵向指定值: {row_values_specified}")

    col_values_specified = None
    if args.col_values:
        col_values_specified = [v.strip() for v in args.col_values.split(',') if v.strip()]
        print(f"  横向指定值: {col_values_specified}")

    # 4. 构建矩阵
    matrix, row_values, col_values, stats = build_matrix(
        df, args.row_col, args.col_col, value_col,
        row_values_specified, col_values_specified
    )

    diagnostics = {
        '输入文件': str(args.file),
        '数据Sheet': args.sheet,
        '参与统计行数': len(df),
        '有效金额行数': stats['有效金额行数'],
        '空金额行数': stats['空金额行数'],
        '不可解析金额行数': stats['不可解析金额行数'],
        '不可解析金额样例': stats['不可解析金额样例'],
        '元数据重复ASIN行数': duplicate_meta_rows,
        '子表重复ASIN数': duplicate_data_asins,
        '生成时间': dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }

    # 5. 输出 Excel（只替换通过校验的临时结果）
    try:
        export_excel(matrix, row_values, col_values, args.row_col, args.col_col,
                     output_path, source_path=args.file, diagnostics=diagnostics)
    except SafeWriteError as exc:
        print(f'错误: {exc}')
        sys.exit(1)

    # 6. 打印矩阵预览
    print(f"\n{'=' * 60}")
    print("  矩阵预览（销额）:")
    print(f"{'=' * 60}")

    # 打印表头
    header = f"{'':>15} " + " ".join(f"{cv:>15}" for cv in col_values)
    print(header)
    print("-" * len(header))

    # 打印每一行
    for row_val in row_values:
        row_str = f"{row_val:>15} "
        for col_val in col_values:
            cell = matrix[row_val].get(col_val)
            if cell and cell.get('count', 0) > 0 and math.isfinite(cell.get('sales', math.nan)):
                row_str += f"{cell['sales']:>15,.0f} "
            elif cell:
                row_str += f"{'缺金额':>14} "
            else:
                row_str += f"{'':>15} "
        print(row_str)

    print(f"\n{'=' * 60}")
    print("  完成")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
