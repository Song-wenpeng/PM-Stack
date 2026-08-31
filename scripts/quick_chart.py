# -*- coding: utf-8 -*-
"""
PM Stack 数据作图后端 — 接收结构化数据，生成专业图表

设计定位:
  - 数据清洗/列类型判断/图表类型推荐 → 由 AI（PM Stack 前端）完成
  - 本脚本只做一件事：接收干净的结构化数据 → 渲染图表 PNG

调用方式（按推荐优先级）:
  1. stdin 管道（AI 清洗后的 CSV/TSV 直接传入）:
       echo "颜色,销量\n白色,15\n黑色,12" | python quick_chart.py --type bar
       cat data.csv | python quick_chart.py                  # 自动检测类型

  2. JSON 配置字符串:
       python quick_chart.py --config '{...}'

  3. JSON 配置文件:
       python quick_chart.py --config chart.json

  4. Excel 文件（调试用，内置自动检测）:
       python quick_chart.py --file data.xlsx

JSON 配置格式:
  {
    "type": "bar | barh | pie | line | stacked_area",
    "title": "图表标题",
    "labels": ["A","B","C"],        // X轴/分类
    "values": [10, 20, 15],         // Y轴/数值
    // 或
    "x": ["2024-01","2024-02"],     // line 图 X 轴
    "series": {"产品A":[1,2], "产品B":[3,4]},  // line 图多系列
    // 可选
    "output": "./out/custom.png",
    "sort": "desc | asc | none",
    "top_n": 10,
    "color_by": "values"            // bar 图按值着色
  }

stdin CSV 格式（AI 清洗后输出）:
  第一行 = 列名（header）
  其余行 = 数据
  示例:
    颜色,产品数
    白色,15
    黑色,12
    灰色,8
"""

import os
import sys
import re
import io
import json
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
# 色板 & 样式常量
# ============================================================

PALETTE = [
    '#2a78d6',  # blue
    '#008300',  # green
    '#e87ba4',  # magenta
    '#eda100',  # yellow
    '#1baf7a',  # aqua
    '#eb6834',  # orange
    '#4a3aa7',  # violet
    '#e34948',  # red
]

SURFACE   = '#fcfcfb'
GRID      = '#e1e0d9'
BASELINE  = '#c3c2b7'
INK       = '#0b0b0b'
INK2      = '#52514e'
MUTED     = '#898781'

TITLE_FS  = 18; LABEL_FS = 11; TICK_FS = 9.5
LEGEND_FS = 9.5; ANNO_FS = 8.5
DPI       = 200

OUTPUT_DIR = './图表输出/'


# ============================================================
# 字体
# ============================================================

def _setup_font():
    import matplotlib.font_manager as fm
    for fp in ['C:\\Windows\\Fonts\\msyh.ttc',
               'C:\\Windows\\Fonts\\simhei.ttf']:
        if os.path.exists(fp):
            try:
                fm.fontManager.addfont(fp)
                bold = 'C:\\Windows\\Fonts\\msyhbd.ttc'
                if 'msyh' in fp and os.path.exists(bold):
                    fm.fontManager.addfont(bold)
                name = fm.FontProperties(fname=fp).get_name()
                plt.rcParams['font.family'] = name
                plt.rcParams['axes.unicode_minus'] = False
                return name
            except Exception:
                continue
    return None


# ============================================================
# 数据输入解析
# ============================================================

def read_stdin():
    """从 stdin 读取 CSV/TSV/JSON 数据。"""
    raw = sys.stdin.read().strip()
    if not raw:
        raise ValueError("stdin 为空，请管道传入数据")

    # JSON?
    if raw.startswith('{'):
        return parse_json(raw)

    # CSV/TSV
    return pd.read_csv(io.StringIO(raw), sep=None, engine='python')


