# -*- coding: utf-8 -*-
"""
ASIN数据提取与趋势分析脚本

从指定文件夹的 *_销量拆分.xlsx 文件中,按 ASIN 提取指定字段,
按年月排序输出数据表和趋势图,支持多ASIN分组对比。

用法:
    # 单ASIN查询
    python extract_asin_trend.py --folder ./排插_US/ --asins B00DOMYL24

    # 多ASIN带分组
    python extract_asin_trend.py --folder ./排插_US/ \
        --asins B00XXX,B00YYY,B00ZZZ,B00AAA \
        --groups 塔形,塔形,塔形,条形

    # 命令行支持 ASIN:标签 语法
    python extract_asin_trend.py --folder ./排插_US/ \
        --asins B00XXX:产品A,B00YYY:产品B

    # 从配置文件读取 (支持 csv / xlsx / json)
    python extract_asin_trend.py --folder ./排插_US/ --config asin_list.csv
    python extract_asin_trend.py --folder ./排插_US/ --config asin_list.json

    # 指定字段与输出
    python extract_asin_trend.py --folder ./排插_US/ --asins B00XXX,B00YYY \
        --field 月销量 --output result.xlsx --chart trend.png

    # 弹窗显示图表 (默认不弹窗)
    python extract_asin_trend.py --folder ./排插_US/ --asins B00XXX --show

    # 只出表/只出图
    python extract_asin_trend.py --folder ./排插_US/ --asins B00XXX --no-chart
    python extract_asin_trend.py --folder ./排插_US/ --asins B00XXX --no-table

    # 调整DPI与列名映射
    python extract_asin_trend.py --folder ./排插_US/ --config data.xlsx \
        --asin-col 子ASIN --group-col 品类 --label-col 产品名 --dpi 300
"""

import os
import re
import sys
import argparse

# 统一处理 Windows 终端编码问题
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # 默认不弹窗，用 --show 覆盖
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from collections import defaultdict

# ============================================================
# 参数解析
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description='ASIN数据提取与趋势分析 — 从销量拆分文件中按ASIN提取时间序列'
    )
    parser.add_argument('--folder', required=True,
                        help='包含 *_销量拆分.xlsx 文件的文件夹路径')
    parser.add_argument('--asins', default='',
                        help='要查询的ASIN，逗号分隔')
    parser.add_argument('--groups', default='',
                        help='与ASIN一一对应的分组标签，逗号分隔 (如: 塔形,塔形,条形)')
    parser.add_argument('--config', default='',
                        help='CSV/JSON配置文件路径 (含 ASIN,分组,标签 列)，替代 --asins')
    parser.add_argument('--field', default='子体销量_矫正',
                        help='要提取的数据列名 (默认: 子体销量_矫正)')
    parser.add_argument('--output', default='',
                        help='输出xlsx路径 (默认: asin_trend_{field}.xlsx)')
    parser.add_argument('--chart', default='',
                        help='输出图表路径 (默认: asin_trend_{field}.png)')
    parser.add_argument('--show', action='store_true',
                        help='显示图表窗口 (非交互环境请勿使用)')
    parser.add_argument('--no-table', action='store_true',
                        help='不生成xlsx表格')
    parser.add_argument('--no-chart', action='store_true',
                        help='不生成趋势图')
    parser.add_argument('--dpi', type=int, default=200,
                        help='图表DPI (默认200)')
    parser.add_argument('--asin-col', default='ASIN',
                        help='配置文件中ASIN列名 (默认: ASIN)')
    parser.add_argument('--group-col', default='',
                        help='配置文件中分组列名 (自动检测: 分组/排插类型/类别)')
    parser.add_argument('--label-col', default='',
                        help='配置文件中标签列名 (默认同ASIN)')
    return parser.parse_args()


