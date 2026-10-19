from tests import support
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from core.config_manager import ConfigManager
from core.reviews.prompt_editor import PromptEditorDialog, update_prompt
from scripts.comments_step_1_fast import build_prompt

class PromptEditorTests(unittest.TestCase):
    def setUp(self):
        support.qt_app()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = ConfigManager(str(self.root / 'config.json'))
        self.original = json.loads(Path(self.manager.resolve_config('product_configs.json')).read_text(encoding='utf-8'))
        self.path = self.root / 'product_configs.json'
        self.path.write_text(json.dumps({'products': self.original, 'version': 2}, ensure_ascii=False), encoding='utf-8')
        self.patch = mock.patch.object(self.manager, 'resolve_config', return_value=str(self.path))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(support.cleanup_qt_widgets)

    def test_edit_roundtrip_preserves_metadata_fields_and_other_categories(self):
        before = self.path.read_bytes()
        base = self.original['general']
        saved = update_prompt(self.manager, 'general', '新系统角色', '新产品说明', ['新分析任务'], base)
        document = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(document['version'], 2)
        expected = copy.deepcopy(self.original)
        expected['general'].update(system_prompt='新系统角色', product_desc='新产品说明', tasks=['新分析任务'])
        self.assertEqual(document['products'], expected)
        self.assertIn('新分析任务', build_prompt(saved, '评论'))
        self.assertEqual(next((self.root / 'template-backups').glob('*.json')).read_bytes(), before)
        reopened = PromptEditorDialog(self.manager, selected='general')
        self.assertEqual(reopened.system.toPlainText(), '新系统角色')
        self.assertIn('新产品说明', reopened.preview.toPlainText())

    def test_invalid_conflicting_and_failed_writes_preserve_original(self):
        before = self.path.read_bytes()
        base = self.original['general']
        for args in [('', 'desc', ['task'], base), ('sys', 'desc', ['task'], {})]:
            with self.assertRaises(ValueError):
                update_prompt(self.manager, 'general', *args)
            self.assertEqual(self.path.read_bytes(), before)
        with mock.patch('core.reviews.category_editor.os.replace', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                update_prompt(self.manager, 'general', 'sys', 'desc', ['task'], base)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_frozen_save_preserves_restored_user_template_location(self):
        base = self.original['general']
        before = self.path.read_bytes()
        exe_dir = self.root / 'portable'
        exe_dir.mkdir()
        with mock.patch('sys.frozen', True, create=True), mock.patch('sys.executable', str(exe_dir / 'PM Stack.exe')):
            update_prompt(self.manager, 'general', 'new system', 'new desc', ['new task'], base)
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['products']['general']['system_prompt'], 'new system')
        self.assertNotEqual(self.path.read_bytes(), before)
        self.assertEqual(next((self.root / 'template-backups').glob('*.json')).read_bytes(), before)

    def test_dialog_preview_save_switch_and_discard(self):
        dialog = PromptEditorDialog(self.manager, selected='general')
        dialog.tasks.setPlainText(dialog.tasks.toPlainText() + '\n测试新增提取指令')
        self.assertIn('测试新增提取指令', dialog.preview.toPlainText())
        self.assertTrue(dialog._dirty())
        with mock.patch.object(dialog, '_discard', return_value=False):
            dialog.category.setCurrentIndex(dialog.category.findData('adapter'))
        self.assertEqual(dialog.category.currentData(), 'general')
        dialog._save()
        self.assertTrue(dialog.changed)
        self.assertFalse(dialog._dirty())
        dialog.system.setPlainText('未保存修改')
        dialog._load()
        self.assertFalse(dialog._dirty())
        self.assertNotEqual(dialog.system.toPlainText(), '未保存修改')
        dialog.category.setCurrentIndex(dialog.category.findData('adapter'))
        self.assertEqual(dialog.current_key, 'adapter')

if __name__ == '__main__':
    unittest.main()
