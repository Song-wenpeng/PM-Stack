from tests import support
import unittest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListView
from core.matrix_workspace import MatrixWorkspace

class MatrixLayoutTests(unittest.TestCase):
    def test_field_library_above_three_column_canvas(self):
        app = support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)
        w = MatrixWorkspace()
        w.resize(1200, 760)
        w.show()
        app.processEvents()
        self.assertEqual(w.fields.flow(), QListView.Flow.LeftToRight)
        self.assertTrue(w.fields.isWrapping())
        self.assertEqual(w.matrix_split.count(), 3)
        self.assertIs(w.matrix_split.widget(0), w.drop_targets['vertical'])
        self.assertIs(w.matrix_split.widget(2), w.drop_targets['horizontal'])
        self.assertLess(w.fields.mapTo(w, w.fields.rect().bottomLeft()).y(), w.matrix_split.mapTo(w, w.matrix_split.rect().topLeft()).y())
        self.assertGreater(w.table.width(), w.drop_targets['vertical'].width())
        w.close()

    def test_restored_matrix_tabs_keep_new_workspace(self):
        from unittest.mock import Mock
        from modules.product_matrix import ModuleWidget
        support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)
        module = ModuleWidget(Mock(), Mock())
        self.assertEqual([module.matrix_tabs.tabText(i) for i in range(module.matrix_tabs.count())], ['自由组合矩阵', '使用场景矩阵', '销额透视矩阵', '品牌×分类矩阵'])
        self.assertIs(module.matrix_tabs.currentWidget(), module.free_matrix)
        self.assertTrue(hasattr(module, 'm3_file'))
        self.assertTrue(hasattr(module, 'matrix_file'))

    def test_restored_scenario_and_brand_handlers_dispatch(self):
        from unittest.mock import Mock, patch
        from modules.product_matrix import ModuleWidget
        support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)
        module = ModuleWidget(Mock(), Mock())
        module.matrix_file.setText('source.xlsx')
        module.matrix_sheet.setText('数据')
        module.matrix_output.setText('result.xlsx')
        with patch.object(module, '_run') as run:
            module._run_matrix()
            self.assertEqual(run.call_args.args[0], 'product_matrix.py')
            self.assertEqual(run.call_args.kwargs['env_overrides']['MATRIX_SOURCE_SHEET'], '数据')
        module.m3_file.setText('source.xlsx')
        module.m3_sheet.setText('数据')
        module.m3_brands.setText('Brand A')
        with patch.object(module, '_run') as run:
            module._run_matrix3()
            self.assertEqual(run.call_args.args[0], 'product_matrix3.py')

    def test_restored_handlers_reject_source_output_collision(self):
        from unittest.mock import Mock, patch
        from modules.product_matrix import ModuleWidget
        support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)
        m = ModuleWidget(Mock(), Mock())
        m.matrix_file.setText('source.xlsx'); m.matrix_sheet.setText('数据'); m.matrix_output.setText('source.xlsx')
        with patch.object(m, '_run') as run:
            self.assertFalse(m._run_matrix())
            run.assert_not_called()
        m.m3_file.setText('product_matrix3.xlsx'); m.m3_sheet.setText('数据'); m.m3_brands.setText('A')
        with patch.object(m, '_run') as run:
            self.assertFalse(m._run_matrix3())
            run.assert_not_called()

    def test_restored_scripts_preserve_input_on_collision(self):
        import tempfile, subprocess, os, sys
        from pathlib import Path
        from openpyxl import Workbook
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'product_matrix3.xlsx'
            book = Workbook(); book.active.title = '数据'; book.create_sheet('原件保留'); book.save(source)
            before = source.read_bytes()
            env = dict(os.environ, MATRIX_EXCEL_FILE=str(source), MATRIX_SOURCE_SHEET='数据', MATRIX_OUTPUT_FILE=str(source))
            commands = [[sys.executable, str(root/'scripts/product_matrix.py')], [sys.executable, str(root/'scripts/product_matrix3.py'), '--file', str(source), '--sheet', '数据', '--brands', 'A', '--category-col', '分类', '--brand-col', '品牌']]
            for command in commands:
                result = subprocess.run(command, cwd=folder, env=env, capture_output=True, timeout=60)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('禁止覆盖输入原件'.encode('utf-8'), result.stderr)
                self.assertEqual(source.read_bytes(), before)