def parse_json(raw_or_path):
    """解析 JSON 字符串或文件路径。返回标准化 dict 或 DataFrame。"""
    # 可能是文件路径
    if os.path.exists(raw_or_path):
        with open(raw_or_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    else:
        cfg = json.loads(raw_or_path)

    # 如果有 labels/values → 转为 DataFrame
    if 'labels' in cfg and 'values' in cfg:
        x_label = cfg.get('x_label', cfg.get('labels_name', '类别'))
        y_label = cfg.get('y_label', cfg.get('values_name', '数值'))
        df = pd.DataFrame({x_label: cfg['labels'], y_label: cfg['values']})
        # 把 type/title 等字段附加到 df.attrs
        df.attrs['_chart_cfg'] = {k: v for k, v in cfg.items()
                                   if k not in ('labels', 'values',
                                                'x_label', 'y_label',
                                                'labels_name', 'values_name')}
        return df

    # x + series (line 图多系列)
    if 'x' in cfg and 'series' in cfg:
        data = {cfg.get('x_label', 'x'): cfg['x']}
        data.update(cfg['series'])
        df = pd.DataFrame(data)
        df.attrs['_chart_cfg'] = {k: v for k, v in cfg.items()
                                   if k not in ('x', 'series', 'x_label')}
        return df

    # 通用表格格式
    if 'columns' in cfg and 'data' in cfg:
        df = pd.DataFrame(cfg['data'], columns=cfg['columns'])
        df.attrs['_chart_cfg'] = {k: v for k, v in cfg.items()
                                   if k not in ('columns', 'data')}
        return df

    raise ValueError(
        "JSON 格式不支持。支持格式:\n"
        "  {'labels':[...], 'values':[...], 'type':'bar'}\n"
        "  {'x':[...], 'series':{...}, 'type':'line'}\n"
        "  {'columns':[...], 'data':[[...],...]}")


def read_excel(filepath, sheet=0):
    xls = pd.ExcelFile(filepath)
    if isinstance(sheet, int) or sheet not in xls.sheet_names:
        sheet = xls.sheet_names[0]
    return pd.read_excel(xls, sheet)


# ============================================================
# AI 辅助函数（供 PM Stack 调用，也可脚本内部自动用）
# ============================================================

def classify_columns(df):
    """分类每列：datetime / numeric / categorical / text。"""
    result = {}
    for col in df.columns:
        s = df[col].dropna()
        if len(s) == 0:
            result[col] = 'empty'; continue

        # 日期检测
        if s.dtype == 'object':
            hits = sum(1 for v in s.head(30) if pd.notna(v) and
                       re.match(r'^\d{4}[-/\.]\d{2}([-/\.]\d{2})?$', str(v).strip()))
            if hits >= len(s.head(30)) * 0.6:
                result[col] = 'datetime'; continue

        # 数值检测
        if pd.api.types.is_numeric_dtype(s):
            nu = s.nunique()
            # 小数据集 + 几乎全部唯一 → numeric（如 [15,12,8,5]）
            # 大数据集 + 少量唯一值 → categorical（如评分 1-5）
            if nu <= 12 and nu / len(s) < 0.6:
                result[col] = 'categorical'
            else:
                result[col] = 'numeric'
            continue

        # 文本 → 分类 or 自由文本
        nu = s.nunique()
        ratio = nu / len(s)
        result[col] = 'categorical' if (ratio < 0.5 and nu <= 100) else 'text'
        continue

    return result


def suggest_chart_type(df, col_types=None):
    """根据数据结构推荐图表类型。"""
    if col_types is None:
        col_types = classify_columns(df)

    cat_cols = [c for c, t in col_types.items() if t == 'categorical']
    num_cols = [c for c, t in col_types.items() if t == 'numeric']
    date_cols = [c for c, t in col_types.items() if t == 'datetime']
    text_cols = [c for c, t in col_types.items() if t == 'text']
    label_cols = cat_cols + text_cols

    # 宽表 → line
    if len(num_cols) >= 5 and len(df) <= 30:
        return 'line'

    # 日期 + 数值 → line
    if date_cols and num_cols:
        return 'line'

    # 分类 + 数值
    if label_cols and num_cols:
        n_cats = df[label_cols[0]].nunique()
        if n_cats <= 8:
            return 'pie'
        elif n_cats <= 30:
            return 'barh'
        else:
            return 'barh'

    # 仅分类 → pie
    if label_cols and not num_cols:
        n_cats = df[label_cols[0]].nunique()
        return 'pie' if n_cats <= 8 else 'barh'

    # 仅数值 → bar
    if num_cols:
        return 'bar'

    return 'bar'


# ============================================================
# 数据预处理（聚合、排序、截断）
# ============================================================

def prep_xy(df, x_col=None, y_col=None, agg='sum', sort='desc', top_n=0):
    """从 DataFrame 提取 labels + values。

    - y_col=None → 统计 x_col 频次
    - x_col=None → 用第一列作标签
    """
    cols = df.columns.tolist()

    if x_col is None:
        x_col = cols[0]
    if y_col is None:
        y_col = cols[1] if len(cols) > 1 else None

    if x_col not in df.columns:
        raise KeyError(f"X 列「{x_col}」不存在。可用: {cols}")

    # 频次统计模式
    if y_col is None or y_col not in df.columns:
        counts = df[x_col].astype(str).str.strip().value_counts()
        labels, values = list(counts.index), list(counts.values)
        y_label = '数量'
        return _apply_sort_top(labels, values, sort, top_n), y_label

    # 聚合模式
    df_w = df[[x_col, y_col]].copy()
    df_w[x_col] = df_w[x_col].astype(str).str.strip()
    df_w[y_col] = pd.to_numeric(df_w[y_col], errors='coerce')
    df_w = df_w.dropna()

    if df_w.empty:
        return ([], []), y_col

    if agg == 'sum':
        g = df_w.groupby(x_col)[y_col].sum()
    elif agg == 'mean':
        g = df_w.groupby(x_col)[y_col].mean()
    else:
        g = df_w.groupby(x_col)[y_col].first()

    g = g.dropna().sort_values(ascending=False)
    labels, values = list(g.index), list(g.values)
    y_label = f'{y_col} ({agg})' if agg != 'sum' else y_col

    return _apply_sort_top(labels, values, sort, top_n), y_label


def _apply_sort_top(labels, values, sort, top_n):
    if sort == 'asc':
        order = np.argsort(values)
        labels = [labels[i] for i in order]
        values = [values[i] for i in order]
    elif sort == 'desc':
        order = np.argsort(values)[::-1]
        labels = [labels[i] for i in order]
        values = [values[i] for i in order]

    if top_n and len(labels) > top_n:
        rest = sum(values[top_n:])
        labels = labels[:top_n] + [f'其他({len(labels)-top_n}项)']
        values = values[:top_n] + [rest]

    return labels, values


# ============================================================
# 图表绘制
# ============================================================

def _init_ax(ax, font_name):
    ax.set_facecolor(SURFACE)
    ax.grid(True, linestyle='-', alpha=0.5, color=GRID, linewidth=0.5)
    for sp in ['top', 'right']:
        ax.spines[sp].set_visible(False)
    ax.spines['left'].set_color(BASELINE)
    ax.spines['bottom'].set_color(BASELINE)
    ax.tick_params(colors=MUTED)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: f'{v/1e6:.1f}M' if abs(v) >= 1e6
        else (f'{v:,.0f}' if abs(v) >= 100
              else (f'{int(v)}' if v == int(v) else f'{v:.1f}'))))
    fk = {'fontname': font_name} if font_name else {}
    return fk