def load_asin_config(args):
    """从命令行或配置文件加载 ASIN 列表、分组、标签。

    支持格式:
      - xlsx/csv 文件: 通过 --asin-col / --group-col / --label-col 指定列
      - JSON文件: [{"asin":"...", "group":"...", "label":"..."}, ...]
      - 命令行 --asins: B00XXX, B00YYY 或 B00XXX:标签名

    Returns:
        records: [(asin, group, label), ...]
    """
    if args.config:
        ext = os.path.splitext(args.config)[1].lower()

        # ---- xlsx / csv ----
        if ext in ('.xlsx', '.xls'):
            df = pd.read_excel(args.config, dtype=str)
        elif ext == '.csv':
            df = pd.read_csv(args.config, encoding='utf-8', dtype=str)
        elif ext == '.json':
            import json
            with open(args.config, 'r', encoding='utf-8') as f:
                data = json.load(f)
            records = []
            for item in data:
                records.append((
                    item['asin'],
                    item.get('group', ''),
                    item.get('label', item['asin'])
                ))
            return records
        else:
            if ext:
                print(f"错误: 不支持的配置文件格式: {ext}，支持 .xlsx / .csv / .json")
            else:
                print(f"错误: 配置文件路径没有扩展名，支持 .xlsx / .csv / .json\n  路径: {args.config}")
            sys.exit(1)

        cols = list(df.columns)
        print(f"\n  配置文件: {args.config}")
        print(f"  可用列: {', '.join(cols)}")

        # ---- ASIN列 ----
        if args.asin_col in cols:
            asin_col = args.asin_col
            print(f"  ASIN列: [{asin_col}] (手动指定)")
        else:
            # 自动找名为 ASIN 的列，否则用第一列
            asin_col = next((c for c in cols if c.upper() == 'ASIN'), None)
            if asin_col:
                print(f"  ASIN列: [{asin_col}] (自动检测)")
            else:
                asin_col = cols[0]
                print(f"  ASIN列: [{asin_col}] (默认第一列，可用 --asin-col 指定)")

        # ---- 分组列 ----
        if args.group_col:
            if args.group_col not in cols:
                print(f"错误: 指定的分组列「{args.group_col}」不在文件中。可用列: {', '.join(cols)}")
                sys.exit(1)
            group_col = args.group_col
            print(f"  分组列: [{group_col}] (手动指定)")
        else:
            # 自动检测候选列
            group_candidates = ['分组', '排插类型', '类型', '类别', 'group', 'category']
            group_col = next((c for c in group_candidates if c in cols), '')
            if group_col:
                print(f"  分组列: [{group_col}] (自动检测，可用 --group-col 覆盖)")
            else:
                print(f"  分组列: 未指定 (所有ASIN归为同一组，可用 --group-col 指定)")

        # ---- 标签列 ----
        if args.label_col:
            if args.label_col not in cols:
                print(f"错误: 指定的标签列「{args.label_col}」不在文件中。可用列: {', '.join(cols)}")
                sys.exit(1)
            label_col = args.label_col
            print(f"  标签列: [{label_col}] (手动指定)")
        else:
            label_candidates = ['标签', '名称', '产品名', 'label', 'name']
            label_col = next((c for c in label_candidates if c in cols), '')
            if label_col:
                print(f"  标签列: [{label_col}] (自动检测)")
            else:
                print(f"  标签列: 使用ASIN (可用 --label-col 指定)")

        records = []
        for _, row in df.iterrows():
            asin = str(row[asin_col]).strip()
            if not asin or asin.lower() == 'nan':
                continue
            group = str(row[group_col]).strip() if group_col else ''
            if group.lower() == 'nan':
                group = ''
            label = str(row[label_col]).strip() if label_col else asin
            if label.lower() == 'nan':
                label = asin
            records.append((asin, group, label))

        if not records:
            print("错误: 配置文件中未找到有效的ASIN数据")
            sys.exit(1)

        return records

    # ---- 命令行模式 ----
    raw = [a.strip() for a in args.asins.split(',') if a.strip()]
    if not raw:
        print("错误: 请通过 --asins 或 --config 指定ASIN列表")
        sys.exit(1)

    asins = []
    labels = []
    for item in raw:
        if ':' in item:
            a, lbl = item.split(':', 1)
            asins.append(a.strip())
            labels.append(lbl.strip())
        else:
            asins.append(item)
            labels.append(item)

    groups = [g.strip() for g in args.groups.split(',') if g.strip()] if args.groups else []
    groups = groups + [''] * (len(asins) - len(groups))

    records = []
    for asin, group, label in zip(asins, groups, labels):
        records.append((asin, group, label))
    return records


# ============================================================
# 文件名年月提取
# ============================================================

