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

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import pandas as pd
import numpy as np


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
        matrix: {row_val: {col_val: {'sales': float, 'count': int, 'avg': float}}}
        row_values: 纵向维度值列表（排序后）
        col_values: 横向维度值列表（排序后）
    """
    # 验证列是否存在
    for col in [row_col, col_col, value_col]:
        if col not in df.columns:
            print(f"错误: 列「{col}」不在数据中。可用列: {', '.join(df.columns)}")
            sys.exit(1)

    # 转换销列为数值
    df[value_col] = pd.to_numeric(df[value_col], errors='coerce')

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

            if len(subset) > 0:
                total_sales = subset[value_col].sum()
                asin_count = len(subset)
                avg_sales = total_sales / asin_count if asin_count > 0 else 0
                matrix[row_val][col_val] = {
                    'sales': total_sales,
                    'count': asin_count,
                    'avg': avg_sales
                }
            else:
                matrix[row_val][col_val] = None

    return matrix, row_values, col_values


# ============================================================
# Excel 输出
# ============================================================

def export_excel(matrix, row_values, col_values, row_col, col_col, output_path):
    """输出 Excel 表格。"""
    # 构建数据
    data = []
    for row_val in row_values:
        row_data = [row_val]
        for col_val in col_values:
            cell = matrix[row_val].get(col_val)
            if cell:
                # 格式: 销额 (ASIN数量个, 平均销额均)
                cell_text = f"{cell['sales']:,.0f} ({cell['count']}个, {cell['avg']:,.1f}均)"
            else:
                cell_text = ''
            row_data.append(cell_text)
        data.append(row_data)

    # 创建 DataFrame
    columns = [row_col] + col_values
    df_matrix = pd.DataFrame(data, columns=columns)

    # 计算汇总行和列
    summary_row = [f"合计"]
    for col_val in col_values:
        total_sales = 0
        total_count = 0
        for row_val in row_values:
            cell = matrix[row_val].get(col_val)
            if cell:
                total_sales += cell['sales']
                total_count += cell['count']
        if total_count > 0:
            avg_sales = total_sales / total_count
            summary_row.append(f"{total_sales:,.0f} ({total_count}个, {avg_sales:,.1f}均)")
        else:
            summary_row.append('')

    # 添加汇总行
    df_summary = pd.DataFrame([summary_row], columns=columns)
    df_final = pd.concat([df_matrix, df_summary], ignore_index=True)

    # 输出 Excel
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df_final.to_excel(writer, sheet_name='产品矩阵', index=False)

        # 添加参数信息 sheet
        info_df = pd.DataFrame({
            '参数': ['纵向维度', '横向维度', '销额列'],
            '值': [row_col, col_col, '已聚合']
        })
        info_df.to_excel(writer, sheet_name='参数信息', index=False)

    print(f"\n  矩阵已保存: {output_path}")


# ============================================================
# 主入口
# ============================================================

def main():
    args = parse_args()

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
        df_merge['_month_value'] = pd.to_numeric(df_merge['_month_value'], errors='coerce')
        # merge via ASIN (元数据左连接)
        if 'ASIN' not in df.columns:
            print(f"错误: 元数据 Sheet「{args.sheet}」中无 ASIN 列。可用列: {', '.join(df.columns)}")
            sys.exit(1)
        df['ASIN'] = df['ASIN'].astype(str).str.strip()
        before = len(df)
        df = df.merge(df_merge, on='ASIN', how='left')
        after = len(df)
        print(f"  合并月份数据: {before} 条 → {df['_month_value'].notna().sum()} 条有值")
        value_col = '_month_value'
    else:
        value_col = args.value_col

    # 2. 应用筛选条件
    df = filter_data(df, args.filter)

    if df.empty:
        print("\n筛选后没有数据，请检查筛选条件。")
        sys.exit(1)

    print(f"\n  有效数据: {len(df)} 条")

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
    matrix, row_values, col_values = build_matrix(
        df, args.row_col, args.col_col, value_col,
        row_values_specified, col_values_specified
    )

    # 5. 输出 Excel
    output_path = args.output
    if not output_path:
        output_path = "product_matrix.xlsx"

    export_excel(matrix, row_values, col_values, args.row_col, args.col_col, output_path)

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
            if cell:
                row_str += f"{cell['sales']:>15,.0f} "
            else:
                row_str += f"{'':>15} "
        print(row_str)

    print(f"\n{'=' * 60}")
    print("  完成")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
