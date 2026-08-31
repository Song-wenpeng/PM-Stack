# -*- coding: utf-8 -*-
"""Tower 品类趋势图：按插孔数 / 颜色 / 线长分组，画历史月销量 + 月销额趋势

METRICS 支持两种定义方式：
  1. {"sheet": "历史月销量", "label": "月销量"}          → 直接读 Sheet
  2. {"label": "月均价(€)", "compute": {"num": "月销额(€)", "den": "月销量"}}  → 计算派生指标

Sheet 不存在时自动跳过，不会报错。
"""

import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# ============================================================
# 配置
# ============================================================
INPUT_FILE = os.getenv("TREND_INPUT_FILE", r"C:\Users\QJH\Desktop\普通排插-DE-12-0331.xlsx")
SHEET_TAGGING = os.getenv("TREND_SHEET_TAGGING", "Competitor-DE-202512")
OUTPUT_DIR = os.getenv("TREND_OUTPUT_DIR", "./Tower趋势图/")

FILTER_COL = os.getenv("TREND_FILTER_COL", "排插类型")
FILTER_VAL = os.getenv("TREND_FILTER_VAL", "Tower")
DIMENSIONS = [
    item.strip()
    for item in os.getenv("TREND_DIMENSIONS", "插孔数,颜色,线长").split(",")
    if item.strip()
]

METRICS = [
    {"sheet": "历史月销量", "label": "月销量"},
    {"sheet": "历史月销额", "label": "月销额"},
    # 需要均价图时取消下面注释即可：
    # {"label": "月均价", "compute": {"num": "月销额", "den": "月销量"}},
]

# ============================================================
# 字体 & 样式
# ============================================================
def setup_font():
    """设置中文字体，并返回字体名称。

    注意：这里不要返回 FontProperties 对象再传给 set_fontproperties，
    否则可能把前面设置好的 fontsize 覆盖回默认字号，导致标题、图例、标注变小。
    """
    import matplotlib.font_manager as fm
    for fpath in ['C:\\Windows\\Fonts\\msyh.ttc', 'C:\\Windows\\Fonts\\simhei.ttf']:
        if os.path.exists(fpath):
            try:
                fm.fontManager.addfont(fpath)
                bold = 'C:\\Windows\\Fonts\\msyhbd.ttc'
                if 'msyh' in fpath and os.path.exists(bold):
                    fm.fontManager.addfont(bold)
                prop = fm.FontProperties(fname=fpath)
                font_name = prop.get_name()
                plt.rcParams['font.family'] = font_name
                plt.rcParams['axes.unicode_minus'] = False
                return font_name
            except Exception:
                continue
    return None


COLORS = ['#2563EB', '#DC2626', '#059669', '#7C3AED', '#D97706',
          '#DB2777', '#0891B2', '#E11D48', '#16A34A', '#8B5CF6']

# 字号统一控制：后续觉得大/小，优先改这里
TITLE_FONTSIZE = 34          # 标题
AXIS_LABEL_FONTSIZE = 24     # X/Y轴标题
TICK_FONTSIZE = 20           # X/Y轴刻度
LEGEND_FONTSIZE = 20         # 图例
END_LABEL_FONTSIZE = 18      # 折线首尾数值标注


def fmt_y(v, _):
    if abs(v) >= 1e6:
        return f'{v/1e6:.1f}M'
    elif abs(v) >= 1e4:
        return f'{v:,.0f}'
    else:
        return f'{v:,.1f}' if abs(v) < 10 else f'{v:,.0f}'


# ============================================================
# 数据加载
# ============================================================
def load_data():
    """加载打标表 + 所有指标宽表，返回 (asin_info, {label: df_wide})。"""
    xls = pd.ExcelFile(INPUT_FILE)
    available_sheets = xls.sheet_names
    print(f"Excel 中的 Sheet: {available_sheets}")

    # 打标表
    df_tag = pd.read_excel(INPUT_FILE, sheet_name=SHEET_TAGGING)
    tower = df_tag[df_tag[FILTER_COL] == FILTER_VAL].copy()
    tower['ASIN'] = tower['ASIN'].astype(str).str.strip()
    print(f"Tower 产品数: {len(tower)}")
    for dim in DIMENSIONS:
        print(f"  {dim}: {tower[dim].value_counts().to_dict()}")

    asin_info = tower[['ASIN'] + DIMENSIONS].set_index('ASIN')

    # 加载 sheet 型指标
    dataframes = {}  # label → df_wide
    for m in METRICS:
        if "sheet" not in m:
            continue
        sheet = m["sheet"]
        if sheet not in available_sheets:
            print(f"  [跳过] Sheet '{sheet}' 不存在，指标 '{m['label']}' 不可用")
            continue
        df = pd.read_excel(INPUT_FILE, sheet_name=sheet)
        df['ASIN'] = df['ASIN'].astype(str).str.strip()
        dataframes[m["label"]] = df
        print(f"  已加载: {m['label']} ← Sheet '{sheet}' ({df.shape[0]} 行 × {df.shape[1]} 列)")

    # 计算派生指标
    month_col_pattern = None  # 缓存：从已加载的宽表中检测年月列模式
    for m in METRICS:
        if "compute" not in m:
            continue
        num_label = m["compute"]["num"]
        den_label = m["compute"]["den"]
        if num_label not in dataframes or den_label not in dataframes:
            print(f"  [跳过] 计算 '{m['label']}' 依赖缺失 (需要 '{num_label}' 和 '{den_label}')")
            continue

        df_num = dataframes[num_label].copy()
        df_den = dataframes[den_label].copy()

        # 检测年月列
        if month_col_pattern is None:
            month_col_pattern = _detect_month_cols(df_num)

        result = df_num[['ASIN']].copy()
        for mc in month_col_pattern:
            if mc in df_num.columns and mc in df_den.columns:
                result[mc] = pd.to_numeric(df_num[mc], errors='coerce') / \
                             pd.to_numeric(df_den[mc], errors='coerce').replace(0, None)
            else:
                result[mc] = None
        dataframes[m["label"]] = result
        print(f"  已计算: {m['label']} = {num_label} / {den_label}")

    return asin_info, dataframes


