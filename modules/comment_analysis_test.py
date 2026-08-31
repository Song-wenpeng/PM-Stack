# -*- coding: utf-8 -*-
"""评论分析测试模块 — 一键完成_TEST（并发版特征提取）

与原「评论分析」模块的一键完成流程一致，区别仅在于：
- Step 1 使用 comments_step_1_fast.py（线程池并发调用 AI）
- 输出文件带 _TEST 后缀，不覆盖原流程结果
- 可调并发数（默认 8）并提供全局 RPM/TPM 限速
- 每 20 条保存断点，支持继续/仅补跑失败项
- Step 1 存在失败时阻止 Step 2，避免生成不完整结论
- Step 2 汇总洞察复用原 comments_step_2.py

原模块与原脚本零改动，本模块仅用于并发方案的效果验证。
"""

import os
import json
import tempfile
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QHBoxLayout, QComboBox,
    QLineEdit, QSpinBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from core.widgets import (
    Card, LogConsole, FileDropLineEdit, make_button, configure_combo,
    file_row, set_running_state, default_output,
)

MODULE_INFO = {
    "name": "评论分析TEST",
    "icon": "⚡",
    "category": "分析中心",
    "order": 1.5,
    "description": "并发版评论分析测试：AI特征提取加速 → 汇总洞察",
}