def _set_labels(ax, title, xlabel, ylabel, font_name):
    fk = {'fontname': font_name} if font_name else {}
    ax.set_title(title, fontsize=TITLE_FS, fontweight='bold', pad=18, color=INK, **fk)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=LABEL_FS, labelpad=10, color=INK2, **fk)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=LABEL_FS, labelpad=10, color=INK2, **fk)


def _safe_font(val, font_name):
    return {'fontname': font_name} if font_name and val else {}


# ---------- 柱状图 ----------

def draw_bar(labels, values, title, y_label, font_name, sort='desc', top_n=0):
    n = len(labels)
    fig, ax = plt.subplots(figsize=(max(12, n * 0.65), 7))
    fk = _init_ax(ax, font_name)

    colors = [PALETTE[i % len(PALETTE)] for i in range(n)]
    x = np.arange(n)
    bars = ax.bar(x, values, width=0.65, color=colors, edgecolor='white',
                  linewidth=0.8, zorder=3)

    # 顶部数值标注
    y_max = max(values) if values else 1
    for xi, val in zip(x, values):
        if pd.notna(val) and val > 0:
            ax.text(xi, val + y_max * 0.015,
                    f'{val:,.0f}' if abs(val) >= 100 else f'{val:.1f}',
                    ha='center', va='bottom', fontsize=ANNO_FS, color=INK2,
                    fontweight='bold', **_safe_font(True, font_name))

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha='right', fontsize=TICK_FS, **fk)
    ax.set_xlim(-0.6, n - 0.4)
    ax.tick_params(axis='y', labelsize=TICK_FS)
    if y_max > 0:
        ax.set_ylim(0, y_max * 1.12)

    _set_labels(ax, title, '', y_label, font_name)
    plt.tight_layout(pad=1.5)
    return fig


# ---------- 水平条形图 ----------

def draw_barh(labels, values, title, y_label, font_name, sort='desc', top_n=0):
    n = len(labels)
    h = max(6, n * 0.45)
    fig, ax = plt.subplots(figsize=(11, h))
    fk = _init_ax(ax, font_name)

    y_pos = np.arange(n)
    # 第一名高亮（emphasis），其余灰色
    colors = [PALETTE[0] if i == 0 else '#d4d4d0' for i in range(n)]
    edges = [PALETTE[0] if i == 0 else BASELINE for i in range(n)]

    ax.barh(y_pos, values, height=0.6, color=colors, edgecolor=edges,
            linewidth=0.8, zorder=3)

    x_max = max(values) if values else 1
    for yi, val in zip(y_pos, values):
        if pd.notna(val):
            c = INK if yi == 0 else INK2
            ax.text(val + x_max * 0.015, yi,
                    f'{val:,.0f}' if abs(val) >= 100 else f'{val:.1f}',
                    ha='left', va='center', fontsize=ANNO_FS + 1, color=c,
                    fontweight='bold', **_safe_font(True, font_name))

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=TICK_FS, **fk)
    ax.invert_yaxis()
    ax.tick_params(axis='x', labelsize=TICK_FS)
    ax.set_xlim(0, x_max * 1.15)

    _set_labels(ax, title, y_label, '', font_name)
    plt.tight_layout(pad=1.5)
    return fig


# ---------- 饼图（环形） ----------