def _detect_month_cols(df):
    """从宽表中识别 YYYY-MM 格式的年月列。"""
    cols = [c for c in df.columns if c not in ('ASIN', '分组') and not df[c].dtype == 'object']
    return sorted(cols, key=lambda x: tuple(map(int, str(x).split('-'))))


# ============================================================
# 分组汇总
# ============================================================
def prepare_series(df_wide, asin_info, dim):
    """宽表 merge 打标维度，按维度字段拆分为时间序列。

    Returns:
        months: [str] 排序后的年月列表
        dim_map: {ASIN: group_name}
        series:  {ASIN: pd.Series(index=months, values=float)}
    """
    tower_asins = asin_info.index.tolist()
    df = df_wide[df_wide['ASIN'].isin(tower_asins)].copy()
    df = df.merge(asin_info[[dim]], left_on='ASIN', right_index=True, how='left')

    month_cols = _detect_month_cols(df_wide)

    dim_map = {}
    series = {}
    for _, row in df.iterrows():
        label = row['ASIN']
        group = str(row[dim]).strip()
        dim_map[label] = group
        vals = pd.to_numeric(row[month_cols], errors='coerce')
        vals.index = month_cols
        series[label] = vals

    return month_cols, dim_map, series


# ============================================================
# 图表绘制
# ============================================================
def draw_chart(months, dim_map, series, dim_name, metric_name, output_path):
    """画趋势图：总和面积图 + 个体 ASIN 淡色细线。"""
    font_name = setup_font()
    n_months = len(months)
    x = list(range(n_months))

    groups = sorted(set(dim_map.values()))
    group_labels = {}
    for label, s in series.items():
        group_labels[label] = dim_map.get(label, '')

    df = pd.DataFrame(series)  # index=months, columns=ASIN labels

    # 画布不要过宽，否则插入 Word / 聊天窗口预览时会被整体缩小，字体看起来也会变小
    fig, ax = plt.subplots(figsize=(20, 9))
    ax.set_facecolor('#FAFBFC')
    ax.grid(True, linestyle='-', alpha=0.35, color='#CBD5E1', linewidth=0.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#CBD5E1')
    ax.spines['bottom'].set_color('#CBD5E1')

    n_groups = len(groups)
    for gi, grp in enumerate(groups):
        main_color = COLORS[gi % len(COLORS)]
        grp_cols = [c for c in df.columns if group_labels.get(c) == grp]
        if not grp_cols:
            continue

        grp_data = df[grp_cols]
        grp_sum = grp_data.sum(axis=1, skipna=True)

        # 个体 ASIN 淡色细线
        for col in grp_cols:
            valid = grp_data[col].notna()
            if valid.sum() >= 2:
                ax.plot([xi for xi, v in zip(x, valid) if v],
                        grp_data[col].values[valid],
                        color=main_color, alpha=0.18, linewidth=1.0, zorder=2)

        # 总和面积图 + 顶部实线
        sum_mask = grp_sum.notna()
        if sum_mask.sum() >= 2:
            ax.fill_between(x, 0, grp_sum.values,
                            where=sum_mask.values,
                            color=main_color, alpha=0.25, zorder=3)
            ax.plot([xi for xi, v in zip(x, sum_mask) if v],
                    grp_sum.values[sum_mask],
                    color=main_color, linewidth=3.0, zorder=4,
                    label=f'{grp} (n={len(grp_cols)})')

        # 首尾数值标注
        valid_vals = grp_sum.dropna()
        if len(valid_vals) >= 2:
            first_val = valid_vals.iloc[0]
            last_val = valid_vals.iloc[-1]
            first_xi = months.index(valid_vals.index[0])
            last_xi = months.index(valid_vals.index[-1])
            for xi, val, ha in [(first_xi, first_val, 'right'),
                                (last_xi, last_val, 'left')]:
                offset = -12 if ha == 'right' else 12
                ann = ax.annotate(f'{val:,.0f}', xy=(xi, val),
                                  xytext=(offset, 8), textcoords='offset points',
                                  ha=ha, fontsize=END_LABEL_FONTSIZE, color=main_color, fontweight='bold',
                                  bbox=dict(boxstyle='round,pad=0.25', facecolor='white',
                                            edgecolor=main_color, alpha=0.85, linewidth=0.7))
                if font_name:
                    ann.set_fontname(font_name)

    # 图例（左上角内部）
    leg = ax.legend(loc='upper left', frameon=True, fontsize=LEGEND_FONTSIZE,
                    framealpha=0.92, edgecolor='#CBD5E1',
                    borderpad=0.55, handlelength=2.4)
    if font_name:
        for txt in leg.get_texts():
            txt.set_fontname(font_name)

    # X 轴
    ax.set_xticks(x)
    step = max(1, n_months // 24)
    shown = [months[i] if i % step == 0 else '' for i in range(n_months)]
    ax.set_xticklabels(shown, rotation=45, ha='right', fontsize=TICK_FONTSIZE)
    ax.set_xlim(-0.6, n_months - 0.4)

    # Y 轴
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_y))
    ax.tick_params(axis='y', labelsize=TICK_FONTSIZE)

    # 标题
    title = f'Tower {dim_name} — {metric_name} 趋势'
    title_kw = dict(fontsize=TITLE_FONTSIZE, fontweight='bold', pad=24, color='#1E293B')
    xlabel_kw = dict(fontsize=AXIS_LABEL_FONTSIZE, labelpad=14, color='#64748B')
    ylabel_kw = dict(fontsize=AXIS_LABEL_FONTSIZE, labelpad=14, color='#64748B')
    if font_name:
        title_kw['fontname'] = font_name
        xlabel_kw['fontname'] = font_name
        ylabel_kw['fontname'] = font_name
    ax.set_title(title, **title_kw)
    ax.set_xlabel('年月', **xlabel_kw)
    ax.set_ylabel(metric_name, **ylabel_kw)

    ax.margins(x=0.01)
    y_min, y_max = ax.get_ylim()
    y_pad = max((y_max - y_min) * 0.08, 1)
    ax.set_ylim(max(0, y_min - y_pad), y_max + y_pad)

    plt.tight_layout(pad=1.5)
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, dpi=180, bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.close()
    print(f"  → {output_path}")


