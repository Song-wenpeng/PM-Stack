"""Shutdown must not discard running work; one broken module must not kill the app."""
from tests import support

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QWidget

from core.runner import ScriptRunner


class FakeEvent:
    def __init__(self):
        self.accepted = None

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


class ExitGuardTests(unittest.TestCase):
    def setUp(self):
        from core.main_window import MainWindow
        self.app = support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)
        self.addCleanup(lambda: ScriptRunner.wait_until_idle(15))
        with patch.object(MainWindow, '_show_startup_issues'):
            self.window = MainWindow()
        self.addCleanup(self.window.deleteLater)

    def test_close_without_running_task_is_accepted(self):
        event = FakeEvent()
        with patch.object(ScriptRunner, 'is_any_running', return_value=False), \
                patch.object(self.window, '_ask_exit_choice') as ask:
            self.window.closeEvent(event)
        self.assertTrue(event.accepted)
        ask.assert_not_called()

    def test_cancel_keeps_window_open(self):
        event = FakeEvent()
        with patch.object(ScriptRunner, 'is_any_running', return_value=True), \
                patch.object(self.window, '_ask_exit_choice',
                             return_value=self.window.EXIT_CANCEL), \
                patch.object(self.window, '_block_until_idle') as wait:
            self.window.closeEvent(event)
        self.assertFalse(event.accepted)
        wait.assert_not_called()

    def test_force_exit_is_allowed_without_waiting(self):
        event = FakeEvent()
        with patch.object(ScriptRunner, 'is_any_running', return_value=True), \
                patch.object(self.window, '_ask_exit_choice',
                             return_value=self.window.EXIT_FORCE), \
                patch.object(self.window, '_block_until_idle') as wait:
            self.window.closeEvent(event)
        self.assertTrue(event.accepted)
        wait.assert_not_called()

    def test_wait_choice_does_not_send_stop_signal(self):
        event = FakeEvent()
        with patch.object(ScriptRunner, 'is_any_running', return_value=True), \
                patch.object(self.window, '_ask_exit_choice',
                             return_value=self.window.EXIT_WAIT), \
                patch.object(ScriptRunner, 'request_stop_all') as stop, \
                patch.object(self.window, '_block_until_idle', return_value=True) as wait:
            self.window.closeEvent(event)
        self.assertTrue(event.accepted)
        stop.assert_not_called()
        wait.assert_called_once()

    def test_stop_choice_writes_cooperative_signal_and_waits(self):
        event = FakeEvent()
        with patch.object(ScriptRunner, 'is_any_running', return_value=True), \
                patch.object(self.window, '_ask_exit_choice',
                             return_value=self.window.EXIT_STOP), \
                patch.object(ScriptRunner, 'request_stop_all', return_value=['x']) as stop, \
                patch.object(self.window, '_block_until_idle', return_value=True) as wait:
            self.window.closeEvent(event)
        self.assertTrue(event.accepted)
        stop.assert_called_once()
        wait.assert_called_once()

    def test_unfinished_wait_does_not_close(self):
        event = FakeEvent()
        with patch.object(ScriptRunner, 'is_any_running', return_value=True), \
                patch.object(self.window, '_ask_exit_choice',
                             return_value=self.window.EXIT_STOP), \
                patch.object(ScriptRunner, 'request_stop_all', return_value=[]), \
                patch.object(self.window, '_block_until_idle', return_value=False):
            self.window.closeEvent(event)
        self.assertFalse(event.accepted)

    def test_app_update_install_uses_the_same_guard(self):
        package = Path(tempfile.gettempdir()) / 'pm-stack-package.zip'
        with patch('sys.frozen', True, create=True), \
                patch.object(self.window, '_confirm_exit_while_running',
                             return_value=False) as guard, \
                patch('core.main_window.launch_updater_helper') as launch, \
                patch.object(self.window.app_updater, 'get_manifest') as manifest:
            self.window._start_app_install(str(package))
        guard.assert_called_once()
        launch.assert_not_called()
        manifest.assert_not_called()

    def test_app_update_install_proceeds_when_guard_allows(self):
        package = Path(tempfile.gettempdir()) / 'pm-stack-package.zip'
        manifest = type('M', (), {'version': 'v9.9.9', 'sha256': 'abc'})()
        with patch('sys.frozen', True, create=True), \
                patch('sys.executable', str(Path(tempfile.gettempdir()) / 'pm-stack.exe')), \
                patch.object(self.window, '_confirm_exit_while_running', return_value=True), \
                patch('core.main_window.launch_updater_helper') as launch, \
                patch.object(self.window.app_updater, 'get_manifest', return_value=manifest), \
                patch('core.main_window.QTimer.singleShot') as quit_timer:
            self.window._start_app_install(str(package))
        launch.assert_called_once()
        quit_timer.assert_called_once()


