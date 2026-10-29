"""Workbook adapters and auditable sample-market calculations for the dashboard."""
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
import re
import os
import uuid

import numpy as np
import pandas as pd

KEYS = ['站点', '币种', 'ASIN', '月份']
METRICS = ['销量', '销售额']
REQUIRED = ['ASIN', '月份', '销量', '销售额']
ALIASES = {
    'ASIN': ['ASIN', 'asin', '子ASIN', '子体ASIN'],
    '月份': ['月份', '月度', '日期', 'month'],
    '销量': ['销量', '月销量', '月销量更新_矫正后'],
    '销售额': ['销售额', '销额', '月销售额', '月销售额更新_矫正后'],
    '品牌': ['品牌', 'Brand', 'brand'],
    '站点': ['站点', '国家', '市场'],
    '币种': ['币种', '货币', 'currency'],
    '品类': ['品类', '三级分类细分', '三级分类', '产品分类', '类别'],
}


def month_text(value):
    if pd.isna(value):
        raise ValueError('月份不可为空。')
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return str(pd.Period(value, freq='M'))
    text = str(value).strip()
    if re.fullmatch(r'\d{6}', text):
        text = text[:4] + '-' + text[4:]
    match = re.fullmatch(r'(\d{4})[-/.年](\d{1,2})(?:月|[-/.]\d{1,2}(?: .*)?)?', text)
    if not match or not 1 <= int(match[2]) <= 12:
        raise ValueError(f'无法识别月份「{text}」，请使用 YYYY-MM 或 Excel 日期。')
    return f'{match[1]}-{int(match[2]):02d}'


def clean_frame(frame):
    frame = frame.copy().dropna(how='all')
    frame.columns = [str(c).strip() for c in frame.columns]
    if len(set(frame.columns)) != len(frame.columns):
        raise ValueError('表头去除空格后存在重复列，请先修正。')
    return frame


@dataclass
class Dataset:
    frame: pd.DataFrame
    source: str = ''
    notes: list = field(default_factory=list)
    available_history: bool = False
    issues: list = field(default_factory=list)
    feature_fields: list = field(default_factory=list)
    import_options: dict = field(default_factory=dict)


def attribute_text(value):
    if pd.isna(value):
        return '未指定'
    if isinstance(value, (float, np.floating)) and np.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value).strip() or '未指定'


def normalize(frame, mapping, site='', currency='', source=''):
    frame = clean_frame(frame)
    for key in REQUIRED:
        if not mapping.get(key) or mapping[key] not in frame:
            raise ValueError(f'请映射「{key}」字段。')
    selected = [v for v in mapping.values() if v]
    if len(selected) != len(set(selected)):
        raise ValueError('不同标准字段不可映射到同一列。')
    renames = {v: k for k, v in mapping.items() if v}
    for original, target in renames.items():
        if original != target and target in frame and target not in renames:
            raise ValueError(f'原表已有「{target}」列，请选择该列或先重命名，避免字段冲突。')
    data = frame.rename(columns=renames)
    for original, target in renames.items():
        if original != target and original not in data:
            data[original] = frame[original]
    for key, default in [('站点', site), ('币种', currency), ('品牌', '未知品牌'), ('品类', '未分类')]:
        if key not in data:
            data[key] = default.strip() or '未指定'
        data[key] = data[key].fillna('').astype(str).str.strip().replace('', default.strip() or '未指定')
    data['币种'] = data['币种'].str.upper()
    data['站点'] = data['站点'].str.upper()
    data['ASIN'] = data['ASIN'].fillna('').astype(str).str.strip().str.upper()
    if data.empty or data['ASIN'].eq('').any():
        raise ValueError('数据为空或有 ASIN 缺失，请修正后导入。')
    data['月份'] = data['月份'].map(month_text)
    notes = []
    for metric in METRICS:
        raw = data[metric].replace(r'^\s*$', np.nan, regex=True)
        numeric = pd.to_numeric(raw.astype(str).str.replace(',', '', regex=False), errors='coerce')
        invalid = raw.notna() & (numeric.isna() | ~np.isfinite(numeric))
        if invalid.any() or numeric.lt(0).any():
            raise ValueError(f'「{metric}」存在非数字、负数或无穷值，请先清洗；空白可保留为缺失。')
        data[metric] = numeric
        if numeric.isna().any():
            notes.append(f'{metric}缺失 {numeric.isna().sum()} 条；相关汇总显示不可用，不按 0 处理。')
    before = len(data)
    data = data.drop_duplicates()
    if before != len(data):
        notes.append(f'已去除 {before - len(data)} 条完全相同的重复记录。')
    if data.duplicated(KEYS, keep=False).any():
        raise ValueError('同一站点、币种、ASIN、月份有冲突记录。请统一父/子体及修正口径后导入，不自动相加。')
    data['均价'] = data['销售额'].div(data['销量'].where(data['销量'].gt(0)))
    for col in data.columns:
        if col not in METRICS + ['均价', '月份']:
            data[col] = data[col].map(attribute_text)
    notes.append('仅统计导入样本；父/子 ASIN 不自动合并，请勿混入重叠统计。')
    return Dataset(data.reset_index(drop=True), source, notes)