class ModuleWidget(QWidget):
    def __init__(self, config_mgr, runner):
        super().__init__()
        self.config_mgr = config_mgr
        self.runner = runner
        self._stop_file = os.path.join(tempfile.gettempdir(), "comment_stop.signal")
        self._stopped = False
        self._overrides = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.setSpacing(14)

        card = Card(
            "一键完成_TEST（并发版）",
            "并发执行 AI特征提取 → 归类汇总。输出带 _TEST 后缀，不影响原流程结果")
        form = QFormLayout()
        form.setSpacing(10)

        self.input_edit = FileDropLineEdit(placeholder="选择或拖入原始评论 Excel 文件")
        form.addRow("输入文件:", file_row(self.input_edit, "open", parent=self))

        self.output_edit = FileDropLineEdit(placeholder="留空则自动在输入文件旁生成")
        form.addRow("输出文件:", file_row(self.output_edit, "save", parent=self))
        self.input_edit.textChanged.connect(
            lambda: self._auto_output(self.input_edit, self.output_edit))

        self.product_combo = configure_combo(QComboBox())
        form.addRow("分析品类:", self.product_combo)

        self.sheets_edit = QLineEdit()
        self.sheets_edit.setPlaceholderText("逗号分隔，如: 5 star,4 star,3 star（留空处理全部）")
        form.addRow("评论数据表:", self.sheets_edit)

        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 12)
        self.concurrency_spin.setValue(8)
        self.concurrency_spin.setToolTip("126 条实测推荐 8；频繁 429 时降至 4，12 为高级选项")
        form.addRow("并发数:", self.concurrency_spin)

        self.rpm_spin = QSpinBox()
        self.rpm_spin.setRange(0, 100000)
        self.rpm_spin.setValue(900)
        self.rpm_spin.setSpecialValueText("关闭")
        self.rpm_spin.setToolTip("服务商 RPM 为 1000 时建议保留约 10% 余量")
        form.addRow("RPM 安全上限:", self.rpm_spin)

        self.tpm_spin = QSpinBox()
        self.tpm_spin.setRange(0, 10000000)
        self.tpm_spin.setSingleStep(10000)
        self.tpm_spin.setValue(90000)
        self.tpm_spin.setSpecialValueText("关闭")
        self.tpm_spin.setToolTip("服务商 TPM 为 100,000 时建议设置 90,000")
        form.addRow("TPM 安全上限:", self.tpm_spin)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.run_btn = make_button("开始/重新分析", "primary")
        self.run_btn.clicked.connect(lambda _checked=False: self._run_full(False))
        self.retry_btn = make_button("继续/补跑失败", "compact", "复用断点，只请求未完成或失败条目")
        self.retry_btn.clicked.connect(lambda _checked=False: self._run_full(True))
        self.stop_btn = make_button("停止", "danger", "当前条目处理完成后停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.retry_btn)
        btn_row.addWidget(self.stop_btn)
        form.addRow(btn_row)

        card.content_layout.addLayout(form)
        layout.addWidget(card)
        self.log = LogConsole()
        layout.addWidget(self.log)
        layout.addStretch()

        self._populate_products()

    # ---- 小工具 ----

    @staticmethod
    def _auto_output(input_edit, output_edit):
        """输入改变时更新自动建议，但保留用户手工填写的输出路径。"""
        inp = input_edit.text().strip()
        suggested = default_output(inp, "_AI全流程_TEST") if inp else ""
        previous_auto = output_edit.property("_autoOutputValue")
        current = output_edit.text().strip()
        if not current or current == (previous_auto or ""):
            output_edit.setText(suggested)
            output_edit.setProperty("_autoOutputValue", suggested)

    def _populate_products(self):
        """读取品类配置填充下拉框（userData 存稳定 key）。"""
        path = self.config_mgr.resolve_config("product_configs.json")
        products = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                items = cfg.get("products", cfg)
                if isinstance(items, dict):
                    for key, data in items.items():
                        if isinstance(data, dict) and data.get("display_name"):
                            products.append((data["display_name"], key))
                        else:
                            products.append((key, key))
            except Exception:
                products = []

        self.product_combo.blockSignals(True)
        self.product_combo.clear()
        self.product_combo.addItem("请选择品类…")
        self.product_combo.setItemData(0, QColor("#8F959E"), Qt.ItemDataRole.ForegroundRole)
        for display, key in products:
            self.product_combo.addItem(display, userData=key)
        self.product_combo.blockSignals(False)

    # ---- 停止控制 ----

    def _stop(self):
        """创建停止信号文件。"""
        try:
            with open(self._stop_file, "w") as f:
                f.write("stop")
            self._stopped = True
        except Exception:
            pass

    def _clear_stop(self):
        self._stopped = False
        if os.path.exists(self._stop_file):
            os.remove(self._stop_file)

    def _is_stopped(self):
        return self._stopped or os.path.exists(self._stop_file)

    def _set_running(self, running):
        self.stop_btn.setEnabled(running)
        set_running_state(self.run_btn, running)
        self.retry_btn.setEnabled(not running)

    # ---- 脚本执行 ----

    def _build_env(self):
        env = self.config_mgr.get_env_dict()
        env["CONFIG_FILE"] = self.config_mgr.resolve_config("product_configs.json")
        return env

    def _run_full(self, resume_only=False):
        if self.runner.is_running() or self.runner.is_any_running():
            self.log.append("[提示] 当前有任务正在运行，请等待完成。")
            return
        inp = self.input_edit.text().strip()
        if not inp:
            self.log.append("[提示] 请先选择「输入文件」")
            return
        prod = self.product_combo.currentData()
        if not prod:
            self.log.append("[提示] 请先选择分析品类。")
            return

        p = Path(inp)
        out_dir = str(p.parent)
        step1_path = os.path.join(out_dir, f"{p.stem}_AI处理_TEST{p.suffix}")
        checkpoint_path = f"{step1_path}.checkpoint.json"
        if resume_only and not os.path.exists(checkpoint_path):
            self.log.append("[提示] 没有找到可继续的断点，请先开始一次分析。")
            return
        user_out = self.output_edit.text().strip()
        if user_out:
            step2_path = user_out
        else:
            step2_path = os.path.join(out_dir, f"{p.stem}_AI全流程_TEST{p.suffix}")

        self._overrides = {
            "RAW_INPUT_FILE": inp,
            "CURRENT_PRODUCT": prod,
            "STEP1_OUTPUT_FILE": step1_path,
            "STEP2_OUTPUT_FILE": step2_path,
            "STEP1_CONCURRENCY": str(self.concurrency_spin.value()),
            "STEP1_RPM_LIMIT": str(self.rpm_spin.value()),
            "STEP1_TPM_LIMIT": str(self.tpm_spin.value()),
            "STEP1_MAX_FAILURE_RATE": "0",
        }
        if resume_only:
            self._overrides["STEP1_RESUME_ONLY"] = "1"
        sheets = self.sheets_edit.text().strip()
        if sheets:
            self._overrides["TARGET_SHEETS"] = sheets

        self._clear_stop()
        self._set_running(True)
        self.log.clear()
        self.log.set_status("running")
        mode = "断点继续/补跑失败" if resume_only else "并发测试"
        self.log.append(f"=== 一键完成_TEST（{mode}）开始 ===\n")
        self.log.append(
            f"并发数: {self.concurrency_spin.value()} | "
            f"RPM: {self.rpm_spin.value() or '关闭'} | "
            f"TPM: {self.tpm_spin.value() or '关闭'}"
        )
        self.log.append("→ Step 1: AI特征提取（并发）...")
        self._run_step("comments_step_1_fast.py", self._on_step1_done)

    def _run_step(self, script, done_handler):
        try:
            self.runner.finished_signal.disconnect()
        except TypeError:
            pass
        self.runner.finished_signal.connect(done_handler)
        env = self._build_env()
        env.update(self._overrides)
        script_path = os.path.join(self.config_mgr.get_script_dir(), script)
        self.runner.run_script(script_path, env_extra=env)

    def _on_step1_done(self, code):
        try:
            self.runner.finished_signal.disconnect(self._on_step1_done)
        except TypeError:
            pass
        if self._is_stopped():
            self.log.append("\n[停止] 用户中止。已完成条目保存在 Step 1 输出文件中。")
            self.log.set_status("error")
            self._set_running(False)
            return
        if code == 2:
            self.log.append(
                "✗ Step 1 仍有失败条目，已阻止 Step 2。"
                "请点击「继续/补跑失败」。"
            )
            self.log.set_status("error")
            self._set_running(False)
            return
        if code != 0:
            self.log.append(f"✗ Step 1 失败 (退出码: {code})")
            self.log.set_status("error")
            self._set_running(False)
            return
        self.log.append("✓ Step 1 完成")
        self.log.append("→ Step 2: AI归类总结...")
        self._run_step("comments_step_2.py", self._on_step2_done)

    def _on_step2_done(self, code):
        try:
            self.runner.finished_signal.disconnect(self._on_step2_done)
        except TypeError:
            pass
        if self._is_stopped():
            self.log.append("\n[停止] 用户中止。")
            self.log.set_status("error")
        elif code != 0:
            self.log.append(f"✗ Step 2 失败 (退出码: {code})")
            self.log.set_status("error")
        else:
            self.log.append("✓ Step 2 完成\n\n=== 全流程完成 ===")
            self.log.set_status("ok")
        self._set_running(False)
