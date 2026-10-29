"""A corrupt config must not block startup, and the vision model must match the UI."""
from tests import support

import json
from pathlib import Path
import re
import tempfile
import unittest

from core.config_manager import (ConfigManager, DEFAULT_CONFIG, DEFAULT_VISION_MODEL)

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
EXTRACTION_SCRIPTS = ('exstract_from_description.py', 'exstract_from_description_fast.py')


class ConfigRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'config.json'

    def write(self, text):
        self.path.write_text(text, encoding='utf-8')
        return self.path.read_bytes()

    def quarantined(self):
        return sorted(self.root.glob('config.json.corrupt-*'))

    def test_corrupt_json_does_not_block_startup_and_keeps_original_bytes(self):
        original = self.write('{"api_key": "x", broken')
        manager = ConfigManager(str(self.path))
        self.assertEqual(manager.get('base_url'), DEFAULT_CONFIG['base_url'])
        self.assertTrue(any('无法读取' in w for w in manager.get_warnings()))
        self.assertTrue(any('默认配置' in w for w in manager.get_warnings()))
        found = self.quarantined()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].read_bytes(), original)
        self.assertFalse(self.path.exists())

    def test_wrong_json_type_is_recovered(self):
        original = self.write('[1, 2, 3]')
        manager = ConfigManager(str(self.path))
        self.assertEqual(manager.get('theme'), DEFAULT_CONFIG['theme'])
        self.assertTrue(manager.get_warnings())
        self.assertEqual(self.quarantined()[0].read_bytes(), original)

    def test_unreadable_config_file_is_reported_without_crash(self):
        self.path.mkdir()  # a directory cannot be read as JSON
        manager = ConfigManager(str(self.path))
        self.assertEqual(manager.get('theme'), DEFAULT_CONFIG['theme'])
        self.assertTrue(any('无法读取' in w for w in manager.get_warnings()))

    def test_missing_config_file_is_not_a_warning(self):
        manager = ConfigManager(str(self.path))
        self.assertEqual(manager.get_warnings(), [])
        self.assertFalse(self.quarantined())

    def test_valid_config_still_loads_without_warnings(self):
        self.write(json.dumps({'theme': 'dark', 'model_name': 'custom-model'}))
        manager = ConfigManager(str(self.path))
        self.assertEqual(manager.get_warnings(), [])
        self.assertEqual(manager.get('theme'), 'dark')
        self.assertEqual(manager.get('model_name'), 'custom-model')

    def test_save_after_recovery_writes_valid_config_and_keeps_quarantine(self):
        original = self.write('{oops')
        manager = ConfigManager(str(self.path))
        quarantined = self.quarantined()[0]
        manager.set('theme', 'dark')
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['theme'], 'dark')
        self.assertEqual(quarantined.read_bytes(), original)
        reloaded = ConfigManager(str(self.path))
        self.assertEqual(reloaded.get_warnings(), [])
        self.assertEqual(reloaded.get('theme'), 'dark')

    def test_two_corrupt_files_in_a_row_do_not_collide(self):
        first = self.write('{bad-1')
        ConfigManager(str(self.path))
        kept = self.quarantined()[0]
        second = self.write('{bad-2')
        ConfigManager(str(self.path))
        found = self.quarantined()
        self.assertEqual(len(found), 2)
        self.assertEqual(kept.read_bytes(), first)
        self.assertIn(second, [item.read_bytes() for item in found])

    def test_real_entry_point_reports_config_warning_from_before_restore(self):
        from unittest.mock import patch
        import main
        from core.main_window import MainWindow
        app = support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)
        original = self.write('{broken-at-entry')
        report = self.root / 'startup.json'
        shown = []
        with patch('main.QApplication', return_value=app), \
                patch('sys.argv', ['main.py', '--startup-check', str(report)]), \
                patch.object(ConfigManager, '_default_user_config_path', return_value=str(self.path)), \
                patch.object(ConfigManager, '_default_legacy_config_path', return_value=None), \
                patch.object(ConfigManager, 'get_app_update_manifest_source', return_value=''), \
                patch.object(MainWindow, '_show_startup_issues', side_effect=shown.append):
            main.main()
        self.assertTrue(report.exists())
        self.assertTrue(any('无法读取' in warning for group in shown for warning in group))
        self.assertEqual(self.quarantined()[0].read_bytes(), original)


class VisionModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'config.json'

    def manager(self, values=None):
        if values is not None:
            self.path.write_text(json.dumps(values), encoding='utf-8')
        return ConfigManager(str(self.path))

    def test_blank_vision_model_exports_the_builtin_default(self):
        manager = self.manager()
        self.assertEqual(manager.effective_vision_model(), DEFAULT_VISION_MODEL)
        self.assertEqual(manager.get_env_dict()['MODEL_VISION'], DEFAULT_VISION_MODEL)

    def test_whitespace_only_vision_model_uses_the_default(self):
        manager = self.manager({'vision_model_name': '   '})
        self.assertEqual(manager.get_env_dict()['MODEL_VISION'], DEFAULT_VISION_MODEL)

    def test_explicit_vision_model_is_exported(self):
        manager = self.manager({'vision_model_name': 'gpt-4o'})
        self.assertEqual(manager.effective_vision_model(), 'gpt-4o')
        self.assertEqual(manager.get_env_dict()['MODEL_VISION'], 'gpt-4o')

    def test_vision_model_does_not_inherit_the_text_model(self):
        manager = self.manager({'model_name': 'deepseek-ai/DeepSeek-V3'})
        self.assertEqual(manager.get_env_dict()['MODEL_VISION'], DEFAULT_VISION_MODEL)

    def test_core_default_matches_the_extraction_scripts(self):
        """The scripts keep their own literal default; it must not drift."""
        pattern = re.compile(r'os\.getenv\(\s*"MODEL_VISION"\s*,\s*"([^"]+)"\s*\)')
        for name in EXTRACTION_SCRIPTS:
            with self.subTest(script=name):
                text = (SCRIPTS / name).read_text(encoding='utf-8')
                match = pattern.search(text)
                self.assertIsNotNone(match, f'{name} 中的视觉模型默认值已改变写法')
                self.assertEqual(match.group(1), DEFAULT_VISION_MODEL)

    def test_settings_dialog_states_the_effective_model(self):
        from PyQt6.QtWidgets import QLabel
        from unittest.mock import patch
        from core.main_window import MainWindow, SettingsDialog
        support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)
        with patch.object(MainWindow, '_show_startup_issues'):
            window = MainWindow()
        self.addCleanup(window.deleteLater)
        dialog = SettingsDialog(window.config_mgr, window.updater, window)
        self.addCleanup(dialog.deleteLater)
        self.assertIn(DEFAULT_VISION_MODEL, dialog.vision_model_edit.placeholderText())
        notes = ' '.join(label.text() for label in dialog.findChildren(QLabel))
        self.assertIn('不会继承上方的文本模型', notes)
        self.assertNotIn('留空则使用上方 API 配置。', notes)


if __name__ == '__main__':
    unittest.main()
