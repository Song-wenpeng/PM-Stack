"""PyQt6 UI for Amazon review collection, browsing, cloud sync, and export."""

from __future__ import annotations

import os
import json
import re
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.runner import ScriptRunner
from core.widgets import Card, FileDropLineEdit, LogConsole, configure_combo, make_button

from .config import DEFAULT_MARKETPLACE, MARKETPLACES, MAX_REVIEW_PAGES, MAX_REVIEWS_PER_STAR
from .exporter import export_reviews_for_analysis, fetch_all_reviews
from .detail_export import export_review_details
from .migration import IMPORT_MARKER, import_legacy_database
from .normalizer import extract_asin
from .paths import BACKUP_DIR, EXPORT_DIR, LEGACY_DB_PATH
from .repository import ReviewRepository
from .scraper import AmazonReviewScraper, CollectionCancelled
from .service import collect_product
from .store import ReviewStore
from .metadata import label_summary, review_extra_detail


_MARKETPLACE_LABELS = {
    "amazon.com": "美国 · amazon.com",
    "amazon.co.uk": "英国 · amazon.co.uk",
    "amazon.de": "德国 · amazon.de",
    "amazon.co.jp": "日本 · amazon.co.jp",
    "amazon.com.au": "澳洲 · amazon.com.au",
}


