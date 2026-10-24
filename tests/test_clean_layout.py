"""Keep primary actions reachable while forms and configuration panels scroll."""
from tests import support

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QTabWidget, QPushButton, QLabel

from core.config_manager import ConfigManager
from core.main_window import MainWindow


class CleanLayoutTests(unittest.TestCase):
    def setUp(self):
        self.app = support.qt_app()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(support.cleanup_qt_widgets)
        self.config = ConfigManager(str(Path(self.temp.name) / 'config.json'))
        self.config.update({'auto_check_app_update': False, 'auto_check_update': False,
                            'nav_expanded': False})
        with patch('core.main_window.ConfigManager', return_value=self.config):
            self.window = MainWindow()
        self.window.resize(1080, 700)
        self.window.show()
        self.app.processEvents()

    def module(self, name):
        index, widget = next((i, w) for i, (info, w) in
                             enumerate(self.window._modules) if info['name'] == name)
        self.window._switch_module(index)
        self.app.processEvents()
        return widget

    def assert_in_window(self, control):
        self.app.processEvents()
        self.assertTrue(control.isVisible())
        bounds = self.window.centralWidget()
        self.assertTrue(bounds.rect().contains(control.mapTo(bounds, QPoint(0, 0))))
        self.assertTrue(bounds.rect().contains(control.mapTo(
            bounds, control.rect().bottomRight())))

    def test_review_action_stays_visible_with_many_files_and_more_options(self):
        reviews = self.module('评论分析')
        self.assertFalse(reviews.start_btn.isEnabled())
        reviews.inputs = [{'path': str(Path(self.temp.name) / f'reviews-{i}.xlsx'),
                           'sheets': [{'name': '评论', 'count': 100}],
                           'selected': ['评论'], 'product': 'general'} for i in range(20)]
        reviews._render_inputs()
        reviews.more_options.show()
        self.app.processEvents()
        self.assertIn('2000', reviews.scope_hint.text())
        self.assertTrue(reviews.start_btn.isEnabled())
        self.assert_in_window(reviews.start_btn)
        reviews.inputs.clear()
        reviews._render_inputs()
        self.assertFalse(reviews.start_btn.isEnabled())

    def test_clean_tasks_keep_inputs_and_have_one_reachable_action(self):
        sales = self.module('销量数据')
        sales.split_input.setText('first.xlsx')
        self.assertTrue(sales.run_btn1.isEnabled())
        for i in (1, 0):
            sales.clean_tasks.button(i).click()
            self.app.processEvents()
            self.assertEqual(sum(b.isVisible() for b in sales.clean_run_buttons), 1)
            self.assert_in_window(sales.clean_run_buttons[i])
        self.assertEqual(sales.split_input.text(), 'first.xlsx')
        sales.log1.append('[提示] 请选择正确的文件')
        self.assertTrue(sales.clean_log_toggle.isChecked())
        self.assert_in_window(sales.run_btn1)

    def test_top_navigation_and_workspaces_survive_switching(self):
        # A legacy collapsed-sidebar preference must not hide the new navigation.
        self.window.resize(880, 620)
        self.app.processEvents()
        self.assertIsNone(self.window.findChild(QLabel, 'NavBrand'))
        buttons = self.window._nav_buttons
        self.assertEqual([b.text() for b in buttons], ['评论分析', '销量数据', '产品矩阵', '市场规划', '展示看板'])
        self.assertEqual(len({b.mapTo(self.window, QPoint()).y() for b in buttons}), 1)
        self.assertEqual(self.window.stack.width(), self.window.centralWidget().width())
        for i, button in enumerate(buttons):
            self.assert_in_window(button)
            button.click()
            self.assertEqual(self.window.stack.currentIndex(), i)
            self.assertEqual(sum(b.isChecked() for b in buttons), 1)
            self.assertEqual(self.window.page_title.text(), button.text())
        self.assert_in_window(self.window._theme_btn)
        self.assert_in_window(self.window._settings_btn)
        self.window.activateWindow()
        QTest.keyClick(self.window, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertEqual(self.window.stack.currentIndex(), 0)
        self.window._theme_btn.click()
        self.assertEqual(ConfigManager(self.config.get_path()).get('theme'), 'dark')
        self.assertEqual(self.window.stack.currentIndex(), 0)
        self.window._theme_btn.click()
        products = self.module('产品矩阵')
        tabs = products.findChild(QTabWidget)
        tabs.setCurrentWidget(products.free_matrix)
        products.free_matrix.config_toggle.click()
        self.app.processEvents()
        self.assertFalse(products.free_matrix.config_scroll.isVisible())
        self.module('市场规划')
        self.module('产品矩阵')
        self.assertFalse(products.free_matrix.config_scroll.isVisible())
        export = next(button for button in products.free_matrix.findChildren(QPushButton)
            if button.text() == '导出当前矩阵 Excel')
        self.assert_in_window(export)


if __name__ == '__main__':
    unittest.main()
