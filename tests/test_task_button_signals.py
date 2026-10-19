"""Regression: decorated handlers must consume Qt clicked(bool) signals safely."""
from tests import support
import unittest
from unittest.mock import patch
from PyQt6.QtWidgets import QPushButton, QLineEdit
from core.task_ui import validated
from core.source_picker import browse_excel_source


class TaskButtonSignalTests(unittest.TestCase):
    def setUp(self):
        self.app = support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)

    def test_clicked_bool_is_not_forwarded_to_argumentless_action(self):
        class Task:
            def __init__(self):
                self.field = QLineEdit('filled')
                self.button = QPushButton()
                self.button.setCheckable(True)
                self.calls = 0
                self.button.clicked.connect(self.action)

            @validated(lambda s: [(s.field, 'Source')], 'button')
            def action(self):
                self.calls += 1

        task = Task()
        task.button.click()  # clicked(True)
        task.button.click()  # clicked(False)
        self.assertEqual(task.calls, 2)
        task.field.clear()
        task.button.click()
        self.assertEqual(task.calls, 2)
        task.field.setText('filled')
        task.action()  # direct invocation remains valid
        self.assertEqual(task.calls, 3)

    def test_file_and_folder_use_native_dialog_defaults_and_cancel_returns_empty(self):
        with patch('core.source_picker.QFileDialog.getOpenFileName', return_value=('sample.xlsx', '')) as pick:
            self.assertEqual(browse_excel_source(), 'sample.xlsx')
            self.assertNotIn('options', pick.call_args.kwargs)
        with patch('core.source_picker.QFileDialog.getExistingDirectory', return_value='folder') as pick:
            self.assertEqual(browse_excel_source(want_dir=True), 'folder')
            self.assertNotIn('options', pick.call_args.kwargs)
        with patch('core.source_picker.QFileDialog.getOpenFileName', return_value=('', '')):
            self.assertEqual(browse_excel_source(), '')


if __name__ == '__main__':
    unittest.main()