# ============================================================
# 数据表导出
# ============================================================
def save_tables(asin_info, dataframes, output_xlsx):
    """每个 (维度 × 指标) 一个 Sheet，行=ASIN，列=年月。"""
    dim_sheets = {}
    for dim in DIMENSIONS:
        for label, df_wide in dataframes.items():
            _, dim_map, series = prepare_series(df_wide, asin_info, dim)
            if not series:
                continue
            df_out = pd.DataFrame(series).T
            df_out.index.name = 'ASIN'
            df_out.insert(0, dim, [dim_map.get(idx, '') for idx in df_out.index])

            sheet_name = f'{dim}_{label}'[:31]
            dim_sheets[sheet_name] = df_out

    if not dim_sheets:
        print("无数据可导出")
        return

    os.makedirs(os.path.dirname(output_xlsx) or '.', exist_ok=True)
    with pd.ExcelWriter(output_xlsx, engine='openpyxl') as writer:
        for sheet_name, sdf in dim_sheets.items():
            sdf.to_excel(writer, sheet_name=sheet_name)
    print(f"数据表: {output_xlsx}")


# ============================================================
# 主入口
# ============================================================
def main():
    print("=" * 60)
    print("  Tower 品类趋势图")
    print(f"  文件: {INPUT_FILE}")
    print(f"  维度: {DIMENSIONS}")
    print(f"  指标: {[m['label'] for m in METRICS]}")
    print("=" * 60)

    asin_info, dataframes = load_data()

    if not dataframes:
        print("错误: 没有可用的指标数据，请检查 METRICS 配置和 Excel Sheet 名称")
        return

    total_charts = 0
    for dim in DIMENSIONS:
        for label, df_wide in dataframes.items():
            months, dim_map, series = prepare_series(df_wide, asin_info, dim)
            if not series:
                print(f"  [跳过] {dim} — {label}: 无数据")
                continue

            safe_name = label.replace('/', '_').replace('(', '').replace(')', '').replace('€', 'EUR')
            fname = f"Tower_{dim}_{safe_name}.png"
            output = os.path.join(OUTPUT_DIR, fname)
            draw_chart(months, dim_map, series, dim, label, output)
            total_charts += 1

    xlsx_path = os.path.join(OUTPUT_DIR, "Tower_趋势数据.xlsx")
    save_tables(asin_info, dataframes, xlsx_path)

    print(f"\n完成 — {total_charts} 张图 + 1 个数据表 → {OUTPUT_DIR}")


if __name__ == '__main__':
    main()
