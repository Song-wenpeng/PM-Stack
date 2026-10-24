"""Opt-in local verification of an actual research workbook; never modifies input."""
import hashlib
import json
import time
from pathlib import Path

import pandas as pd
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QApplication

from core.dashboard_data import Query, analyze
from core.theme import THEME


def verify_research(window, source, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    before = hashlib.sha256(Path(source).read_bytes()).hexdigest()
    for name in ['msyh.ttc', 'msyhbd.ttc', 'segoeui.ttf']:
        QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts') / name))
    index, widget = next((i, w) for i, (info, w) in enumerate(window._modules) if info['name'] == '展示看板')
    app = QApplication.instance()
    started = time.perf_counter()
    widget.start_load(source)
    while widget.dataset is None and time.perf_counter() - started < 90:
        app.processEvents()
        time.sleep(.02)
    if widget.dataset is None:
        raise RuntimeError('工作簿自动导入未完成')
    elapsed = time.perf_counter() - started
    data = widget.dataset
    opt = data.import_options
    latest = max(data.frame['月份'])
    with pd.ExcelFile(source) as book:
        units = pd.read_excel(book, sheet_name=opt['units'])
        revenue = pd.read_excel(book, sheet_name=opt['revenue'])
        meta = pd.read_excel(book, sheet_name=opt['sheet'])
    q = Query(latest, latest, opt['site'], opt['currency'])
    result = analyze(data, q)
    expected_units = pd.to_numeric(units[latest], errors='raise').sum(min_count=1)
    expected_revenue = pd.to_numeric(revenue[latest], errors='raise').sum(min_count=1)
    assert abs(result['kpi']['销量'] - expected_units) < .001
    assert abs(result['kpi']['销售额'] - expected_revenue) < .01
    assert result['coverage']['known'] == int(revenue[latest].notna().sum())
    assert not data.frame.duplicated(['站点', '币种', 'ASIN', '月份']).any()
    # Independently filter the real source's feature columns and sum its historical columns.
    selected = set(meta.loc[(pd.to_numeric(meta['打标'], errors='coerce') == 1) &
                            (pd.to_numeric(meta['插孔数'], errors='coerce') == 3), 'ASIN'])
    q.filters = {'打标': ['1'], '插孔数': ['3']}
    filtered = analyze(data, q)
    expected_filtered = revenue.loc[revenue['ASIN'].isin(selected), latest].sum(min_count=1)
    assert abs(filtered['kpi']['销售额'] - expected_filtered) < .01
    assert set(filtered['market']['ASIN']) == selected
    window._switch_module(index)
    window.resize(1360, 1000)
    window.show()
    changed = time.perf_counter()
    widget.start.setCurrentText('2026-01')
    app.processEvents()
    month_seconds = time.perf_counter() - changed
    changed = time.perf_counter()
    widget.brand.setCurrentText('CCCEI')
    app.processEvents()
    brand_seconds = time.perf_counter() - changed
    widget.brand.setCurrentIndex(0)
    widget.add_attribute_fields(['插孔数', '线长', '包装数', '三级分类'])
    for theme in ['light', 'dark']:
        THEME.set_theme(theme)
        app.setStyleSheet(THEME.qss())
        app.processEvents()
        window.grab().save(str(target.parent / f'research-{theme}.png'))
        for name, combo in [('month', widget.start), ('brand', widget.brand)]:
            combo.showPopup()
            app.processEvents()
            assert combo.popup.height() <= 380
            combo.popup.grab().save(str(target.parent / f'{name}-{theme}.png'))
            combo.hidePopup()
    widget.filters = q.filters
    widget.start.setCurrentText(latest)
    widget.refresh()
    widget.tabs.setCurrentIndex(1)
    THEME.set_theme('light')
    app.setStyleSheet(THEME.qss())
    window.resize(1000, 760)
    app.processEvents()
    window.grab().save(str(target.parent / 'research-features.png'))
    widget.table.selectRow(0)
    # Check workbook transfer without depending on Amazon image networking.
    from unittest.mock import patch
    from core.matrix_workspace import MatrixWorkspace
    with patch.object(MatrixWorkspace, 'attach_image', return_value=None):
        widget.send_matrix()
    products = window._modules[window.stack.currentIndex()][1]
    assert products.free_matrix.frame['ASIN'].nunique() == 1
    after = hashlib.sha256(Path(source).read_bytes()).hexdigest()
    assert before == after
    target.write_text(json.dumps({'status': 'ok', 'version': window.windowTitle(),
        'import_seconds': round(elapsed, 2), 'month_change_seconds': round(month_seconds, 3), 'brand_change_seconds': round(brand_seconds, 3), 'products': data.frame['ASIN'].nunique(),
        'monthly_records': len(data.frame), 'latest_month': latest,
        'latest_units': float(expected_units), 'latest_revenue': float(expected_revenue),
        'coverage': result['coverage'], 'feature_filter_products': len(selected),
        'feature_filter_revenue': float(expected_filtered), 'issues': data.issues,
        'source_unchanged_sha256': before, 'matrix': 'ok'}, ensure_ascii=False, indent=2), encoding='utf-8')