def draw_pie(labels, values, title, y_label, font_name):
    # 合并 < 2% 的小项
    total = sum(values)
    merged_x, merged_y = [], []
    other_sum, other_n = 0, 0
    for x, y in zip(labels, values):
        if y / total < 0.02:
            other_sum += y; other_n += 1
        else:
            merged_x.append(x); merged_y.append(y)
    if other_n > 0:
        merged_x.append(f'其他({other_n}项)')
        merged_y.append(other_sum)

    n = len(merged_x)
    fig, ax = plt.subplots(figsize=(9, 7))
    colors = [PALETTE[i % len(PALETTE)] for i in range(n)]

    wedges, _, autotexts = ax.pie(
        merged_y, labels=None, autopct='%1.1f%%',
        startangle=90, colors=colors,
        wedgeprops={'width': 0.45, 'edgecolor': 'white', 'linewidth': 2},
        pctdistance=0.78,
        textprops={'fontsize': ANNO_FS + 1, 'color': INK})

    for t in autotexts:
        if font_name:
            t.set_fontname(font_name)

    ct = ax.text(0, 0, f'{total:,.0f}', ha='center', va='center',
                 fontsize=22, fontweight='bold', color=INK)
    if font_name:
        ct.set_fontname(font_name)

    leg_labels = [f'{x}  ({y:,.0f})' for x, y in zip(merged_x, merged_y)]
    leg = ax.legend(wedges, leg_labels, loc='center left',
                    bbox_to_anchor=(1, 0.5), frameon=False,
                    fontsize=LEGEND_FS, handlelength=1.5)
    for txt in leg.get_texts():
        if font_name:
            txt.set_fontname(font_name)

    _set_labels(ax, title, '', '', font_name)
    plt.tight_layout(pad=1.5)
    return fig


# ---------- 折线图 ----------

