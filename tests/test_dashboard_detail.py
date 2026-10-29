"""Clipboard, product links and selection scope in dashboard detail rows."""
from tests import support
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from PyQt6.QtCore import Qt, QItemSelectionModel
from PyQt6.QtTest import QTest
from PyQt6.QtGui import QContextMenuEvent

from core.config_manager import ConfigManager
from modules.display_dashboard import ModuleWidget
from tests.test_dashboard import dataset, fixture


class DashboardDetailTests(unittest.TestCase):
    def setUp(self):
        self.app = support.qt_app()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(support.cleanup_qt_widgets)
        self.widget = ModuleWidget(ConfigManager(str(Path(self.temp.name) / 'config.json')), None)
        frame = fixture().replace({'ASIN': {'A1': 'B0000510Z9', 'B1': 'B000000002'}})
        frame['备注'] = '第一行\n第二行\t带制表符'
        self.widget.set_dataset(dataset(frame))
        self.widget.start.setCurrentText('2026-01')
        self.widget.resize(1100, 800)
        self.widget.tabs.setCurrentIndex(1)
        self.widget.show()
        self.app.processEvents()

    def index(self, row, column):
        return self.widget.proxy.index(row, list(self.widget.model.frame).index(column))

    def test_copy_cells_after_sort_preserves_grid_and_matrix_selection(self):
        self.widget.proxy.sort(self.index(0, '销售额').column(), Qt.SortOrder.DescendingOrder)
        table = self.widget.table
        table.setCurrentIndex(self.index(0, '品牌'))
        selected = table.selectionModel()
        selected.select(self.index(0, '销量'), QItemSelectionModel.SelectionFlag.Select)
        table.setFocus()
        QTest.keyClick(table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.app.clipboard().text(), 'B\t60')
        self.assertEqual(self.widget.visible_frame(selected=True)['ASIN'].tolist(), ['B000000002'])
        table.copy_cell(self.index(0, '备注'))
        self.assertEqual(self.app.clipboard().text(), '第一行\n第二行\t带制表符')
        table.copy_selection(whole_rows=True)
        rows = list(csv.reader(io.StringIO(self.app.clipboard().text()), delimiter='\t'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][self.index(0, '备注').column()], '第一行\n第二行\t带制表符')

    def test_click_asin_uses_filtered_sorted_row_and_current_market(self):
        self.widget.search.setText('B000000002')
        table = self.widget.table
        index = self.index(0, 'ASIN')
        with patch('core.dashboard_widgets.QDesktopServices.openUrl', return_value=True) as opened:
            QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=table.visualRect(index).center())
            self.assertEqual(opened.call_args[0][0].toString(), 'https://www.amazon.com/dp/B000000002')
            opened.reset_mock()
            QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.ControlModifier, table.visualRect(index).center())
            self.assertFalse(opened.called)
            QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton,
                            pos=table.visualRect(self.index(0, '品牌')).center())
            self.assertFalse(opened.called)
        frame = fixture().assign(ASIN=lambda f: f['ASIN'].map({'A1': 'B0000510Z9', 'B1': 'B000000002'}), 站点='UK', 币种='GBP')
        self.widget.search.clear()
        self.widget.set_dataset(dataset(frame))
        index = self.index(0, 'ASIN')
        with patch('core.dashboard_widgets.QDesktopServices.openUrl', return_value=True) as opened:
            QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=table.visualRect(index).center())
            self.assertTrue(opened.call_args[0][0].toString().startswith('https://www.amazon.co.uk/dp/'))

    def test_right_click_copies_the_cell_under_pointer(self):
        table = self.widget.table
        index = self.index(1, '品牌')
        point = table.visualRect(index).center()
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, table.viewport().mapToGlobal(point))
        def choose_copy(menu, *args):
            menu.actions()[0].trigger()
        with patch('core.dashboard_widgets.QMenu.exec', new=choose_copy):
            self.app.sendEvent(table.viewport(), event)
        self.assertEqual(self.app.clipboard().text(), 'B')

    def test_unsupported_market_or_invalid_asin_does_not_open(self):
        for asin, site in [('bad/id', 'US'), ('B0000510Z9', 'UNKNOWN')]:
            with self.subTest(asin=asin, site=site):
                self.widget.set_dataset(dataset(fixture().assign(ASIN=asin, 站点=site).drop_duplicates(['ASIN', '月份'])))
                table = self.widget.table
                index = self.index(0, 'ASIN')
                with patch('core.dashboard_widgets.QDesktopServices.openUrl') as opened:
                    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=table.visualRect(index).center())
                    self.assertFalse(opened.called)


if __name__ == '__main__':
    unittest.main()
