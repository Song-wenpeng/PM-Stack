# -*- coding: utf-8 -*-
"""
产品矩阵3 — 品牌×三级分类 图片矩阵

列 = 品牌（手动指定），行 = 三级分类分组（自适应行数）。
每个单元格嵌入：商品主图 + ASIN + 自定义属性。

用法:
    python product_matrix3.py \
        --file data.xlsx --sheet "Sheet名" \
        --category-col "三级分类" --brand-col "品牌" \
        --brands "BrandA,BrandB,BrandC" \
        --attrs "插孔布局,功率,价格"

    # 带筛选条件
    python product_matrix3.py --file data.xlsx --sheet "元数据" \
        --filter "排插类型=条形" \
        --category-col "三级分类" --brand-col "品牌" \
        --brands "BrandA,BrandB" --attrs "插孔布局,额定功率"

    # 完整示例
    python product_matrix3.py \
        --file "C:/Users/QJH/WPSDrive/排插_数据_US.xlsx" \
        --sheet "competitor-US-202604" \
        --filter "排插类型=条形" \
        --category-col "三级分类" --category-values "普通排插,家用增强,工具排插" \
        --brand-col "品牌" --brands "BrandA,BrandB,BrandC" \
        --image-col "商品主图" --asin-col "ASIN" \
        --attrs "插孔布局,额定功率,价格" \
        --sort-col "上架时间" --sort-ascending \
        --output "product_matrix_v3.xlsx"
"""

import os
import re
import sys
import time
import argparse

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import requests
import pandas as pd
import numpy as np
from pathlib import Path
from io import BytesIO
from PIL import Image as PILImage

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter


# ============================================================
# 参数解析
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description='产品矩阵3 — 品牌×三级分类 图片矩阵（自适应行数）'
    )
    parser.add_argument('--file', required=True, help='Excel 文件路径')
    parser.add_argument('--sheet', required=True, help='Sheet 名称')
    parser.add_argument('--filter', action='append', default=[],
                        help='筛选条件，格式: 列名=值，可多次指定 (如 --filter 排插类型=条形)')
    parser.add_argument('--category-col', required=True,
                        help='行分组列名（如 三级分类）')
    parser.add_argument('--category-values', default='',
                        help='指定分组值，逗号分隔（留空=全部）')
    parser.add_argument('--brand-col', required=True,
                        help='品牌列名（如 品牌）')
    parser.add_argument('--brands', required=True,
                        help='目标品牌，逗号分隔（如 BrandA,BrandB）')
    parser.add_argument('--image-col', default='商品主图',
                        help='商品主图列名 (默认: 商品主图)')
    parser.add_argument('--asin-col', default='ASIN',
                        help='ASIN 列名 (默认: ASIN)')
    parser.add_argument('--attrs', default='',
                        help='额外属性列，逗号分隔（如 插孔布局,功率,价格）')
    parser.add_argument('--sort-col', default='',
                        help='排序列名（留空=按ASIN排序）')
    parser.add_argument('--sort-ascending', action='store_true', default=True,
                        help='升序排列 (默认)')
    parser.add_argument('--sort-descending', dest='sort_ascending', action='store_false',
                        help='降序排列')
    parser.add_argument('--parent-asin-col', default='',
                        help='父ASIN列名，用于合并变体（留空=不合并，每个子ASIN独立）')
    parser.add_argument('--sales-col', default='',
                        help='销量列名，选销量最高的变体为代表（启用变体合并时必填）')
    parser.add_argument('--variant-cols', default='',
                        help='描述变体的属性列，逗号分隔（如 线长,颜色）')
    parser.add_argument('--launch-date-col', default='',
                        help='上架时间列名，用于提取年份（如 上架时间）')
    parser.add_argument('--output', default='product_matrix3.xlsx',
                        help='输出文件路径 (默认: product_matrix3.xlsx)')
    parser.add_argument('--image-height', type=int, default=120,
                        help='图片高度(px) (默认: 120)')
    parser.add_argument('--image-dir', default='',
                        help='图片缓存目录 (默认: %%TEMP%%/matrix3_images)')
    parser.add_argument('--keep-cache', action='store_true',
                        help='保留下载的图片缓存 (默认删除)')
    return parser.parse_args()


# ============================================================
# 数据 I/O（复用 product_matrix2 模式）
# ============================================================

def load_data(file_path, sheet_name):
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
        mask = df[col].astype(str).str.strip() == val
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
# 工具函数（复用 product_matrix 模式）
# ============================================================