def from_history(meta, units, revenue, mapping, site='', currency='', source=''):
    """Join existing ASIN × month sheets without summing duplicate identifiers."""
    meta, units, revenue = map(clean_frame, (meta, units, revenue))
    asin_col = mapping.get('ASIN')
    if not asin_col or asin_col not in meta:
        raise ValueError('请映射属性表中的 ASIN。')
    meta = meta.rename(columns={asin_col: 'ASIN'})
    for frame in (meta, units, revenue):
        if 'ASIN' not in frame:
            raise ValueError('历史销量/销额表必须包含名为 ASIN 的列。')
        frame['ASIN'] = frame['ASIN'].fillna('').astype(str).str.strip().str.upper()
        if frame['ASIN'].eq('').any() or frame['ASIN'].duplicated().any():
            raise ValueError('历史表模式要求每张表的 ASIN 唯一且不为空；多站点请使用月度明细模式。')
    def melt(frame, metric):
        cols = {}
        for col in frame.columns:
            if col == 'ASIN':
                continue
            try:
                cols[col] = month_text(col)
            except ValueError:
                continue
        if not cols or len(set(cols.values())) != len(cols):
            raise ValueError('历史表缺少月份列或月份重复；请使用 YYYY-MM 表头。')
        return frame[['ASIN', *cols]].rename(columns=cols).melt('ASIN', var_name='月份', value_name=metric)
    long = melt(units, '销量').merge(melt(revenue, '销售额'), on=['ASIN', '月份'], how='outer', validate='one_to_one')
    missing = set(long['ASIN']) - set(meta['ASIN'])
    if missing:
        raise ValueError(f'有 {len(missing)} 个历史 ASIN 缺少属性资料，例如 {sorted(missing)[0]}。')
    # Historical metrics replace current snapshot metrics, avoiding ambiguous names.
    meta = meta.drop(columns=['月份', *METRICS, '均价'], errors='ignore')
    data = long.merge(meta, on='ASIN', how='left', validate='many_to_one')
    mapping = {k: v for k, v in mapping.items() if k not in REQUIRED and v}
    mapping.update({k: k for k in REQUIRED})
    return normalize(data, mapping, site, currency, source)


def total(series):
    return float(series.sum()) if len(series) and series.notna().all() else float('nan')


def available_total(series):
    return float(series.sum(min_count=1))


def ratio(a, b):
    return a / b if pd.notna(a) and pd.notna(b) and b > 0 else float('nan')


@dataclass
class Query:
    start: str
    end: str
    site: str
    currency: str
    filters: dict = field(default_factory=dict)
    brand: str = ''
    group: str = '品牌'
    metric: str = '销售额'
    top: int = 10
    price_min: float | None = None
    price_max: float | None = None


def grouped_total(frame, keys, metric, known_only):
    group = frame.groupby(keys, dropna=False)[metric]
    sums = group.sum(min_count=1)
    return sums if known_only else sums.where(group.count().eq(group.size()))