class CooperativeStopTests(unittest.TestCase):
    def setUp(self):
        self.app = support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)
        self.addCleanup(lambda: ScriptRunner.wait_until_idle(15))

    def test_registered_stop_files_are_written_then_cleaned_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'stop.json'
            ScriptRunner._register_stop_file('token-a', path)
            try:
                written = ScriptRunner.request_stop_all()
                self.assertIn(str(path), written)
                self.assertTrue(json.loads(path.read_text(encoding='utf-8'))['stop'])
            finally:
                ScriptRunner._release_stop_file('token-a')
            self.assertFalse(path.exists())

    def test_run_script_exports_stop_file_and_task_stops_cooperatively(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'marker.txt'
            script = Path(tmp) / 'waiter.py'
            script.write_text(
                'import os, time\n'
                'from pathlib import Path\n'
                'stop = Path(os.environ["PM_STACK_STOP_FILE"])\n'
                'marker = Path(os.environ["TEST_MARKER"])\n'
                'for _ in range(1000):\n'
                '    if stop.exists():\n'
                '        marker.write_text("saved-then-stopped", encoding="utf-8")\n'
                '        break\n'
                '    time.sleep(0.01)\n'
                'else:\n'
                '    marker.write_text("never-stopped", encoding="utf-8")\n',
                encoding='utf-8')
            runner = ScriptRunner()
            self.addCleanup(runner.deleteLater)
            self.assertTrue(runner.run_script(str(script), env_extra={'TEST_MARKER': str(marker)}))
            self.assertTrue(ScriptRunner.is_any_running())
            ScriptRunner.request_stop_all()
            self.assertTrue(ScriptRunner.wait_until_idle(30))
            self.assertEqual(marker.read_text(encoding='utf-8'), 'saved-then-stopped')
            self.assertFalse(ScriptRunner.is_any_running())

    def test_wait_until_idle_times_out_while_a_task_holds_the_lock(self):
        acquired = ScriptRunner._execution_lock.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            self.assertFalse(ScriptRunner.wait_until_idle(0.2, poll=0.01))
        finally:
            ScriptRunner._execution_lock.release()
        self.assertTrue(ScriptRunner.wait_until_idle(0.2))


class ModuleFaultIsolationTests(unittest.TestCase):
    def setUp(self):
        from core.main_window import MainWindow
        self.app = support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)
        self.MainWindow = MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def build(self, scan=None):
        with patch.object(self.MainWindow, '_show_startup_issues'), \
                (patch.object(self.MainWindow, '_scan_module_dir', scan)
                 if scan else _Noop()):
            window = self.MainWindow()
        self.addCleanup(window.deleteLater)
        return window

    def test_broken_widget_leaves_other_modules_usable(self):
        class Boom(QWidget):
            def __init__(self, *args):
                raise RuntimeError('构造失败')

        real_scan = self.MainWindow._scan_module_dir
        info = {'name': '坏模块', 'order': 999, 'description': ''}

        def fake_scan(window, modules_dir, discovered, source):
            if source == 'builtin':
                real_scan(window, modules_dir, discovered, source)
            else:
                discovered.append((info, Boom, source))

        window = self.build(fake_scan)
        names = [item[0].get('name') for item in window._modules]
        self.assertNotIn('坏模块', names)
        self.assertGreaterEqual(len(names), 5)
        self.assertIn('坏模块', [name for name, _ in window._module_failures])
        self.assertIn('构造失败', window._module_failures[-1][1])
        self.assertEqual(window.stack.count(), len(names))
        self.assertEqual(len(window._module_runners), len(names))

    def test_import_failure_is_recorded_not_just_printed(self):
        window = self.build()
        broken = Path(self.tmp.name) / 'broken_mod.py'
        broken.write_text('raise ImportError("boom")\n', encoding='utf-8')
        window._module_failures.clear()
        discovered = []
        window._scan_module_dir(self.tmp.name, discovered, 'plugin')
        self.assertEqual(discovered, [])
        self.assertEqual([name for name, _ in window._module_failures], ['broken_mod'])

    def test_startup_issues_combine_module_failures_and_config_warnings(self):
        window = self.build()
        window._module_failures = [('坏模块', 'RuntimeError: x')]
        shown = []
        with patch.object(window.config_mgr, 'get_warnings',
                          return_value=['用户配置无法读取，已改用默认配置']), \
                patch.object(window, '_show_startup_issues', side_effect=shown.append):
            window._report_startup_issues()
        self.assertEqual(len(window._startup_issues), 2)
        self.assertEqual(len(shown), 1)
        self.assertIn('坏模块', shown[0][0])

    def test_clean_startup_reports_nothing(self):
        window = self.build()
        window._module_failures = []
        with patch.object(window.config_mgr, 'get_warnings', return_value=[]), \
                patch.object(window, '_show_startup_issues') as show:
            window._report_startup_issues()
        self.assertEqual(window._startup_issues, [])
        show.assert_not_called()


class _Noop:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


if __name__ == '__main__':
    unittest.main()