def draw_line(x_vals, series_dict, title, y_label, font_name):
    """series_dict: {name: [values]}"""
    n_pts = len(x_vals)
    fig, ax = plt.subplots(figsize=(max(14, n_pts * 0.35), 7))
    fk = _init_ax(ax, font_name)
    x = np.arange(n_pts)

    for i, (name, vals) in enumerate(series_dict.items()):
        color = PALETTE[i % len(PALETTE)]
        arr = np.array(vals, dtype=float)
        valid = ~np.isnan(arr)
        if valid.sum() < 2:
            continue

        ax.plot(x[valid], arr[valid], color=color, linewidth=2.5,
                marker='o', markersize=5, markeredgecolor='white',
                markeredgewidth=1, zorder=5, label=str(name))

        vi = np.where(valid)[0]
        if len(vi) >= 2:
            for idx, ha in [(vi[0], 'right'), (vi[-1], 'left')]:
                ax.annotate(
                    f'{arr[idx]:,.0f}',
                    xy=(idx, arr[idx]),
                    xytext=(-15 if ha == 'right' else 15, 8),
                    textcoords='offset points', ha=ha,
                    fontsize=ANNO_FS, color=color, fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                              edgecolor=color, alpha=0.85, linewidth=0.7),
                    **_safe_font(True, font_name))

    if len(series_dict) > 1:
        leg = ax.legend(loc='upper left', frameon=True, fontsize=LEGEND_FS,
                        framealpha=0.92, edgecolor=GRID, borderpad=0.6)
        for txt in leg.get_texts():
            if font_name:
                txt.set_fontname(font_name)

    # X 轴
    ax.set_xticks(x)
    step = max(1, n_pts // 16)
    shown = [str(x_vals[i]) if i % step == 0 else '' for i in range(n_pts)]
    ax.set_xticklabels(shown, rotation=45, ha='right', fontsize=TICK_FS, **fk)
    ax.set_xlim(-0.6, n_pts - 0.4)
    ax.tick_params(axis='y', labelsize=TICK_FS)
    ax.margins(x=0.01)

    _set_labels(ax, title, '', y_label, font_name)
    plt.tight_layout(pad=1.5)
    return fig


# ---------- 100% 堆积面积图 ----------

def draw_stacked_area(x_vals, series_dict, title, y_label, font_name):
    """100% 堆积面积图 — 展示各部分占比随时间/维度变化。

    series_dict: {name: [values]}，各系列等长。
    每个 X 位置归一化到 100%，右侧末尾直接标注类别+占比。
    """
    n_pts = len(x_vals)
    n_series = len(series_dict)
    # 右侧留出标注空间
    fig, ax = plt.subplots(figsize=(max(16, n_pts * 0.5), 7.5))
    fk = _init_ax(ax, font_name)
    x = np.arange(n_pts)

    # 转为二维数组，NaN → 0
    names = list(series_dict.keys())
    data = np.array([series_dict[n] for n in names], dtype=float)
    data = np.nan_to_num(data, nan=0.0)

    # 每列归一化到 100%
    col_sums = data.sum(axis=0)
    col_sums[col_sums == 0] = 1.0
    data_pct = data / col_sums * 100.0

    # 从下往上堆叠
    y_bottom = np.zeros(n_pts)
    for i, name in enumerate(names):
        color = PALETTE[i % len(PALETTE)]
        y_top = y_bottom + data_pct[i]

        ax.fill_between(x, y_bottom, y_top,
                        color=color, alpha=0.88,
                        edgecolor='white', linewidth=1.5,
                        label=name, zorder=3)
        y_bottom = y_top

    # ---- 右侧末尾标注：类别名 + 最终占比 ----
    last_pcts = data_pct[:, -1]  # 最后一列各系列占比
    cumsum = np.cumsum(last_pcts)
    y_label_positions = []
    for i, name in enumerate(names):
        pct = last_pcts[i]
        y_start = 0 if i == 0 else cumsum[i - 1]
        mid_y = y_start + pct / 2
        y_label_positions.append((name, pct, mid_y, PALETTE[i % len(PALETTE)]))

    # 按 mid_y 排序（从上到下），全部展示，不合并
    y_label_positions.sort(key=lambda t: t[2], reverse=True)

    # 在图表右侧画标注 — 每个系列单独标注
    x_right = n_pts - 0.2
    for name, pct, mid_y, color in y_label_positions:
        # 从堆积区域右边缘引一条水平短线
        ax.annotate(
            '', xy=(n_pts - 0.55, mid_y), xytext=(x_right, mid_y),
            arrowprops=dict(arrowstyle='-', color=color, lw=1.2, alpha=0.7))
        # 标注文字
        ax.text(x_right + 0.3, mid_y, f'{name}  {pct:.1f}%',
                ha='left', va='center',
                fontsize=ANNO_FS + 1, color=INK,
                fontweight='bold',
                **_safe_font(True, font_name))

    # X 轴 — 扩大右侧空间
    ax.set_xticks(x)
    step = max(1, n_pts // 12)
    shown = [str(x_vals[i]) if i % step == 0 else '' for i in range(n_pts)]
    ax.set_xticklabels(shown, rotation=30, ha='right', fontsize=TICK_FS + 1, **fk)
    ax.set_xlim(-0.4, n_pts + max(3, n_series * 0.9))
    ax.set_ylim(0, 100)
    ax.tick_params(axis='y', labelsize=TICK_FS + 1)
    ax.set_ylabel('%', fontsize=LABEL_FS + 1, labelpad=6, color=INK2,
                  fontname=font_name if font_name else None)

    _set_labels(ax, title, '', '', font_name)
    plt.tight_layout(pad=1.5)
    return fig


# ---------- 正负面积堆积图 ----------

def draw_diverging_area(x_vals, series_dict, title, y_label, font_name):
    """正负面积堆积图 — 正值向上堆叠、负值向下堆叠，适合毛利/损益等数据。

    series_dict: {name: [values]}，值可正可负。
    正值在零线上方堆叠，负值在零线下方堆叠，同系列同色。
    """
    n_pts = len(x_vals)
    n_series = len(series_dict)
    fig, ax = plt.subplots(figsize=(max(16, n_pts * 0.5), 7.5))
    fk = _init_ax(ax, font_name)
    x = np.arange(n_pts)

    names = list(series_dict.keys())
    data = np.array([series_dict[n] for n in names], dtype=float)
    data = np.nan_to_num(data, nan=0.0)

    # 分别处理正值和负值
    data_pos = np.maximum(data, 0)   # 只保留正值
    data_neg = np.minimum(data, 0)   # 只保留负值

    # 正值：从 0 向上堆叠
    y_top_pos = np.zeros(n_pts)
    for i, name in enumerate(names):
        color = PALETTE[i % len(PALETTE)]
        vals = data_pos[i]
        if np.any(vals > 0):
            y_next = y_top_pos + vals
            ax.fill_between(x, y_top_pos, y_next,
                            color=color, alpha=0.85,
                            edgecolor='white', linewidth=1.2,
                            label=name, zorder=3)
            y_top_pos = y_next

    # 负值：从 0 向下堆叠
    y_bottom_neg = np.zeros(n_pts)
    for i, name in enumerate(names):
        color = PALETTE[i % len(PALETTE)]
        vals = data_neg[i]
        if np.any(vals < 0):
            y_next = y_bottom_neg + vals  # vals 为负，所以 y_next < y_bottom_neg
            ax.fill_between(x, y_bottom_neg, y_next,
                            color=color, alpha=0.85,
                            edgecolor='white', linewidth=1.2,
                            zorder=3)
            y_bottom_neg = y_next

    # 零线
    ax.axhline(y=0, color=INK, linewidth=1.2, alpha=0.5, zorder=4)

    # 右侧末尾标注：每个系列最终值
    last_vals = data[:, -1]
    pos_indices = np.where(last_vals > 0)[0]
    neg_indices = np.where(last_vals < 0)[0]

    # 正值标注（从零线向上）
    y_cursor = 0
    for idx in pos_indices:
        val = last_vals[idx]
        mid_y = y_cursor + val / 2
        y_cursor += val
        ax.text(n_pts - 0.3, mid_y, f'{names[idx]}  +{val:,.0f}',
                ha='left', va='center',
                fontsize=ANNO_FS, color=PALETTE[idx % len(PALETTE)],
                fontweight='bold',
                **_safe_font(True, font_name))

    # 负值标注（从零线向下）
    y_cursor = 0
    for idx in neg_indices:
        val = last_vals[idx]
        mid_y = y_cursor + val / 2
        y_cursor += val
        ax.text(n_pts - 0.3, mid_y, f'{names[idx]}  {val:,.0f}',
                ha='left', va='center',
                fontsize=ANNO_FS, color=PALETTE[idx % len(PALETTE)],
                fontweight='bold',
                **_safe_font(True, font_name))

    # 图例（去重，每个系列只出现一次）
    handles, labels = ax.get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    leg = ax.legend(unique.values(), unique.keys(),
                    loc='upper center', bbox_to_anchor=(0.5, -0.08),
                    frameon=False, fontsize=LEGEND_FS + 1,
                    ncol=min(n_series, 6), handlelength=2.0)

    for txt in leg.get_texts():
        if font_name:
            txt.set_fontname(font_name)

    # X 轴
    ax.set_xticks(x)
    step = max(1, n_pts // 12)
    shown = [str(x_vals[i]) if i % step == 0 else '' for i in range(n_pts)]
    ax.set_xticklabels(shown, rotation=30, ha='right', fontsize=TICK_FS + 1, **fk)
    ax.set_xlim(-0.4, n_pts + max(2, n_series * 0.6))
    ax.tick_params(axis='y', labelsize=TICK_FS + 1)

    # Y 轴格式 — 正负对称
    y_abs_max = max(abs(data.min()), data.max(), 1)
    ax.set_ylim(-y_abs_max * 1.15, y_abs_max * 1.15)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: f'{v:+,.0f}' if abs(v) >= 100 else f'{v:+.1f}'))

    _set_labels(ax, title, '', y_label, font_name)
    plt.subplots_adjust(bottom=0.18)
    return fig


# ============================================================
# 宽表 → 折线图 提取
# ============================================================

def extract_line_from_wide(df, y_cols=None):
    """从宽表（行=实体，列=时间）提取折线图数据。

    Args:
        df: DataFrame，第一列为实体名，其余列为数值（时间序列）
        y_cols: 要提取的实体标签列表，None 取前 6 行

    Returns:
        x_vals: [str] 时间标签
        series: {name: [values]}
    """
    col_types = classify_columns(df)
    num_cols = [c for c, t in col_types.items() if t == 'numeric']
    date_cols = [c for c, t in col_types.items() if t == 'datetime']

    # 确定时间轴：优先日期列，否则数值列
    time_cols = date_cols if date_cols else num_cols
    if not time_cols:
        time_cols = df.columns[1:].tolist()

    # 排序
    sorted_times = sorted(time_cols, key=lambda v: tuple(
        map(int, str(v).split('-'))) if re.match(r'^\d{4}-\d{2}', str(v))
        else str(v))
    x_vals = sorted_times

    # 实体标签列
    label_col = df.columns[0]
    if y_cols is None:
        y_cols = df[label_col].head(6).tolist()

    series = {}
    for name in y_cols:
        row = df[df[label_col].astype(str).str.strip() == str(name).strip()]
        if row.empty:
            continue
        vals = []
        for tc in sorted_times:
            if tc in row.columns:
                v = row[tc].values[0]
                vals.append(float(v) if pd.notna(v) else np.nan)
            else:
                vals.append(np.nan)
        series[str(name)] = vals

    return x_vals, series


# ============================================================
# 保存
# ============================================================

def _save(fig, title, chart_type, output_dir):
    safe = re.sub(r'[\\/:*?"<>|]', '_', title or 'chart')[:40]
    fname = f"{chart_type}_{safe}.png"
    path = os.path.join(output_dir, fname)
    os.makedirs(output_dir, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)
    return path


# ============================================================
# 主调度
# ============================================================

def generate_chart(data, chart_type=None, title='', sort='desc', top_n=0,
                   x_col=None, y_col=None, output_dir=None):
    """核心 API — PM Stack 可直接 import 调用。

    Args:
        data: 支持三种格式:
              - (labels, values) 二元组
              - {x: [...], series: {...}} dict
              - pd.DataFrame
        chart_type: 'bar'|'barh'|'pie'|'line'|None (None=auto)
        title: 图表标题
        output_dir: 输出目录

    Returns: PNG 文件路径
    """
    font_name = _setup_font()
    out_dir = output_dir or OUTPUT_DIR

    # ---- 解析 data → DataFrame + cfg ----
    if isinstance(data, tuple) and len(data) == 2:
        labels, values = data
        if chart_type is None:
            chart_type = 'pie' if len(labels) <= 8 else 'barh'
        df = pd.DataFrame({'类别': labels, '数值': values})
        df.attrs['_chart_cfg'] = {'type': chart_type, 'title': title,
                                   'x_col': '类别', 'y_col': '数值',
                                   'sort': sort, 'top_n': top_n}

    elif isinstance(data, dict) and 'x' in data and 'series' in data:
        chart_type = chart_type or 'line'
        d = {data.get('x_label', 'x'): data['x']}
        d.update(data['series'])
        df = pd.DataFrame(d)
        df.attrs['_chart_cfg'] = {'type': 'line', 'title': title}

    elif isinstance(data, pd.DataFrame):
        df = data
        cfg = df.attrs.get('_chart_cfg', {})
        chart_type = chart_type or cfg.get('type')
        title = title or cfg.get('title', '')
        sort = cfg.get('sort', sort)
        top_n = cfg.get('top_n', top_n)
        x_col = x_col or cfg.get('x_col')
        y_col = y_col or cfg.get('y_col')
    else:
        raise TypeError(f"不支持的数据类型: {type(data)}")

    # ---- 自动检测 + 列选择 ----
    col_types = classify_columns(df)
    if chart_type is None:
        chart_type = suggest_chart_type(df, col_types)

    num_cols = [c for c, t in col_types.items() if t == 'numeric']
    cat_cols = [c for c, t in col_types.items() if t == 'categorical']
    text_cols = [c for c, t in col_types.items() if t == 'text']

    if x_col is None:
        date_cols = [c for c, t in col_types.items() if t == 'datetime']
        x_col = (date_cols + cat_cols + text_cols + [df.columns[0]])[0]
    if y_col is None and chart_type not in ('line', 'stacked_area', 'diverging_area'):
        y_col = (num_cols + [None])[0]

    print(f"  图表类型: {chart_type}")

    return _render(df, chart_type, col_types, x_col, y_col,
                   title, sort, top_n, font_name, out_dir)


# ============================================================
# 命令行入口
# ============================================================

def _render(df, chart_type, col_types, x_col, y_col, title, sort, top_n,
            font_name, output_dir):
    """内部渲染函数：根据数据形态选择合适的图表策略。"""

    num_cols = [c for c, t in col_types.items() if t == 'numeric']
    date_cols = [c for c, t in col_types.items() if t == 'datetime']
    cat_cols = [c for c, t in col_types.items() if t == 'categorical']
    text_cols = [c for c, t in col_types.items() if t == 'text']
    label_cols = cat_cols + text_cols

    # ================================================================
    # LINE / STACKED_AREA 图：两种形态
    #   A) x+series（第一列为日期/X轴，其余列为多条线/带）
    #   B) 宽表（第一列为实体名，其余数值列为时间序列）
    # ================================================================
    if chart_type in ('line', 'stacked_area', 'diverging_area'):
        n_numeric = len(num_cols)
        n_total = len(df.columns)

        # 形态A: x+series → 第一列是 X 轴，剩余数值列是 series
        first_type = col_types.get(df.columns[0])
        if first_type in ('datetime', 'categorical', 'text') and n_numeric == n_total - 1:
            x_vals = df[df.columns[0]].astype(str).tolist()
            series = {}
            for col in num_cols:
                vals = pd.to_numeric(df[col], errors='coerce').tolist()
                series[col] = vals
            if chart_type == 'stacked_area':
                fig = draw_stacked_area(x_vals, series, title, '占比', font_name)
            elif chart_type == 'diverging_area':
                fig = draw_diverging_area(x_vals, series, title, '数值', font_name)
            else:
                fig = draw_line(x_vals, series, title, '数值', font_name)
            return _save(fig, title, chart_type, output_dir)

        # 形态B: 宽表 → 每行一条线/带
        if n_numeric >= 3 and len(df) <= 30:
            x_vals, series = extract_line_from_wide(df, y_col)
            if x_vals and series:
                if chart_type == 'stacked_area':
                    fig = draw_stacked_area(x_vals, series, title, '占比', font_name)
                elif chart_type == 'diverging_area':
                    fig = draw_diverging_area(x_vals, series, title, '数值', font_name)
                else:
                    fig = draw_line(x_vals, series, title, '数值', font_name)
                return _save(fig, title, chart_type, output_dir)

        # 兜底
        (labels, values), y_label = prep_xy(df, x_col, y_col,
                                            agg='sum', sort=sort, top_n=top_n)
        if chart_type == 'stacked_area':
            fig = draw_stacked_area(labels, {'': values}, title, y_label, font_name)
        elif chart_type == 'diverging_area':
            fig = draw_diverging_area(labels, {'': values}, title, y_label, font_name)
        else:
            fig = draw_line(labels, {'': values}, title, y_label, font_name)
        return _save(fig, title, chart_type, output_dir)

    # ================================================================
    # BAR / BARH / PIE
    # ================================================================
    (labels, values), y_label = prep_xy(df, x_col, y_col,
                                        agg='sum', sort=sort, top_n=top_n)
    if not labels:
        raise ValueError("聚合后无有效数据，请检查列名或筛选条件")

    print(f"  X: {x_col or df.columns[0]} ({len(labels)} 项)")
    print(f"  Y: {y_col or '(频次)'}")

    if chart_type == 'bar':
        fig = draw_bar(labels, values, title, y_label, font_name)
    elif chart_type == 'barh':
        fig = draw_barh(labels, values, title, y_label, font_name)
    elif chart_type == 'pie':
        fig = draw_pie(labels, values, title, y_label, font_name)
    else:
        fig = draw_bar(labels, values, title, y_label, font_name)

    return _save(fig, title, chart_type, output_dir)

def parse_args():
    p = argparse.ArgumentParser(
        description='PM Stack 数据作图 — 接收结构化数据生成图表',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  echo "颜色,数量\\n白色,15\\n黑色,12" | python quick_chart.py --type bar
  python quick_chart.py --config '{"type":"pie","labels":["A","B","C"],"values":[1,2,3]}'
  python quick_chart.py --file data.xlsx
  python quick_chart.py --file data.xlsx --type barh --x 颜色 --y 销量
        """)
    p.add_argument('--config', default='',
                   help='JSON 配置字符串或配置文件路径')
    p.add_argument('--file', default='',
                   help='Excel/CSV 文件路径')
    p.add_argument('--sheet', default=0,
                   help='Sheet 名或索引')
    p.add_argument('--type', default='',
                   choices=['bar', 'barh', 'pie', 'line', 'stacked_area', 'diverging_area'],
                   help='图表类型（不指定则自动检测）')
    p.add_argument('--x', default='',
                   help='X轴/分类列名')
    p.add_argument('--y', default='',
                   help='Y轴/数值列名')
    p.add_argument('--title', default='',
                   help='图表标题')
    p.add_argument('--sort', default='desc',
                   choices=['desc', 'asc', 'none'])
    p.add_argument('--top', type=int, default=0,
                   help='只显示前 N 项')
    p.add_argument('--output', default='',
                   help='输出目录')
    p.add_argument('--list', action='store_true',
                   help='仅分析数据结构，不绑图')
    return p.parse_args()


def main():
    args = parse_args()

    global OUTPUT_DIR
    if args.output:
        OUTPUT_DIR = args.output

    print("=" * 55)
    print("  PM Stack 数据作图")
    print("=" * 55)

    # ---- 1. 获取数据 ----
    if args.config:
        print("  数据源: JSON 配置")
        df = parse_json(args.config)
        # parse_json 返回的 df 可能已经带了 _chart_cfg
    elif args.file:
        print(f"  数据源: {args.file}")
        ext = os.path.splitext(args.file)[1].lower()
        if ext == '.csv':
            df = pd.read_csv(args.file)
        else:
            df = read_excel(args.file, args.sheet)
    elif not sys.stdin.isatty():
        print("  数据源: stdin (管道)")
        df = read_stdin()
        # read_stdin 可能返回带 _chart_cfg 的 df (JSON) 或普通 df (CSV)
    else:
        print("  数据源: 剪贴板")
        try:
            df = pd.read_clipboard(sep=r'\s*\t\s*', engine='python')
            if df.shape[1] <= 1:
                df = pd.read_clipboard(sep=r'\s{2,}', engine='python')
        except Exception as e:
            print(f"剪贴板读取失败: {e}")
            print("请用以下方式之一传入数据:")
            print("  echo ... | python quick_chart.py")
            print("  python quick_chart.py --config '...'")
            print("  python quick_chart.py --file data.xlsx")
            sys.exit(1)

    # 清洗
    df = df.dropna(how='all').dropna(axis=1, how='all').reset_index(drop=True)
    df.columns = [str(c).strip() for c in df.columns]

    print(f"  数据: {df.shape[0]} 行 × {df.shape[1]} 列")
    print(f"  列名: {', '.join(df.columns.tolist())}")

    # ---- 2. 分析 ----
    col_types = classify_columns(df)
    print(f"\n  列分类:")
    for col, ct in col_types.items():
        if ct == 'empty':
            continue
        nu = df[col].nunique()
        nm = df[col].isna().sum()
        extra = f', {nu} 唯一值' if ct in ('categorical', 'datetime') else ''
        extra += f', {nm} 缺失' if nm > 0 else ''
        print(f"    [{ct:12s}] {col}{extra}")

    if args.list:
        suggestion = suggest_chart_type(df, col_types)
        print(f"\n  建议图表: {suggestion}")
        return

    # ---- 3. 用户覆盖配置 ----
    cfg = getattr(df, 'attrs', {}).get('_chart_cfg', {})
    chart_type = args.type or cfg.get('type') or None
    title = args.title or cfg.get('title', '')
    x_col = args.x or cfg.get('x_col') or None
    y_col = args.y or cfg.get('y_col') or None
    if args.top:
        cfg['top_n'] = args.top
    cfg['sort'] = args.sort

    # ---- 4. 自动检测 ----
    if chart_type is None:
        chart_type = suggest_chart_type(df, col_types)
        print(f"\n  自动检测: {chart_type}")
    else:
        print(f"\n  图表类型: {chart_type} (手动指定)")

    if x_col is None and chart_type not in ('line', 'stacked_area', 'diverging_area'):
        # 自动选 x 列
        cat_cols = [c for c, t in col_types.items() if t == 'categorical']
        text_cols = [c for c, t in col_types.items() if t == 'text']
        x_col = (cat_cols + text_cols + [df.columns[0]])[0]

    if y_col is None and chart_type not in ('line', 'stacked_area', 'diverging_area'):
        num_cols = [c for c, t in col_types.items() if t == 'numeric']
        y_col = (num_cols + [None])[0]

    # ---- 5. 出图 ----
    font_name = _setup_font()
    print(f"  字体: {font_name or '默认'}")

    output_path = _render(df, chart_type, col_types, x_col, y_col,
                          title, args.sort, args.top, font_name, OUTPUT_DIR)
    print(f"\n  → {output_path}")

    print(f"\n{'=' * 55}")
    print(f"  完成")
    print(f"{'=' * 55}")


if __name__ == '__main__':
    main()
