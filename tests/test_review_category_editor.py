from tests import support
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.config_manager import ConfigManager
from core.runner import ScriptRunner
from core.reviews.category_editor import add_category, build_category, AddCategoryDialog
from modules.comment_analysis import ModuleWidget
from scripts.comments_step_1_fast import build_prompt


class CategoryEditorTests(unittest.TestCase):
    def setUp(self):
        support.qt_app()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manager = ConfigManager(str(self.root / 'config.json'))
        self.original = json.loads(Path(self.manager.resolve_config('product_configs.json')).read_text(encoding='utf-8'))
        self.path = self.root / 'product_configs.json'
        self.path.write_text(json.dumps(self.original, ensure_ascii=False), encoding='utf-8')
        self.patch = mock.patch.object(self.manager, 'resolve_config', return_value=str(self.path))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(support.cleanup_qt_widgets)

    def test_add_preserves_templates_and_generates_usable_fields(self):
        original_bytes = self.path.read_bytes()
        key = add_category(self.manager, '电源滤波器', '减少音响设备电源干扰', '兼容设备：提取实际连接的设备\n噪声改善')
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        for original_key in self.original:
            self.assertEqual(saved[original_key], self.original[original_key])
        entry = saved[key]
        self.assertEqual(entry['display_name'], '电源滤波器')
        self.assertEqual(entry['stats_fields'][-2:], ['兼容设备', '噪声改善'])
        self.assertEqual(len({f['key'] for f in entry['fields']}), len(entry['fields']))
        self.assertIn('减少音响设备电源干扰', build_prompt(entry, 'Quiet amplifier'))
        self.assertIn('兼容设备', build_prompt(entry, 'Quiet amplifier'))
        self.assertEqual(next((self.root / 'template-backups').glob('*.json')).read_bytes(), original_bytes)

    def test_wrapped_config_and_metadata_are_preserved(self):
        self.path.write_text(json.dumps({'products': self.original, 'version': 2}), encoding='utf-8')
        key = add_category(self.manager, '收纳架', '桌面收纳')
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['version'], 2)
        self.assertIn(key, saved['products'])
        self.assertEqual(len(saved['products']), len(self.original) + 1)

    def test_invalid_inputs_do_not_modify_existing_file(self):
        before = self.path.read_bytes()
        for name, description, dimensions in [('', 'test', ''), ('通用', 'test', ''), ('新品类', '', ''), ('新品类', 'test', '正向关注点'), ('新品类', 'test', '尺寸\n尺寸')]:
            with self.assertRaises(ValueError):
                add_category(self.manager, name, description, dimensions)
            self.assertEqual(self.path.read_bytes(), before)

    def test_corrupt_file_is_not_overwritten(self):
        self.path.write_text('broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            add_category(self.manager, '新', '测试')
        self.assertEqual(self.path.read_text(), 'broken')

    def test_dialog_validation_then_save_and_refresh_all_selectors(self):
        widget = ModuleWidget(self.manager, ScriptRunner())
        dialog = AddCategoryDialog(self.manager, widget)
        dialog._save()
        self.assertIn('名称', dialog.error_label.text())
        self.assertIsNone(dialog.created_key)
        dialog.name_edit.setText('电源滤波器')
        dialog.description_edit.setPlainText('音响供电滤波设备')
        dialog._save()
        self.assertIsNotNone(dialog.created_key)
        widget._refresh_templates()
        self.assertGreater(widget.product_combo.findData(dialog.created_key), 0)
        self.assertGreater(widget.review_collection.excel_options.category.findData(dialog.created_key), 0)
        self.assertIn(dialog.created_key, widget.review_collection.excel_options.configs)
        # New category must not silently replace the user's current choice.
        self.assertIsNone(widget.product_combo.currentData())

    def test_atomic_replace_failure_keeps_existing_templates(self):
        before = self.path.read_bytes()
        with mock.patch('core.reviews.category_editor.os.replace', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                add_category(self.manager, '新品类', '产品说明')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.root.glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
