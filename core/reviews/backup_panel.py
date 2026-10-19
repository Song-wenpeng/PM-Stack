"""Local backup, verification and restart recovery controls."""
from datetime import datetime
from pathlib import Path
from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QSpinBox, QLabel, QListWidget, QFileDialog, QMessageBox
from core.widgets import Card, FileDropLineEdit, LogConsole, make_button
from core.runner import ScriptRunner
from .backup import BackupManager
from .paths import LEGACY_DB_PATH


class BackupPanel(QWidget):
    def __init__(self, config_mgr, collection, parent=None):
        super().__init__(parent)
        self.config = config_mgr
        self.collection = collection
        self.manager = BackupManager(config_mgr)
        layout = QVBoxLayout(self)
        card = Card('本地备份与恢复', '备份评论数据库、分析记录、任务资料、报告和品类模板。恢复在下次启动时执行，并先备份当前数据。')
        row = QHBoxLayout()
        self.directory = FileDropLineEdit(want_dir=True, placeholder=str(self.manager.directory()))
        self.directory.setText(str(self.manager.directory()))
        row.addWidget(self.directory,1)
        for title, callback in [('浏览',self.choose_directory),('立即备份',self.backup),('打开目录',self.open_directory)]:
            button = make_button(title); button.clicked.connect(callback); row.addWidget(button)
        card.content_layout.addLayout(row)
        options = QHBoxLayout()
        self.auto = QCheckBox('每天首次空闲时自动备份')
        self.auto.setChecked(bool(self.config.get('review_auto_backup',True)))
        self.keep = QSpinBox(); self.keep.setRange(1,100); self.keep.setValue(int(self.config.get('review_backup_keep',10)))
        options.addWidget(self.auto); options.addWidget(QLabel('自动备份保留数量')); options.addWidget(self.keep); options.addStretch()
        card.content_layout.addLayout(options)
        self.auto.toggled.connect(self.save_options); self.keep.valueChanged.connect(self.save_options)
        self.directory.editingFinished.connect(self.save_options)
        self.list = QListWidget(); self.list.setMaximumHeight(150)
        card.content_layout.addWidget(self.list)
        actions = QHBoxLayout()
        for title, callback in [('刷新列表',self.refresh),('校验所选备份',self.verify),('恢复所选备份',self.restore_selected),('选择备份恢复',self.choose_restore),('取消待恢复',self.cancel_restore)]:
            button = make_button(title); button.clicked.connect(callback); actions.addWidget(button)
        card.content_layout.addLayout(actions)
        self.status = QLabel(); self.status.setWordWrap(True); card.content_layout.addWidget(self.status)
        note = QLabel('备份范围：评论分析资料；其他业务模块文件需另行保存。API 密钥、云端登录凭据和浏览器会话不进入备份，换电脑后需重新配置模型密钥。手动备份和恢复前备份不会自动清理。')
        note.setWordWrap(True); card.content_layout.addWidget(note)
        self.import_legacy_btn = make_button('导入旧 ReviewCollector 评论库')
        self.import_legacy_btn.setVisible(LEGACY_DB_PATH.exists())
        self.import_legacy_btn.clicked.connect(collection._import_legacy)
        card.content_layout.addWidget(self.import_legacy_btn)
        layout.addWidget(card)
        self.log = LogConsole(max_height=150); layout.addWidget(self.log); layout.addStretch()
        self._last_auto_attempt = ''
        self.timer = QTimer(self); self.timer.timeout.connect(self.auto_backup); self.timer.start(60000)
        QTimer.singleShot(10000,self.auto_backup)
        self.refresh()

    def busy(self):
        workflow = self.collection.parent()
        analysis_busy = any(getattr(workflow,key,None) for key in ('_active','_queue','_preparing','_worker'))
        return bool(analysis_busy or self.collection._workers or self.collection._collection_running or ScriptRunner.is_any_running())

    def save_options(self, *_):
        try:
            self.config.update({'review_backup_dir':self.directory.text().strip(),
                                'review_auto_backup':self.auto.isChecked(), 'review_backup_keep':self.keep.value()})
        except Exception as exc: self.log.append(str(exc))

    def choose_directory(self):
        path = QFileDialog.getExistingDirectory(self,'选择备份目录',self.directory.text())
        if path: self.directory.setText(path); self.save_options(); self.refresh()

    def open_directory(self):
        path = Path(self.directory.text()).expanduser().resolve(); path.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def refresh(self):
        self.list.clear()
        self.list.addItems([str(path) for path in self.manager.list_backups()])
        self.status.setText('已有待恢复备份。请关闭软件后重新启动。' if self.manager.pending.exists() else '评论数据保存在本机；恢复备份后自动加载本地评论和分析记录。')

    def backup(self, _checked=False, kind='manual'):
        if self.busy(): self.log.append('请等待采集、导入或分析任务完成，再进行备份。'); return
        self.save_options()
        keep = self.keep.value()
        self.collection._set_collection_running(True)
        def work(log):
            path, manifest = self.manager.create(kind=kind)
            if kind == 'auto': self.manager.prune_auto(keep)
            return path,manifest
        def done(result):
            self.collection._set_collection_running(False)
            path,manifest = result
            self.config.set('review_backup_last_date',datetime.now().strftime('%Y-%m-%d'))
            self.log.append(f'备份完成：{path}；分析任务 {manifest["tasks"]} 个。')
            if manifest['missing']: self.log.append(f'有 {len(manifest["missing"])} 个文件尚未生成或已不存在，详见备份清单。')
            self.log.set_status('ok'); self.refresh()
        started = self.collection._start_task('backup',work,done,self.log,
                    on_error=lambda message:self.collection._set_collection_running(False))
        if not started: self.collection._set_collection_running(False)

    def auto_backup(self):
        day = datetime.now().strftime('%Y-%m-%d')
        if (not self.auto.isChecked() or self.busy() or self.manager.pending.exists()
                or self._last_auto_attempt == day or self.config.get('review_backup_last_date') == day): return
        self._last_auto_attempt = day
        self.backup(kind='auto')

    def selected(self):
        item = self.list.currentItem()
        return item.text() if item else None

    def verify(self):
        path = self.selected()
        if not path: self.log.append('请先选择备份。'); return
        def done(manifest): self.log.append(f'备份校验通过：{manifest["created"]}，{manifest["tasks"]} 个分析任务。')
        self.collection._start_task('backup',lambda log:self.manager.inspect(path),done,self.log)

    def restore_selected(self):
        if self.selected(): self.restore(self.selected())
        else: self.log.append('请先选择备份。')

    def choose_restore(self):
        path,_ = QFileDialog.getOpenFileName(self,'选择本地备份',str(self.manager.directory()),'PM Stack 备份 (*.zip *.db)')
        if path: self.restore(path)

    def restore(self,path):
        if self.busy(): self.log.append('请等待正在运行的任务完成再恢复。'); return
        if QMessageBox.question(self,'恢复本地备份','恢复会替换当前评论数据库和备份中的分析资料。下次启动前会自动备份当前数据。是否安排恢复？') != QMessageBox.StandardButton.Yes: return
        def done(_): self.log.append('备份已校验并安排恢复，请关闭软件后重新启动。'); self.refresh()
        self.collection._start_task('backup',lambda log:self.manager.stage_restore(path),done,self.log)

    def cancel_restore(self):
        if self.busy(): return
        self.manager.cancel_restore(); self.refresh()
