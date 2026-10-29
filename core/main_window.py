# -*- coding: utf-8 -*-
"""主窗口 — 顶部模块导航 + 页面标题栏 + 独立页面滚动 + 双主题

布局:
    ┌────────────────────────────────┐
    │ 模块导航              主题/设置 │
    ├────────────────────────────────┤
    │ 页面标题 + 副标题 + 徽章         │
    │ 模块内容区（滚动）               │
    └────────────────────────────────┘
"""

import os
import sys
import importlib
import time
import traceback

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStatusBar, QDialog, QFormLayout, QLineEdit, QDialogButtonBox,
    QGroupBox, QMessageBox, QCheckBox, QScrollArea, QStackedWidget,
    QToolButton, QButtonGroup, QFrame, QApplication, QSizePolicy,
    QProgressBar,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QScreen, QShortcut, QKeySequence

from .config_manager import ConfigManager, DEFAULT_VISION_MODEL
from .runner import ScriptRunner
from .theme import THEME
from .icons import get_icon, get_module_icon
from .updater import Updater
from .app_updater import ApplicationUpdater, launch_updater_helper
from .widgets import make_button, make_hint_label


CURRENT_VERSION = "v1.11.7"
APP_NAME = "PM Stack"
APP_TITLE = f"{APP_NAME} {CURRENT_VERSION}"