def analyze(dataset, query):
    data = dataset.frame
    aggregate = available_total if dataset.available_history else total
    if query.start > query.end:
        raise ValueError('开始月份不能晚于结束月份。')
    if query.price_min is not None and query.price_max is not None and query.price_min > query.price_max:
        raise ValueError('最低均价不能高于最高均价。')
    if query.group not in data or query.metric not in METRICS:
        raise ValueError('请选择有效的分组与统计指标。')
    mask = (data['站点'] == query.site) & (data['币种'] == query.currency)
    available = set(data.loc[mask, '月份'])
    for col, values in query.filters.items():
        if col in ('品牌', '月份', '站点', '币种', *METRICS, '均价') or col not in data:
            raise ValueError(f'不支持的市场筛选字段：{col}')
        if values:
            mask &= data[col].isin(values)
    if query.price_min is not None:
        mask &= data['均价'] >= query.price_min
    if query.price_max is not None:
        mask &= data['均价'] <= query.price_max
    base = data.loc[mask]
    periods = pd.period_range(query.start, query.end, freq='M')
    months = [str(p) for p in periods]
    market = base[base['月份'].isin(months)]
    detail = market[market['品牌'] == query.brand] if query.brand else market
    market_total = aggregate(market[query.metric])
    grouped = grouped_total(market, query.group, query.metric, dataset.available_history).sort_values(ascending=False)
    ranking = grouped.rename_axis('分组').reset_index(name='数值')
    ranking['份额'] = ranking['数值'].map(lambda x: ratio(x, market_total))
    top = ranking.head(query.top).copy()
    others_label = '其余分组合计'
    while others_label in set(ranking['分组']):
        others_label += '（汇总）'
    if len(ranking) > query.top:
        rest = ranking.iloc[query.top:]
        value = aggregate(rest['数值'])
        top = pd.concat([top, pd.DataFrame([{'分组': others_label, '数值': value, '份额': ratio(value, market_total)}])], ignore_index=True)
    trend = pd.DataFrame(index=months)
    trend.index.name = '月份'
    trend['市场数值'] = grouped_total(market, '月份', query.metric, dataset.available_history).reindex(months)
    trend['所选品牌数值'] = grouped_total(detail, '月份', query.metric, dataset.available_history).reindex(months)
    trend['所选品牌份额'] = [ratio(a, b) for a, b in zip(trend['所选品牌数值'], trend['市场数值'])]
    shares = grouped_total(market, ['月份', query.group], query.metric, dataset.available_history).unstack(query.group).reindex(months)
    shares = shares.div(trend['市场数值'].where(trend['市场数值'] > 0), axis=0)
    units, revenue = aggregate(detail['销量']), aggregate(detail['销售额'])
    paired = detail[detail['销量'].notna() & detail['销售额'].notna()]
    mean_price = ratio(aggregate(paired['销售额']), aggregate(paired['销量'])) if dataset.available_history else ratio(revenue, units)
    trend['有效记录数'] = market.groupby('月份')[query.metric].count().reindex(months, fill_value=0)
    trend['样本记录数'] = market.groupby('月份').size().reindex(months, fill_value=0)
    trend['数据覆盖率'] = trend['有效记录数'].div(trend['样本记录数'].where(trend['样本记录数'] > 0))
    def growth(offset):
        previous = [str(p + offset) for p in periods]
        if not set(months + previous).issubset(available):
            return float('nan')
        prior = base[base['月份'].isin(previous)]
        if query.brand:
            prior = prior[prior['品牌'] == query.brand]
        current = aggregate(detail[query.metric])
        # Missing group/month is unknown, never silently zero-fill.
        if set(detail['月份']) != set(months) or set(prior['月份']) != set(previous):
            return float('nan')
        if dataset.available_history:
            if detail.groupby('月份')[query.metric].count().eq(0).any() or prior.groupby('月份')[query.metric].count().eq(0).any():
                return float('nan')
        old = aggregate(prior[query.metric])
        return ratio(current - old, old)
    return {'market': market, 'detail': detail, 'ranking': ranking, 'top': top,
            'trend': trend.reset_index(), 'shares': shares.reset_index(),
            'kpi': {'销量': units, '销售额': revenue, '加权均价': mean_price,
                    '活跃ASIN': detail.loc[detail['销量'] > 0, 'ASIN'].nunique(),
                    '总ASIN': detail['ASIN'].nunique(),
                    '同比': growth(-12), '上期比': growth(-len(periods)),
                    '数据覆盖率': ratio(int(detail[query.metric].notna().sum()), len(detail))},
            'missing_months': sorted(set(months) - available), 'others_label': others_label,
            'coverage': {'known': int(market[query.metric].notna().sum()), 'total': len(market),
                         'known_asins': market.loc[market[query.metric].notna(), 'ASIN'].nunique()},
            'available_history': dataset.available_history}


def product_snapshot(detail, available_history=False):
    if detail.empty:
        return detail.copy()
    latest = detail.sort_values('月份').drop_duplicates(['站点', '币种', 'ASIN'], keep='last')
    attrs = latest.drop(columns=['月份', *METRICS, '均价'])
    sums = detail.groupby(['站点', '币种', 'ASIN'], as_index=False)[METRICS].agg(available_total if available_history else total)
    result = attrs.merge(sums, on=['站点', '币种', 'ASIN'], validate='one_to_one')
    mean_price = result['销售额'].div(result['销量'].where(result['销量'] > 0))
    if available_history:
        paired = detail[detail['销量'].notna() & detail['销售额'].notna()]
        paired_sums = paired.groupby(['站点', '币种', 'ASIN'], as_index=False)[METRICS].agg(available_total)
        paired_sums['期间加权均价'] = paired_sums['销售额'].div(paired_sums['销量'].where(paired_sums['销量'] > 0))
        aligned = result[['站点', '币种', 'ASIN']].merge(paired_sums[['站点', '币种', 'ASIN', '期间加权均价']], on=['站点', '币种', 'ASIN'], how='left')
        mean_price = aligned['期间加权均价']
    result['价格($)' if set(result['币种']) == {'USD'} else '期间加权均价'] = mean_price
    return result


