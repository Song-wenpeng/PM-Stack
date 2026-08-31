# -*- coding: utf-8 -*-
"""
单文件多 Sheet 趋势图 — 按属性字段分组，画历史数据聚合趋势

从一个 Excel 文件中同时读取元数据 Sheet 和历史数据 Sheet，
按指定属性列（颜色、品牌、类型等）分组聚合后绘制趋势线图。

用法:
    # 不分组，看所有ASIN的总量趋势（只需两个参数）
    python trend_by_attribute.py --file data.xlsx --data-sheet "历史数据"

    # 按颜色分组，画总量趋势
    python trend_by_attribute.py --file data.xlsx \\
        --meta-sheet "竞品表" --data-sheet "历史数据" \\
        --group-col 颜色 --aggregate sum

    # 按品牌分组，画均值趋势
    python trend_by_attribute.py --file data.xlsx \\
        --meta-sheet "竞品表" --data-sheet "历史数据" \\
        --group-col 品牌 --aggregate mean

    # 带筛选条件（只看 Tower 类型）
    python trend_by_attribute.py --file data.xlsx \\
        --meta-sheet "竞品表" --data-sheet "历史数据" \\
        --group-col 颜色 --filter "排插类型=Tower"

    # 调整小组合并阈值和输出
    python trend_by_attribute.py --file data.xlsx \\
        --meta-sheet "竞品表" --data-sheet "历史数据" \\
        --group-col 颜色 --merge-threshold 5 --output result.png --dpi 300
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


# ============================================================
# 参数解析
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description='单文件多 Sheet 趋势图 — 按属性分组画历史数据聚合趋势'
    )
    parser.add_argument('--file', required=True,
                        help='Excel 文件路径')
    parser.add_argument('--meta-sheet', default='',
                        help='元数据 Sheet 名（含 ASIN 和分组字段，不分组时可省略）')
    parser.add_argument('--data-sheet', required=True,
                        help='历史数据 Sheet 名（行=ASIN，列=月份）')
    parser.add_argument('--data-sheet-2', default='',
                        help='第二个数据 Sheet 名（启用双轴模式，左轴=第一Sheet，右轴=第二Sheet）')
    parser.add_argument('--group-col', default='',
                        help='用于分组的列名（如 颜色、品牌、排插类型，省略则不分组）')
    parser.add_argument('--aggregate', default='sum', choices=['sum', 'mean'],
                        help='聚合方式: sum=总量, mean=均值 (默认: sum)')
    parser.add_argument('--filter', action='append', default=[],
                        help='筛选条件，格式: 列名=值 (如 --filter 排插类型=Tower --filter 颜色=黑色)，可多次指定')
    parser.add_argument('--values', default='',
                        help='只展示分组列的指定值，逗号分隔 (如 "900J,1080J,2100J")')
    parser.add_argument('--chart-type', default='auto', choices=['auto', 'line', 'area'],
                        help='图表类型: auto=自动选择, line=折线图, area=百分比堆叠面积图 (默认: auto)')
    parser.add_argument('--top-n', type=int, default=6,
                        help='分组模式下展示前N个分组，其余归入"其他" (默认: 6)')
    parser.add_argument('--export-share', action='store_true',
                        help='分组模式下输出各品牌占比数据表（Excel格式）')
    parser.add_argument('--export-data', default='',
                        help='导出ASIN×月份详细数据文件路径 (如 export_data.xlsx)')
    parser.add_argument('--export-only', action='store_true',
                        help='只导出数据，不生成图片')
    parser.add_argument('--avg-price', action='store_true',
                        help='双轴模式下叠加月均价趋势线（销额/销量，保留两位小数）')
    parser.add_argument('--avg-price-only', action='store_true',
                        help='双轴模式下只显示销量+均价，不显示销额趋势线')
    parser.add_argument('--merge-threshold', type=int, default=3,
                        help='小组合并阈值，低于此归入"其他" (默认: 3)')
    parser.add_argument('--output', default='',
                        help='输出图片路径 (默认: trend_{group_col}.png)')
    parser.add_argument('--dpi', type=int, default=200,
                        help='图表 DPI (默认: 200)')
    parser.add_argument('--show', action='store_true',
                        help='显示图表窗口')
    return parser.parse_args()


# ============================================================
# 字体 & 样式
# ============================================================

def setup_font():
    """设置中文字体，返回字体名称字符串。

    优先微软雅黑（注册常规+粗体两个字重，标题加粗可真正生效），
    无雅黑时退回黑体（无粗体字重，加粗会回退常规并打印 findfont 警告）。
    """
    import matplotlib.font_manager as fm
    candidates = [
        ('C:\\Windows\\Fonts\\msyh.ttc', 'C:\\Windows\\Fonts\\msyhbd.ttc'),
        ('C:\\Windows\\Fonts\\simhei.ttf', None),
    ]
    for regular, bold in candidates:
        if os.path.exists(regular):
            try:
                fm.fontManager.addfont(regular)
                if bold and os.path.exists(bold):
                    fm.fontManager.addfont(bold)
                prop = fm.FontProperties(fname=regular)
                font_name = prop.get_name()
                plt.rcParams['font.family'] = font_name
                plt.rcParams['axes.unicode_minus'] = False
                return font_name
            except Exception:
                continue
    return None


COLORS = ['#2563EB', '#DC2626', '#059669', '#7C3AED', '#D97706',
          '#DB2777', '#0891B2', '#E11D48', '#16A34A', '#8B5CF6']

TITLE_FONTSIZE = 17
AXIS_LABEL_FONTSIZE = 11
TICK_FONTSIZE = 8.5
LEGEND_FONTSIZE = 10
END_LABEL_FONTSIZE = 8


def fmt_y(v, _):
    if abs(v) >= 1e6:
        return f'{v/1e6:.1f}M'
    elif abs(v) >= 1e4:
        return f'{v:,.0f}'
    else:
        return f'{v:,.1f}' if abs(v) < 10 else f'{v:,.0f}'


# ============================================================
# 数据读取
# ============================================================

def load_data(file_path, meta_sheet, data_sheet, group_col, filter_exprs):
    """读取元数据和历史数据，返回分组结果。

    Returns:
        groups: {group_name: [asin, ...]}
        df_data: 宽格式 DataFrame (index=ASIN, columns=月份, values=float)
        meta_df: 元数据 DataFrame（不分组时为 None）
    """
    if not os.path.isfile(file_path):
        if os.path.isdir(file_path):
            print(f"错误: 输入的是文件夹，需要选择具体的 Excel 文件。路径: {file_path}")
        else:
            print(f"错误: 文件不存在。路径: {file_path}")
        sys.exit(1)
    xls = pd.ExcelFile(file_path)

    # ---- 历史数据 ----
    if data_sheet not in xls.sheet_names:
        print(f"错误: 历史数据 Sheet「{data_sheet}」不存在。可用: {', '.join(xls.sheet_names)}")
        sys.exit(1)
    df_data = pd.read_excel(xls, sheet_name=data_sheet)

    if 'ASIN' not in df_data.columns:
        print(f"错误: 历史数据 Sheet 中无 ASIN 列。可用列: {', '.join(df_data.columns)}")
        sys.exit(1)

    df_data['ASIN'] = df_data['ASIN'].astype(str).str.strip()
    df_data = df_data.set_index('ASIN')
    df_data = df_data.drop(columns=['分组'], errors='ignore')

    # 数值化
    for col in df_data.columns:
        df_data[col] = pd.to_numeric(df_data[col], errors='coerce')

    # ---- 不分组模式（无筛选条件时直接返回全部） ----
    if not group_col and not filter_exprs:
        groups = {'全部ASIN': list(df_data.index)}
        xls.close()
        return groups, df_data, None

    # ---- 需要读取元数据（有筛选条件或有分组字段） ----
    if not meta_sheet:
        meta_sheet = xls.sheet_names[0]
        print(f"  元数据 Sheet 未指定，默认使用第一个 Sheet: {meta_sheet}")
    if meta_sheet not in xls.sheet_names:
        print(f"错误: 元数据 Sheet「{meta_sheet}」不存在。可用: {', '.join(xls.sheet_names)}")
        sys.exit(1)
    meta_df = pd.read_excel(xls, sheet_name=meta_sheet)

    if 'ASIN' not in meta_df.columns:
        print(f"错误: 元数据 Sheet 中无 ASIN 列。可用列: {', '.join(meta_df.columns)}")
        sys.exit(1)

    meta_df['ASIN'] = meta_df['ASIN'].astype(str).str.strip()

    # 筛选（支持多条件）
    for filter_expr in filter_exprs:
        if '=' not in filter_expr:
            print(f"错误: --filter 格式应为 列名=值，收到: {filter_expr}")
            sys.exit(1)
        fcol, fval = filter_expr.split('=', 1)
        fcol, fval = fcol.strip(), fval.strip()
        if fcol not in meta_df.columns:
            print(f"错误: 筛选列「{fcol}」不在元数据中。可用列: {', '.join(meta_df.columns)}")
            sys.exit(1)
        before = len(meta_df)
        # 支持多值：列名=值1,值2,值3（英文逗号分隔）
        fvals = [v.strip() for v in fval.split(',') if v.strip()]
        # 先尝试字符串比较
        mask = meta_df[fcol].astype(str).str.strip().isin(fvals)
        # 如果结果为空，尝试数值比较（处理数字列如 Pack数）
        if mask.sum() == 0:
            try:
                fval_nums = [float(v) for v in fvals]
                mask = meta_df[fcol].isin(fval_nums)
            except (ValueError, TypeError):
                pass
        meta_df = meta_df[mask]
        print(f"  筛选: {fcol}={fval}  ({before} → {len(meta_df)} 条)")

    # ---- 不分组但有筛选条件 ----
    if not group_col:
        filtered_asins = [a for a in meta_df['ASIN'].tolist() if a in df_data.index]
        df_data = df_data.loc[filtered_asins]
        groups = {'筛选结果': filtered_asins}
        xls.close()
        print(f"  筛选后 ASIN: {len(filtered_asins)} 个")
        return groups, df_data, None

    # ---- 分组模式 ----
    if group_col not in meta_df.columns:
        print(f"错误: 元数据 Sheet 中无「{group_col}」列。可用列: {', '.join(meta_df.columns)}")
        sys.exit(1)

    # ASIN → 分组映射
    asin_group = {}
    for _, row in meta_df.iterrows():
        asin = row['ASIN']
        grp = str(row[group_col]).strip()
        if grp and grp.lower() != 'nan':
            asin_group[asin] = grp

    # 只保留有分组信息的 ASIN
    valid_asins = [a for a in df_data.index if a in asin_group]
    df_data = df_data.loc[valid_asins]

    # 按属性分组
    groups = {}
    for asin in df_data.index:
        grp = asin_group[asin]
        groups.setdefault(grp, []).append(asin)

    xls.close()
    return groups, df_data, meta_df


# ============================================================
# 图表绘制
# ============================================================

def make_chart(groups, df_data, group_col, aggregate, merge_threshold,
               output_path, dpi, show, font_name, filter_exprs=None, data_label='子体销量'):
    """绘制分组聚合趋势图。"""

    # 按 ASIN 个数排名，取前6，第7名以后归入"其他"
    MAX_DISPLAY = 6

    sorted_by_count = sorted(groups.items(), key=lambda x: -len(x[1]))
    final_groups = {}
    other_asins = []
    for i, (g, asins) in enumerate(sorted_by_count):
        if i < MAX_DISPLAY:
            final_groups[g] = asins
        else:
            other_asins.extend(asins)
    if other_asins:
        final_groups['其他'] = other_asins

    months = list(df_data.columns)
    x = list(range(len(months)))

    # 计算聚合值
    agg_func = np.nansum if aggregate == 'sum' else np.nanmean
    group_series = {}
    for g, asins in final_groups.items():
        vals = agg_func(df_data.loc[asins].values.astype(float), axis=0)
        group_series[g] = vals

    # 按末期值排序（大的在上）
    sorted_groups = sorted(final_groups, key=lambda g: group_series[g][-1], reverse=True)

    # ---- 画图 ----
    fig, ax = plt.subplots(figsize=(max(18, len(months) * 0.5), 8))
    ax.set_facecolor('#FAFBFC')
    ax.grid(True, linestyle='-', alpha=0.35, color='#CBD5E1', linewidth=0.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#CBD5E1')
    ax.spines['bottom'].set_color('#CBD5E1')

    font_kw = {'fontname': font_name} if font_name else {}

    for gi, g in enumerate(sorted_groups):
        color = COLORS[gi % len(COLORS)]
        n = len(final_groups[g])
        vals = group_series[g]
        ax.plot(x, vals, color=color, linewidth=2.8, marker='o', markersize=5,
                markeredgecolor='white', markeredgewidth=1.2, zorder=5,
                label=f'{g} (n={n})')

        # 首尾数值标注
        valid_idx = [i for i in range(len(vals)) if not np.isnan(vals[i])]
        if len(valid_idx) >= 2:
            for idx, ha in [(valid_idx[0], 'right'), (valid_idx[-1], 'left')]:
                val = vals[idx]
                offset = -15 if ha == 'right' else 15
                ann_kw = dict(xy=(idx, val), xytext=(offset, 8),
                              textcoords='offset points', ha=ha,
                              fontsize=END_LABEL_FONTSIZE, color=color,
                              fontweight='bold',
                              bbox=dict(boxstyle='round,pad=0.3',
                                        facecolor='white', edgecolor=color,
                                        alpha=0.85, linewidth=0.8))
                if font_name:
                    ann_kw['fontname'] = font_name
                ax.annotate(f'{val:,.0f}', **ann_kw)

    # X 轴
    ax.set_xticks(x)
    step = max(1, len(months) // 16)
    labels = [months[i] if i % step == 0 else '' for i in range(len(months))]
    ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=TICK_FONTSIZE, **font_kw)
    ax.set_xlim(-0.6, len(months) - 0.4)

    # Y 轴
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_y))

    # 标题
    agg_label = '总量' if aggregate == 'sum' else '均值'
    if group_col:
        title = f'{group_col}分组 — {data_label}{agg_label}趋势'
    else:
        title = f'{data_label}{agg_label}趋势'
    if filter_exprs:
        filter_str = ' & '.join(filter_exprs)
        title = f'{filter_str} — {title}'
    ax.set_title(title, fontsize=TITLE_FONTSIZE, fontweight='bold', pad=18,
                 color='#1E293B', **font_kw)
    ax.set_xlabel('年月', fontsize=AXIS_LABEL_FONTSIZE, labelpad=10,
                  color='#64748B', **font_kw)
    ax.set_ylabel(f'{data_label} ({agg_label})',
                  fontsize=AXIS_LABEL_FONTSIZE, labelpad=10,
                  color='#64748B', **font_kw)

    # 图例
    leg = ax.legend(loc='upper left', frameon=True, fontsize=LEGEND_FONTSIZE,
                    framealpha=0.92, edgecolor='#CBD5E1',
                    borderpad=0.8, handlelength=2.5)
    if font_name:
        for txt in leg.get_texts():
            txt.set_fontproperties(font_name)

    ax.margins(x=0.01)
    y_min, y_max = ax.get_ylim()
    y_pad = (y_max - y_min) * 0.08
    ax.set_ylim(max(0, y_min - y_pad), y_max + y_pad)

    plt.tight_layout(pad=1.5)

    if not output_path:
        output_path = f"trend_{group_col}.png"
    plt.savefig(output_path, dpi=dpi, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    print(f"\n  图表已保存: {output_path}")

    if show:
        plt.switch_backend('TkAgg')
        plt.show()

    plt.close()
    return output_path


# ============================================================
# 双轴图表
# ============================================================

def make_dual_chart(groups, df_data_1, df_data_2, group_col, aggregate,
                    merge_threshold, output_path, dpi, show, font_name,
                    label_1='销量', label_2='销额', filter_exprs=None,
                    show_avg_price=False, avg_price_only=False):
    """双 Y 轴趋势图：左轴=指标1，右轴=指标2。"""

    MAX_DISPLAY = 6

    sorted_by_count = sorted(groups.items(), key=lambda x: -len(x[1]))
    final_groups = {}

    if len(sorted_by_count) <= MAX_DISPLAY:
        final_groups = dict(sorted_by_count)
    else:
        for name, asins in sorted_by_count[:MAX_DISPLAY]:
            final_groups[name] = asins
        other_asins = []
        for name, asins in sorted_by_count[MAX_DISPLAY:]:
            other_asins.extend(asins)
        final_groups['其他'] = other_asins

    n_groups = max(len(final_groups), 2)
    # 销量主指标用更深的蓝色区间，突出主线
    blue_cmap = plt.cm.Blues(np.linspace(0.65, 0.95, n_groups))
    orange_cmap = plt.cm.Oranges(np.linspace(0.35, 0.9, n_groups))
    dates = [str(c) for c in df_data_1.columns]

    setup_font()
    font_kw = {'fontname': font_name} if font_name else {}

    fig, ax1 = plt.subplots(figsize=(14, 7))
    ax2 = ax1.twinx()

    for i, (name, asins) in enumerate(final_groups.items()):
        valid_1 = [a for a in asins if a in df_data_1.index]
        valid_2 = [a for a in asins if a in df_data_2.index]

        if valid_1:
            grp_data_1 = df_data_1.loc[valid_1]
            if aggregate == 'sum':
                agg_1 = grp_data_1.sum()
            else:
                agg_1 = grp_data_1.mean()
            ax1.plot(dates, agg_1.values, color=blue_cmap[i], linewidth=2.6,
                     marker='o', markersize=4, label=f'{name} ({label_1})')

        if valid_2 and not avg_price_only:
            grp_data_2 = df_data_2.loc[valid_2]
            if aggregate == 'sum':
                agg_2 = grp_data_2.sum()
            else:
                agg_2 = grp_data_2.mean()
            ax2.plot(dates, agg_2.values, color=orange_cmap[i], linewidth=2,
                     linestyle='--', marker='s', markersize=3, label=f'{name} ({label_2})')

    # 月均价趋势线
    ax3 = None
    need_avg_price = show_avg_price or avg_price_only
    if need_avg_price:
        # 汇总所有分组的销量和销额，计算月均价
        all_asins_1 = set()
        all_asins_2 = set()
        for asins in groups.values():
            all_asins_1.update(a for a in asins if a in df_data_1.index)
            all_asins_2.update(a for a in asins if a in df_data_2.index)
        common_asins = all_asins_1 & all_asins_2
        if common_asins:
            vol_total = df_data_1.loc[list(common_asins)].sum()
            rev_total = df_data_2.loc[list(common_asins)].sum()
            avg_price = rev_total / vol_total.replace(0, float('nan'))

            if avg_price_only:
                # 均价直接画在 ax2 上，替代销额
                # 均价为辅助参考线：更细、无标记过大，避免抢主线视觉
                line_avg, = ax2.plot(dates, avg_price.values, color='#10B981',
                                     linewidth=1.4, linestyle='-.', marker='D',
                                     markersize=3, label='月均价')
                ax2.set_ylabel('月均价', fontsize=AXIS_LABEL_FONTSIZE, labelpad=10,
                               color='#10B981', **font_kw)
                ax2.tick_params(axis='y', colors='#10B981')
                # 锁定刻度数量，避免 AutoLocator 在小区间上产生不等距刻度
                ax2.yaxis.set_major_locator(mticker.MaxNLocator(nbins=6, integer=False))
                ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:.2f}'))
                for xi, yi in zip(range(len(dates)), avg_price.values):
                    if not pd.isna(yi):
                        ax2.annotate(f'{yi:.2f}', (xi, yi), textcoords='offset points',
                                     xytext=(0, 10), ha='center', fontsize=7, color='#10B981')
            else:
                # 叠加模式：均价画在独立的 ax3 上
                ax3 = ax1.twinx()
                ax3.spines['right'].set_position(('outward', 60))
                line3, = ax3.plot(dates, avg_price.values, color='#10B981', linewidth=1.4,
                                  linestyle='-.', marker='D', markersize=3, label='月均价')
                ax3.set_ylabel('月均价', fontsize=AXIS_LABEL_FONTSIZE, labelpad=10,
                               color='#10B981', **font_kw)
                ax3.tick_params(axis='y', colors='#10B981')
                ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:.2f}'))
                for xi, yi in zip(range(len(dates)), avg_price.values):
                    if not pd.isna(yi):
                        ax3.annotate(f'{yi:.2f}', (xi, yi), textcoords='offset points',
                                     xytext=(0, 10), ha='center', fontsize=7, color='#10B981')

    ax1.set_xlabel('年月', fontsize=AXIS_LABEL_FONTSIZE, labelpad=10,
                   color='#64748B', **font_kw)
    agg_label = '总量' if aggregate == 'sum' else '均值'
    ax1.set_ylabel(f'{label_1} ({agg_label})', fontsize=AXIS_LABEL_FONTSIZE,
                   labelpad=10, color='#3B82F6', **font_kw)
    if not avg_price_only:
        ax2.set_ylabel(f'{label_2} ({agg_label})', fontsize=AXIS_LABEL_FONTSIZE,
                       labelpad=10, color='#F59E0B', **font_kw)

    ax1.tick_params(axis='y', colors='#3B82F6')
    if not avg_price_only:
        ax2.tick_params(axis='y', colors='#F59E0B')
    ax1.tick_params(axis='x', rotation=45)

    # 简洁风格：去框，只留底部轴线和浅横线
    for ax in [ax1, ax2]:
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#CBD5E1')
        ax.spines['bottom'].set_color('#CBD5E1')
    ax1.grid(True, axis='y', alpha=0.25, color='#CBD5E1', linewidth=0.5)
    ax1.set_axisbelow(True)

    # 合并图例
    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    all_lines = lines_1 + lines_2
    all_labels = labels_1 + labels_2
    if ax3:
        lines_3, labels_3 = ax3.get_legend_handles_labels()
        all_lines += lines_3
        all_labels += labels_3
    ax1.legend(all_lines, all_labels, loc='upper left',
               frameon=True, fontsize=LEGEND_FONTSIZE, framealpha=0.9)

    # 计算ASIN总数
    total_asins = sum(len(asins) for asins in groups.values())

    # 标题
    if group_col:
        title = f'{group_col}分组 — {label_1} vs {label_2}{agg_label}趋势'
    else:
        title = f'{label_1} vs {label_2}{agg_label}趋势'
    if filter_exprs:
        filter_str = ' & '.join(filter_exprs)
        title = f'{filter_str} — {title}'
    ax1.set_title(title, fontsize=TITLE_FONTSIZE, fontweight='bold', pad=18,
                  color='#1E293B', **font_kw)

    # 副标题：ASIN个数（缩小字体，向右侧移动）
    subtitle = f'筛选ASIN: {total_asins}个'
    ax1.text(0.98, 1.01, subtitle, transform=ax1.transAxes,
             fontsize=TICK_FONTSIZE, ha='right', va='bottom',
             color='#94A3B8', **font_kw)

    def fmt_y(x, _):
        if x >= 1_000_000:
            return f'{x/1_000_000:.1f}M'
        if x >= 1_000:
            return f'{x/1_000:.1f}K'
        return f'{x:.0f}'

    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_y))
    if not avg_price_only:
        ax2.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_y))

    plt.tight_layout(pad=1.5)

    if not output_path:
        output_path = f"trend_{group_col}_dual.png"
    plt.savefig(output_path, dpi=dpi, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    print(f"\n  图表已保存: {output_path}")

    if show:
        plt.switch_backend('TkAgg')
        plt.show()

    plt.close()
    return output_path


# ============================================================
# 数据导出
# ============================================================

def export_detail_data(groups, df_data_1, df_data_2, group_col, filter_exprs, output_path):
    """导出ASIN×月份详细数据 — 每个ASIN占3行（销量/销额/均价），月份横向展开。

    Args:
        groups: {group_name: [asin, ...]}
        df_data_1: 销量 DataFrame (index=ASIN, columns=月份)
        df_data_2: 销额 DataFrame (index=ASIN, columns=月份)
        group_col: 分组字段名
        filter_exprs: 筛选条件列表
        output_path: 输出文件路径
    """
    all_asins = []
    for asins in groups.values():
        all_asins.extend(asins)
    all_asins = sorted(set(all_asins))

    months = list(df_data_1.columns)

    # 表头：ASIN | 分组 | 指标 | 月份1 | 月份2 | ...
    headers = ['ASIN', '分组', '指标'] + [str(m) for m in months]

    rows = []
    for asin in all_asins:
        group_name = ''
        for g, asins in groups.items():
            if asin in asins:
                group_name = g
                break

        # 提取销量和销额序列
        vol_vals = []
        rev_vals = []
        for month in months:
            v = 0
            if asin in df_data_1.index and month in df_data_1.columns:
                val = df_data_1.loc[asin, month]
                v = val if pd.notna(val) else 0
            vol_vals.append(v)

            r = 0
            if asin in df_data_2.index and month in df_data_2.columns:
                val = df_data_2.loc[asin, month]
                r = val if pd.notna(val) else 0
            rev_vals.append(r)

        # 计算均价
        avg_vals = []
        for v, r in zip(vol_vals, rev_vals):
            avg_vals.append(round(r / v, 2) if v > 0 else 0)

        # 3 行：销量 / 销额 / 均价
        rows.append([asin, group_name, '销量'] + vol_vals)
        rows.append([asin, group_name, '销额'] + rev_vals)
        rows.append([asin, group_name, '均价'] + avg_vals)

    df_export = pd.DataFrame(rows, columns=headers)

    # 用 openpyxl 写入并合并 ASIN / 分组 单元格
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, Border, Side
    wb = Workbook()
    ws = wb.active
    ws.title = 'ASIN明细'

    # 写表头
    header_font = Font(bold=True)
    thin = Side(style='thin', color='CCCCCC')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal='center', vertical='center')

    for ci, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=ci, value=h)
        c.font = header_font
        c.border = border
        c.alignment = center

    # 写数据
    for ri, row_data in enumerate(rows, start=2):
        for ci, val in enumerate(row_data, start=1):
            c = ws.cell(row=ri, column=ci, value=val)
            c.border = border
            if ci >= 4:  # 月份数值列居中
                c.alignment = center

    # 合并 ASIN 列和分组列（每3行合并为一个）
    n_asins = len(all_asins)
    for i in range(n_asins):
        start_row = 2 + i * 3  # 表头占第1行
        end_row = start_row + 2
        ws.merge_cells(start_row=start_row, start_column=1,
                       end_row=end_row, end_column=1)
        ws.cell(row=start_row, column=1).alignment = Alignment(horizontal='center', vertical='center')
        ws.merge_cells(start_row=start_row, start_column=2,
                       end_row=end_row, end_column=2)
        ws.cell(row=start_row, column=2).alignment = Alignment(horizontal='center', vertical='center')

    # 参数信息 Sheet
    ws2 = wb.create_sheet('参数信息')
    info_data = {
        '参数': ['分组字段', '筛选条件', '销量Sheet', '销额Sheet'],
        '值': [group_col,
               ' & '.join(filter_exprs) if filter_exprs else '无',
               '已导入', '已导入']
    }
    for ci, h in enumerate(['参数', '值'], start=1):
        ws2.cell(row=1, column=ci, value=h).font = header_font
    for ri, (k, v) in enumerate(zip(info_data['参数'], info_data['值']), start=2):
        ws2.cell(row=ri, column=1, value=k)
        ws2.cell(row=ri, column=2, value=v)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    wb.save(output_path)

    print(f"\n  数据已导出: {output_path}")
    print(f"  ASIN数量: {len(all_asins)}（每个3行：销量/销额/均价，已合并单元格）")
    print(f"  月份范围: {months[0]} ~ {months[-1]}")

    return output_path


# ============================================================
# 百分比堆叠面积图
# ============================================================

def make_share_area_chart(groups, df_data, group_col, top_n, output_path, dpi,
                          show, font_name, filter_exprs=None, data_label='子体销量',
                          export_share=False, aggregate='sum'):
    """绘制百分比堆叠面积图 — 展示各品牌占总市场的比例变化。

    Args:
        groups: {group_name: [asin, ...]}
        df_data: DataFrame (index=ASIN, columns=月份)
        group_col: 分组字段名
        top_n: 展示前N个分组
        output_path: 输出路径
        dpi: 图片DPI
        show: 是否显示窗口
        font_name: 字体名称
        filter_exprs: 筛选条件列表
        data_label: 数据标签（用于标题）
        export_share: 是否输出占比数据表
        aggregate: 聚合方式（sum/mean）
    """

    # ---- 数据预处理 ----
    # 计算每个分组的聚合值
    agg_func = np.nansum if aggregate == 'sum' else np.nanmean
    group_agg = {}
    for g, asins in groups.items():
        vals = agg_func(df_data.loc[asins].values.astype(float), axis=0)
        group_agg[g] = vals

    # 按末期份额排序（取末期值最大的 top_n 个）
    last_month_idx = -1
    group_last_share = {}
    for g, vals in group_agg.items():
        group_last_share[g] = vals[last_month_idx]

    sorted_groups = sorted(group_last_share.keys(), key=lambda x: group_last_share[x], reverse=True)

    # 取前 top_n 个，其余归入"其他"
    final_groups = {}
    other_agg = np.zeros(len(df_data.columns))
    for i, g in enumerate(sorted_groups):
        if i < top_n:
            final_groups[g] = group_agg[g]
        else:
            other_agg += group_agg[g]

    if np.any(other_agg > 0):
        final_groups['其他'] = other_agg

    # 按末期份额重新排序（从大到小，"其他"固定在最后）
    final_sorted = sorted(final_groups.keys(),
                          key=lambda x: final_groups[x][last_month_idx] if x != '其他' else -1,
                          reverse=True)
    if '其他' in final_groups:
        final_sorted.remove('其他')
        final_sorted.append('其他')

    # ---- 计算占比百分比 ----
    months = list(df_data.columns)
    x = list(range(len(months)))

    # 计算每个时间点的总和
    total_per_month = np.zeros(len(months))
    for g in final_sorted:
        total_per_month += final_groups[g]

    # 计算占比百分比
    share_data = {}
    for g in final_sorted:
        share_pct = np.where(total_per_month > 0,
                             final_groups[g] / total_per_month * 100,
                             0)
        share_data[g] = share_pct

    # ---- 绘图 ----
    fig, ax = plt.subplots(figsize=(max(16, len(months) * 0.4), 8))
    ax.set_facecolor('#FAFBFC')

    # 准备堆叠数据（反转顺序，使最大的在上方）
    # stackplot 默认从下往上堆叠，所以需要将最大的放在列表末尾
    reversed_sorted = list(reversed(final_sorted))
    share_arrays = [share_data[g] for g in reversed_sorted]

    # 绘制堆叠面积图
    ax.stackplot(x, *share_arrays,
                 colors=[COLORS[i % len(COLORS)] for i in range(len(reversed_sorted))],
                 alpha=0.85, edgecolor='white', linewidth=0.5)

    # ---- 末期标注 ----
    font_kw = {'fontname': font_name} if font_name else {}
    import matplotlib.font_manager as fm
    font_prop = fm.FontProperties(fname=font_name) if font_name and os.path.exists(font_name) else None

    # 计算每个分层的末期中心位置（用于标注）
    # 注意：stackplot 从下往上堆叠，所以需要从下往上计算
    cumulative = np.zeros(len(months))
    for i, g in enumerate(reversed_sorted):
        share = share_data[g]
        last_share = share[last_month_idx]
        if last_share > 0:
            center_y = cumulative[last_month_idx] + last_share / 2
            # 标注占比
            label_text = f'{last_share:.1f}%'
            ax.annotate(label_text,
                        xy=(x[-1], center_y),
                        xytext=(10, 0),
                        textcoords='offset points',
                        ha='left', va='center',
                        fontsize=9, fontweight='bold',
                        color='white',
                        bbox=dict(boxstyle='round,pad=0.3',
                                  facecolor=COLORS[i % len(COLORS)],
                                  edgecolor='white', alpha=0.9),
                        **font_kw)
        cumulative += share

    # ---- 坐标轴设置 ----
    ax.set_xticks(x)
    step = max(1, len(months) // 16)
    labels = [months[i] if i % step == 0 else '' for i in range(len(months))]
    ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=TICK_FONTSIZE, **font_kw)
    ax.set_xlim(-0.6, len(months) - 0.4)
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
    if group_col:
        title = f'{group_col}分组 — {data_label}占比趋势'
    else:
        title = f'{data_label}占比趋势'
    if filter_exprs:
        filter_str = ' & '.join(filter_exprs)
        title = f'{filter_str} — {title}'
    ax.set_title(title, fontsize=TITLE_FONTSIZE, fontweight='bold', pad=18,
                 color='#1E293B', **font_kw)
    ax.set_xlabel('年月', fontsize=AXIS_LABEL_FONTSIZE, labelpad=10,
                  color='#64748B', **font_kw)
    ax.set_ylabel('占比 (%)', fontsize=AXIS_LABEL_FONTSIZE, labelpad=10,
                  color='#64748B', **font_kw)

    # ---- 图例（放在图表外右侧）----
    # 创建图例句柄（使用正确的顺序：从大到小）
    legend_handles = []
    legend_labels = []
    for i, g in enumerate(final_sorted):
        handle = plt.Rectangle((0, 0), 1, 1,
                               facecolor=COLORS[(len(reversed_sorted) - 1 - i) % len(COLORS)],
                               edgecolor='white', linewidth=0.5)
        legend_handles.append(handle)
        legend_labels.append(g)

    leg = ax.legend(legend_handles, legend_labels,
                    loc='upper left',
                    bbox_to_anchor=(1.15, 1.0),
                    frameon=True, fontsize=LEGEND_FONTSIZE,
                    framealpha=0.95, edgecolor='#CBD5E1',
                    borderpad=0.8, handlelength=1.5,
                    ncol=1, title=group_col,
                    title_fontsize=LEGEND_FONTSIZE + 1)
    # 修复图例乱码问题
    if font_prop:
        for txt in leg.get_texts():
            txt.set_fontproperties(font_prop)
        leg.get_title().set_fontproperties(font_prop)

    plt.tight_layout(pad=1.5)

    # 保存图片
    if not output_path:
        output_path = f"trend_{group_col}_share.png"
    plt.savefig(output_path, dpi=dpi, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    print(f"\n  图表已保存: {output_path}")

    if show:
        plt.switch_backend('TkAgg')
        plt.show()

    plt.close()

    # ---- 导出占比数据表 ----
    if export_share:
        # 构建数据表
        share_df_data = {'月份': months}
        for g in final_sorted:
            share_df_data[g] = share_data[g].round(2)

        share_df = pd.DataFrame(share_df_data)

        # 计算输出路径
        base, _ = os.path.splitext(output_path)
        share_output = f"{base}_share_data.xlsx"

        # 导出 Excel
        with pd.ExcelWriter(share_output, engine='openpyxl') as writer:
            share_df.to_excel(writer, sheet_name='占比数据', index=False)

            # 添加图表信息 sheet
            info_df = pd.DataFrame({
                '参数': ['分组字段', '聚合方式', '展示数量', '筛选条件', '数据标签'],
                '值': [group_col, aggregate, top_n,
                       ' & '.join(filter_exprs) if filter_exprs else '无',
                       data_label]
            })
            info_df.to_excel(writer, sheet_name='参数信息', index=False)

        print(f"  占比数据表已保存: {share_output}")

    return output_path


# ============================================================
# 主入口
# ============================================================

def main():
    args = parse_args()

    print("=" * 60)
    print("  单文件多 Sheet 趋势图")
    print("=" * 60)
    print(f"  文件:     {args.file}")
    print(f"  历史数据: {args.data_sheet}")
    print(f"  聚合方式: {args.aggregate}")
    if args.filter:
        print(f"  筛选条件: {' & '.join(args.filter)}")
    if args.group_col:
        print(f"  元数据:   {args.meta_sheet}")
        print(f"  分组字段: {args.group_col}")
    else:
        print(f"  分组:     无（全部ASIN合计）")

    # 1. 加载数据
    groups, df_data, meta_df = load_data(
        args.file, args.meta_sheet, args.data_sheet,
        args.group_col, args.filter
    )

    # --values 过滤：只保留指定的分组值
    if args.values and args.group_col:
        keep_values = [v.strip() for v in args.values.split(',') if v.strip()]
        before_count = len(groups)
        groups = {g: asins for g, asins in groups.items() if g in keep_values}
        after_count = len(groups)
        removed = before_count - after_count
        if removed > 0:
            print(f"  值过滤: 指定 {len(keep_values)} 个值，移除 {removed} 个不匹配分组")
        # 确保 df_data 只包含保留的 ASIN
        keep_asins = set()
        for asins in groups.values():
            keep_asins.update(asins)
        df_data = df_data.loc[df_data.index.isin(keep_asins)]

    print(f"\n  匹配 ASIN: {len(df_data)} 个")
    print(f"  时间跨度:  {df_data.columns[0]} ~ {df_data.columns[-1]}")

    # 2. 分组统计
    if args.group_col:
        print(f"  分组数:    {len(groups)}")
        print(f"\n  分组明细:")
        for g in sorted(groups, key=lambda k: -len(groups[k])):
            asins = groups[g]
            total = df_data.loc[asins].sum().sum()
            print(f"    {g}: {len(asins)} 个ASIN, 总销量 {total:,.0f}")

        # 小组合并提示
        small = {g: asins for g, asins in groups.items() if len(asins) < args.merge_threshold}
        if small:
            total_small = sum(len(v) for v in small.values())
            print(f"\n  合并到\"其他\"的小组 ({total_small}个ASIN): "
                  f"{', '.join(f'{g}({len(v)})' for g, v in sorted(small.items(), key=lambda x: -len(x[1])))}")
    else:
        total = df_data.sum().sum()
        print(f"  总销量:    {total:,.0f}")

    # 3. 出图
    font_name = setup_font()

    # 加载第二个Sheet（如果有）
    df_data_2 = None
    if args.data_sheet_2:
        groups_2, df_data_2, _ = load_data(
            args.file, args.meta_sheet, args.data_sheet_2,
            args.group_col, args.filter
        )
        # --values 过滤第二个 Sheet
        if args.values and args.group_col:
            df_data_2 = df_data_2.loc[df_data_2.index.isin(keep_asins)]
        print(f"  第二指标: {args.data_sheet_2} ({len(df_data_2)} 个ASIN)")

    # 导出数据（如果指定了 --export-data）
    if args.export_data:
        if df_data_2 is None:
            print("错误: 导出数据需要指定 --data-sheet-2（销额Sheet）")
            sys.exit(1)
        export_detail_data(groups, df_data, df_data_2, args.group_col,
                           args.filter, args.export_data)

    # 生成图片（如果没有指定 --export-only）
    if not args.export_only:
        if args.data_sheet_2:
            # 双轴模式
            make_dual_chart(groups, df_data, df_data_2, args.group_col, args.aggregate,
                            args.merge_threshold, args.output, args.dpi, args.show,
                            font_name, label_1=args.data_sheet, label_2=args.data_sheet_2,
                            filter_exprs=args.filter, show_avg_price=args.avg_price,
                            avg_price_only=args.avg_price_only)
        elif args.group_col:
            # 分组模式：根据 chart-type 选择图表类型
            if args.chart_type == 'area' or (args.chart_type == 'auto' and not args.data_sheet_2):
                # 使用百分比堆叠面积图
                make_share_area_chart(groups, df_data, args.group_col, args.top_n,
                                      args.output, args.dpi, args.show, font_name,
                                      filter_exprs=args.filter, data_label=args.data_sheet,
                                      export_share=args.export_share, aggregate=args.aggregate)
            else:
                # 使用折线图
                make_chart(groups, df_data, args.group_col, args.aggregate,
                           args.merge_threshold, args.output, args.dpi, args.show,
                           font_name, filter_exprs=args.filter, data_label=args.data_sheet)
        else:
            # 不分组模式：使用折线图
            make_chart(groups, df_data, args.group_col, args.aggregate,
                       args.merge_threshold, args.output, args.dpi, args.show,
                       font_name, filter_exprs=args.filter, data_label=args.data_sheet)

    print(f"\n{'=' * 60}")
    print(f"  完成")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
