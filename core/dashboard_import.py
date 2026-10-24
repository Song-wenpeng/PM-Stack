"""Detect research workbooks and join history with product features by ASIN."""
import re
from urllib.parse import urlparse

import pandas as pd

from core.dashboard_data import ALIASES, REQUIRED, clean_frame, month_text, normalize, from_history

FEATURES = ['插孔数', '插位数', '线长', '包装数', '颜色', '三级分类', 'USB', '打标',
            '分类', '插孔方向', '线型', '使用场景', '安装方式', '产品类型', '包装尺寸分段']
COUNTRIES = {'US': 'USD', 'UK': 'GBP', 'GB': 'GBP', 'DE': 'EUR', 'FR': 'EUR',
             'IT': 'EUR', 'ES': 'EUR', 'CA': 'CAD', 'JP': 'JPY', 'AU': 'AUD'}


def mapping_for(columns):
    return {key: next((alias for alias in aliases if alias in columns), '') for key, aliases in ALIASES.items()}


def detect_workbook(book):
    """Read headers only. Ambiguous roles require adjustment, never select by row order."""
    headers = {name: [str(c).strip() for c in pd.read_excel(book, sheet_name=name, nrows=0).columns]
               for name in book.sheet_names}
    monthly = {}
    for name, cols in headers.items():
        dates = []
        for col in cols:
            try:
                dates.append(month_text(col))
            except ValueError:
                pass
        if 'ASIN' in cols and dates:
            monthly[name] = dates
    def history_role(names):
        exact = [n for n in monthly if n in names]
        if len(exact) == 1:
            return exact[0]
        return ''
    units = history_role(['历史销量', '子体销量', '销量历史', '月销量'])
    revenue = history_role(['历史销额', '历史销售额', '子体销额', '子体销售额', '销额历史', '月销额'])
    attrs = [n for n, cols in headers.items() if n not in monthly and mapping_for(cols)['ASIN']
             and ('品牌' in cols or any(c in cols for c in FEATURES)) and '日志' not in n]
    product_sheets = [n for n in attrs if re.match(r'Product[-_]', n, re.I)]
    if len(product_sheets) == 1:
        attrs = product_sheets
    long_sheets = [n for n, cols in headers.items() if all(mapping_for(cols)[k] for k in REQUIRED)]
    history = bool(monthly)
    sheet = attrs[0] if len(attrs) == 1 and history else long_sheets[0] if len(long_sheets) == 1 else ''
    cols = headers.get(sheet, [])
    mapping = mapping_for(cols)
    # Preserve the named sub-category separately; the main classification is the overview category.
    mapping['品类'] = next((c for c in ['品类', '产品分类', '分类', '三级分类', '类别'] if c in cols), '')
    match = re.search(r'(?:^|[-_])(US|UK|GB|DE|FR|IT|ES|CA|JP|AU)(?:[-_]|$)', sheet, re.I)
    site = match[1].upper() if match else ''
    currency = COUNTRIES.get(site, '')
    options = {'mode': 1 if history else 0, 'sheet': sheet, 'units': units, 'revenue': revenue,
               'mapping': mapping, 'site': site, 'currency': currency}
    reasons = []
    if not sheet:
        reasons.append('无法唯一确定商品属性表' if history else '无法唯一确定月度明细表')
    if history and (not units or not revenue):
        reasons.append('无法唯一确定历史销量和历史销额表')
    for key, default in [('站点', site), ('币种', currency)]:
        if not mapping[key] and not default:
            reasons.append(f'需要补充{key}')
    options['ready'] = not reasons
    options['reasons'] = reasons
    options['headers'] = headers
    return options


def linked_asin(value):
    text = '' if pd.isna(value) else str(value).strip()
    try:
        url = urlparse(text)
        if not re.fullmatch(r'(?:www\.)?amazon\.[a-z.]+', url.hostname or '', re.I):
            return ''
        match = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?#]|$)', url.path, re.I)
        return match[1].upper() if match else ''
    except ValueError:
        return ''


def consolidate_attributes(meta, asin_column):
    """Keep one product per key; use URL evidence only for an unambiguous duplicate."""
    meta = clean_frame(meta)
    meta[asin_column] = meta[asin_column].fillna('').astype(str).str.strip().str.upper()
    if meta[asin_column].eq('').any():
        raise ValueError('商品属性表有 ASIN 缺失，请补充后再导入。')
    issues, records = [], []
    link_col = next((c for c in ['商品详情页链接', '商品链接', '链接'] if c in meta), '')
    for asin, group in meta.groupby(asin_column, sort=False):
        if len(group) == 1:
            row = group.iloc[0].copy()
            if link_col and linked_asin(row[link_col]) not in ('', asin):
                issues.append({'ASIN': asin, '原表行': str(group.index[0] + 2), '处理': 'ASIN 与商品链接不一致，按 ASIN 列关联历史，请核对'})
            records.append(row)
            continue
        rows = ', '.join(str(i + 2) for i in group.index)
        if link_col:
            linked = group[link_col].map(linked_asin)
            matches = linked.eq(asin)
            if matches.sum() == 1 and linked.ne('').all():
                records.append(group.loc[matches].iloc[0].copy())
                chosen = group.index[matches][0] + 2
                issues.append({'ASIN': asin, '原表行': rows, '处理': f'重复 ASIN：采用商品链接与 ASIN 一致的第 {chosen} 行，其他行不重复关联历史'})
                continue
        # Complementary values can merge. Genuine conflicts remain visible as unknown attributes.
        record = group.iloc[0].copy()
        conflicts = []
        for col in group:
            values = group[col].dropna()
            values = values[values.astype(str).str.strip().ne('')]
            normalized = values.astype(str).str.strip()
            if normalized.nunique() > 1:
                record[col] = '待核对（属性冲突）'
                conflicts.append(col)
            elif len(values):
                record[col] = values.iloc[0]
        records.append(record)
        issues.append({'ASIN': asin, '原表行': rows, '处理': '重复 ASIN 合并为一条；' + ('冲突字段标记待核对：' + '、'.join(conflicts) if conflicts else '一致或互补属性已合并')})
    return pd.DataFrame(records).reset_index(drop=True), issues


def load_workbook(path, options=None):
    with pd.ExcelFile(path) as book:
        detected = detect_workbook(book) if options is None else options
        if options is None and not detected['ready']:
            return None, detected
        opt = detected
        data = pd.read_excel(book, sheet_name=opt['sheet'])
        args = (opt['mapping'], opt['site'], opt['currency'], path)
        if opt['mode']:
            data, issues = consolidate_attributes(data, opt['mapping']['ASIN'])
            result = from_history(data, pd.read_excel(book, sheet_name=opt['units']),
                                  pd.read_excel(book, sheet_name=opt['revenue']), *args)
            result.available_history = True
            result.issues = issues
            result.notes = [note.replace('相关汇总显示不可用，不按 0 处理', '按已知记录汇总，并显示覆盖率；空白不补零') for note in result.notes]
            result.notes.insert(0, f'按 ASIN 关联：{opt["sheet"]} + {opt["units"]} + {opt["revenue"]}。属性为主表当前快照。')
            if issues:
                result.notes.insert(1, f'发现 {len(issues)} 项属性关联问题，可在“数据说明”查看处理明细。')
        else:
            result = normalize(data, *args)
        result.import_options = {k: v for k, v in opt.items() if k not in ('headers', 'reasons', 'ready')}
        result.feature_fields = [c for c in FEATURES if c in result.frame]
        return result, detected