class _TaskThread(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    def __init__(self, target: Callable, parent=None):
        super().__init__(parent)
        self._target = target

    def run(self):
        try:
            self.result.emit(self._target(self.log_signal.emit))
        except Exception as exc:
            self.log_signal.emit(traceback.format_exc())
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class ReviewCollectionPanel(QWidget):
    """A nested submodule hosted by the existing comment-analysis page."""

    analysis_requested = pyqtSignal(str)

    def __init__(self, config_mgr, runner, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self.runner = runner
        self._workers: Dict[str, _TaskThread] = {}
        self._cancel_event = threading.Event()
        self._cloud_cancel_event = threading.Event()
        self._cloud_running = False
        self._collection_running = False
        self._extension_job_id = None
        self._extension_last_event = None
        self._product_rows = []
        self._review_rows = []
        self._build_ui()
        self._load_cloud_settings()
        self._extension_timer = QTimer(self)
        self._extension_timer.timeout.connect(self._poll_extension_job)
        self._extension_timer.start(500)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        tabs = QTabWidget()
        tabs.addTab(self._build_collect_page(), "评论采集")
        tabs.addTab(self._build_library_page(), "评论库")
        tabs.addTab(self._build_cloud_page(), "云端与备份")
        layout.addWidget(tabs)
        self.inner_tabs = tabs

    def _build_collect_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        card = Card(
            "Amazon 评论采集",
            "从浏览器采集或导入 Excel，结果统一进入评论库并自动去重。",
        )
        form = QFormLayout()
        form.setSpacing(10)
        self.collect_engine = configure_combo(QComboBox())
        self.collect_engine.addItem("日常浏览器 · 复用登录（推荐）", "extension")
        self.collect_engine.addItem("采集专用 Edge · 独立登录", "dedicated")
        self.collect_engine.addItem("Excel 导入 · 卖家精灵 / 本地文件", "excel")
        form.addRow("数据来源:", self.collect_engine)
        from .extension_panel import ExtensionPanel
        self.extension_panel = ExtensionPanel(self)
        form.addRow(self.extension_panel)
        from .excel_options import ExcelImportOptions
        self.excel_options = ExcelImportOptions(self.config_mgr,self)
        form.addRow(self.excel_options)
        self.excel_options.path.textChanged.connect(self._excel_path_changed)
        self.excel_options.ai.toggled.connect(self._apply_collection_method)
        self.collect_asins = QPlainTextEdit()
        self.collect_asins.setPlaceholderText("输入 ASIN 或 Amazon 商品链接，多个可用空格、逗号或换行分隔")
        self.collect_asins.setMaximumHeight(78)
        form.addRow("ASIN / 链接:", self.collect_asins)

        self.marketplace = configure_combo(QComboBox())
        self.marketplace.setMinimumContentsLength(18)
        for key in MARKETPLACES:
            self.marketplace.addItem(_MARKETPLACE_LABELS.get(key, key), key)
        default_index = self.marketplace.findData(DEFAULT_MARKETPLACE)
        self.marketplace.setCurrentIndex(max(0, default_index))
        form.addRow("站点:", self.marketplace)
        self.advanced_options = QWidget()
        options = QHBoxLayout(self.advanced_options)
        options.setContentsMargins(0, 0, 0, 0)
        options.setSpacing(8)
        self.collect_mode = configure_combo(QComboBox())
        self.collect_mode.addItem("按星级采集", "star")
        self.collect_mode.addItem("按时间采集", "flat")
        self.collect_pages = QSpinBox()
        self.collect_pages.setRange(1, 100)
        self.collect_pages.setValue(MAX_REVIEW_PAGES)
        self.collect_pages.setMinimumWidth(76)
        self.collect_max = QSpinBox()
        self.collect_max.setRange(1, 5000)
        self.collect_max.setValue(MAX_REVIEWS_PER_STAR)
        self.collect_max.setMinimumWidth(92)
        for caption, widget in (
            ("模式", self.collect_mode),
            ("页数", self.collect_pages),
            ("每星级上限", self.collect_max),
        ):
            options.addWidget(QLabel(caption))
            options.addWidget(widget)
            options.addSpacing(16)
        options.addStretch()
        form.addRow(self.advanced_options)
        self.collect_hint = QLabel()
        self.collect_hint.setWordWrap(True)
        form.addRow(self.collect_hint)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.collect_new_btn = make_button("首次采集", "primary")
        self.collect_new_btn.clicked.connect(lambda: self._start_collection(False))
        self.collect_update_btn = make_button("增量采集")
        self.collect_update_btn.clicked.connect(lambda: self._start_collection(True))
        self.collect_stop_btn = make_button("停止", "danger")
        self.collect_stop_btn.setEnabled(False)
        self.collect_stop_btn.clicked.connect(self._stop_collection)
        actions.addWidget(self.collect_new_btn)
        actions.addWidget(self.collect_update_btn)
        actions.addWidget(self.collect_stop_btn)
        actions.addStretch()
        form.addRow(actions)
        card.content_layout.addLayout(form)
        layout.addWidget(card)
        self.collect_log = LogConsole(max_height=260)
        layout.addWidget(self.collect_log)
        self.collect_engine.currentIndexChanged.connect(self._apply_collection_method)
        self._apply_collection_method()
        layout.addStretch()
        return page

    def _build_library_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        product_card = Card("商品与评论", "在线时优先查询 Supabase；不可用时自动回退本地缓存。")
        product_actions = QHBoxLayout()
        refresh_btn = make_button("刷新")
        refresh_btn.clicked.connect(self.refresh_products)
        product_actions.addWidget(refresh_btn)
        manage_btn = make_button("导入记录 · 纠错 / 移除")
        manage_btn.clicked.connect(self._manage_imports)
        product_actions.addWidget(manage_btn)
        self.library_status = QLabel("尚未查询")
        self.library_status.setObjectName("CardSubtitle")
        product_actions.addWidget(self.library_status)
        product_actions.addStretch()
        product_card.content_layout.addLayout(product_actions)

        self.products_table = self._make_table(
            ["ASIN", "站点", "小类目", "评论数", "均分", "最近采集", "标题"]
        )
        self.products_table.setMaximumHeight(170)
        self.products_table.itemSelectionChanged.connect(self.refresh_reviews)
        product_card.content_layout.addWidget(self.products_table)
        layout.addWidget(product_card)

        review_card = Card("评论查询", "选择商品后可按星级和关键词筛选；不选择商品则查询整个工作区。")
        filters = QHBoxLayout()
        self.rating_filter = configure_combo(QComboBox())
        self.rating_filter.addItem("全部星级", None)
        for star in range(5, 0, -1):
            self.rating_filter.addItem(f"{star} 星", star)
        filters.addWidget(self.rating_filter)
        self.keyword_filter = QLineEdit()
        self.keyword_filter.setPlaceholderText("标题或正文关键词")
        filters.addWidget(self.keyword_filter, 1)
        self.query_limit = QSpinBox()
        self.query_limit.setRange(1, 5000)
        self.query_limit.setValue(500)
        self.query_limit.setPrefix("显示 ")
        filters.addWidget(self.query_limit)
        query_btn = make_button("查询")
        query_btn.clicked.connect(self.refresh_reviews)
        filters.addWidget(query_btn)
        export_btn = make_button("导出 Excel")
        export_btn.clicked.connect(lambda: self._export_reviews(False))
        filters.addWidget(export_btn)
        analyze_btn = make_button("发送到一键分析", "primary")
        analyze_btn.clicked.connect(lambda: self._export_reviews(True))
        filters.addWidget(analyze_btn)
        review_card.content_layout.addLayout(filters)

        self.reviews_table = self._make_table(
            ["星级", "来源筛选", "日期", "评论者", "标题", "正文预览", "AI 标签"]
        )
        self.reviews_table.itemDoubleClicked.connect(self._show_review_detail)
        review_card.content_layout.addWidget(self.reviews_table)
        layout.addWidget(review_card, 1)
        return page

    def _build_cloud_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        cloud = Card(
            "Supabase 云端",
            "使用 Authentication 用户和 publishable/anon key；请勿填写 service_role key。密码不会保存。",
        )
        form = QFormLayout()
        self.cloud_url = QLineEdit()
        self.cloud_url.setPlaceholderText("https://xxxx.supabase.co")
        form.addRow("项目 URL:", self.cloud_url)
        self.cloud_key = QLineEdit()
        self.cloud_key.setPlaceholderText("sb_publishable_... 或 anon key")
        form.addRow("可发布密钥:", self.cloud_key)
        account = QHBoxLayout()
        self.cloud_email = QLineEdit()
        self.cloud_email.setPlaceholderText("邮箱")
        self.cloud_password = QLineEdit()
        self.cloud_password.setPlaceholderText("密码（不保存）")
        self.cloud_password.setEchoMode(QLineEdit.EchoMode.Password)
        account.addWidget(self.cloud_email)
        account.addWidget(self.cloud_password)
        form.addRow("账号:", account)
        actions = QHBoxLayout()
        login_btn = make_button("登录并同步", "primary")
        login_btn.clicked.connect(self._cloud_login)
        sync_btn = make_button("同步全部待处理")
        sync_btn.clicked.connect(self._cloud_sync)
        logout_btn = make_button("退出登录", "danger")
        logout_btn.clicked.connect(self._cloud_logout)
        actions.addWidget(login_btn)
        actions.addWidget(sync_btn)
        actions.addWidget(logout_btn)
        self._cloud_buttons=[login_btn,sync_btn,logout_btn]
        self.cloud_stop_btn=make_button("停止同步")
        self.cloud_stop_btn.setEnabled(False)
        self.cloud_stop_btn.clicked.connect(self._cloud_cancel_event.set)
        actions.addWidget(self.cloud_stop_btn)
        self.cloud_status = QLabel("")
        actions.addStretch()
        actions.addWidget(self.cloud_status)
        form.addRow(actions)
        cloud.content_layout.addLayout(form)
        layout.addWidget(cloud)

        backup = Card("本地缓存与迁移", "备份使用 SQLite 在线备份，不会移动或删除原数据库。")
        backup_row = QHBoxLayout()
        self.backup_dir = FileDropLineEdit(want_dir=True, placeholder=str(BACKUP_DIR))
        backup_row.addWidget(self.backup_dir, 1)
        browse_btn = make_button("浏览")
        browse_btn.clicked.connect(self._choose_backup_dir)
        backup_row.addWidget(browse_btn)
        backup_btn = make_button("立即备份")
        backup_btn.clicked.connect(self._backup_local)
        backup_row.addWidget(backup_btn)
        self.import_legacy_btn = make_button("导入旧 ReviewCollector 评论库")
        self.import_legacy_btn.clicked.connect(self._import_legacy)
        self.import_legacy_btn.setVisible(LEGACY_DB_PATH.exists())
        backup_row.addWidget(self.import_legacy_btn)
        backup.content_layout.addLayout(backup_row)
        layout.addWidget(backup)
        self.cloud_log = LogConsole(max_height=240)
        layout.addWidget(self.cloud_log)
        layout.addStretch()
        return page

    @staticmethod
    def _make_table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def _start_task(
        self,
        key: str,
        target: Callable,
        on_result: Callable,
        log_console: Optional[LogConsole] = None,
        on_error: Optional[Callable] = None,
    ) -> bool:
        if key in self._workers:
            return False
        worker = _TaskThread(target, self)
        if log_console:
            worker.log_signal.connect(log_console.append)
        worker.result.connect(on_result)

        def failed(message):
            if log_console:
                log_console.append(f"[错误] {message}")
                log_console.set_status("error")
            if on_error:
                on_error(message)

        def finished():
            self._workers.pop(key, None)
            worker.deleteLater()

        worker.failed.connect(failed)
        worker.finished.connect(finished)
        self._workers[key] = worker
        worker.start()
        return True

    def _parse_asins(self):
        tokens = re.split(r"[\s,，;；]+", self.collect_asins.toPlainText().strip())
        result = []
        for token in tokens:
            asin = extract_asin(token)
            if asin and asin not in result:
                result.append(asin)
        invalid = [asin for asin in result if not re.fullmatch(r"[A-Z0-9]{10}", asin)]
        if not result or invalid:
            raise ValueError("请输入有效的 10 位 ASIN 或 Amazon 商品链接")
        return result

    def _excel_path_changed(self, value):
        from .excel_import import filename_asin
        candidate = filename_asin(value)
        if candidate:
            self.collect_asins.setPlainText(candidate)

    def _apply_collection_method(self):
        engine = self.collect_engine.currentData()
        extension, excel = engine == "extension", engine == "excel"
        self.extension_panel.setVisible(extension)
        self.excel_options.setVisible(excel)
        self.advanced_options.setVisible(engine == "dedicated")
        self.collect_update_btn.setVisible(engine == "dedicated")
        self.collect_new_btn.setText(
            ("导入并提取标签" if self.excel_options.ai.isChecked() else "导入评论") if excel else
            ("采集最新一页" if extension else "首次采集"))
        self.collect_stop_btn.setText("停止" if engine != "extension" else "取消任务")
        self.collect_asins.setPlaceholderText(
            "导出目标商品 ASIN（可从文件名自动识别），不会替换评论链接中的变体 ASIN" if excel else
            ("输入一个 ASIN 或 Amazon 商品链接" if extension else
             "输入 ASIN 或 Amazon 商品链接，多个可用空格、逗号或换行分隔"))
        self.collect_hint.setText(
            "Excel：先入库，再按所选品类提取标签；重复执行复用成功结果。停止后保留已导入评论和已完成标签。" if excel else
            ("日常浏览器：一个商品、最新一页；扩展中可立即检查任务。自动去重，不自动上传云端。"
             if extension else "专用 Edge：支持多商品、按星级或时间采集；需要在专用浏览器中登录。"))

    def _start_excel_collection(self):
        from .excel_import import read_import, import_reviews, extract_labels
        path = self.excel_options.path.text().strip()
        asin = self.collect_asins.toPlainText().strip()
        marketplace = self.marketplace.currentData()
        ai, sync = self.excel_options.ai.isChecked(), self.excel_options.sync.isChecked()
        category = self.excel_options.category.currentData()
        config = self.excel_options.configs.get(category)
        env = self.config_mgr.get_env_dict()
        if not path:
            self.collect_log.append("[提示] 请先选择评论 Excel 文件")
            return
        if ai and (not config or not (env.get("API_KEY") or env.get(env.get("API_ENV_NAME","SILICONFLOW_API_KEY")))):
            self.collect_log.append("[提示] 请先配置模型密钥和品类模板；也可取消提取标签，先导入评论。")
            return
        self._cancel_event.clear()
        self.collect_log.clear()
        self.collect_log.set_status("running")
        self._set_collection_running(True)
        def target(log):
            data = read_import(path,asin,marketplace)
            log(f"[文件] {data['row_count']} 条，唯一评论 {data['unique_count']} 条，文件内重复 {data['file_duplicates']} 条")
            log("[变体来源] "+json.dumps(data["variants"],ensure_ascii=False))
            for warning in data["warnings"][:10]: log("[提示] "+warning)
            if self._cancel_event.is_set(): raise CollectionCancelled("已停止，未导入")
            store = ReviewStore()
            repository = None
            try:
                new, duplicates = import_reviews(store,data,log)
                stats = extract_labels(store,data,category,config,env,
                        stop=self._cancel_event.is_set,log=log) if ai else None
                result = {"new":new,"duplicates":duplicates,"labels":stats,"sync":None}
                if sync and not self._cancel_event.is_set():
                    repository = ReviewRepository(store)
                    result["sync"] = repository.sync_pending(limit=200,force=True,stop=self._cancel_event.is_set,progress=log)
                return result
            finally:
                if repository: repository.close()
                store.close()
        def done(result):
            self._set_collection_running(False)
            self.collect_log.append(f"[导入完成] 新增 {result['new']}，重复 {result['duplicates']}")
            labels = result["labels"]
            if labels:
                self.collect_log.append(f"[标签] 新提取 {labels['success']}，复用 {labels['cached']}，失败 {labels['failed']}，未处理 {labels.get('pending',0)}")
            cloud = result["sync"]
            if cloud:
                self.collect_log.append(f"[同步] 成功 {cloud['synced']} 批，剩余 {cloud['remaining']} 批；{cloud['error']}")
            elif sync:
                self.collect_log.append("[同步] 已停止，成功结果留在本地待同步队列")
            failed = bool((labels and (labels["failed"] or labels["cancelled"])) or (cloud and cloud["error"]))
            self.collect_log.set_status("error" if failed else "ok")
            self.refresh_products()
        started = self._start_task("collect",target,done,self.collect_log,
                                  on_error=lambda message:self._set_collection_running(False))
        if not started: self._set_collection_running(False)

    def _set_collection_running(self, running: bool):
        self.excel_options.setEnabled(not running)
        self._collection_running = running
        self.collect_new_btn.setEnabled(not running)
        self.collect_update_btn.setEnabled(not running)
        self.collect_stop_btn.setEnabled(running)
        for widget in (self.collect_engine, self.collect_asins, self.marketplace,
                       self.collect_mode, self.collect_pages, self.collect_max):
            widget.setEnabled(not running)

    def _start_extension_collection(self):
        try:
            bridge = self.extension_panel.bridge
            if not bridge or not bridge.snapshot()["connected"]:
                raise ValueError("请先点击“连接扩展 / 复制连接码”，在浏览器扩展里粘贴并连接。")
            value = self.collect_asins.toPlainText().strip()
            if len(re.split(r"[\s,，;；]+", value)) != 1:
                raise ValueError("日常浏览器目前每次采集一个商品，请只输入一个链接或 ASIN。")
            job = bridge.submit(value, self.marketplace.currentData())
        except ValueError as exc:
            self.collect_log.append(f"[提示] {exc}")
            return
        self._extension_job_id = job["id"]
        self._extension_last_event = None
        self.collect_log.clear()
        self.collect_log.set_status("running")
        self.collect_log.append(f"[日常浏览器] {job['marketplace']} / {job['asin']} · 最新一页")
        self._set_collection_running(True)
        self._poll_extension_job()

    def _poll_extension_job(self):
        if not self._extension_job_id:
            return
        bridge = self.extension_panel.bridge
        job = bridge.snapshot()["job"] if bridge else None
        if not job or job["id"] != self._extension_job_id:
            self.collect_log.append("[停止] 扩展连接已断开，当前任务已取消。")
            self.collect_log.set_status("error")
            self._extension_job_id = None
            self._set_collection_running(False)
            return
        event = (job["status"], job["message"])
        if event != self._extension_last_event:
            self.collect_log.append(job["message"])
            self._extension_last_event = event
        if job["status"] in ("done", "error", "cancelled"):
            self._extension_job_id = None
            self._set_collection_running(False)
            self.collect_log.set_status("ok" if job["status"] == "done" else "error")
            if job["status"] == "done":
                self.refresh_products()

    def _start_collection(self, incremental: bool):
        if self._collection_running:
            return
        if ScriptRunner.is_any_running():
            self.collect_log.append("[提示] 当前有分析任务正在运行，请等待完成。")
            return
        if self.collect_engine.currentData() == "excel":
            self._start_excel_collection()
            return
        if self.collect_engine.currentData() == "extension":
            self._start_extension_collection()
            return
        try:
            asins = self._parse_asins()
        except ValueError as exc:
            self.collect_log.append(f"[提示] {exc}")
            return
        marketplace = self.marketplace.currentData() or DEFAULT_MARKETPLACE
        mode = self.collect_mode.currentData()
        pages = self.collect_pages.value()
        maximum = self.collect_max.value()
        self._cancel_event.clear()
        self.collect_log.clear()
        self.collect_log.set_status("running")
        self._set_collection_running(True)

        def target(log):
            store = ReviewStore()
            repository = ReviewRepository(store)
            scraper = AmazonReviewScraper(
                marketplace=marketplace,
                headless=False,
                should_stop=self._cancel_event.is_set,
                log_callback=log,
            )
            totals = {"products": 0, "new": 0, "duplicates": 0, "cancelled": False}
            try:
                for index, asin in enumerate(asins, 1):
                    if self._cancel_event.is_set():
                        raise CollectionCancelled("用户已停止评论采集")
                    log(f"\n>>> 商品 {index}/{len(asins)}: {asin}")
                    new_count, duplicate_count = collect_product(
                        store,
                        scraper,
                        asin,
                        marketplace,
                        pages,
                        maximum,
                        incremental,
                        mode=mode,
                        repository=repository,
                        log_callback=log,
                    )
                    totals["products"] += 1
                    totals["new"] += new_count
                    totals["duplicates"] += duplicate_count
            except CollectionCancelled:
                totals["cancelled"] = True
            finally:
                scraper.close()
                repository.close()
                store.close()
            return totals

        started = self._start_task(
            "collect",
            target,
            self._collection_finished,
            self.collect_log,
            on_error=lambda _message: self._set_collection_running(False),
        )
        if not started:
            self._set_collection_running(False)
            self.collect_log.append("[提示] 上一个采集任务正在结束，请稍后重试。")

    def _stop_collection(self):
        if self._extension_job_id:
            if self.extension_panel.bridge:
                self.extension_panel.bridge.cancel()
            self._poll_extension_job()
            return
        self._cancel_event.set()
        self.collect_stop_btn.setEnabled(False)
        self.collect_log.append("[停止] 已请求停止，将在当前浏览器操作结束后退出。")

    def _collection_finished(self, result):
        self._set_collection_running(False)
        if result["cancelled"]:
            self.collect_log.append("[停止] 评论采集已停止。")
            self.collect_log.set_status("error")
        else:
            self.collect_log.append(
                f"\n[完成] 商品 {result['products']} 个，新增 {result['new']} 条，重复 {result['duplicates']} 条"
            )
            self.collect_log.set_status("ok")
        self.refresh_products()

    def _manage_imports(self):
        if self._collection_running or any(w.isRunning() for w in self._workers.values()):
            QMessageBox.information(self,"请稍候","请等待当前任务结束后再管理导入记录。")
            return
        from .import_manager import ImportManagerDialog
        dialog = ImportManagerDialog(self)
        dialog.exec()
        self.refresh_products()

    def _selected_product(self):
        row = self.products_table.currentRow()
        if row < 0 or row >= len(self._product_rows):
            return None
        return self._product_rows[row]

    def refresh_products(self):
        self.library_status.setText("正在读取…")

        def target(_log):
            repository = ReviewRepository()
            try:
                products, source = repository.product_stats()
                total, total_source = repository.total_reviews()
                return products, total, source, total_source, repository.cloud_error
            finally:
                repository.close()

        self._start_task(
            "products",
            target,
            self._products_loaded,
            on_error=lambda message: self.library_status.setText(message),
        )

    def _products_loaded(self, payload):
        products, total, source, total_source, cloud_error = payload
        self._product_rows = products
        self.products_table.setRowCount(len(products))
        for row_index, product in enumerate(products):
            values = [
                product.get("asin", ""),
                product.get("marketplace", ""),
                product.get("category_name", ""),
                product.get("review_count", 0),
                product.get("avg_rating", ""),
                product.get("last_scraped_at", ""),
                product.get("title", ""),
            ]
            for column, value in enumerate(values):
                self.products_table.setItem(row_index, column, QTableWidgetItem(str(value or "")))
        status = f"{total_source}共 {total} 条；商品列表来自 {source}"
        if cloud_error:
            status += f"；云端回退原因：{cloud_error}"
        self.library_status.setText(status)

    def _current_filters(self):
        product = self._selected_product()
        return {
            "asin": product.get("asin") if product else None,
            "rating": self.rating_filter.currentData(),
            "keyword": self.keyword_filter.text().strip(),
        }

    def refresh_reviews(self):
        filters = self._current_filters()
        limit = self.query_limit.value()
        self.library_status.setText("正在查询评论…")

        def target(_log):
            repository = ReviewRepository()
            try:
                rows, source = repository.query_reviews(**filters, limit=limit)
                return rows, source, repository.cloud_error
            finally:
                repository.close()

        self._start_task(
            "reviews",
            target,
            self._reviews_loaded,
            on_error=lambda message: self.library_status.setText(message),
        )

    def _reviews_loaded(self, payload):
        rows, source, cloud_error = payload
        self._review_rows = rows
        self.reviews_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("rating", ""),
                row.get("star_filter", ""),
                row.get("review_date") or row.get("review_date_raw") or "",
                row.get("reviewer_name", ""),
                row.get("title", ""),
                row.get("content", "")[:180],
                label_summary(row),
            ]
            for column, value in enumerate(values):
                self.reviews_table.setItem(row_index, column, QTableWidgetItem(str(value or "")))
        status = f"显示 {len(rows)} 条，来源：{source}"
        if cloud_error:
            status += f"；云端回退原因：{cloud_error}"
        self.library_status.setText(status)

    def _show_review_detail(self, item):
        row_index = item.row()
        if not 0 <= row_index < len(self._review_rows):
            return
        row = self._review_rows[row_index]
        QMessageBox.information(
            self,
            "评论详情",
            f"评论者：{row.get('reviewer_name', '')}\n"
            f"星级：{row.get('rating', '')}\n"
            f"日期：{row.get('review_date') or row.get('review_date_raw') or ''}\n"
            f"标题：{row.get('title', '')}\n\n"
            f"{row.get('content', '')}\n\n"
            f"链接：{row.get('review_url', '')}\n\n"
            + review_extra_detail(row),
        )

    def _export_reviews(self, for_analysis: bool):
        default_name = f"评论分析输入_{datetime.now():%Y%m%d_%H%M%S}.xlsx" if for_analysis else f"评论明细含AI结果_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存评论分析文件",
            str(EXPORT_DIR / default_name),
            "Excel (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        filters = self._current_filters()
        self.library_status.setText("正在导出全部匹配评论…")

        def target(_log):
            repository = ReviewRepository()
            try:
                rows, source = repository.export_snapshot(**filters)
                destination = export_reviews_for_analysis(rows, path) if for_analysis else export_review_details(rows, path)
                return destination, len(rows), source
            finally:
                repository.close()

        def done(payload):
            destination, count, source = payload
            self.library_status.setText(f"已从 {source} 导出 {count} 条：{destination}")
            if for_analysis:
                self.analysis_requested.emit(destination)
            else:
                QMessageBox.information(self, "导出成功", f"已导出 {count} 条评论：\n{destination}")

        self._start_task(
            "export",
            target,
            done,
            on_error=lambda message: self.library_status.setText(message),
        )

    def _load_cloud_settings(self):
        store = ReviewStore()
        try:
            self.cloud_url.setText(store.get_setting("supabase_url", "") or "")
            self.cloud_key.setText(store.get_setting("supabase_key", "") or "")
            self.cloud_email.setText(store.get_setting("supabase_email", "") or "")
            self.backup_dir.setText(store.get_setting("review_backup_dir", "") or "")
            self._update_cloud_status(store)
            imported = bool(store.get_setting(IMPORT_MARKER, ""))
            self.import_legacy_btn.setEnabled(not imported)
            if imported:
                self.import_legacy_btn.setText("旧评论库已导入")
        finally:
            store.close()

    def _update_cloud_status(self, store=None):
        owns_store = store is None
        store = store or ReviewStore()
        try:
            stats = store.outbox_stats()
            logged_in = bool(store.get_setting("supabase_session", ""))
            self.cloud_status.setText(
                ("已保存会话（联网时验证）" if logged_in else "未保存登录会话，请重新登录")
                + f"；待同步 {stats['pending'] + stats['failed'] + stats['syncing']} 个任务"
            )
        finally:
            if owns_store:
                store.close()

    def _set_cloud_running(self,running):
        self._cloud_running=running
        for button in self._cloud_buttons:button.setEnabled(not running)
        self.cloud_stop_btn.setEnabled(running)
        for field in (self.cloud_url,self.cloud_key,self.cloud_email,self.cloud_password):
            field.setEnabled(not running)

    def _cloud_done(self,result,workspace=""):
        self._set_cloud_running(False)
        self.cloud_password.clear()
        prefix=f"已登录工作区 {workspace[:8]}…；" if workspace else ""
        message=prefix+f"已同步 {result['synced']} 个任务，失败 {result['failed']}，待处理 {result['remaining']}"
        if result.get("cancelled"):message+="；已停止，未完成任务下次继续"
        if result.get("error"):message+="；"+result["error"]
        elif result["remaining"] and not result.get("cancelled"):message+="；新增或等待中的任务可再次同步"
        self.cloud_log.append(message)
        self.cloud_log.set_status("error" if result.get("error") else "ok")
        self._update_cloud_status()

    def _cloud_failed(self,message):
        self._set_cloud_running(False)
        self.cloud_password.clear()
        self._update_cloud_status()

    def _cloud_login(self):
        if self._cloud_running:return
        url=self.cloud_url.text().strip();key=self.cloud_key.text().strip()
        email=self.cloud_email.text().strip();password=self.cloud_password.text()
        missing=[name for name,value in (("项目 URL",url),("可发布密钥",key),("邮箱",email),("密码",password)) if not value]
        if missing:
            self.cloud_log.append("[提示] 尚未填写："+ "、".join(missing))
            return
        self._cloud_cancel_event.clear();self._set_cloud_running(True)
        self.cloud_log.set_status("running");self.cloud_status.setText("正在登录并校验会话…")
        def target(log):
            repository=ReviewRepository()
            try:
                workspace=repository.login(url,key,email,password)
                log("登录及本地会话保存已验证，开始同步全部待处理任务")
                result=repository.sync_pending(limit=200,force=True,stop=self._cloud_cancel_event.is_set,progress=log)
                return workspace,result
            finally:repository.close()
        started=self._start_task("cloud",target,lambda payload:self._cloud_done(payload[1],payload[0]),self.cloud_log,on_error=self._cloud_failed)
        if not started:self._set_cloud_running(False)

    def _cloud_sync(self):
        if self._cloud_running:return
        self._cloud_cancel_event.clear();self._set_cloud_running(True)
        self.cloud_log.set_status("running");self.cloud_status.setText("正在恢复会话并同步…")
        def target(log):
            repository=ReviewRepository()
            try:
                return repository.sync_pending(limit=200,force=True,stop=self._cloud_cancel_event.is_set,progress=log)
            finally:repository.close()
        started=self._start_task("cloud",target,self._cloud_done,self.cloud_log,on_error=self._cloud_failed)
        if not started:self._set_cloud_running(False)

    def _cloud_logout(self):
        repository = ReviewRepository()
        try:
            repository.logout()
            self.cloud_password.clear()
            self.cloud_log.append("Supabase 会话已清除；未同步数据仍保留在本地队列。")
            self._update_cloud_status()
        except Exception as exc:
            self.cloud_log.append(f"退出登录失败：{exc}")
        finally:
            repository.close()

    def _choose_backup_dir(self):
        selected = QFileDialog.getExistingDirectory(self, "选择评论库备份目录")
        if selected:
            self.backup_dir.setText(selected)

    def _backup_local(self):
        directory = Path(self.backup_dir.text().strip() or BACKUP_DIR).expanduser().resolve()
        self.cloud_log.set_status("running")

        def target(_log):
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / f"reviews_backup_{datetime.now():%Y%m%d_%H%M%S}.db"
            store = ReviewStore()
            try:
                size = store.backup_to(str(destination))
                store.set_setting("review_backup_dir", str(directory))
                integrity = store.integrity_check()
                return str(destination), size, integrity
            finally:
                store.close()

        def done(payload):
            destination, size, integrity = payload
            self.cloud_log.append(
                f"[备份] {destination}（{size / 1024 / 1024:.2f} MB，完整性：{integrity}）"
            )
            self.cloud_log.set_status("ok")

        self._start_task("backup", target, done, self.cloud_log)

    def _import_legacy(self):
        if not LEGACY_DB_PATH.exists():
            self.cloud_log.append(f"未找到旧评论库：{LEGACY_DB_PATH}")
            return
        answer = QMessageBox.question(
            self,
            "导入旧评论库",
            "将把旧 ReviewCollector 的商品和评论合并到 PM Stack。原数据库不会被修改，是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.cloud_log.set_status("running")

        def target(_log):
            store = ReviewStore()
            try:
                if store.total_reviews():
                    backup = BACKUP_DIR / f"before_legacy_import_{datetime.now():%Y%m%d_%H%M%S}.db"
                    store.backup_to(str(backup))
                return import_legacy_database(store)
            finally:
                store.close()

        def done(result):
            self.cloud_log.append(
                f"[导入完成] 商品 {result['products']} 个，新增唯一评论 {result['reviews']} 条；原库未改动。"
            )
            self.cloud_log.set_status("ok")
            self.import_legacy_btn.setEnabled(False)
            self.import_legacy_btn.setText("旧评论库已导入")
            self._update_cloud_status()
            self.refresh_products()

        self._start_task("legacy", target, done, self.cloud_log)


__all__ = ["ReviewCollectionPanel"]