def clean_filename(name):
    name = str(name).strip()
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def safe_str(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def download_and_resize_image(url, save_path, target_height=75, max_retries=3):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.amazon.co.uk/"
    }
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            img = PILImage.open(BytesIO(response.content)).convert("RGB")
            w, h = img.size
            if h <= 0:
                raise ValueError("图片高度异常")
            ratio = target_height / h
            target_width = max(1, int(w * ratio))
            img = img.resize((target_width, target_height), PILImage.LANCZOS)
            img.save(save_path, format="JPEG", quality=95)
            return save_path
        except Exception as e:
            last_error = e
            print(f"  图片下载失败，第 {attempt}/{max_retries} 次重试：{url[:80]}... 错误：{e}")
            time.sleep(2 * attempt)
    raise last_error


def get_or_download_image(asin, url, image_dir, target_height=75):
    image_dir = Path(image_dir)
    image_dir.mkdir(parents=True, exist_ok=True)
    img_path = image_dir / f"{clean_filename(asin)}.jpg"
    if img_path.exists() and img_path.stat().st_size > 0:
        return img_path
    if not url or not url.startswith("http"):
        return None
    download_and_resize_image(url, img_path, target_height=target_height)
    time.sleep(0.2)
    return img_path


def delete_used_images(image_paths):
    deleted = 0
    for p in image_paths:
        try:
            p = Path(p)
            if p.exists() and p.is_file():
                p.unlink()
                deleted += 1
        except Exception as e:
            print(f"  删除图片失败：{p}，错误：{e}")
    if deleted:
        print(f"已删除临时图片：{deleted} 张")


# ============================================================
# 核心：品牌×分类 矩阵构建
# ============================================================

def build_category_brand_matrix(
    df, category_col, brand_col, asin_col, image_col,
    attr_cols, sort_col, sort_ascending,
    category_values, brands,
    parent_asin_col="", sales_col="", variant_cols=None, launch_date_col="",
):
    """按 分类×品牌 交叉分组，返回嵌套矩阵数据。

    当指定 parent_asin_col 时，同一父ASIN的子体合并为一个条目，
    取销量最高的子体为代表，并汇总变体描述。
    """
    variant_cols = variant_cols or []

    # 验证必需列
    required = [category_col, brand_col, asin_col, image_col]
    for col in required:
        if col not in df.columns:
            print(f"错误: 列「{col}」不在数据中。可用列: {', '.join(df.columns)}")
            sys.exit(1)
    for col in attr_cols:
        if col not in df.columns:
            print(f"错误: 属性列「{col}」不在数据中。可用列: {', '.join(df.columns)}")
            sys.exit(1)

    # 变体合并相关列验证
    do_merge = bool(parent_asin_col)
    if do_merge:
        if parent_asin_col not in df.columns:
            print(f"错误: 父ASIN列「{parent_asin_col}」不在数据中。可用列: {', '.join(df.columns)}")
            sys.exit(1)
        if not sales_col:
            print("错误: 启用变体合并时必须指定 --sales-col")
            sys.exit(1)
        if sales_col not in df.columns:
            print(f"错误: 销量列「{sales_col}」不在数据中。可用列: {', '.join(df.columns)}")
            sys.exit(1)
        for col in variant_cols:
            if col not in df.columns:
                print(f"错误: 变体列「{col}」不在数据中。可用列: {', '.join(df.columns)}")
                sys.exit(1)
        if launch_date_col and launch_date_col not in df.columns:
            print(f"错误: 上架时间列「{launch_date_col}」不在数据中。可用列: {', '.join(df.columns)}")
            sys.exit(1)

    # 清理关键列
    df = df.copy()
    for col in [category_col, brand_col, asin_col, image_col]:
        df[col] = df[col].apply(safe_str)
    df = df[(df[category_col] != "") & (df[brand_col] != "") & (df[asin_col] != "")]

    # 筛选品牌
    brand_set = set(brands)
    df = df[df[brand_col].isin(brand_set)]
    if df.empty:
        print("错误: 筛选后无数据，请检查 --brands 参数")
        sys.exit(1)

    # 确定分类顺序
    if category_values:
        cat_order = category_values
    else:
        cat_order = sorted(df[category_col].unique().tolist())

    # 确定排序列
    sort_key = sort_col if sort_col else asin_col
    if sort_key not in df.columns and sort_col:
        print(f"提示: 排序列「{sort_key}」不存在，将按 ASIN 排序")
        sort_key = asin_col

    if do_merge:
        print(f"  变体合并: 按「{parent_asin_col}」分组，取「{sales_col}」最高者为代表")

    # 构建矩阵
    matrix = {}
    found_brands = set()

    for cat in cat_order:
        cat_df = df[df[category_col] == cat]
        if cat_df.empty:
            continue

        cat_data = {"max_count": 0, "brands": {}}
        brand_counts = []

        for brand in brands:
            bdf = cat_df[cat_df[brand_col] == brand].copy()
            if bdf.empty:
                cat_data["brands"][brand] = []
                continue

            found_brands.add(brand)

            if do_merge:
                products = _merge_variants(
                    bdf, parent_asin_col, sales_col, asin_col, image_col,
                    attr_cols, variant_cols, launch_date_col,
                    sort_key, sort_ascending
                )
            else:
                products = _build_products_simple(
                    bdf, asin_col, image_col, attr_cols,
                    sort_key, sort_ascending
                )

            cat_data["brands"][brand] = products
            brand_counts.append(len(products))

        cat_data["max_count"] = max(brand_counts) if brand_counts else 0
        matrix[cat] = cat_data

    # 移除 max_count=0 的分类
    matrix = {k: v for k, v in matrix.items() if v["max_count"] > 0}

    # 品牌统计
    missing = brand_set - found_brands
    if missing:
        print(f"  警告: 以下品牌在所有分类中均未找到: {', '.join(missing)}")

    active_brands = [b for b in brands if b in found_brands]
    if not active_brands:
        print("错误: 所有指定品牌在数据中均未找到")
        sys.exit(1)

    return matrix, cat_order, active_brands


