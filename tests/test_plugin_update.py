"""Plugin packages must be verified before install, and install must be all-or-nothing."""
from tests import support

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from core import updater
from core.updater import (MANIFEST_FORMAT, Updater, _merge_staged_tree,
                          _commit_merge, _rollback_merge, verify_staged_tree)

APP_VERSION = 'v1.11.5'


class FakeResponse:
    def __init__(self, payload):
        self._data = payload
        self.headers = {'Content-Length': str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        if not size or size < 0:
            out, self._data = self._data, b''
            return out
        out, self._data = self._data[:size], self._data[size:]
        return out


def build_package(root, files, manifest='auto', name='plugin.zip'):
    payload = {rel: text.encode('utf-8') for rel, text in files.items()}
    if manifest == 'auto':
        manifest = {
            'format': MANIFEST_FORMAT,
            'plugin_version': 'v2.0.0',
            'min_app_version': 'v1.0.0',
            'files': {rel: hashlib.sha256(data).hexdigest()
                      for rel, data in payload.items()},
        }
    archive = Path(root) / name
    with zipfile.ZipFile(archive, 'w') as bundle:
        for rel, data in payload.items():
            bundle.writestr(rel, data)
        if manifest is not None:
            bundle.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
    return archive


class ManifestVerificationTests(unittest.TestCase):
    def setUp(self):
        support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.files = {'modules/demo.py': 'print("demo")\n', 'README.md': 'demo plugin\n'}

    def stage(self, archive):
        target = Path(tempfile.mkdtemp(dir=self.root))
        with zipfile.ZipFile(archive) as bundle:
            updater._safe_extract_zip(bundle, target)
        return target

    def verify(self, **kwargs):
        files = kwargs.pop('files', self.files)
        current = kwargs.pop('current', APP_VERSION)
        return verify_staged_tree(self.stage(build_package(self.root, files, **kwargs)), current)

    def test_valid_package_is_accepted(self):
        info = self.verify()
        self.assertEqual(info['plugin_version'], 'v2.0.0')
        self.assertEqual(info['file_count'], 2)

    def test_missing_manifest_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            self.verify(manifest=None)
        self.assertIn('manifest.json', str(caught.exception))

    def test_unsupported_manifest_format_is_rejected(self):
        manifest = {'format': 99, 'plugin_version': 'v2.0.0',
                    'files': {'README.md': hashlib.sha256(b'demo plugin\n').hexdigest()}}
        with self.assertRaises(ValueError) as caught:
            self.verify(files={'README.md': 'demo plugin\n'}, manifest=manifest)
        self.assertIn('格式不受支持', str(caught.exception))

    def test_missing_plugin_version_is_rejected(self):
        manifest = {'format': MANIFEST_FORMAT, 'files': {}}
        with self.assertRaises(ValueError) as caught:
            self.verify(manifest=manifest)
        self.assertIn('plugin_version', str(caught.exception))

    def test_tampered_file_digest_is_rejected(self):
        files = dict(self.files)
        manifest = {'format': MANIFEST_FORMAT, 'plugin_version': 'v2.0.0',
                    'files': {rel: '0' * 64 for rel in files}}
        with self.assertRaises(ValueError) as caught:
            self.verify(files=files, manifest=manifest)
        self.assertIn('校验失败', str(caught.exception))

    def test_malformed_digest_is_rejected(self):
        files = {'README.md': 'demo plugin\n'}
        manifest = {'format': MANIFEST_FORMAT, 'plugin_version': 'v2.0.0',
                    'files': {'README.md': 'not-a-digest'}}
        with self.assertRaises(ValueError) as caught:
            self.verify(files=files, manifest=manifest)
        self.assertIn('校验失败', str(caught.exception))

    def test_undeclared_payload_is_rejected(self):
        manifest = {'format': MANIFEST_FORMAT, 'plugin_version': 'v2.0.0',
                    'files': {'README.md': hashlib.sha256(b'demo plugin\n').hexdigest()}}
        with self.assertRaises(ValueError) as caught:
            self.verify(manifest=manifest)
        self.assertIn('未声明', str(caught.exception))
        self.assertIn('modules/demo.py', str(caught.exception))

    def test_declared_but_absent_file_is_rejected(self):
        files = dict(self.files)
        files['modules/ghost.py'] = 'x = 1\n'
        payload = dict(files)
        del payload['modules/ghost.py']
        manifest = {'format': MANIFEST_FORMAT, 'plugin_version': 'v2.0.0',
                    'files': {rel: hashlib.sha256(text.encode()).hexdigest()
                              for rel, text in files.items()}}
        with self.assertRaises(ValueError) as caught:
            self.verify(files=payload, manifest=manifest)
        self.assertIn('缺少清单声明的文件', str(caught.exception))

    def test_incompatible_min_app_version_is_rejected(self):
        manifest = {'format': MANIFEST_FORMAT, 'plugin_version': 'v2.0.0',
                    'min_app_version': 'v9.9.9',
                    'files': {rel: hashlib.sha256(text.encode()).hexdigest()
                              for rel, text in self.files.items()}}
        with self.assertRaises(ValueError) as caught:
            self.verify(manifest=manifest)
        self.assertIn('请先更新主程序', str(caught.exception))

    def test_unknown_current_version_rejects_declared_minimum(self):
        with self.assertRaises(ValueError) as caught:
            self.verify(current='')
        self.assertIn('无法确认当前主程序版本', str(caught.exception))

    def test_manifest_without_minimum_installs_on_any_version(self):
        manifest = {'format': MANIFEST_FORMAT, 'plugin_version': 'v2.0.0',
                    'files': {rel: hashlib.sha256(text.encode()).hexdigest()
                              for rel, text in self.files.items()}}
        self.assertEqual(self.verify(manifest=manifest, current='')['plugin_version'], 'v2.0.0')


class MergeTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plugins = self.root / 'plugins'
        self.stage = self.root / 'stage'

    def seed_existing(self):
        (self.plugins / 'modules').mkdir(parents=True)
        (self.plugins / 'modules' / 'demo.py').write_text('OLD\n', encoding='utf-8')
        (self.plugins / 'keep.txt').write_text('KEEP\n', encoding='utf-8')

    def seed_stage(self, files):
        self.stage.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            target = self.stage / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')

    def test_successful_merge_replaces_and_commits(self):
        self.seed_existing()
        self.seed_stage({'modules/demo.py': 'NEW\n', 'modules/extra.py': 'EXTRA\n',
                         'manifest.json': '{"format":1}'})
        journal = _merge_staged_tree(self.stage, self.plugins)
        _commit_merge(journal)
        self.assertEqual((self.plugins / 'modules' / 'demo.py').read_text(encoding='utf-8'), 'NEW\n')
        self.assertEqual((self.plugins / 'modules' / 'extra.py').read_text(encoding='utf-8'), 'EXTRA\n')
        self.assertEqual((self.plugins / 'keep.txt').read_text(encoding='utf-8'), 'KEEP\n')
        self.assertFalse((self.plugins / 'manifest.json').exists())
        self.assertEqual([p.name for p in self.root.glob('.pmstack-rollback-*')], [])

    def test_explicit_rollback_restores_the_previous_plugin_set(self):
        self.seed_existing()
        self.seed_stage({'modules/demo.py': 'NEW\n', 'modules/extra.py': 'EXTRA\n'})
        journal = _merge_staged_tree(self.stage, self.plugins)
        _rollback_merge(journal)
        self.assertEqual((self.plugins / 'modules' / 'demo.py').read_text(encoding='utf-8'), 'OLD\n')
        self.assertFalse((self.plugins / 'modules' / 'extra.py').exists())
        self.assertEqual((self.plugins / 'keep.txt').read_text(encoding='utf-8'), 'KEEP\n')
        self.assertEqual([p.name for p in self.root.glob('.pmstack-rollback-*')], [])

    def test_failure_midway_never_leaves_a_mixed_plugin_set(self):
        self.seed_existing()
        self.seed_stage({'modules/a.py': 'A\n', 'modules/b.py': 'B\n', 'modules/c.py': 'C\n'})
        real_copy2 = shutil.copy2
        calls = []

        def flaky(source, destination, **kwargs):
            calls.append(Path(source).name)
            if len(calls) == 2:
                raise OSError('disk full')
            return real_copy2(source, destination, **kwargs)

        with patch('core.updater.shutil.copy2', side_effect=flaky):
            with self.assertRaises(OSError):
                _merge_staged_tree(self.stage, self.plugins)
        self.assertGreaterEqual(len(calls), 2)
        # 事务语义：中途失败后既不留下新文件，也不留下被换走的旧文件缺口。
        self.assertEqual(sorted(p.name for p in (self.plugins / 'modules').iterdir()), ['demo.py'])
        self.assertEqual((self.plugins / 'modules' / 'demo.py').read_text(encoding='utf-8'), 'OLD\n')
        self.assertEqual((self.plugins / 'keep.txt').read_text(encoding='utf-8'), 'KEEP\n')
        self.assertEqual([p.name for p in self.root.glob('.pmstack-rollback-*')], [])

    def test_rollback_directory_is_outside_the_plugin_tree(self):
        self.seed_existing()
        self.seed_stage({'modules/demo.py': 'NEW\n'})
        journal = _merge_staged_tree(self.stage, self.plugins)
        try:
            self.assertIsNotNone(journal['rollback_root'])
            self.assertNotIn(self.plugins, Path(journal['rollback_root']).parents)
            self.assertIn('.pmstack-rollback-', Path(journal['rollback_root']).name)
        finally:
            _rollback_merge(journal)

    def test_failed_restore_keeps_backup_and_reports_recovery_location(self):
        self.seed_existing()
        self.seed_stage({'modules/demo.py': 'NEW\n'})
        journal = _merge_staged_tree(self.stage, self.plugins)
        backup, target = journal['moved'][0]
        real_replace = updater.os.replace

        def locked_restore(source, destination):
            if Path(source) == backup:
                raise PermissionError('synthetic occupied target')
            return real_replace(source, destination)

        with patch('core.updater.os.replace', side_effect=locked_restore):
            with self.assertRaises(OSError) as caught:
                _rollback_merge(journal)
        self.assertEqual(backup.read_text(encoding='utf-8'), 'OLD\n')
        self.assertIn(str(journal['rollback_root']), str(caught.exception))
        # After the lock is released, the retained journal can finish recovery.
        _rollback_merge(journal)
        self.assertEqual(target.read_text(encoding='utf-8'), 'OLD\n')
        self.assertFalse(journal['rollback_root'].exists())


class DownloadThreadTests(unittest.TestCase):
    def setUp(self):
        support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plugins = self.root / 'plugins'
        self.updater = Updater()
        self.addCleanup(self.updater.deleteLater)
        self.updater._current_version = APP_VERSION
        self.updater._last_checksum_url = None
        self.results = []
        self.updater.download_finished.connect(lambda ok, msg: self.results.append((ok, msg)))

    def run_download(self, archive, checksum=None):
        payload = archive.read_bytes()
        responses = [FakeResponse(payload)]
        if checksum is not None:
            self.updater._last_checksum_url = 'https://example.invalid/plugin.zip.sha256'
            responses.append(FakeResponse(checksum.encode('utf-8')))

        def fake_urlopen(request, timeout=None):
            return responses.pop(0)

        with patch('core.updater.urllib.request.urlopen', side_effect=fake_urlopen):
            self.updater._download_thread('https://example.invalid/plugin.zip', str(self.plugins))
        return self.results[-1]

    def test_valid_package_installs_and_records_version(self):
        archive = build_package(self.root, {'modules/demo.py': 'print("demo")\n'})
        ok, message = self.run_download(archive)
        self.assertTrue(ok, message)
        self.assertIn('v2.0.0', message)
        self.assertEqual((self.plugins / 'modules' / 'demo.py').read_text(encoding='utf-8'),
                         'print("demo")\n')
        info = json.loads((self.plugins / 'version.json').read_text(encoding='utf-8'))
        self.assertEqual(info['plugin_version'], 'v2.0.0')
        self.assertEqual(info['file_count'], 1)
        self.assertIn('installed_at', info)

    def test_version_write_failure_rolls_back_payload_and_keeps_old_version(self):
        (self.plugins / 'modules').mkdir(parents=True)
        (self.plugins / 'modules/demo.py').write_text('OLD\n', encoding='utf-8')
        (self.plugins / 'version.json').write_text('{"last_updated":"v1"}', encoding='utf-8')
        archive = build_package(self.root, {'modules/demo.py': 'NEW\n',
                                            'modules/extra.py': 'EXTRA\n'})
        with patch('core.updater._atomic_write_json', side_effect=OSError('disk full')):
            ok, message = self.run_download(archive)
        self.assertFalse(ok)
        self.assertIn('已回滚', message)
        self.assertEqual((self.plugins / 'modules/demo.py').read_text(encoding='utf-8'), 'OLD\n')
        self.assertFalse((self.plugins / 'modules/extra.py').exists())
        self.assertEqual((self.plugins / 'version.json').read_text(encoding='utf-8'),
                         '{"last_updated":"v1"}')

    def test_download_reports_incomplete_rollback_without_deleting_old_payload(self):
        (self.plugins / 'modules').mkdir(parents=True)
        target = self.plugins / 'modules/demo.py'
        target.write_text('OLD\n', encoding='utf-8')
        archive = build_package(self.root, {'modules/demo.py': 'NEW\n'})
        real_replace = updater.os.replace

        def fail_restore(source, destination):
            if '.pmstack-rollback-' in str(source):
                raise PermissionError('synthetic restore lock')
            return real_replace(source, destination)

        with patch('core.updater._atomic_write_json', side_effect=OSError('version write failed')), \
                patch('core.updater.os.replace', side_effect=fail_restore):
            ok, message = self.run_download(archive)
        self.assertFalse(ok)
        self.assertIn('回滚未完成', message)
        self.assertNotIn('已回滚', message)
        backups = list(self.root.glob('.pmstack-rollback-*/modules/demo.py'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding='utf-8'), 'OLD\n')

    def test_corrupt_package_leaves_existing_plugins_untouched(self):
        (self.plugins / 'modules').mkdir(parents=True)
        (self.plugins / 'modules' / 'demo.py').write_text('OLD\n', encoding='utf-8')
        files = {'modules/demo.py': 'print("demo")\n'}
        manifest = {'format': MANIFEST_FORMAT, 'plugin_version': 'v2.0.0',
                    'files': {rel: '0' * 64 for rel in files}}
        archive = build_package(self.root, files, manifest=manifest)
        ok, message = self.run_download(archive)
        self.assertFalse(ok)
        self.assertIn('未改动插件目录', message)
        self.assertEqual((self.plugins / 'modules' / 'demo.py').read_text(encoding='utf-8'), 'OLD\n')
        self.assertFalse((self.plugins / 'version.json').exists())

    def test_missing_manifest_is_rejected_before_touching_plugins(self):
        archive = build_package(self.root, {'modules/demo.py': 'x = 1\n'}, manifest=None)
        ok, message = self.run_download(archive)
        self.assertFalse(ok)
        self.assertIn('manifest.json', message)
        self.assertFalse((self.plugins / 'modules' / 'demo.py').exists())

    def test_checksum_asset_match_and_mismatch(self):
        archive = build_package(self.root, {'modules/demo.py': 'x = 1\n'})
        good = hashlib.sha256(archive.read_bytes()).hexdigest()
        ok, message = self.run_download(archive, checksum=f'{good}  plugin.zip\n')
        self.assertTrue(ok, message)
        self.assertIn('.sha256 资产校验整包摘要', message)

        second = build_package(self.root, {'modules/other.py': 'y = 2\n'}, name='other.zip')
        ok, message = self.run_download(second, checksum=f'{"0" * 64}  other.zip\n')
        self.assertFalse(ok)
        self.assertIn('不一致', message)
        self.assertFalse((self.plugins / 'modules' / 'other.py').exists())

    def test_absent_checksum_asset_reports_https_only_assurance(self):
        archive = build_package(self.root, {'modules/demo.py': 'x = 1\n'})
        ok, message = self.run_download(archive)
        self.assertTrue(ok, message)
        self.assertIn('未提供 .sha256 资产', message)

    def test_malformed_checksum_asset_is_rejected(self):
        archive = build_package(self.root, {'modules/demo.py': 'x = 1\n'})
        ok, message = self.run_download(archive, checksum='not-a-digest\n')
        self.assertFalse(ok)
        self.assertIn('不是有效的 SHA-256', message)


if __name__ == '__main__':
    unittest.main()
