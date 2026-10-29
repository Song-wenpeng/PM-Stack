"""The pairing credential is machine-local: it must not travel in a backup."""
from tests import support

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from core.config_manager import ConfigManager
from core.reviews.backup import BackupManager, CREDENTIAL_SETTINGS, scrub_credentials
from core.reviews.store import ReviewStore

TOKEN = 'SECRET-PAIRING-TOKEN'


class BackupCredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def manager(self, name):
        home = self.root / name
        home.mkdir()
        config = ConfigManager(str(home / 'config.json'))
        config.update({'review_backup_dir': str(home / 'backups')})
        return BackupManager(config, home / 'reviews' / 'data' / 'reviews.db')

    def seed(self, manager):
        store = ReviewStore(str(manager.db_path))
        try:
            store.add_reviews('B012345678', 'amazon.com',
                              [{'review_id': 'r1', 'content': 'original'}])
            store.set_setting('extension_pairing_token', TOKEN)
            store.set_setting('theme_hint', 'keep-me')
        finally:
            store.close()

    def setting(self, db_path, key):
        with closing(sqlite3.connect(db_path)) as conn:
            row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def extract_db(self, archive, target):
        with zipfile.ZipFile(archive) as bundle:
            target.write_bytes(bundle.read('database/reviews.db'))
        return target

    def contents(self, manager):
        store = ReviewStore(str(manager.db_path))
        try:
            return [row['content'] for row in store.query_reviews()]
        finally:
            store.close()

    def test_new_backup_excludes_the_pairing_token(self):
        source = self.manager('source')
        self.seed(source)
        path, _ = source.create()
        staged = self.extract_db(path, self.root / 'staged.db')
        self.assertIsNone(self.setting(staged, 'extension_pairing_token'))
        self.assertEqual(self.setting(staged, 'theme_hint'), 'keep-me')

    def test_other_settings_and_review_data_survive_the_backup(self):
        source = self.manager('source')
        self.seed(source)
        path, manifest = source.create()
        self.assertFalse(manifest['missing'])
        staged = self.extract_db(path, self.root / 'kept.db')
        with closing(sqlite3.connect(staged)) as conn:
            rows = conn.execute('SELECT COUNT(*) FROM reviews').fetchone()[0]
        self.assertEqual(rows, 1)
        self.assertEqual(self.setting(staged, 'theme_hint'), 'keep-me')

    def test_scrub_credentials_removes_only_credentials(self):
        source = self.manager('scrub')
        self.seed(source)
        scrub_credentials(source.db_path)
        self.assertIsNone(self.setting(source.db_path, 'extension_pairing_token'))
        self.assertEqual(self.setting(source.db_path, 'theme_hint'), 'keep-me')
        self.assertEqual(self.contents(source), ['original'])

    def test_scrub_tolerates_a_database_without_settings(self):
        bare = self.root / 'bare.db'
        with closing(sqlite3.connect(bare)) as conn:
            conn.execute('CREATE TABLE reviews (id TEXT)')
            conn.commit()
        scrub_credentials(bare)  # must not raise
        self.assertTrue(bare.exists())

    def test_restore_of_legacy_backup_strips_the_token(self):
        """Archives made before the fix still carry the token; restore must clean it."""
        source = self.manager('legacy')
        self.seed(source)
        legacy_exclusions = tuple(item for item in ('supabase_', 'review_data_scope'))
        with patch('core.reviews.backup.EXCLUDED_SETTINGS', legacy_exclusions):
            path, _ = source.create()
        staged = self.extract_db(path, self.root / 'legacy-staged.db')
        self.assertEqual(self.setting(staged, 'extension_pairing_token'), TOKEN)

        target = self.manager('target')
        self.seed(target)
        self.assertEqual(self.setting(target.db_path, 'extension_pairing_token'), TOKEN)
        target.stage_restore(path)
        target.apply_pending()
        self.assertIsNone(self.setting(target.db_path, 'extension_pairing_token'))
        self.assertEqual(self.contents(target), ['original'])

    def test_credential_list_covers_the_pairing_token(self):
        self.assertIn('extension_pairing_token', CREDENTIAL_SETTINGS)

    def test_bridge_regenerates_a_token_after_scrub(self):
        source = self.manager('bridge')
        self.seed(source)
        scrub_credentials(source.db_path)
        from core.reviews.extension_bridge import ExtensionBridge
        bridge = ExtensionBridge(db_path=str(source.db_path))
        self.assertTrue(bridge.token)
        self.assertNotEqual(bridge.token, TOKEN)
        self.assertEqual(self.setting(source.db_path, 'extension_pairing_token'), bridge.token)


if __name__ == '__main__':
    unittest.main()
