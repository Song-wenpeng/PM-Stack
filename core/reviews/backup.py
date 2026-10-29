"""Versioned local review archives and startup-only recovery."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import uuid
import time
import zipfile
from datetime import datetime
from contextlib import closing

from .store import ReviewStore
from .paths import BACKUP_DIR, DATA_DIR

FORMAT = 1
TASK_PATHS = ('input', 'config', 'step1', 'report', 'log')
# 本机凭据不随备份外流：配对令牌保护的是本机回环服务，
# 谁拿到它就能冒充已授权的浏览器扩展。缺失时桥接会自动重新生成并重新配对。
CREDENTIAL_SETTINGS = ('extension_pairing_token',)
EXCLUDED_SETTINGS = ('supabase_', 'review_data_scope') + CREDENTIAL_SETTINGS
MAX_BYTES = 20 * 1024**3


def scrub_credentials(db_path):
    """删除数据库中的本机凭据设置，使恢复后的备份必须重新配对。"""
    with closing(sqlite3.connect(db_path)) as conn:
        try:
            for key in CREDENTIAL_SETTINGS:
                conn.execute('DELETE FROM settings WHERE key=?', (key,))
            conn.commit()
        except sqlite3.OperationalError:
            pass  # 很旧的数据库可能还没有 settings 表。


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def rename_file(source, target):
    # Windows scanners can briefly hold a freshly written file or directory.
    for attempt in range(6):
        try:
            return Path(source).rename(target)
        except PermissionError:
            if attempt == 5: raise
            time.sleep(0.1)


class BackupManager:
    def __init__(self, config_mgr, db_path=None):
        self.config = config_mgr
        self.root = Path(config_mgr.get_path()).parent.resolve()
        self.db_path = Path(db_path or DATA_DIR / 'reviews.db').resolve()
        self.jobs = self.root / 'comment_analysis'
        self.pending = self.root / 'pending_review_restore'

    def directory(self):
        directory = self.config.get('review_backup_dir')
        if not directory and self.db_path.exists():
            try:
                with closing(sqlite3.connect(self.db_path.as_uri()+'?mode=ro',uri=True)) as conn:
                    row = conn.execute("SELECT value FROM settings WHERE key='review_backup_dir'").fetchone()
                    if row: directory = row[0]
            except sqlite3.OperationalError:
                pass  # Old databases may not have a settings table yet.
        return Path(directory or BACKUP_DIR).expanduser().resolve()

    def create(self, directory=None, kind='manual'):
        directory = Path(directory or self.directory()).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        destination = directory / f'pmstack_reviews_{kind}_{stamp}.zip'
        pending_zip = destination.with_suffix('.partial')
        with tempfile.TemporaryDirectory(prefix='pmstack-backup-') as temporary:
            stage = Path(temporary)
            files = {}
            missing = []
            store = ReviewStore(str(self.db_path))
            try:
                store.backup_to(str(stage / 'reviews.db'))
            finally:
                store.close()
            with closing(sqlite3.connect(stage / 'reviews.db')) as conn:
                for row in list(conn.execute('SELECT key FROM settings')):
                    if row[0].startswith(EXCLUDED_SETTINGS):
                        conn.execute('DELETE FROM settings WHERE key=?', row)
                conn.commit()
                if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('评论数据库完整性检查失败')
            files['database/reviews.db'] = stage / 'reviews.db'
            records_path = self.jobs / 'tasks.json'
            records = json.loads(records_path.read_text(encoding='utf-8')) if records_path.exists() else []
            if not isinstance(records, list):
                raise ValueError('分析任务记录格式错误，已中止备份')
            path_map = {}
            if self.jobs.exists():
                for path in sorted(self.jobs.rglob('*')):
                    if path.is_file() and path.name != 'tasks.json':
                        if path.is_symlink(): raise ValueError('分析目录中包含符号链接')
                        archive = 'analysis/' + path.relative_to(self.jobs).as_posix()
                        files[archive] = path
                        path_map[str(path.resolve())] = archive
            for record in records:
                for key in TASK_PATHS:
                    value = record.get(key)
                    if not value: continue
                    path = Path(value).resolve()
                    if path.is_file():
                        if str(path) not in path_map:
                            archive = f'artifacts/{uuid.uuid4().hex}/{path.name}'
                            files[archive] = path
                            path_map[str(path)] = archive
                    elif key in ('input', 'config', 'step1', 'report'):
                        missing.append({'task': record.get('id'), 'field': key, 'path': str(path)})
            for record in records:
                for key in TASK_PATHS:
                    if record.get(key):
                        record[key] = path_map.get(str(Path(record[key]).resolve()), '')
                # The task's normalized input is sufficient to resume on another computer.
                record['source'] = record.get('input', '')
            (stage / 'tasks.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
            files['analysis/tasks.json'] = stage / 'tasks.json'
            template = Path(self.config.resolve_config('product_configs.json'))
            if template.is_file(): files['templates/product_configs.json'] = template
            preferences = {key: value for key, value in self.config.get_all().items()
                           if key in ('base_url', 'model_name', 'vision_base_url', 'vision_model_name', 'theme')}
            (stage / 'preferences.json').write_text(json.dumps(preferences, ensure_ascii=False), encoding='utf-8')
            files['preferences.json'] = stage / 'preferences.json'
            manifest = {'format': FORMAT, 'app_version': 'v1.10.16', 'kind': kind,
                        'created': datetime.now().isoformat(timespec='seconds'), 'tasks': len(records),
                        'missing': missing, 'files': {}}
            try:
                with zipfile.ZipFile(pending_zip, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                    for name, path in files.items():
                        # Copy first: hash and archive must refer to the same bytes.
                        snapshot = stage / ('copy-' + uuid.uuid4().hex)
                        shutil.copy2(path, snapshot)
                        manifest['files'][name] = {'sha256': digest(snapshot), 'size': snapshot.stat().st_size}
                        archive.write(snapshot, name)
                    archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
                self.inspect(pending_zip)
                os.replace(pending_zip, destination)
            finally:
                pending_zip.unlink(missing_ok=True)
        return destination, manifest

    @staticmethod
    def inspect(path, extract_to=None):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)): raise ValueError('备份包含重复文件')
            total = 0
            for info in archive.infolist():
                name = PurePosixPath(info.filename)
                if (name.is_absolute() or '..' in name.parts or '\\' in info.filename
                        or ':' in info.filename or not name.parts
                        or (info.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError('备份包含不安全路径')
                total += info.file_size
            if total > MAX_BYTES: raise ValueError('备份解压大小超过 20 GB')
            manifest_info = archive.getinfo('manifest.json')
            if manifest_info.file_size > 10 * 1024**2: raise ValueError('备份清单过大')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('format') != FORMAT: raise ValueError('不支持此备份格式')
            expected = manifest.get('files', {})
            if set(names) != set(expected) | {'manifest.json'}: raise ValueError('备份清单与内容不一致')
            if 'database/reviews.db' not in expected or 'analysis/tasks.json' not in expected:
                raise ValueError('备份缺少数据库或分析记录')
            for name, meta in expected.items():
                if not (name == 'database/reviews.db' or name == 'preferences.json'
                        or name == 'templates/product_configs.json'
                        or name.startswith(('analysis/', 'artifacts/'))):
                    raise ValueError('备份包含未知资料类型')
                value = hashlib.sha256()
                written = 0
                output = None
                try:
                    if extract_to:
                        target = Path(extract_to) / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        output = target.open('wb')
                    with archive.open(name) as source:
                        for block in iter(lambda: source.read(1024 * 1024), b''):
                            written += len(block); value.update(block)
                            if output: output.write(block)
                finally:
                    if output: output.close()
                if value.hexdigest() != meta['sha256'] or written != meta['size']:
                    raise ValueError('备份校验失败：' + name)
            return manifest

    def list_backups(self):
        return sorted(self.directory().glob('pmstack_reviews_*.zip'), key=lambda p: p.name, reverse=True)

    def prune_auto(self, keep=10):
        paths = sorted(self.directory().glob('pmstack_reviews_auto_*.zip'), key=lambda p:p.name, reverse=True)
        # Only archives generated by this feature are eligible; manual/safety backups remain.
        for path in paths[max(1, int(keep)):]:
            self.inspect(path)
            path.unlink()

    def stage_restore(self, path):
        if self.pending.exists(): raise ValueError('已有待恢复备份，请先重启完成或取消恢复')
        self.root.mkdir(parents=True, exist_ok=True)
        if Path(path).suffix.lower() == '.db':
            # A legacy DB restores reviews only; keep the current analysis files.
            with tempfile.TemporaryDirectory(prefix='pmstack-legacy-') as temporary:
                stage = Path(temporary)
                full, manifest = self.create(stage, kind='legacy_restore')
                snapshot = stage/'legacy.db'
                source = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
                target = sqlite3.connect(snapshot)
                try: source.backup(target)
                finally: source.close(); target.close()
                manifest['files']['database/reviews.db'] = {'size':snapshot.stat().st_size,'sha256':digest(snapshot)}
                converted = stage/'converted.zip'
                with zipfile.ZipFile(full) as old, zipfile.ZipFile(converted,'w',zipfile.ZIP_DEFLATED) as new:
                    for name in old.namelist():
                        if name not in ('manifest.json','database/reviews.db'): new.writestr(name,old.read(name))
                    new.write(snapshot,'database/reviews.db')
                    new.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
                return self.stage_restore(converted)
        with tempfile.TemporaryDirectory(prefix='pmstack-restore-', dir=self.root) as temporary:
            stage = Path(temporary)
            self.inspect(path, stage)
            database = stage / 'database/reviews.db'
            with closing(sqlite3.connect(database)) as conn:
                if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError('备份数据库损坏')
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'reviews','products','product_reviews','settings'}.issubset(tables): raise ValueError('不是 PM Stack 评论数据库')
                version = conn.execute('PRAGMA user_version').fetchone()[0]
                if version > 3: raise ValueError('备份数据库版本高于当前程序')
            records = json.loads((stage/'analysis/tasks.json').read_text(encoding='utf-8'))
            if not isinstance(records,list): raise ValueError('分析记录格式错误')
            expected = self.inspect(path)['files']
            for row in records:
                if not isinstance(row,dict) or not isinstance(row.get('id'),str): raise ValueError('分析记录格式错误')
                if not row['id'] or not all(c.isalnum() or c in '_-' for c in row['id']): raise ValueError('任务 ID 不安全')
                for key in TASK_PATHS + ('source',):
                    value = row.get(key)
                    if value and (not isinstance(value,str) or value not in expected or not value.startswith(('analysis/','artifacts/'))):
                        raise ValueError('分析记录引用不存在的备份文件')
            shutil.copy2(path, stage/'archive.zip')
            rename_file(stage,self.pending)
        return True

    def cancel_restore(self):
        if self.pending.exists(): shutil.rmtree(self.pending)

    def apply_pending(self):
        if not self.pending.exists(): return None
        self.inspect(self.pending/'archive.zip')
        # Re-extract the validated immutable archive; ignore modifications to staging files.
        with tempfile.TemporaryDirectory(prefix='pmstack-apply-', dir=self.root) as temporary:
            stage = Path(temporary)
            self.inspect(self.pending/'archive.zip', stage)
            # 旧备份可能仍带有配对令牌；在落回本机之前先清除。
            staged_db = stage/'database/reviews.db'
            if staged_db.exists():
                scrub_credentials(staged_db)
            safety, _ = self.create(kind='before_restore')
            records = json.loads((stage/'analysis/tasks.json').read_text(encoding='utf-8'))
            artifact_root = self.root / 'restored_review_files' / uuid.uuid4().hex
            for row in records:
                for key in TASK_PATHS + ('source',):
                    value = row.get(key)
                    if value:
                        parts = PurePosixPath(value).parts
                        target = self.jobs.joinpath(*parts[1:]) if parts[0] == 'analysis' else artifact_root.joinpath(*parts[1:])
                        row[key] = str(target)
                    elif key in ('report','step1','log'):
                        task = self.jobs / row['id']
                        if Path(row['id']).name != row['id'] or ':' in row['id']: raise ValueError('任务 ID 不安全')
                        row[key] = str(task / {'report':'report.xlsx','step1':'labels.xlsx','log':'analysis.log'}[key])
                if row.get('status') in ('running','queued'):
                    row.update(status='stopped', message='已从备份恢复，可继续分析。')
            (stage/'analysis/tasks.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
            moves = [(stage/'database/reviews.db', self.db_path), (stage/'analysis', self.jobs)]
            if (stage/'artifacts').exists(): moves.append((stage/'artifacts',artifact_root))
            template = stage/'templates/product_configs.json'
            if template.exists(): moves.append((template,self.root/'product_configs.json'))
            replaced = []
            try:
                for source, target in moves:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.is_symlink(): raise ValueError('恢复目标不能是符号链接')
                    original = stage / ('original-' + uuid.uuid4().hex)
                    existed = target.exists()
                    if existed: rename_file(target,original)
                    replaced.append((target, original, existed))
                    rename_file(source,target)
                # Old WAL files must not be applied to the restored database.
                for suffix in ('-wal','-shm'):
                    sidecar = Path(str(self.db_path)+suffix)
                    if sidecar.exists():
                        saved = stage / ('original-sidecar-' + uuid.uuid4().hex)
                        rename_file(sidecar,saved); replaced.append((sidecar,saved,True))
                preferences = json.loads((stage/'preferences.json').read_text(encoding='utf-8'))
                allowed = ('base_url','model_name','vision_base_url','vision_model_name','theme')
                self.config.update({k:v for k,v in preferences.items() if k in allowed})
            except Exception:
                for target, original, existed in reversed(replaced):
                    if target.exists():
                        if target.is_dir(): shutil.rmtree(target)
                        else: target.unlink()
                    if existed: rename_file(original,target)
                raise
        self.cancel_restore()
        return safety