class MainWindow(QMainWindow):
    def __init__(self, startup_warnings=()):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(880, 620)

        self.config_mgr = ConfigManager()
        # 入口在待恢复备份处理前会先读配置；坏文件已隔离后第二次读取不再告警。
        self._entry_config_warnings = tuple(startup_warnings)
        self.app_updater = ApplicationUpdater(self)
        self.updater = Updater(self)
        self.app_updater.check_finished.connect(
            self._on_app_update_checked)
        self.app_updater.progress.connect(self._on_app_update_progress)
        self.app_updater.download_finished.connect(
            self._on_app_download_finished)

        # 主题（持久化，默认浅色）
        THEME.set_theme(self.config_mgr.get("theme", "light"))
        QApplication.instance().setStyleSheet(THEME.qss())

        self._modules = []          # [(info, widget), ...]
        self._module_runners = []   # 每个模块独立信号，执行仍全局串行
        self._nav_buttons = []      # 与 _modules 对应的导航按钮
        self._module_failures = []  # [(名称, 原因), ...] 单个模块坏掉不拖垮整个应用
        self._startup_issues = []   # 启动后一次性告知用户的模块与配置问题
        self._init_ui()
        self._load_modules()
        self._update_status()
        self._set_initial_geometry()
        self._report_startup_issues()

        # 启动时检查主程序更新（共享盘或公开 HTTPS 地址）。
        manifest_source = self.config_mgr.get_app_update_manifest_source()
        if (self.config_mgr.get("auto_check_app_update", True)
                and manifest_source):
            self.app_updater.check_update(manifest_source, CURRENT_VERSION)

        # 插件更新保留原有 GitHub Release ZIP 通道。
        if self.config_mgr.get("auto_check_update") and self.config_mgr.get("github_repo"):
            self.updater.check_finished.connect(self._on_update_checked)
            self.updater.check_update(
                self.config_mgr.get("github_repo"), CURRENT_VERSION)

    # ================================================================
    # UI 构建
    # ================================================================

    def _set_initial_geometry(self):
        """初始几何必须完整落在可用区域内。

        可用区域带屏幕原点：非主屏或有偏移的屏幕上只按宽高居中会把窗口摆到屏幕外。
        1080x700 只是期望值，小屏上以可用区域为硬上限，不能强行放大。
        """
        area = QScreen.availableGeometry(QApplication.primaryScreen())
        w = min(1440, max(1080, int(area.width() * 0.82)), area.width())
        h = min(900, max(700, int(area.height() * 0.85)), area.height())
        # 最小尺寸同样不能超过可用区域，否则 Qt 会把窗口重新撑大到屏幕外。
        self.setMinimumSize(min(880, area.width()), min(620, area.height()))
        x = area.x() + (area.width() - w) // 2
        y = area.y() + (area.height() - h) // 2
        self.setGeometry(x, y, w, h)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ================= 顶部横向模块导航 =================
        self._nav_bar = QWidget()
        self._nav_bar.setObjectName("NavBar")
        nav_layout = QHBoxLayout(self._nav_bar)
        nav_layout.setContentsMargins(24, 6, 24, 6)
        nav_layout.setSpacing(8)

        # 插件较多时可横向滚动，右侧工具按钮始终可见。
        self._nav_scroll = QScrollArea()
        self._nav_scroll.setObjectName("NavScroll")
        self._nav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._nav_scroll.setWidgetResizable(True)
        self._nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._nav_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nav_scroll.setFixedHeight(52)
        self._nav_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        nav_items = QWidget()
        nav_items.setObjectName("NavItems")
        self._nav_layout = QHBoxLayout(nav_items)
        self._nav_layout.setContentsMargins(0, 0, 0, 0)
        self._nav_layout.setSpacing(6)
        self._nav_layout.addStretch()
        self._nav_scroll.setWidget(nav_items)
        nav_layout.addWidget(self._nav_scroll, 1)
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_group.idClicked.connect(self._switch_module)

        # 主题切换
        self._theme_btn = QToolButton()
        self._theme_btn.setObjectName("NavUtility")
        self._theme_btn.setFixedSize(38, 38)
        self._theme_btn.setAccessibleName("切换主题")
        self._theme_btn.clicked.connect(self._toggle_theme)
        nav_layout.addWidget(self._theme_btn)

        # 设置
        settings_btn = QToolButton()
        settings_btn.setObjectName("NavUtility")
        settings_btn.setFixedSize(38, 38)
        settings_btn.setAccessibleName("全局设置")
        settings_btn.setToolTip("设置（API / 更新 / 插件）")
        settings_btn.clicked.connect(self._open_settings)
        nav_layout.addWidget(settings_btn)
        self._settings_btn = settings_btn

        main_layout.addWidget(self._nav_bar)

        # ================= 全宽内容区 =================
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # 顶部标题栏
        header = QWidget()
        header.setObjectName("Header")
        self.page_header = header
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(28, 16, 28, 14)
        header_layout.setSpacing(16)

        self.page_title = QLabel(APP_NAME)
        self.page_title.setObjectName("PageTitle")
        self.page_subtitle = QLabel("选择顶部模块开始处理数据")
        self.page_subtitle.setObjectName("PageSubtitle")
        self.page_subtitle.setWordWrap(True)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        title_col.addWidget(self.page_title)
        title_col.addWidget(self.page_subtitle)
        header_layout.addLayout(title_col, 1)

        self.api_badge = QLabel()
        self.api_badge.setObjectName("ApiBadge")
        header_layout.addWidget(
            self.api_badge, alignment=Qt.AlignmentFlag.AlignVCenter)
        content_layout.addWidget(header)

        # 模块工作区：页面各自管理滚动，底部操作不随长表单移出窗口。
        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack)

        main_layout.addWidget(content, stretch=1)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self._refresh_utility_icons()

    # ================================================================
    # 主题
    # ================================================================

    def _toggle_theme(self):
        THEME.toggle()
        self.config_mgr.set("theme", THEME.name)
        QApplication.instance().setStyleSheet(THEME.qss())
        self._refresh_utility_icons()
        self._refresh_nav_icons()
        self.api_badge.style().unpolish(self.api_badge)
        self.api_badge.style().polish(self.api_badge)

    def _refresh_utility_icons(self):
        t = THEME.tokens()
        # 主题切换按钮：当前浅色则显示月亮（切到深色），反之显示太阳
        target = "moon" if THEME.name == "light" else "sun"
        self._theme_btn.setIcon(get_icon(target, t["text2"], 20))
        self._theme_btn.setToolTip(
            "切换到深色模式" if THEME.name == "light" else "切换到浅色模式")
        self._settings_btn.setIcon(get_icon("settings", t["text2"], 20))

    def _refresh_nav_icons(self):
        """按当前主题与选中态重绘导航图标。"""
        t = THEME.tokens()
        for i, btn in enumerate(self._nav_buttons):
            name = self._modules[i][0].get("name", "")
            fallback = self._modules[i][0].get("icon", "")
            color = t["text_on_accent"] if btn.isChecked() else t["text2"]
            btn.setIcon(get_module_icon(name, color, 18, fallback))

    # ================================================================
    # 模块加载（内置 + 插件）
    # ================================================================

    def _load_modules(self):
        discovered = []
        builtin_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "modules")
        self._scan_module_dir(builtin_dir, discovered, "builtin")

        plugin_dir = self.config_mgr.get_plugin_dir()
        self._scan_module_dir(
            os.path.join(plugin_dir, "modules"), discovered, "plugin")

        # 去重（内置优先）+ 排序
        seen = set()
        unique = []
        for info, widget_cls, _source in discovered:
            name = info.get("name", "")
            if name in seen:
                continue
            seen.add(name)
            unique.append((info, widget_cls))
        unique.sort(key=lambda x: x[0].get("order", 99))

        first_btn = None
        for info, widget_cls in unique:
            name = info.get("name", "未知")
            runner = ScriptRunner(self)
            # 单个模块构造失败只跳过该模块，其余功能照常可用。
            try:
                widget = widget_cls(self.config_mgr, runner)
            except Exception as exc:
                self._module_failures.append((name, f'{type(exc).__name__}: {exc}'))
                traceback.print_exc()
                runner.deleteLater()
                continue
            self._module_runners.append(runner)
            index = self.stack.count()
            self._modules.append((info, widget))
            # Workspaces own their scrolling and keep actions in view.
            if widget.property("workspacePage"):
                self.stack.addWidget(widget)
            else:
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                scroll.setWidget(widget)
                self.stack.addWidget(scroll)

            btn = QToolButton()
            btn.setObjectName("NavItem")
            btn.setFixedHeight(38)
            btn.setMinimumWidth(116)
            btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setCheckable(True)
            name = info.get("name", "未知")
            btn.setText(name)
            btn.setAccessibleName(name)
            desc = info.get("description", "")
            btn.setToolTip(f"{name}\n{desc}" if desc else name)
            self._nav_group.addButton(btn, index)
            self._nav_buttons.append(btn)
            self._nav_layout.insertWidget(self._nav_layout.count() - 1, btn)
            if first_btn is None:
                first_btn = btn

        for info, widget in self._modules:
            if info.get('name') == '展示看板':
                widget.matrix_requested.connect(self._open_dashboard_matrix)

        if first_btn is not None:
            first_btn.setChecked(True)
            self._switch_module(self._nav_group.id(first_btn))

        # Ctrl+1..9 快速切换
        for idx in range(min(9, self.stack.count())):
            sc = QShortcut(QKeySequence(f"Ctrl+{idx + 1}"), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(lambda i=idx: self._switch_module(i))

    def _open_dashboard_matrix(self, path):
        for index, (info, widget) in enumerate(self._modules):
            if info.get('name') == '产品矩阵' and hasattr(widget, 'open_dashboard_source'):
                widget.open_dashboard_source(path)
                self._switch_module(index)
                return

    def _scan_module_dir(self, modules_dir, discovered, source):
        if not os.path.isdir(modules_dir):
            return
        for fname in os.listdir(modules_dir):
            if fname.startswith("_") or not fname.endswith(".py"):
                continue
            module_name = fname[:-3]
            try:
                if modules_dir not in sys.path:
                    sys.path.insert(0, modules_dir)
                mod = importlib.import_module(module_name)
                info = getattr(mod, "MODULE_INFO", None)
                widget_cls = getattr(mod, "ModuleWidget", None)
                if info and widget_cls and issubclass(widget_cls, QWidget):
                    discovered.append((info, widget_cls, source))
            except Exception as e:
                # 只 print 等于没人看见；失败要汇总后告知用户。
                self._module_failures.append(
                    (module_name, f'{type(e).__name__}: {e}'))
                print(f"[警告] 加载{source}模块 {module_name} 失败: {e}")

    def _switch_module(self, index):
        if not (0 <= index < self.stack.count()):
            return
        self.stack.setCurrentIndex(index)
        btn = self._nav_group.button(index)
        if btn and not btn.isChecked():
            btn.setChecked(True)
        if btn:
            self._nav_scroll.ensureWidgetVisible(btn, 8, 0)
        info = self._modules[index][0]
        self.page_title.setText(info.get("name", APP_NAME))
        self.page_subtitle.setText(info.get("description", ""))
        self.page_header.setVisible(info.get("name") != "产品矩阵")
        self._refresh_nav_icons()

    # ================================================================
    # 状态
    # ================================================================

    def _update_status(self):
        api_key = self.config_mgr.get("api_key", "")
        self.api_badge.setText("● AI 已配置（未验证）" if api_key else "● AI 服务未配置")
        self.api_badge.setToolTip(
            "已安全保存 API Key，但尚未验证接口连通性"
            if api_key else "请在设置中配置 API Key"
        )
        self.api_badge.setProperty("configured", bool(api_key))
        self.api_badge.style().unpolish(self.api_badge)
        self.api_badge.style().polish(self.api_badge)

        if not hasattr(self, "_sb_api"):
            self._sb_api = QLabel()
            self._sb_mod = QLabel()
            self._sb_ver = QLabel(CURRENT_VERSION)
            for w in (self._sb_api, self._sb_mod, self._sb_ver):
                w.setObjectName("FormHint")
                self.status_bar.addPermanentWidget(w)
        self._sb_api.setText("API: 已配置（未验证）" if api_key else "API: 未配置")
        self._sb_mod.setText(f"模块: {len(self._modules)}")
        self.status_bar.showMessage("  就绪")

    def show_status(self, message, timeout=5000):
        """供各模块调用的统一状态栏消息接口。"""
        self.status_bar.showMessage(f"  {message}", timeout)

    # ================================================================
    # 更新
    # ================================================================

    def _on_app_update_checked(self, has_update, message):
        if not has_update:
            if "失败" in message or "错误" in message:
                self.show_status(message, 8000)
            return
        manifest = self.app_updater.get_manifest()
        if manifest is None:
            return
        action = "必须更新" if manifest.mandatory else "可选更新"
        reply = QMessageBox.question(
            self,
            "发现主程序更新",
            f"{message}\n\n类型：{action}\n\n是否立即下载？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if not self.app_updater.download_update():
                QMessageBox.information(self, "更新", "主程序更新正在处理中。")

    def _on_app_update_progress(self, percent, message):
        suffix = f" ({percent}%)" if percent else ""
        self.status_bar.showMessage(f"  {message}{suffix}")

    def _on_app_download_finished(self, success, message, downloaded_path):
        if not success:
            QMessageBox.warning(self, "主程序更新失败", message)
            return
        reply = QMessageBox.question(
            self,
            "更新已准备好",
            f"{message}\n\n是否立即关闭 PM Stack、安装更新并重新启动？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._start_app_install(downloaded_path)

    def _start_app_install(self, downloaded_path):
        if not getattr(sys, "frozen", False):
            QMessageBox.information(
                self, "源码模式",
                "源码运行时只验证下载，不会替换 Python 入口。请在打包版本中测试安装。",
            )
            return
        # 更新退出同样会终止 daemon 线程，先走与关窗一致的确认。
        if not self._confirm_exit_while_running("安装更新并重启"):
            return
        manifest = self.app_updater.get_manifest()
        if manifest is None:
            QMessageBox.warning(self, "更新失败", "更新清单状态已失效，请重新检查。")
            return
        target = os.path.abspath(sys.executable)
        helper = os.path.join(os.path.dirname(target), "PM Stack Updater.exe")
        try:
            launch_updater_helper(
                helper, downloaded_path, target, os.getpid(),
                manifest.version, manifest.sha256,
            )
        except Exception as exc:
            QMessageBox.critical(self, "无法启动更新器", str(exc))
            return
        self.status_bar.showMessage("  正在退出并安装主程序更新...")
        QTimer.singleShot(250, QApplication.instance().quit)

    def _on_update_checked(self, has_update, message):
        """插件更新检查完成。"""
        if has_update:
            reply = QMessageBox.question(
                self, "发现新版本", f"{message}\n\n是否下载更新？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self._do_download_update()

    def _do_download_update(self):
        download_url = self.updater.get_last_download_url()
        if not download_url:
            QMessageBox.warning(self, "错误", "未找到可下载的插件包。")
            return
        plugin_dir = self.config_mgr.get_plugin_dir()
        self.updater.download_finished.connect(self._on_download_finished)
        self.updater.progress.connect(
            lambda msg: self.status_bar.showMessage(f"  {msg}"))
        self.updater.download_update(download_url, plugin_dir)

    def _on_download_finished(self, success, message):
        if success:
            QMessageBox.information(self, "更新完成", message)
        else:
            QMessageBox.warning(self, "更新失败", message)

    # ================================================================
    # 退出与任务生命周期
    # ================================================================

    EXIT_WAIT = "wait"
    EXIT_STOP = "stop"
    EXIT_FORCE = "force"
    EXIT_CANCEL = "cancel"

    def closeEvent(self, event):
        if self._confirm_exit_while_running("关闭 PM Stack"):
            event.accept()
        else:
            event.ignore()

    def _confirm_exit_while_running(self, action_label, ask=None, wait=None):
        """返回 True 才允许退出。

        脚本跑在 daemon 线程里，解释器一退出线程就被硬终止，脚本没机会执行
        finally 与断点保存。所以这里只写协作停止信号并等待，不杀线程。
        ask / wait 可注入，便于测试决策分支。
        """
        if not ScriptRunner.is_any_running():
            return True
        choice = (ask or self._ask_exit_choice)(action_label)
        if choice == self.EXIT_CANCEL:
            return False
        if choice == self.EXIT_FORCE:
            self.show_status("已按强制退出处理，未保存的批次可能丢失。", 8000)
            return True
        if choice == self.EXIT_STOP:
            written = ScriptRunner.request_stop_all()
            self.show_status(f"已请求 {len(written)} 个任务安全停止，正在等待保存…", 8000)
        finished = bool((wait or self._block_until_idle)())
        if not finished:
            self.show_status("任务仍未结束，已取消本次退出；可再次尝试或选择强制退出。", 8000)
        return finished

    def _ask_exit_choice(self, action_label):
        box = QMessageBox(self)
        box.setWindowTitle("任务正在运行")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"{action_label}前检测到仍有任务在运行。")
        box.setInformativeText(
            "直接退出会中断脚本，未保存的批次可能丢失。\n"
            "可以等待任务自然完成，或请求安全停止——脚本会保存已完成的行与断点后再退出。")
        wait_btn = box.addButton("等待完成", QMessageBox.ButtonRole.AcceptRole)
        stop_btn = box.addButton("请求停止并等待保存", QMessageBox.ButtonRole.AcceptRole)
        force_btn = box.addButton("强制退出（可能丢数据）",
                                  QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(wait_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is stop_btn:
            return self.EXIT_STOP
        if clicked is force_btn:
            return self.EXIT_FORCE
        if clicked is cancel_btn:
            return self.EXIT_CANCEL
        return self.EXIT_WAIT

    def _block_until_idle(self, timeout=600.0):
        """等待执行锁释放；可放弃等待，超时也不强行退出。"""
        dialog = QDialog(self)
        dialog.setWindowTitle("等待任务安全保存")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        label = QLabel("正在等待任务保存已完成的结果与断点，请不要强制结束进程。")
        label.setWordWrap(True)
        layout.addWidget(label)
        bar = QProgressBar()
        bar.setRange(0, 0)
        layout.addWidget(bar)
        give_up = make_button("放弃等待", "secondary")
        layout.addWidget(give_up)
        abandoned = []
        give_up.clicked.connect(lambda: (abandoned.append(True), dialog.reject()))
        dialog.show()
        deadline = time.monotonic() + timeout
        try:
            while ScriptRunner.is_any_running():
                if abandoned or time.monotonic() >= deadline:
                    return False
                QApplication.processEvents()
                time.sleep(0.05)
            return True
        finally:
            dialog.close()

    def _report_startup_issues(self):
        """模块加载失败与配置警告此前只 print 或根本没被读取，这里统一告知用户。"""
        issues = [f"模块「{name}」未能加载：{detail}"
                  for name, detail in self._module_failures]
        issues += list(dict.fromkeys(str(warning) for warning in
                       (*self._entry_config_warnings, *self.config_mgr.get_warnings())))
        self._startup_issues = issues
        if issues:
            self._show_startup_issues(issues)

    def _show_startup_issues(self, issues):
        QMessageBox.warning(
            self, "启动警告",
            "以下问题不影响其余功能，但需要你留意：\n\n"
            + "\n".join(f"· {item}" for item in issues))

    def _open_settings(self):
        dlg = SettingsDialog(self.config_mgr, self.updater, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._update_status()
            source = self.config_mgr.get_app_update_manifest_source()
            if self.config_mgr.get("auto_check_app_update", True) and source:
                self.app_updater.check_update(source, CURRENT_VERSION)


class SettingsDialog(QDialog):
    def __init__(self, config_mgr, updater, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self.updater = updater
        self.setWindowTitle("设置")
        self.setMinimumSize(600, 620)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(18, 18, 18, 18)
        outer_layout.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 2, 8, 2)
        layout.setSpacing(14)
        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

        # ---- API 配置 ----
        api_group = QGroupBox("API 配置")
        form = QFormLayout(api_group)

        self.api_key_edit = QLineEdit(config_mgr.get("api_key", ""))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        form.addRow("API Key:", self.api_key_edit)
        key_note = QLabel("密钥将使用 Windows DPAPI 加密，并保存到当前用户的本机配置目录。")
        key_note.setObjectName("FormHint")
        key_note.setWordWrap(True)
        form.addRow(key_note)

        self.base_url_edit = QLineEdit(config_mgr.get("base_url", ""))
        self.base_url_edit.setPlaceholderText("如 https://api.siliconflow.cn/v1")
        form.addRow("Base URL:", self.base_url_edit)

        self.model_edit = QLineEdit(config_mgr.get("model_name", ""))
        self.model_edit.setPlaceholderText("如 deepseek-ai/DeepSeek-V3")
        form.addRow("Model:", self.model_edit)

        layout.addWidget(api_group)

        # ---- 视觉模型配置 ----
        vision_group = QGroupBox("视觉模型配置（图片识别专用）")
        vision_form = QFormLayout(vision_group)

        vision_note = QLabel(
            "Vision API Key 与 Base URL 留空时继承上方配置；模型名留空则使用内置默认视觉模型"
            f"（{DEFAULT_VISION_MODEL}），不会继承上方的文本模型——文本模型通常不支持图片输入。")
        vision_note.setObjectName("FormHint")
        vision_note.setWordWrap(True)
        vision_form.addRow(vision_note)

        self.vision_key_edit = QLineEdit(config_mgr.get("vision_api_key", ""))
        self.vision_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.vision_key_edit.setPlaceholderText("留空则使用上方 API Key")
        vision_form.addRow("Vision API Key:", self.vision_key_edit)

        self.vision_url_edit = QLineEdit(config_mgr.get("vision_base_url", ""))
        self.vision_url_edit.setPlaceholderText("留空则使用上方 Base URL")
        vision_form.addRow("Vision Base URL:", self.vision_url_edit)

        self.vision_model_edit = QLineEdit(config_mgr.get("vision_model_name", ""))
        # 占位符显示留空时真正生效的模型，而不是一个含糊的示例。
        self.vision_model_edit.setPlaceholderText(
            f"留空则使用 {config_mgr.effective_vision_model()}")
        vision_form.addRow("Vision Model:", self.vision_model_edit)

        layout.addWidget(vision_group)

        # ---- 主程序更新 ----
        app_update_group = QGroupBox("主程序更新（共享盘 / GitHub Releases）")
        app_update_form = QFormLayout(app_update_group)

        self.app_manifest_edit = QLineEdit(
            config_mgr.get("app_update_manifest", ""))
        resolved_source = config_mgr.get_app_update_manifest_source()
        self.app_manifest_edit.setPlaceholderText(
            resolved_source or r"如 \\server\share\PM Stack\update.json 或 HTTPS 地址")
        app_update_form.addRow("update.json:", self.app_manifest_edit)

        app_update_note = make_hint_label(
            "支持公司共享盘、file:// 和公开 HTTPS；HTTP 会被拒绝。"
            "下载后将校验 SHA-256，再由同目录的独立更新器替换主程序。")
        app_update_form.addRow(app_update_note)

        self.auto_app_update_cb = QCheckBox("启动时自动检查主程序更新")
        self.auto_app_update_cb.setChecked(
            config_mgr.get("auto_check_app_update", True))
        app_update_form.addRow(self.auto_app_update_cb)

        self.app_update_checker = ApplicationUpdater(self)
        self.app_update_checker.check_finished.connect(
            self._on_app_check_done)
        self.check_app_update_btn = make_button("验证更新地址", "compact")
        self.check_app_update_btn.clicked.connect(self._check_app_update)
        self.app_update_status = make_hint_label("")
        app_check_row = QHBoxLayout()
        app_check_row.addWidget(self.check_app_update_btn)
        app_check_row.addWidget(self.app_update_status)
        app_check_row.addStretch()
        app_update_form.addRow(app_check_row)
        layout.addWidget(app_update_group)

        # ---- 插件更新 ----
        update_group = QGroupBox("插件更新（高级）")
        update_form = QFormLayout(update_group)

        self.github_repo_edit = QLineEdit(config_mgr.get("github_repo", ""))
        self.github_repo_edit.setPlaceholderText("username/repo-name")
        update_form.addRow("GitHub 仓库:", self.github_repo_edit)

        self.auto_update_cb = QCheckBox("启动时自动检查插件更新")
        self.auto_update_cb.setChecked(config_mgr.get("auto_check_update", True))
        update_form.addRow(self.auto_update_cb)

        self.check_update_btn = make_button("检查插件更新", "compact")
        self.check_update_btn.clicked.connect(self._check_update)
        self._update_check_in_progress = False
        self.update_status_label = make_hint_label("")
        check_row = QHBoxLayout()
        check_row.addWidget(self.check_update_btn)
        check_row.addWidget(self.update_status_label)
        check_row.addStretch()
        update_form.addRow(check_row)

        layout.addWidget(update_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer_layout.addWidget(buttons)

    def _check_app_update(self):
        source = (
            self.app_manifest_edit.text().strip()
            or self.config_mgr.get_app_update_manifest_source()
        )
        if not source:
            self.app_update_status.setText("请先填写 update.json 地址")
            return
        self.check_app_update_btn.setEnabled(False)
        self.app_update_status.setText("正在验证...")
        if not self.app_update_checker.check_update(source, CURRENT_VERSION):
            self.app_update_status.setText("已有检查正在进行")

    def _on_app_check_done(self, has_update, message):
        self.check_app_update_btn.setEnabled(True)
        self.app_update_status.setText(message.replace("\n", " "))

    def _check_update(self):
        if self._update_check_in_progress:
            return
        repo = self.github_repo_edit.text().strip()
        if not repo:
            self.update_status_label.setText("请先填写 GitHub 仓库地址")
            return
        self._update_check_in_progress = True
        self.check_update_btn.setEnabled(False)
        self.update_status_label.setText("正在检查...")
        try:
            self.updater.check_finished.disconnect(self._on_check_done)
        except TypeError:
            pass
        self.updater.check_finished.connect(self._on_check_done)
        try:
            self.updater.check_update(repo, CURRENT_VERSION)
        except Exception as exc:
            self._update_check_in_progress = False
            self.check_update_btn.setEnabled(True)
            self.update_status_label.setText(f"检查更新失败: {exc}")

    def _on_check_done(self, has_update, message):
        self._update_check_in_progress = False
        self.check_update_btn.setEnabled(True)
        self.update_status_label.setText(message)

    def _save(self):
        values = {
            "api_key": self.api_key_edit.text().strip(),
            "base_url": self.base_url_edit.text().strip(),
            "model_name": self.model_edit.text().strip(),
            "vision_api_key": self.vision_key_edit.text().strip(),
            "vision_base_url": self.vision_url_edit.text().strip(),
            "vision_model_name": self.vision_model_edit.text().strip(),
            "app_update_manifest": self.app_manifest_edit.text().strip(),
            "auto_check_app_update": self.auto_app_update_cb.isChecked(),
            "github_repo": self.github_repo_edit.text().strip(),
            "auto_check_update": self.auto_update_cb.isChecked(),
        }
        try:
            self.config_mgr.update(values)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", f"无法安全保存配置：\n{exc}")
            return
        self.accept()