def _build_products_simple(bdf, asin_col, image_col, attr_cols, sort_key, sort_ascending):
    """简单模式：每行一个产品，不做变体合并。"""
    if sort_key and sort_key in bdf.columns:
        bdf["_sort"] = pd.to_datetime(bdf[sort_key], errors="coerce")
        bdf = bdf.sort_values(by="_sort", ascending=sort_ascending, na_position="last")
    else:
        bdf = bdf.sort_values(by=asin_col, ascending=True)

    products = []
    for _, row in bdf.iterrows():
        attrs = {}
        for ac in attr_cols:
            attrs[ac] = safe_str(row.get(ac, ""))
        products.append({
            "asin": safe_str(row[asin_col]),
            "image_url": safe_str(row[image_col]),
            "attrs": attrs,
            "summary": "",
        })
    return products


def _merge_variants(bdf, parent_asin_col, sales_col, asin_col, image_col,
                    attr_cols, variant_cols, launch_date_col,
                    sort_key, sort_ascending):
    """变体合并模式：同一父ASIN下取销量最高子体为代表，汇总变体信息。"""
    bdf["_sales_num"] = pd.to_numeric(bdf[sales_col], errors="coerce").fillna(0)

    # 按父ASIN分组
    groups = {}
    for _, row in bdf.iterrows():
        parent = safe_str(row.get(parent_asin_col, ""))
        if not parent:
            parent = safe_str(row[asin_col])
        if parent not in groups:
            groups[parent] = []
        groups[parent].append(row)

    products = []
    for parent, rows in groups.items():
        best = max(rows, key=lambda r: r["_sales_num"])

        # 常规属性
        attrs = {}
        for ac in attr_cols:
            attrs[ac] = safe_str(best.get(ac, ""))

        # 汇总变体描述
        summary_parts = []
        for vc in variant_cols:
            vals = set()
            for r in rows:
                v = safe_str(r.get(vc, ""))
                if v:
                    vals.add(v)
            if vals:
                sorted_vals = sorted(vals)
                summary_parts.append(f"{'/'.join(sorted_vals)}{vc}变体")

        # 汇总上架年份
        if launch_date_col:
            years = set()
            for r in rows:
                dt = pd.to_datetime(r.get(launch_date_col), errors="coerce")
                if pd.notna(dt):
                    years.add(str(dt.year))
            if years:
                sorted_years = sorted(years)
                summary_parts.append(f"上架时间:{'/'.join(sorted_years)}")

        summary = "\n".join(summary_parts) if summary_parts else ""

        products.append({
            "asin": safe_str(best[asin_col]),
            "image_url": safe_str(best[image_col]),
            "attrs": attrs,
            "summary": summary,
        })

    # 排序
    if sort_key and sort_key in bdf.columns:
        def _get_sort_val(p):
            for parent, rows in groups.items():
                for r in rows:
                    if safe_str(r[asin_col]) == p["asin"]:
                        return pd.to_datetime(r.get(sort_key), errors="coerce") or pd.NaT
            return pd.NaT
        products.sort(key=_get_sort_val, reverse=not sort_ascending)
        # NaT 排最后
        nat_first = not sort_ascending
        products.sort(key=lambda p: pd.isna(_get_sort_val(p)), reverse=nat_first)

    return products