def extract_year_month(filename):
    """从文件名提取年月。
    排插_US_2024-05_销量拆分.xlsx → '2024-05'
    DE_202512_销量拆分.xlsx → '2025-12'
    """
    # YYYY-MM
    m = re.search(r'(\d{4})-(\d{2})', filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    # YYYY.MM
    m = re.search(r'(\d{4})\.(\d{2})', filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    # YYYYMM
    m = re.search(r'(\d{4})(\d{2})(?:\D|$)', filename)
    if m:
        year, month = m.group(1), m.group(2)
        if 1 <= int(month) <= 12:
            return f"{year}-{month}"
    return None


# ============================================================
# 数据提取核心
# ============================================================

def scan_files(folder):
    """扫描文件夹，返回 [(filepath, year_month), ...] 按年月排序。"""
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"文件夹不存在: {folder}")

    entries = []
    for fname in os.listdir(folder):
        if not fname.endswith('.xlsx') or fname.startswith('~$'):
            continue
        if '_销量拆分' not in fname:
            continue
        ym = extract_year_month(fname)
        if not ym:
            continue
        entries.append((os.path.join(folder, fname), ym))

    entries.sort(key=lambda x: x[1])
    return entries


def extract_data(folder, records, field):
    """遍历所有拆分文件，按ASIN提取指定字段。

    Args:
        folder: 文件夹路径
        records: [(asin, group, label), ...]
        field: 要提取的列名

    Returns:
        df_wide: index=年月, columns=ASIN标签, values=字段值
        warnings: 警告信息列表
    """
    entries = scan_files(folder)
    if not entries:
        raise RuntimeError(f"文件夹中未找到 *_销量拆分.xlsx 文件: {folder}")

    asin_set = set(r[0] for r in records)
    asin_to_label = {r[0]: r[2] for r in records}
    warnings = []
    all_data = {}        # {ym: {label: value}}
    found_asins = set()  # 追踪已找到的ASIN

    for filepath, ym in entries:
        try:
            df = pd.read_excel(filepath)
        except Exception as e:
            warnings.append(f"读取失败 {os.path.basename(filepath)}: {e}")
            continue

        if 'ASIN' not in df.columns:
            warnings.append(f"文件无ASIN列: {os.path.basename(filepath)}")
            continue

        if field not in df.columns:
            warnings.append(f"文件无「{field}」列: {os.path.basename(filepath)}")
            continue

        df['ASIN'] = df['ASIN'].astype(str).str.strip()
        mask = df['ASIN'].isin(asin_set)
        matched = df[mask]

        if matched.empty:
            continue

        if ym not in all_data:
            all_data[ym] = {}

        for _, row in matched.iterrows():
            asin = row['ASIN']
            label = asin_to_label.get(asin, asin)
            val = row[field]
            if pd.isna(val):
                val = np.nan
            else:
                found_asins.add(asin)
            all_data[ym][label] = val

    # ---- 缺失ASIN告警 ----
    missing_asins = asin_set - found_asins
    if missing_asins:
        warnings.append(
            f"以下 {len(missing_asins)} 个ASIN在所有文件中均未找到: "
            f"{', '.join(sorted(missing_asins)[:10])}"
            f"{'...' if len(missing_asins) > 10 else ''}"
        )

    # 部分缺失（找到了但有些月份没有数据）
    if not all_data:
        raise RuntimeError("未找到任何匹配数据，请检查ASIN和文件夹")

    df_wide = pd.DataFrame(all_data).T
    df_wide.index.name = '年月'
    df_wide = df_wide.sort_index()

    # 数值化
    for col in df_wide.columns:
        df_wide[col] = pd.to_numeric(df_wide[col], errors='coerce')

    # 检查覆盖度不足的ASIN（少于一半月份有数据）
    n_total = len(entries)
    for col in df_wide.columns:
        n_valid = df_wide[col].notna().sum()
        if n_valid == 0:
            warnings.append(f"ASIN [{col}] 在所有月份均无有效数据")
        elif n_valid < n_total * 0.5:
            warnings.append(
                f"ASIN [{col}] 仅 {n_valid}/{n_total} 个月有数据 (覆盖度不足50%)")

    return df_wide, warnings


# ============================================================
# 输出表格
# ============================================================

def save_table(df, field, records, output_path=None):
    """保存数据表到xlsx，行=ASIN，列=年月。

    records: [(asin, group, label), ...] — label 对应 df 的列名
    """
    if not output_path:
        output_path = f"asin_trend_{field}.xlsx"

    # label → group 映射
    label_to_group = {}
    for asin, grp, lbl in records:
        label_to_group[lbl] = grp if grp else ''

    groups = sorted(set(g for g in label_to_group.values() if g))

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        # ---- 明细数据：行=ASIN, 列=年月 ----
        df_T = df.T
        df_T.index.name = 'ASIN'
        # 加入分组列
        df_T.insert(0, '分组', [label_to_group.get(c, '') for c in df.columns])
        df_T.to_excel(writer, sheet_name='明细数据')

        # ---- 分组均值：行=组, 列=年月 ----
        if groups:
            summary = {}
            for grp in groups:
                grp_cols = [c for c in df.columns if label_to_group.get(c) == grp]
                if grp_cols:
                    summary[grp] = df[grp_cols].mean(axis=1)
            if summary:
                df_summary = pd.DataFrame(summary).T
                df_summary.index.name = '分组'
                df_summary.to_excel(writer, sheet_name='分组均值')

        # ---- 统计信息 ----
        stats = pd.DataFrame({
            'ASIN': df.columns,
            '分组': [label_to_group.get(c, '') for c in df.columns],
            '数据月数': df.notna().sum().values,
            '均值': df.mean().values.round(1),
            '最小值': df.min().values,
            '最大值': df.max().values,
        })
        stats.to_excel(writer, sheet_name='统计信息', index=False)

    print(f"数据表已保存: {output_path}")
    return output_path


# ============================================================
# 图表绘制
# ============================================================

def setup_chinese_font():
    """配置中文字体，返回 FontProperties 对象或 None。"""
    import matplotlib.font_manager as fm

    font_paths = [
        'C:\\Windows\\Fonts\\msyh.ttc',
        'C:\\Windows\\Fonts\\simhei.ttf',
        'C:\\Windows\\Fonts\\simkai.ttf',
    ]
    for fpath in font_paths:
        if os.path.exists(fpath):
            try:
                fm.fontManager.addfont(fpath)
                bold = 'C:\\Windows\\Fonts\\msyhbd.ttc'
                if 'msyh' in fpath and os.path.exists(bold):
                    fm.fontManager.addfont(bold)
                prop = fm.FontProperties(fname=fpath)
                # 同时设置 rcParams 作为保底
                font_name = prop.get_name()
                plt.rcParams['font.family'] = font_name
                plt.rcParams['axes.unicode_minus'] = False
                return prop
            except Exception:
                continue
    return None


def make_chart(df, field, records, output_path=None, show=False, dpi=200):
    """生成专业风格趋势图。缺失数据按0处理。"""
    # NaN → 0（图表用，不修改原始df）
    df = df.fillna(0)

    try:
        import seaborn as sns
        sns.set_style('whitegrid')
        sns.set_context('notebook', font_scale=1.1)
    except ImportError:
        pass

    # 字体设置必须在 seaborn 之后，避免被覆盖
    font_prop = setup_chinese_font()
    print(f"使用字体: {font_prop.get_name() if font_prop else '默认'}")

    # groups: label → group
    label_to_group = {}
    for asin, grp, lbl in records:
        label_to_group[lbl] = grp if grp else ''

    groups = sorted(set(g for g in label_to_group.values() if g))

    color_pool = ['#2563EB', '#DC2626', '#059669', '#7C3AED', '#D97706',
                  '#DB2777', '#0891B2', '#E11D48', '#16A34A', '#8B5CF6']

    months = df.index.tolist()
    n_months = len(months)
    n_asins = len(df.columns)

    # ---- 创建图表 ----
    fig, ax = plt.subplots(figsize=(max(14, n_months * 0.35), 7))

    # 背景 & 网格
    ax.set_facecolor('#FAFBFC')
    ax.grid(True, linestyle='-', alpha=0.35, color='#CBD5E1', linewidth=0.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#CBD5E1')
    ax.spines['bottom'].set_color('#CBD5E1')

    x = list(range(n_months))

    if groups:
        # ---- 分组模式 ----
        n_groups = len(groups)
        for gi, grp in enumerate(groups):
            main_color = color_pool[gi % len(color_pool)]
            grp_cols = [c for c in df.columns if label_to_group.get(c) == grp]
            if not grp_cols:
                continue

            grp_data = df[grp_cols]
            grp_mean = grp_data.mean(axis=1, skipna=True)
            grp_min = grp_data.min(axis=1, skipna=True)
            grp_max = grp_data.max(axis=1, skipna=True)

            # 范围填充带（跳过NaN段）
            valid_mask = grp_mean.notna()
            if valid_mask.any():
                ax.fill_between(x, grp_min.values, grp_max.values,
                                where=valid_mask.values,
                                color=main_color, alpha=0.08, zorder=1)

            # 个体细线
            for col in grp_cols:
                valid = df[col].notna()
                if valid.any():
                    ax.plot([xi for xi, v in zip(x, valid) if v],
                            df[col].values[valid],
                            color=main_color, alpha=0.2, linewidth=0.6, zorder=2)

            # 组均值粗线
            if valid_mask.any():
                ax.plot([xi for xi, v in zip(x, valid_mask) if v],
                        grp_mean.values[valid_mask],
                        color=main_color, linewidth=2.8,
                        marker='o', markersize=6, markeredgecolor='white',
                        markeredgewidth=1.2, zorder=5,
                        label=f'{grp} (n={len(grp_cols)})')

            # 首尾数值标注（取有效值）
            valid_vals = grp_mean.dropna()
            if len(valid_vals) >= 2:
                first_idx = valid_vals.index[0]
                last_idx = valid_vals.index[-1]
                first_val = valid_vals.iloc[0]
                last_val = valid_vals.iloc[-1]
                first_xi = months.index(first_idx)
                last_xi = months.index(last_idx)
                for xi, val, ha in [(first_xi, first_val, 'right'),
                                    (last_xi, last_val, 'left')]:
                    offset = -15 if ha == 'right' else 15
                    ann_kw = dict(xy=(xi, val), xytext=(offset, 8),
                                  textcoords='offset points', ha=ha,
                                  fontsize=8, color=main_color, fontweight='bold',
                                  bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                                            edgecolor=main_color, alpha=0.85, linewidth=0.8))
                    if font_prop:
                        ann_kw['fontproperties'] = font_prop
                    ax.annotate(f'{val:,.0f}', **ann_kw)

        # 图例：3组及以上移到图外
        if n_groups >= 3:
            leg = ax.legend(loc='upper left', frameon=True, fontsize=9,
                            framealpha=0.92, edgecolor='#CBD5E1',
                            borderpad=0.6, handlelength=2.2,
                            bbox_to_anchor=(1.01, 1))
        else:
            leg = ax.legend(loc='upper left', frameon=True, fontsize=10,
                            framealpha=0.92, edgecolor='#CBD5E1',
                            borderpad=0.8, handlelength=2.5)
        if font_prop:
            for txt in leg.get_texts():
                txt.set_fontproperties(font_prop)
    else:
        # ---- 无分组模式 ----
        palette = plt.cm.tab20 if n_asins <= 20 else plt.cm.gist_rainbow
        for i, col in enumerate(df.columns):
            color = palette(i / max(1, n_asins))
            valid = df[col].notna()
            if valid.any():
                ax.plot([xi for xi, v in zip(x, valid) if v],
                        df[col].values[valid],
                        color=color, linewidth=1.5, marker='o',
                        markersize=4, label=col, zorder=3)

        ncol = min(4, max(1, n_asins // 15))
        leg = ax.legend(loc='upper left', frameon=True, fontsize=7.5,
                        framealpha=0.92, edgecolor='#CBD5E1',
                        ncol=ncol, borderpad=0.6, columnspacing=0.8)
        if font_prop:
            for txt in leg.get_texts():
                txt.set_fontproperties(font_prop)

    # ---- X轴 ----
    ax.set_xticks(x)
    step = max(1, n_months // 16)
    shown_labels = [months[i] if i % step == 0 else '' for i in range(n_months)]
    ax.set_xticklabels(shown_labels, rotation=45, ha='right', fontsize=8.5,
                       fontproperties=font_prop)
    ax.set_xlim(-0.6, n_months - 0.4)
    ax.xaxis.set_tick_params(pad=4)

    # ---- Y轴 ----
    def fmt_y(v, _):
        if abs(v) >= 1e6:
            return f'{v/1e6:.1f}M'
        elif abs(v) >= 1e4:
            return f'{v:,.0f}'
        else:
            return f'{v:,.1f}' if abs(v) < 10 else f'{v:,.0f}'
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_y))
    ax.yaxis.set_tick_params(pad=2)

    # ---- 标题 ----
    group_hint = f' — {" vs ".join(groups)}' if groups else ''
    title_kw = dict(fontsize=17, fontweight='bold', pad=18, color='#1E293B')
    xlabel_kw = dict(fontsize=11, labelpad=10, color='#64748B')
    ylabel_kw = dict(fontsize=11, labelpad=10, color='#64748B')
    if font_prop:
        title_kw['fontproperties'] = font_prop
        xlabel_kw['fontproperties'] = font_prop
        ylabel_kw['fontproperties'] = font_prop

    ax.set_title(f'{field} 趋势{group_hint}', **title_kw)
    ax.set_xlabel('年月', **xlabel_kw)
    ax.set_ylabel(field, **ylabel_kw)

    # ---- 微调 ----
    ax.margins(x=0.01)
    y_min, y_max = ax.get_ylim()
    y_pad = (y_max - y_min) * 0.08
    ax.set_ylim(y_min - y_pad, y_max + y_pad)

    plt.tight_layout(pad=1.5)

    if not output_path:
        output_path = f"asin_trend_{field}.png"
    plt.savefig(output_path, dpi=dpi, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    print(f"趋势图已保存: {output_path}")

    if show:
        plt.switch_backend('TkAgg')
        plt.show()

    plt.close()


# ============================================================
# 主入口
# ============================================================

def main():
    args = parse_args()

    # 1. 加载ASIN配置
    records = load_asin_config(args)
    asin_set = set(r[0] for r in records)

    print("=" * 60)
    print("  ASIN 数据提取 & 趋势分析")
    print("=" * 60)
    print(f"  文件夹: {args.folder}")
    print(f"  字段:   {args.field}")
    print(f"  ASIN数: {len(records)}")

    groups = set(r[1] for r in records if r[1])
    if groups:
        print(f"  分组:   {', '.join(groups)}")
        for grp in sorted(groups):
            members = [r[0] for r in records if r[1] == grp]
            print(f"    {grp} ({len(members)}个): {', '.join(members[:5])}{'...' if len(members) > 5 else ''}")

    # 2. 扫描文件并提取数据
    print(f"\n  扫描文件...")
    entries = scan_files(args.folder)
    print(f"  找到 {len(entries)} 个拆分文件 ({entries[0][1] if entries else 'N/A'} ~ {entries[-1][1] if entries else 'N/A'})")

    print(f"\n  提取数据...")
    df, warnings = extract_data(args.folder, records, args.field)

    if warnings:
        print(f"\n  警告 ({len(warnings)}):")
        for w in warnings[:10]:
            print(f"    - {w}")
        if len(warnings) > 10:
            print(f"    ... 共 {len(warnings)} 条")

    print(f"\n  结果: {len(df)} 个月 × {len(df.columns)} 个ASIN")
    if not df.empty:
        print(f"  数据范围: {df.min().min():.0f} ~ {df.max().max():.0f}")
        print(f"  时间跨度: {df.index[0]} ~ {df.index[-1]}")

    # 3. 输出表格
    if not args.no_table:
        output_xlsx = args.output or f"asin_trend_{args.field}.xlsx"
        save_table(df, args.field, records, output_xlsx)
    else:
        print("  已跳过表格生成 (--no-table)")

    # 4. 出图
    if args.no_chart:
        print("  已跳过图表生成 (--no-chart)")
    elif len(df) > 1:
        output_chart = args.chart or f"asin_trend_{args.field}.png"
        make_chart(df, args.field, records,
                   output_path=output_chart, show=args.show, dpi=args.dpi)
    else:
        print("  数据点不足，跳过出图")

    print(f"\n{'=' * 60}")
    print(f"  完成")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
