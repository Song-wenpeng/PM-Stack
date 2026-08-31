# -*- coding: utf-8 -*-
"""
品牌份额趋势图（百分比堆叠面积图） — 按品牌统计月度销量/销额占比趋势

用法:
    python brand_share_trend.py --file data.xlsx --meta-sheet 元数据 --data-sheet 子体销量 --brand-col 品牌

    # 只看前 N 个品牌，其余归入"其他"
    python brand_share_trend.py --file data.xlsx --meta-sheet 元数据 --data-sheet 子体销量 --brand-col 品牌 --top 8

    # 指定输出路径和 DPI
    python brand_share_trend.py --file data.xlsx --meta-sheet 元数据 --data-sheet 子体销量 --brand-col 品牌 --output brand_share.png --dpi 200

    # 筛选条件（只看某个子集）
    python brand_share_trend.py --file data.xlsx --meta-sheet 元数据 --data-sheet 子体销量 --brand-col 品牌 --filter "使用场景=旅行"

    # 输出占比数据表
    python brand_share_trend.py --file data.xlsx --meta-sheet 元数据 --data-sheet 子体销量 --brand-col 品牌 --export-share
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

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker


def parse_args():
    parser = argparse.ArgumentParser(description='品牌份额趋势图')
    parser.add_argument('--file', required=True, help='Excel 文件路径')
    parser.add_argument('--meta-sheet', required=True, help='元数据 Sheet 名')
    parser.add_argument('--data-sheet', required=True, help='数据 Sheet 名（行=ASIN，列=月份）')
    parser.add_argument('--brand-col', required=True, help='品牌列名（元数据中的列）')
    parser.add_argument('--top', type=int, default=8, help='展示前 N 个品牌，其余归入"其他"（默认 8）')
    parser.add_argument('--filter', action='append', default=[], help='筛选条件，格式: 列名=值，可多次指定')
    parser.add_argument('--output', default='', help='输出图片路径（默认: brand_share_{brand_col}.png）')
    parser.add_argument('--dpi', type=int, default=200, help='图表 DPI（默认 200）')
    parser.add_argument('--show', action='store_true', help='显示图表窗口')
    parser.add_argument('--export-share', action='store_true', help='输出各品牌占比数据表（Excel格式）')
    return parser.parse_args()


def setup_font():
    import matplotlib.font_manager as fm
    for fpath in ['C:\\Windows\\Fonts\\msyh.ttc', 'C:\\Windows\\Fonts\\simhei.ttf']:
        if os.path.exists(fpath):
            try:
                fm.fontManager.addfont(fpath)
                bold = 'C:\\Windows\\Fonts\\msyhbd.ttc'
                if 'msyh' in fpath and os.path.exists(bold):
                    fm.fontManager.addfont(bold)
                prop = fm.FontProperties(fname=fpath)
                return fpath, prop.get_name()
            except Exception:
                pass
    return None, None


def main():
    args = parse_args()

    if not os.path.isfile(args.file):
        print(f"错误: 文件不存在: {args.file}")
        sys.exit(1)

    xls = pd.ExcelFile(args.file)

    # ---- 读取数据 ----
    if args.data_sheet not in xls.sheet_names:
        print(f"错误: 数据 Sheet「{args.data_sheet}」不存在。可用: {', '.join(xls.sheet_names)}")
        sys.exit(1)

    df_data = pd.read_excel(xls, sheet_name=args.data_sheet)
    if 'ASIN' not in df_data.columns:
        print(f"错误: 数据 Sheet 中无 ASIN 列。可用: {', '.join(df_data.columns)}")
        sys.exit(1)

    df_data['ASIN'] = df_data['ASIN'].astype(str).str.strip()
    df_data = df_data.set_index('ASIN')
    df_data = df_data.drop(columns=['分组'], errors='ignore')
    for col in df_data.columns:
        df_data[col] = pd.to_numeric(df_data[col], errors='coerce')

    # ---- 读取元数据 ----
    if not args.meta_sheet:
        args.meta_sheet = xls.sheet_names[0]
        print(f"  元数据 Sheet 未指定，默认使用第一个 Sheet: {args.meta_sheet}")
    if args.meta_sheet not in xls.sheet_names:
        print(f"错误: 元数据 Sheet「{args.meta_sheet}」不存在。可用: {', '.join(xls.sheet_names)}")
        sys.exit(1)

    meta_df = pd.read_excel(xls, sheet_name=args.meta_sheet)
    meta_df.columns = meta_df.columns.astype(str).str.strip()
    if 'ASIN' not in meta_df.columns:
        print(f"错误: 元数据 Sheet 中无 ASIN 列。可用: {', '.join(meta_df.columns)}")
        sys.exit(1)
    meta_df['ASIN'] = meta_df['ASIN'].astype(str).str.strip()

    if args.brand_col not in meta_df.columns:
        print(f"错误: 元数据中无「{args.brand_col}」列。可用: {', '.join(meta_df.columns)}")
        sys.exit(1)

    # ---- 筛选 ----
    for expr in args.filter:
        if '=' not in expr:
            print(f"错误: --filter 格式应为 列名=值，收到: {expr}")
            sys.exit(1)
        col, val = expr.split('=', 1)
        col, val = col.strip(), val.strip()
        if col not in meta_df.columns:
            print(f"错误: 筛选列「{col}」不在元数据中。可用: {', '.join(meta_df.columns)}")
            sys.exit(1)
        before = len(meta_df)
        # 支持多值：列名=值1,值2,值3（英文逗号分隔）
        vals = [v.strip() for v in val.split(',') if v.strip()]
        meta_df = meta_df[meta_df[col].astype(str).str.strip().isin(vals)]
        print(f"  筛选: {col}={val}  ({before} → {len(meta_df)} 条)")

    # ---- 构建 ASIN → 品牌映射 ----
    asin_brand = dict(zip(meta_df['ASIN'], meta_df[args.brand_col].astype(str).str.strip()))
    valid_asins = [a for a in df_data.index if a in asin_brand and asin_brand[a] and asin_brand[a].lower() != 'nan']
    df_data = df_data.loc[valid_asins]

    # ---- 按品牌分组汇总 ----
    brands = {}
    for asin in df_data.index:
        brand = asin_brand[asin]
        brands.setdefault(brand, []).append(asin)

    # ---- 计算月度份额（先计算，再排序） ----
    dates = [str(c) for c in df_data.columns]

    # 每月总销量
    total_monthly = df_data.sum()

    # 每个品牌的月度销量和末期份额
    brand_monthly = {}
    brand_last_share = {}
    for brand, asins in brands.items():
        monthly = df_data.loc[asins].sum()
        brand_monthly[brand] = monthly
        # 计算末期份额
        last_month_total = total_monthly.iloc[-1]
        if last_month_total > 0:
            brand_last_share[brand] = monthly.iloc[-1] / last_month_total * 100
        else:
            brand_last_share[brand] = 0

    # 按末期份额排序（从大到小）
    sorted_brands = sorted(brand_last_share.keys(), key=lambda x: brand_last_share[x], reverse=True)
    top_brands = sorted_brands[:args.top]
    other_brands = sorted_brands[args.top:]

    print(f"\n  总 ASIN: {len(valid_asins)}")
    print(f"  品牌总数: {len(brands)}")
    print(f"  展示前 {args.top} 品牌 + 其他")
    print(f"  Top 品牌: {top_brands}")
    if other_brands:
        other_asins_count = sum(len(brands[b]) for b in other_brands)
        print(f"  其他品牌 ({len(other_brands)} 个, {other_asins_count} 个ASIN): {other_brands[:5]}{'...' if len(other_brands) > 5 else ''}")

    # 合并其他品牌
    if other_brands:
        other_asins = []
        for b in other_brands:
            other_asins.extend(brands[b])
        brand_monthly['其他'] = df_data.loc[other_asins].sum()

    # 计算占比（只保留 top N 品牌和其他）
    brand_share = {}
    # 先计算 top N 品牌
    for brand in top_brands:
        monthly = brand_monthly[brand]
        share = (monthly / total_monthly.replace(0, float('nan'))) * 100
        brand_share[brand] = share
    # 再计算其他
    if other_brands:
        monthly = brand_monthly['其他']
        share = (monthly / total_monthly.replace(0, float('nan'))) * 100
        brand_share['其他'] = share

    # ---- 按末期份额排序（从大到小） ----
    # 获取末期（最后一个月）的份额
    last_month = list(brand_share.keys())[0]  # 只是为了获取列名
    last_shares = {}
    for brand, share in brand_share.items():
        # 获取最后一个非空值
        valid_values = share.dropna()
        if len(valid_values) > 0:
            last_shares[brand] = valid_values.iloc[-1]
        else:
            last_shares[brand] = 0

    # 按末期份额排序（从大到小），"其他"固定在最后
    sorted_brands = sorted(last_shares.keys(), key=lambda x: last_shares[x] if x != '其他' else -1, reverse=True)
    if '其他' in sorted_brands:
        sorted_brands.remove('其他')
        sorted_brands.append('其他')

    # 重新排序 brand_share
    brand_share_sorted = {brand: brand_share[brand] for brand in sorted_brands}

    # ---- 绘图（百分比堆叠面积图） ----
    import matplotlib.font_manager as fm
    font_path, font_name = setup_font()
    font_kw = {'fontname': font_name} if font_name else {}
    font_prop = fm.FontProperties(fname=font_path) if font_path else None

    n_brands = len(brand_share_sorted)

    # 对比色配色
    COLORS = ['#2563EB', '#DC2626', '#059669', '#7C3AED', '#D97706',
              '#DB2777', '#0891B2', '#E11D48', '#16A34A', '#8B5CF6']

    fig, ax = plt.subplots(figsize=(max(16, len(dates) * 0.4), 8))
    ax.set_facecolor('#FAFBFC')

    x = np.arange(len(dates))

    # 准备堆叠数据（确保每列总和为100%）
    share_arrays = [brand_share_sorted[brand].values for brand in sorted_brands]

    # 计算每月总份额（用于归一化）
    total_per_month = np.zeros(len(dates))
    for arr in share_arrays:
        # 将NaN替换为0进行计算
        total_per_month += np.nan_to_num(arr, nan=0)

    # 归一化：确保每列总和为100%
    normalized_arrays = []
    for arr in share_arrays:
        # 将NaN替换为0
        arr_clean = np.nan_to_num(arr, nan=0)
        # 归一化
        normalized = np.where(total_per_month > 0, arr_clean / total_per_month * 100, 0)
        normalized_arrays.append(normalized)

    # 绘制堆叠面积图（反转顺序，使最大的在上方）
    # stackplot 默认从下往上堆叠，所以需要将最大的放在列表末尾
    reversed_brands = list(reversed(sorted_brands))
    reversed_arrays = list(reversed(normalized_arrays))
    reversed_colors = [COLORS[(n_brands - 1 - i) % len(COLORS)] for i in range(n_brands)]

    ax.stackplot(x, *reversed_arrays,
                 colors=reversed_colors,
                 alpha=0.85, edgecolor='white', linewidth=0.5)

    # ---- 末期标注 ----
    # 计算每个分层的末期中心位置（用于标注）
    cumulative = np.zeros(len(dates))
    for i, brand in enumerate(reversed_brands):
        share = reversed_arrays[i]
        # 末期值
        last_share = share[-1]
        if last_share > 0:
            center_y = cumulative[-1] + last_share / 2
            # 标注占比
            cnt = len(other_brands) if brand == '其他' else len(brands[brand])
            label_text = f'{last_share:.1f}%'
            ax.annotate(label_text,
                        xy=(x[-1], center_y),
                        xytext=(10, 0),
                        textcoords='offset points',
                        ha='left', va='center',
                        fontsize=9, fontweight='bold',
                        color='white',
                        bbox=dict(boxstyle='round,pad=0.3',
                                  facecolor=reversed_colors[i],
                                  edgecolor='white', alpha=0.9),
                        **font_kw)
        cumulative += share

    # ---- 坐标轴设置 ----
    ax.set_xticks(x)
    step = max(1, len(dates) // 16)
    labels = [dates[i] if i % step == 0 else '' for i in range(len(dates))]
    ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=9, **font_kw)
    ax.set_xlim(-0.6, len(dates) - 0.4)
    ax.set_ylim(0, 100)

    # Y轴格式化
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'{v:.0f}%'))

    # 网格线
    ax.grid(True, linestyle='-', alpha=0.35, color='#CBD5E1', linewidth=0.5, axis='y')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#CBD5E1')
    ax.spines['bottom'].set_color('#CBD5E1')

    # 标题
    filter_str = ''
    if args.filter:
        filter_str = f" ({' & '.join(args.filter)}) "
    ax.set_title(f'{args.brand_col}份额趋势{filter_str}', fontsize=14,
                 fontweight='bold', pad=18, color='#1E293B', **font_kw)
    ax.set_xlabel('年月', fontsize=12, labelpad=10, color='#64748B', **font_kw)
    ax.set_ylabel('市场份额 (%)', fontsize=12, labelpad=10, color='#64748B', **font_kw)

    # ---- 图例（放在图表外右侧）----
    # 创建图例句柄（使用正确的顺序：从大到小）
    # 堆叠图中：reversed_brands[i] 使用 reversed_colors[i]
    # 图例需要：sorted_brands[i] 对应的颜色
    # 由于 reversed_brands = list(reversed(sorted_brands))
    # 所以 sorted_brands[i] 对应 reversed_brands[n_brands-1-i]
    # 因此颜色应该是 reversed_colors[n_brands-1-i]
    other_asins_count = sum(len(brands[b]) for b in other_brands) if other_brands else 0
    legend_handles = []
    legend_labels = []
    for i, brand in enumerate(sorted_brands):
        cnt = other_asins_count if brand == '其他' else len(brands[brand])
        # 颜色对应：sorted_brands[i] 在堆叠图中的位置是 n_brands-1-i
        color_idx = n_brands - 1 - i
        handle = plt.Rectangle((0, 0), 1, 1,
                               facecolor=reversed_colors[color_idx],
                               edgecolor='white', linewidth=0.5)
        legend_handles.append(handle)
        legend_labels.append(f'{brand} ({cnt}个)')

    leg = ax.legend(legend_handles, legend_labels,
                    loc='upper left',
                    bbox_to_anchor=(1.15, 1.0),
                    frameon=True, fontsize=9,
                    framealpha=0.95, edgecolor='#CBD5E1',
                    borderpad=0.8, handlelength=1.5,
                    ncol=1, title=args.brand_col,
                    title_fontsize=10)
    # 修复图例乱码问题
    if font_prop:
        for txt in leg.get_texts():
            txt.set_fontproperties(font_prop)
        leg.get_title().set_fontproperties(font_prop)

    plt.tight_layout(pad=1.5)

    if not args.output:
        args.output = f"brand_share_{args.brand_col}.png"

    plt.savefig(args.output, dpi=args.dpi, bbox_inches='tight', facecolor='white', edgecolor='none')
    print(f"\n  图表已保存: {args.output}")

    if args.show:
        plt.switch_backend('TkAgg')
        plt.show()

    plt.close()

    # ---- 导出占比数据表 ----
    if args.export_share:
        # 构建数据表
        share_df_data = {'月份': dates}
        for i, brand in enumerate(sorted_brands):
            share_df_data[brand] = normalized_arrays[i].round(2)

        share_df = pd.DataFrame(share_df_data)

        # 计算输出路径
        base, _ = os.path.splitext(args.output)
        share_output = f"{base}_share_data.xlsx"

        # 导出 Excel
        with pd.ExcelWriter(share_output, engine='openpyxl') as writer:
            share_df.to_excel(writer, sheet_name='占比数据', index=False)

            # 添加图表信息 sheet
            info_df = pd.DataFrame({
                '参数': ['分组列', '展示数量', '筛选条件'],
                '值': [args.brand_col, args.top,
                       ' & '.join(args.filter) if args.filter else '无']
            })
            info_df.to_excel(writer, sheet_name='参数信息', index=False)

        print(f"  占比数据表已保存: {share_output}")


if __name__ == '__main__':
    main()