# ============================================================
# Excel 生成（raw openpyxl）
# ============================================================

# 样式常量
HEADER_FILL = PatternFill("solid", fgColor="D9EAF7")
SECTION_FILL = PatternFill("solid", fgColor="E8ECF0")
EMPTY_FILL = PatternFill("solid", fgColor="F5F5F5")
HEADER_FONT = Font(bold=True, size=11)
SECTION_FONT = Font(bold=True, size=11)
ASIN_FONT = Font(size=9)
ATTR_FONT = Font(size=8, color="666666")
POS_FONT = Font(size=8, color="999999")
THIN = Side(style="thin", color="DDDDDD")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER_BOTTOM = Alignment(horizontal="center", vertical="bottom", wrap_text=True)
CENTER_MIDDLE = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT_MIDDLE = Alignment(horizontal="left", vertical="center", wrap_text=True)


def create_workbook(
    matrix, cat_order, brands, image_dir, image_height,
    category_col, asin_col, attr_cols,
):
    """生成带图片嵌入的 Excel 工作簿。

    布局:
      Row 1: 表头 — A列=分类列名, B列起=品牌名(N款)
      每个分类节:
        - 节标题行（合并，深灰底色）
        - max_count 行产品行，每行高 = image_height + 70px
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "产品矩阵"

    n_brands = len(brands)
    used_images = []
    failed_records = []

    # ---- 表头行 ----
    ws.row_dimensions[1].height = 36

    # A1: 分类列名
    c = ws.cell(row=1, column=1)
    c.value = category_col
    c.fill = HEADER_FILL
    c.font = HEADER_FONT
    c.alignment = CENTER_MIDDLE
    c.border = BORDER
    ws.column_dimensions[get_column_letter(1)].width = 15

    # B1+: 品牌名 (N款)
    for bi, brand in enumerate(brands):
        col = bi + 2
        # 统计该品牌的总产品数
        total = 0
        for cat in cat_order:
            if cat in matrix and brand in matrix[cat]["brands"]:
                total += len(matrix[cat]["brands"][brand])
        c = ws.cell(row=1, column=col)
        c.value = f"{brand}\n共{total}款"
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = CENTER_MIDDLE
        c.border = BORDER
        ws.column_dimensions[get_column_letter(col)].width = 20

    # ---- 分类节 ----
    current_row = 2
    product_row_height = image_height + 70

    for cat in cat_order:
        if cat not in matrix:
            continue

        cat_data = matrix[cat]
        max_count = cat_data["max_count"]
        last_col = n_brands + 1  # 最后一列的编号

        # -- 节标题行 --
        ws.row_dimensions[current_row].height = 24
        ws.merge_cells(start_row=current_row, start_column=1,
                       end_row=current_row, end_column=last_col)
        c = ws.cell(row=current_row, column=1)
        c.value = cat
        c.fill = SECTION_FILL
        c.font = SECTION_FONT
        c.alignment = LEFT_MIDDLE
        c.border = BORDER
        # 给合并区域所有单元格加边框和底色
        for col in range(2, last_col + 1):
            cc = ws.cell(row=current_row, column=col)
            cc.fill = SECTION_FILL
            cc.border = BORDER
        current_row += 1

        # -- 产品行 --
        for pos in range(max_count):
            ws.row_dimensions[current_row].height = product_row_height

            # A列：序号
            c = ws.cell(row=current_row, column=1)
            c.value = f"#{pos + 1}"
            c.font = POS_FONT
            c.alignment = CENTER_MIDDLE
            c.border = BORDER

            # 各品牌列
            for bi, brand in enumerate(brands):
                col = bi + 2
                col_letter = get_column_letter(col)
                products = cat_data["brands"].get(brand, [])

                if pos < len(products):
                    # 有产品
                    prod = products[pos]
                    asin = prod["asin"]
                    img_url = prod["image_url"]
                    attrs = prod["attrs"]

                    cell = ws.cell(row=current_row, column=col)
                    cell.border = BORDER
                    cell.alignment = CENTER_BOTTOM

                    # 构建文本：ASIN + 属性 + 变体汇总
                    lines = [asin]
                    for attr_name, attr_val in attrs.items():
                        if attr_val:
                            lines.append(f"{attr_name}: {attr_val}")
                        else:
                            lines.append(f"{attr_name}: -")
                    summary = prod.get("summary", "")
                    if summary:
                        lines.append(summary)
                    cell.value = "\n".join(lines)

                    # 图片下载 & 嵌入
                    try:
                        img_path = get_or_download_image(
                            asin, img_url, image_dir, target_height=image_height
                        )
                        if img_path and img_path.exists():
                            xl_img = XLImage(str(img_path))
                            ws.add_image(xl_img, f"{col_letter}{current_row}")
                            used_images.append(img_path)
                        else:
                            # 无图：在文本前加标记
                            cell.value = "[无图]\n" + (cell.value or "")
                    except Exception as e:
                        print(f"  图片下载失败: {asin} — {e}")
                        cell.value = "[下载失败]\n" + (cell.value or "")
                        failed_records.append({
                            "ASIN": asin, "品牌": brand, "分类": cat,
                            "图片链接": img_url, "错误": str(e),
                        })
                else:
                    # 空位
                    cc = ws.cell(row=current_row, column=col)
                    cc.fill = EMPTY_FILL
                    cc.border = BORDER

            current_row += 1

    # ---- 冻结窗格 ----
    ws.freeze_panes = "B2"

    # ---- 失败记录 Sheet ----
    if failed_records:
        fail_ws = wb.create_sheet("图片下载失败记录")
        headers = ["ASIN", "品牌", "分类", "图片链接", "错误"]
        for ci, h in enumerate(headers, start=1):
            fail_ws.cell(row=1, column=ci).value = h
            fail_ws.cell(row=1, column=ci).font = Font(bold=True)
        for ri, rec in enumerate(failed_records, start=2):
            for ci, h in enumerate(headers, start=1):
                fail_ws.cell(row=ri, column=ci).value = rec.get(h, "")

    return wb, used_images


# ============================================================
# 主入口
# ============================================================

def main():
    args = parse_args()

    # 图片缓存目录
    image_dir = args.image_dir or os.path.join(
        os.environ.get("TEMP", os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp")),
        "matrix3_images"
    )

    # 解析逗号分隔参数
    brands = [b.strip() for b in args.brands.split(",") if b.strip()]
    if not brands:
        print("错误: --brands 不能为空")
        sys.exit(1)

    category_values = None
    if args.category_values:
        category_values = [v.strip() for v in args.category_values.split(",") if v.strip()]

    attr_cols = [a.strip() for a in args.attrs.split(",") if a.strip()]

    print("=" * 60)
    print("  产品矩阵3 — 品牌×分类 图片矩阵")
    print("=" * 60)
    print(f"  文件:       {args.file}")
    print(f"  Sheet:      {args.sheet}")
    print(f"  分类列:     {args.category_col}")
    print(f"  品牌列:     {args.brand_col}")
    print(f"  目标品牌:   {', '.join(brands)}")
    print(f"  属性列:     {attr_cols if attr_cols else '(无)'}")
    if args.filter:
        print(f"  筛选条件:   {' & '.join(args.filter)}")
    if category_values:
        print(f"  分类值:     {', '.join(category_values)}")
    print(f"  图片高度:   {args.image_height}px")

    # 1. 加载 & 筛选
    df = load_data(args.file, args.sheet)
    df = filter_data(df, args.filter)

    if df.empty:
        print("\n筛选后没有可处理的数据。")
        sys.exit(1)

    print(f"\n  有效数据: {len(df)} 条")

    # 2. 构建矩阵
    matrix, cat_order, active_brands = build_category_brand_matrix(
        df,
        args.category_col, args.brand_col,
        args.asin_col, args.image_col,
        attr_cols,
        args.sort_col, args.sort_ascending,
        category_values, brands,
        args.parent_asin_col, args.sales_col,
        [v.strip() for v in args.variant_cols.split(",") if v.strip()],
        args.launch_date_col,
    )

    actual_cats = [c for c in cat_order if c in matrix]
    print(f"\n  分类数: {len(actual_cats)}")
    print(f"  品牌数: {len(active_brands)}")
    for cat in actual_cats:
        mc = matrix[cat]["max_count"]
        print(f"    {cat}: {mc} 行")
        for brand in active_brands:
            prods = matrix[cat]["brands"].get(brand, [])
            if prods:
                print(f"      {brand}: {len(prods)} 款")

    # 3. 生成 Excel
    print(f"\n生成 Excel...")
    wb, used_images = create_workbook(
        matrix, cat_order, active_brands,
        image_dir, args.image_height,
        args.category_col, args.asin_col, attr_cols,
    )

    # 4. 保存
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    print(f"  已保存: {output_path}")

    # 5. 清理图片缓存
    if not args.keep_cache and used_images:
        delete_used_images(used_images)

    print(f"\n{'=' * 60}")
    print("  完成")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
