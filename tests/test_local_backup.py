from tests import support
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import zipfile
from unittest.mock import patch
from contextlib import closing
from core.config_manager import ConfigManager
from core.reviews.backup import BackupManager
from core.reviews.store import ReviewStore


class LocalBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.manager('source')
        self.add_review(self.source,'original')
        task = self.source.jobs/'task1'; task.mkdir(parents=True)
        for name in ('input.xlsx','labels.xlsx','product_configs.json','analysis.log'):
            (task/name).write_text('task bytes',encoding='utf-8')
        report = self.root/'external report.xlsx'; report.write_bytes(b'report bytes')
        record = {'id':'task1','input':str(task/'input.xlsx'),'step1':str(task/'labels.xlsx'),
                  'config':str(task/'product_configs.json'),'log':str(task/'analysis.log'),
                  'source':str(self.root/'old-source.xlsx'),'report':str(report),'status':'done'}
        (self.source.jobs/'tasks.json').write_text(json.dumps([record]),encoding='utf-8')
        (self.source.root/'product_configs.json').write_text('{"restored":{}}',encoding='utf-8')

    def manager(self,name):
        home=self.root/name; home.mkdir()
        config=ConfigManager(str(home/'config.json'))
        config.update({'review_backup_dir':str(home/'backups'),'model_name':'backup-model'})
        return BackupManager(config,home/'reviews/data/reviews.db')

    def add_review(self,manager,content):
        store=ReviewStore(str(manager.db_path))
        try:store.add_reviews('B012345678','amazon.com',[{'review_id':content,'content':content}])
        finally:store.close()

    def contents(self,manager):
        store=ReviewStore(str(manager.db_path))
        try:return [row['content'] for row in store.query_reviews()]
        finally:store.close()

    def test_cross_computer_roundtrip_with_report_and_resume_paths(self):
        path,manifest=self.source.create()
        self.assertFalse(manifest['missing'])
        target=self.manager('target'); self.add_review(target,'current')
        target.stage_restore(path)
        self.assertEqual(self.contents(target),['current'])
        safety=target.apply_pending()
        self.assertTrue(safety.exists()); self.assertFalse(target.pending.exists())
        self.assertEqual(self.contents(target),['original'])
        records=json.loads((target.jobs/'tasks.json').read_text(encoding='utf-8'))
        for key in ('input','config','step1','report','log','source'):
            self.assertTrue(Path(records[0][key]).is_file(),key)
            self.assertTrue(Path(records[0][key]).is_relative_to(target.root),key)
        self.assertEqual(Path(records[0]['report']).read_bytes(),b'report bytes')
        self.assertEqual(Path(target.config.resolve_config('product_configs.json')).parent,target.root)

    def test_restored_task_can_generate_missing_output(self):
        records=json.loads((self.source.jobs/'tasks.json').read_text())
        records[0].update(status='running',step1=str(self.root/'not-yet-labels.xlsx'),report=str(self.root/'not-yet-report.xlsx'))
        (self.source.jobs/'tasks.json').write_text(json.dumps(records))
        path,manifest=self.source.create(); self.assertEqual(len(manifest['missing']),2)
        target=self.manager('target'); target.stage_restore(path);target.apply_pending()
        record=json.loads((target.jobs/'tasks.json').read_text(encoding='utf-8'))[0]
        self.assertEqual(record['status'],'stopped')
        self.assertTrue(Path(record['report']).parent.is_dir())
        self.assertTrue(Path(record['step1']).parent.is_dir())

    def test_archive_excludes_credentials(self):
        store=ReviewStore(str(self.source.db_path))
        store.set_setting('supabase_session','private-token');store.close()
        self.source.config._data['api_key']='private-model-key'
        path,_=self.source.create()
        with zipfile.ZipFile(path) as z:
            self.assertNotIn(b'private-model-key',z.read('preferences.json'))
            target=self.root/'database.db';target.write_bytes(z.read('database/reviews.db'))
        with closing(sqlite3.connect(target)) as c:
            self.assertIsNone(c.execute("SELECT value FROM settings WHERE key='supabase_session'").fetchone())

    def test_legacy_db_restores_reviews_and_keeps_analysis(self):
        self.source.stage_restore(self.source.db_path)
        self.add_review(self.source,'later')
        self.source.apply_pending()
        self.assertEqual(self.contents(self.source),['original'])
        self.assertTrue((self.source.jobs/'tasks.json').exists())

    def test_corrupt_file_is_rejected_before_live_changes(self):
        path,_=self.source.create()
        broken=self.root/'broken.zip'
        with zipfile.ZipFile(path) as original,zipfile.ZipFile(broken,'w') as out:
            for name in original.namelist():
                out.writestr(name,b'changed' if name=='analysis/tasks.json' else original.read(name))
        with self.assertRaisesRegex(ValueError,'校验失败'):self.source.stage_restore(broken)
        self.assertFalse(self.source.pending.exists());self.assertEqual(self.contents(self.source),['original'])

    def test_traversal_is_rejected(self):
        path=self.root/'unsafe.zip'
        with zipfile.ZipFile(path,'w') as z:z.writestr('../outside','no')
        with self.assertRaisesRegex(ValueError,'不安全'):self.source.stage_restore(path)
        self.assertFalse((self.root/'outside').exists())

    def test_failed_replace_rolls_back_original_database(self):
        path,_=self.source.create()
        target=self.manager('target');self.add_review(target,'current');target.stage_restore(path)
        original=Path.rename
        def fail(source,destination):
            if source.name=='analysis' and Path(destination)==target.jobs:raise OSError('simulated permission error')
            return original(source,destination)
        with patch.object(Path,'rename',fail):
            with self.assertRaises(OSError):target.apply_pending()
        self.assertEqual(self.contents(target),['current'])
        self.assertTrue(target.pending.exists())
        self.assertTrue(list(target.directory().glob('*before_restore*.zip')))

    def test_auto_retention_preserves_manual_and_safety_archives(self):
        manual,_=self.source.create();safety,_=self.source.create(kind='before_restore')
        for _ in range(3):self.source.create(kind='auto')
        self.source.prune_auto(2)
        self.assertEqual(len(list(self.source.directory().glob('*_auto_*.zip'))),2)
        self.assertTrue(manual.exists());self.assertTrue(safety.exists())

    def test_cancel_staged_restore(self):
        path,_=self.source.create();self.source.stage_restore(path)
        self.source.cancel_restore();self.assertFalse(self.source.pending.exists())
        self.assertEqual(self.contents(self.source),['original'])

    def test_archive_snapshot_has_valid_database(self):
        path,_=self.source.create()
        with zipfile.ZipFile(path) as z:
            target=self.root/'inspect.db';target.write_bytes(z.read('database/reviews.db'))
        with closing(sqlite3.connect(target)) as c:self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
