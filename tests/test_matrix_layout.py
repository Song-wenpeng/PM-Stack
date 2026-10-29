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

    def test_only_requested_matrix_tabs_remain(self):
        from unittest.mock import Mock
        from modules.product_matrix import ModuleWidget
        support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)
        module = ModuleWidget(Mock(), Mock())
        self.assertEqual([module.matrix_tabs.tabText(i) for i in range(module.matrix_tabs.count())], ['自由组合矩阵', '销额透视矩阵'])
        self.assertIs(module.matrix_tabs.currentWidget(), module.free_matrix)
        self.assertFalse(hasattr(module, 'm3_file'))
        self.assertFalse(hasattr(module, 'matrix_file'))