def export_report(path, dataset, query, result, visible_detail=None, detail_context=None):
    """Atomic export; untrusted cell strings are never interpreted as formulas/URLs."""
    path = Path(path)
    temp = path.with_name(f'.{path.stem}-{uuid.uuid4().hex}.xlsx')
    params = {'来源': dataset.source, '口径': '导入样本份额；品牌选择不改变市场分母',
              **query.__dict__, '缺失月份': ', '.join(result['missing_months']),
              '说明': '；'.join(dataset.notes), '上期比': '与紧邻的前一个等长时间段比较；同比与去年相同月份比较',
              '缺失处理': ('历史表按已知记录汇总，空白不补零；份额为已知样本份额，同比/上期比会受覆盖变化影响' if dataset.available_history else '缺失不按零；涉及缺失的汇总不计算'),
              '数据覆盖': str(result.get('coverage', {})), '属性关联问题': str(dataset.issues),
              '均价口径': '仅使用销量与销额均有记录的配对样本计算销售额/销量',
              **(detail_context or {})}
    try:
        with pd.ExcelWriter(temp, engine='xlsxwriter', engine_kwargs={'options': {'strings_to_formulas': False, 'strings_to_urls': False}}) as writer:
            overview = writer.book.add_worksheet('看板图表')
            overview.set_column(0, 9, 15)
            overview.write_string(0, 0, '市场分析看板 · 导入样本')
            overview.write_string(1, 0, f'{query.site} / {query.currency} · {query.start} 至 {query.end} · {query.brand or "全部品牌"}')
            overview.write_string(2, 0, '品牌选择不改变市场分母；空白表示数据不足。明细可另受搜索或图表定位影响。')
            for i, (label, value) in enumerate(result['kpi'].items()):
                overview.write_string(4, i, label)
                if pd.notna(value):
                    fmt = writer.book.add_format({'num_format': ('#,##0' if label in ('总ASIN', '活跃ASIN')
                        else '0.0%' if label in ('同比', '上期比', '数据覆盖率') else '#,##0.00')})
                    overview.write_number(5, i, value, fmt)
            for name, frame in [('商品月度明细', visible_detail if visible_detail is not None else result['detail']),
                                ('品牌或属性排名', result['ranking']), ('市场趋势', result['trend']),
                                ('月度份额', result['shares']), ('指标', pd.DataFrame([result['kpi']])),
                                ('统计口径', pd.DataFrame([(k, str(v)) for k, v in params.items()], columns=['项目', '内容']))]:
                frame.to_excel(writer, sheet_name=name, index=False)
                sheet = writer.sheets[name]
                sheet.freeze_panes(1, 0)
                sheet.autofilter(0, 0, len(frame), max(0, len(frame.columns) - 1))
                sheet.set_column(0, len(frame.columns) - 1, 19)
            n = min(query.top, len(result['ranking']))
            if n:
                chart = writer.book.add_chart({'type': 'bar'})
                chart.add_series({'name': '样本份额', 'categories': ['品牌或属性排名', 1, 0, n, 0],
                                  'values': ['品牌或属性排名', 1, 2, n, 2],
                                  'fill': {'color': '#4D6BFE'}, 'data_labels': {'value': True, 'num_format': '0.0%'}})
                chart.set_title({'name': f'{query.group}样本份额 · Top {query.top}'})
                chart.set_x_axis({'num_format': '0%'})
                chart.set_y_axis({'reverse': True})
                chart.set_legend({'none': True})
                chart.set_size({'width': 900, 'height': max(320, n * 24)})
                overview.insert_chart('A8', chart)
            count = len(result['trend'])
            if count:
                chart = writer.book.add_chart({'type': 'line'})
                for column, name in [(1, '市场样本')] + ([(2, query.brand)] if query.brand else []):
                    chart.add_series({'name': name, 'categories': ['市场趋势', 1, 0, count, 0],
                                      'values': ['市场趋势', 1, column, count, column]})
                chart.set_title({'name': f'{query.metric}趋势 · {query.currency if query.metric == "销售额" else "件"}'})
                chart.set_size({'width': 900, 'height': 360})
                chart.show_blanks_as('gap')
                overview.insert_chart(10 + max(320, n * 24) // 20, 0, chart)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
