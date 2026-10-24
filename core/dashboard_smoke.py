"""Opt-in packaged dashboard smoke check, using synthetic data only."""
import json
from pathlib import Path

import pandas as pd
from PyQt6.QtWidgets import QApplication
from core.dashboard_data import normalize, export_report
from core.theme import THEME


def check_dashboard(window, target):
    # The offscreen Qt platform has no system font discovery on Windows.
    from PyQt6.QtGui import QFontDatabase
    for name in ['msyh.ttc', 'msyhbd.ttc', 'segoeui.ttf']:
        QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts') / name))
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    brands = ['Northstar', 'HomeLink', 'VoltWorks', 'DailyPower', 'PlugMate', 'BrightWay']
    for m, period in enumerate(pd.period_range('2024-01', '2026-08', freq='M')):
        for i in range(18):
            units = round((90 + (18 - i) * 15) * (1 + m * .015) * (1.12 if period.month in (7, 11, 12) else 1))
            price = 12 + i * 1.3
            rows.append({'ASIN': f'DEMO{i:06d}', '月份': str(period), '品牌': brands[i % 6],
                         '销量': units, '销售额': round(units * price, 2), '站点': 'US',
                         '币种': 'USD', '品类': '排插', '插位数': str(4 + i % 4 * 2),
                         'USB接口': 'USB-C' if i % 3 == 0 else 'USB-A',
                         '线长': '1.8m' if i % 2 else '3m', '上架时间': '2023-06-01'})
    frame = pd.DataFrame(rows)
    sample = target.parent / '看板演示数据（模拟）.xlsx'
    frame.to_excel(sample, index=False, sheet_name='月度明细')
    index, widget = next((i, w) for i, (info, w) in enumerate(window._modules) if info['name'] == '展示看板')
    widget.set_dataset(normalize(frame, {k: k for k in ['ASIN', '月份', '销量', '销售额']}, source=str(sample)))
    widget.start.setCurrentText('2026-01')
    widget.end.setCurrentText('2026-08')
    widget.brand.setCurrentText('Northstar')
    widget.add_attribute_fields(['插位数', 'USB接口'])
    widget.add_attribute_fields(['线长'])
    assert len(widget.attribute_controls) == 3
    assert widget.currency.isHidden()
    window._switch_module(index)
    window.resize(1360, 1000)
    window.show()
    app = QApplication.instance()
    screenshots = []
    for theme in ['light', 'dark']:
        THEME.set_theme(theme)
        app.setStyleSheet(THEME.qss())
        app.processEvents()
        path = target.parent / f'dashboard-{theme}.png'
        window.grab().save(str(path))
        screenshots.append(str(path))
        widget.trend.grab().save(str(target.parent / f'trend-{theme}.png'))
        from PyQt6.QtCore import QTimer
        def capture_expanded():
            dialog = app.activeModalWidget()
            if dialog is not None:
                dialog.grab().save(str(target.parent / f'trend-expanded-{theme}.png'))
                dialog.accept()
        QTimer.singleShot(100, capture_expanded)
        widget.trend.open_expanded()
        for name, combo in [('month', widget.start), ('brand', widget.brand)]:
            combo.showPopup()
            app.processEvents()
            assert combo.popup.height() <= 380
            combo.popup.grab().save(str(target.parent / f'{name}-{theme}.png'))
            combo.hidePopup()
    widget.attribute_controls['插位数'].showPopup()
    app.processEvents()
    widget.attribute_controls['插位数'].popup.grab().save(str(target.parent / 'attribute-popup.png'))
    widget.attribute_controls['插位数'].hidePopup()
    widget.drill_group('HomeLink')
    assert widget.proxy.rowCount() == 24
    assert 0 < widget.result['kpi']['样本份额'] < 1
    widget.search.setText('DEMO000001')
    assert widget.proxy.rowCount() == 8
    widget.proxy.sort(list(widget.model.frame.columns).index('销售额'))
    export_report(target.parent / '看板导出验证.xlsx', widget.dataset, widget.query(), widget.result, widget.visible_frame())
    widget.send_matrix()
    products = window._modules[window.stack.currentIndex()][1]
    assert len(products.free_matrix.frame) == 1
    assert products.matrix_tabs.currentWidget() is products.free_matrix
    window._switch_module(index)
    THEME.set_theme('light')
    app.setStyleSheet(THEME.qss())
    window.resize(880, 620)
    app.processEvents()
    app.processEvents()
    window.grab().save(str(target.parent / 'dashboard-small.png'))
    target.write_text(json.dumps({'dashboard': 'ok', 'version': window.windowTitle(),
                                 'modules': [info['name'] for info, _ in window._modules],
                                 'rows': len(frame), 'drill_search_export_matrix': 'ok',
                                 'screenshots': screenshots}, ensure_ascii=False, indent=2), encoding='utf-8')
