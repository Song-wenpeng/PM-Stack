"""Research workbook auto-detection, ASIN reconciliation, and sparse history."""
from tests import support
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtCore import QThreadPool

from core.dashboard_data import Query, analyze, product_snapshot
from core.dashboard_import import detect_workbook, load_workbook, consolidate_attributes
from core.dashboard_widgets import ImportDialog
from core.config_manager import ConfigManager
from modules.display_dashboard import ModuleWidget


class DashboardImportTests(unittest.TestCase):
    def setUp(self):
        self.app = support.qt_app()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(support.cleanup_qt_widgets)
        self.path = Path(self.temp.name) / 'research.xlsx'
        self.meta = pd.DataFrame({'ASIN': ['B000000001', 'B000000002', 'B000000002'],
            '品牌': ['Alpha', 'Beta', 'Wrong'], '插孔数': ['3', '6', '9'],
            '线长': ['3 FT', '6 FT', '9 FT'], '打标': [1., 1., None],
            '三级分类': ['桌面', None, None], '分类': ['排插', '排插', '排插'],
            '商品详情页链接': ['https://www.amazon.com/dp/B000000001', 'https://www.amazon.com/dp/B000000002', 'https://www.amazon.com/dp/B000000003']})
        self.units = pd.DataFrame({'ASIN': ['B000000001', 'B000000002'],
                                  '2025-01': [10, None], '2026-01': [20, 30]})
        self.revenue = pd.DataFrame({'ASIN': ['B000000001', 'B000000002'],
                                    '2025-01': [100, None], '2026-01': [200, 600]})
        self.write_book()

    def write_book(self):
        with pd.ExcelWriter(self.path, engine='openpyxl') as writer:
            pd.DataFrame({'ASIN': ['ignored'], '原行号': [2]}).to_excel(writer, sheet_name='字段提取日志', index=False)
            self.meta.to_excel(writer, sheet_name='Product-US-Last-30-days', index=False)
            self.units.to_excel(writer, sheet_name='历史销量', index=False)
            self.revenue.to_excel(writer, sheet_name='历史销额', index=False)

    def test_auto_detect_skips_log_and_requires_no_format_selection(self):
        data, opt = load_workbook(str(self.path))
        self.assertTrue(opt['ready'])
        self.assertEqual(opt['sheet'], 'Product-US-Last-30-days')
        self.assertEqual((opt['site'], opt['currency']), ('US', 'USD'))
        self.assertEqual(opt['mapping']['品类'], '分类')
        self.assertIn('分类', data.frame)
        self.assertIn('三级分类', data.feature_fields)
        self.assertEqual(set(data.frame['打标']), {'1'})
        dialog = ImportDialog(str(self.path))
        self.assertTrue(dialog.mode.isHidden())
        self.assertEqual(dialog.options()['mode'], 1)

    def test_duplicate_url_evidence_prevents_multiplying_history(self):
        data, _ = load_workbook(str(self.path))
        self.assertEqual(len(data.frame), 4)
        self.assertEqual(set(data.frame['品牌']), {'Alpha', 'Beta'})
        self.assertEqual(len(data.issues), 1)
        self.assertIn('一致', data.issues[0]['处理'])
        result = analyze(data, Query('2026-01', '2026-01', 'US', 'USD'))
        self.assertEqual(result['kpi']['销售额'], 800)

    def test_unresolvable_conflict_is_explicit_not_first_or_last_wins(self):
        self.meta.loc[2, '商品详情页链接'] = self.meta.loc[1, '商品详情页链接']
        clean, issues = consolidate_attributes(self.meta, 'ASIN')
        record = clean.set_index('ASIN').loc['B000000002']
        self.assertEqual(record['品牌'], '待核对（属性冲突）')
        self.assertEqual(record['分类'], '排插')
        self.assertIn('冲突字段', issues[0]['处理'])

    def test_sparse_history_has_known_totals_and_coverage(self):
        data, _ = load_workbook(str(self.path))
        q = Query('2025-01', '2025-01', 'US', 'USD')
        r = analyze(data, q)
        self.assertEqual(r['kpi']['销量'], 10)
        self.assertEqual(r['kpi']['销售额'], 100)
        self.assertEqual(r['kpi']['数据覆盖率'], .5)
        self.assertEqual(r['coverage']['known'], 1)
        self.assertTrue(pd.isna(r['ranking'].set_index('分组').loc['Beta', '份额']))
        q.brand = 'Beta'
        self.assertTrue(pd.isna(analyze(data, q)['kpi']['销售额']))
        q.start = q.end = '2026-01'
        r = analyze(data, q)
        self.assertEqual(r['trend'].iloc[0]['所选品牌份额'], .75)
        self.assertTrue(pd.isna(r['kpi']['同比']))

    def test_feature_filter_and_matrix_use_the_same_history(self):
        data, _ = load_workbook(str(self.path))
        q = Query('2025-01', '2026-01', 'US', 'USD', filters={'插孔数': ['6'], '打标': ['1']})
        r = analyze(data, q)
        self.assertEqual(r['kpi']['销售额'], 600)
        snapshot = product_snapshot(r['detail'], data.available_history)
        self.assertEqual(snapshot.iloc[0]['销售额'], 600)
        self.assertEqual(snapshot.iloc[0]['品牌'], 'Beta')

    def test_weighted_price_uses_paired_samples(self):
        self.revenue.loc[1, '2026-01'] = None
        self.write_book()
        data, _ = load_workbook(str(self.path))
        r = analyze(data, Query('2026-01', '2026-01', 'US', 'USD'))
        self.assertEqual(r['kpi']['销量'], 50)
        self.assertEqual(r['kpi']['销售额'], 200)
        self.assertEqual(r['kpi']['加权均价'], 10)
        snapshot = product_snapshot(r['detail'], True).set_index('ASIN')
        self.assertEqual(snapshot.loc['B000000001', '价格($)'], 10)
        self.assertTrue(pd.isna(snapshot.loc['B000000002', '价格($)']))

    def test_ambiguous_sheets_request_adjustment(self):
        with pd.ExcelWriter(self.path, engine='openpyxl', mode='a') as writer:
            self.meta.to_excel(writer, sheet_name='Product-UK-Last-30-days', index=False)
        data, opt = load_workbook(str(self.path))
        self.assertIsNone(data)
        self.assertFalse(opt['ready'])

    def test_async_import_bypasses_dialog_and_keeps_feature_columns(self):
        cfg = ConfigManager(str(Path(self.temp.name) / 'config.json'))
        widget = ModuleWidget(cfg, None)
        with patch('modules.display_dashboard.ImportDialog') as dialog:
            widget.start_load(str(self.path))
            QThreadPool.globalInstance().waitForDone(10000)
            self.app.processEvents()
            dialog.assert_not_called()
        self.assertIsNotNone(widget.dataset)
        self.assertTrue(widget.import_btn.isEnabled())
        self.assertIn('插孔数', list(widget.model.frame.columns)[:15])
        self.assertEqual(len(widget.dataset.issues), 1)


if __name__ == '__main__':
    unittest.main()
