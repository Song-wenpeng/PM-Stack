# -*- coding: utf-8 -*-
"""评论分析模块 — AI特征提取、归类总结、可视化看板"""

import os
import json
import shutil
import tempfile
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QFormLayout,
    QLineEdit, QHBoxLayout, QFileDialog, QLabel, QPlainTextEdit,
    QMessageBox, QComboBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QSizePolicy

from core.widgets import (
    Card, LogConsole, FileDropLineEdit, make_button, configure_combo,
    file_row, set_running_state, default_output, make_hint_label,
    browse_file, browse_save_file, browse_dir,
)
from core.reviews.panel import ReviewCollectionPanel

MODULE_INFO = {
    "name": "评论分析",
    "icon": "💬",
    "category": "分析中心",
    "order": 1,
    "description": "Amazon 评论采集、云端存储、AI 提取与归类",
}


class ModuleWidget(QWidget):
    def __init__(self, config_mgr, runner):
        super().__init__()
        self.config_mgr = config_mgr
        self.runner = runner
        self._stop_file = os.path.join(tempfile.gettempdir(), "comment_stop.signal")
        self._stopped = False
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.setSpacing(14)

        # ---- 品类配置栏 ----
        cfg_card = Card("分析品类配置", "品类模板决定 AI 提取的标签结构与维度")
        cfg_row = QHBoxLayout()
        cfg_row.setSpacing(10)
        self.cfg_status = make_hint_label("")
        cfg_row.addWidget(self.cfg_status)
        cfg_row.addStretch()
        import_btn = make_button("导入新配置", tooltip="从 JSON 文件导入品类配置")
        import_btn.clicked.connect(self._import_config)
        cfg_row.addWidget(import_btn)
        export_btn = make_button("导出当前配置", tooltip="把当前品类配置导出为 JSON 备份")
        export_btn.clicked.connect(self._export_config)
        cfg_row.addWidget(export_btn)
        cfg_card.content_layout.addLayout(cfg_row)
        layout.addWidget(cfg_card)

        tabs = QTabWidget()
        self.tabs = tabs

        # ================= Tab 0: 评论采集、评论库与云端 =================
        self.review_collection = ReviewCollectionPanel(
            self.config_mgr, self.runner, parent=self
        )
        self.review_collection.analysis_requested.connect(
            self._use_collected_review_file
        )
        tabs.addTab(self.review_collection, "采集与云端")

        # ================= Tab 1: AI提取评论标签 =================
        tab1 = QWidget()
        t1 = QVBoxLayout(tab1)
        t1.setContentsMargins(0, 0, 0, 0)
        t1.setSpacing(14)

        card1 = Card("AI 提取评论标签",
                     "逐条读取评论，用 AI 自动提取评价标签（优缺点、使用场景、问题点等）")
        form1 = QFormLayout()
        form1.setSpacing(10)
        self.s1_input = FileDropLineEdit(placeholder="选择或拖入原始评论 Excel 文件")
        form1.addRow("输入文件:", file_row(self.s1_input, "open", parent=self))
        self.s1_output = FileDropLineEdit(placeholder="留空则自动在输入文件旁生成")
        form1.addRow("输出文件:", file_row(self.s1_output, "save", parent=self))
        self.s1_input.textChanged.connect(
            lambda: self._auto_output(self.s1_input, self.s1_output, "_AI处理"))

        self.s1_product = configure_combo(QComboBox())
        form1.addRow("分析品类:", self.s1_product)

        self.s1_sheets = QLineEdit()
        self.s1_sheets.setPlaceholderText("逗号分隔，如: 5 star,4 star,3 star")
        form1.addRow("评论数据表:", self.s1_sheets)

        self.run_btn1 = make_button("开始提取", "primary")
        self.run_btn1.clicked.connect(self._run_step1)
        form1.addRow(self.run_btn1)
        card1.content_layout.addLayout(form1)
        t1.addWidget(card1)
        self.log_s1 = LogConsole()
        t1.addWidget(self.log_s1)
        t1.addStretch()
        tabs.addTab(tab1, "AI 提取标签")

        # ================= Tab 2: 汇总评论洞察 =================
        tab2 = QWidget()
        t2 = QVBoxLayout(tab2)
        t2.setContentsMargins(0, 0, 0, 0)
        t2.setSpacing(14)

        card2 = Card("汇总评论洞察",
                     "把上一步提取的标签按主题归类汇总，形成分析结论")
        form2 = QFormLayout()
        form2.setSpacing(10)
        self.s2_input = FileDropLineEdit(placeholder="选择或拖入 Step1 输出的标签文件")
        form2.addRow("标签文件:", file_row(self.s2_input, "open", parent=self))
        self.s2_output = FileDropLineEdit(placeholder="留空则自动在输入文件旁生成")
        form2.addRow("输出文件:", file_row(self.s2_output, "save", parent=self))
        self.s2_input.textChanged.connect(
            lambda: self._auto_output(self.s2_input, self.s2_output, "_AI总结"))

        self.s2_product = configure_combo(QComboBox())
        form2.addRow("分析品类:", self.s2_product)

        self.s2_sheets = QLineEdit()
        self.s2_sheets.setPlaceholderText("逗号分隔，如: 5 star,4 star,3 star")
        form2.addRow("评论数据表:", self.s2_sheets)

        self.run_btn2 = make_button("开始汇总", "primary")
        self.run_btn2.clicked.connect(self._run_step2)
        form2.addRow(self.run_btn2)
        card2.content_layout.addLayout(form2)
        t2.addWidget(card2)
        self.log_s2 = LogConsole()
        t2.addWidget(self.log_s2)
        t2.addStretch()
        tabs.addTab(tab2, "汇总洞察")

        # ================= Tab 3: 一键完成分析 =================
        tab3 = QWidget()
        t3 = QVBoxLayout(tab3)
        t3.setContentsMargins(0, 0, 0, 0)
        t3.setSpacing(14)

        card3 = Card("一键完成分析",
                     "自动完成 提取标签 → 归类汇总 全流程，一次出结果")
        form3 = QFormLayout()
        form3.setSpacing(10)
        self.s12_input = FileDropLineEdit(placeholder="选择或拖入原始评论 Excel 文件")
        form3.addRow("输入文件:", file_row(self.s12_input, "open", parent=self))

        self.s12_product = configure_combo(QComboBox())
        form3.addRow("分析品类:", self.s12_product)

        self.s12_sheets = QLineEdit()
        self.s12_sheets.setPlaceholderText("逗号分隔，如: 5 star,4 star,3 star")
        form3.addRow("评论数据表:", self.s12_sheets)

        btn_row3 = QHBoxLayout()
        btn_row3.setSpacing(10)
        self.run_btn3 = make_button("一键完成分析", "primary")
        self.run_btn3.clicked.connect(self._run_full)
        self.stop_btn3 = make_button("停止", "danger", "当前条目处理完成后停止")
        self.stop_btn3.setEnabled(False)
        self.stop_btn3.clicked.connect(self._stop)
        btn_row3.addWidget(self.run_btn3)
        btn_row3.addWidget(self.stop_btn3)
        form3.addRow(btn_row3)
        card3.content_layout.addLayout(form3)
        t3.addWidget(card3)
        self.log_s12 = LogConsole()
        t3.addWidget(self.log_s12)
        t3.addStretch()
        tabs.addTab(tab3, "一键完成")

        # ================= Tab 4: 多文件批量分析 =================
        tab4 = QWidget()
        t4 = QVBoxLayout(tab4)
        t4.setContentsMargins(0, 0, 0, 0)
        t4.setSpacing(14)

        card4 = Card("多文件批量分析",
                     "多个评论文件依次执行完整分析，每个文件独立出结果")
        form4 = QFormLayout()
        form4.setSpacing(10)

        self.batch_files = QPlainTextEdit()
        self.batch_files.setPlaceholderText("每行一个文件路径，可点击下方按钮逐个添加")
        self.batch_files.setMaximumHeight(96)
        self.batch_files.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        form4.addRow("文件列表:", self.batch_files)

        btn_add = make_button("+ 添加文件", "compact")
        btn_add.clicked.connect(self._batch_add_file)
        form4.addRow(btn_add)

        self.batch_product = configure_combo(QComboBox())
        form4.addRow("分析品类:", self.batch_product)

        self.batch_sheets = QLineEdit()
        self.batch_sheets.setPlaceholderText("逗号分隔，如: 5 star,4 star,3 star")
        form4.addRow("评论数据表:", self.batch_sheets)

        self.batch_output_dir = FileDropLineEdit(
            want_dir=True, placeholder="留空则输出到各输入文件所在目录")
        form4.addRow("输出目录:", file_row(self.batch_output_dir, "dir", parent=self))

        btn_row4 = QHBoxLayout()
        btn_row4.setSpacing(10)
        self.run_btn4 = make_button("开始批量分析", "primary")
        self.run_btn4.clicked.connect(self._run_batch)
        self.stop_btn4 = make_button("停止", "danger", "当前文件处理完成后停止")
        self.stop_btn4.setEnabled(False)
        self.stop_btn4.clicked.connect(self._stop)
        btn_row4.addWidget(self.run_btn4)
        btn_row4.addWidget(self.stop_btn4)
        form4.addRow(btn_row4)
        card4.content_layout.addLayout(form4)
        t4.addWidget(card4)
        self.log_batch = LogConsole()
        t4.addWidget(self.log_batch)
        t4.addStretch()
        tabs.addTab(tab4, "批量分析")

        layout.addWidget(tabs)
        self._refresh_cfg_status()

    # ---- 小工具 ----

    def _use_collected_review_file(self, path):
        """Receive a compatible workbook exported from the review library."""
        self.s12_input.setText(path)
        self.s12_sheets.clear()
        self.tabs.setCurrentWidget(self.tabs.widget(3))
        self.log_s12.clear()
        self.log_s12.append(
            f"[已就绪] 已载入评论库导出文件：\n{path}\n"
            "请选择分析品类，然后点击“一键完成分析”。"
        )

    @staticmethod
    def _auto_output(input_edit, output_edit, suffix):
        """输入改变时更新自动建议，但保留用户手工填写的输出路径。"""
        inp = input_edit.text().strip()
        suggested = default_output(inp, suffix) if inp else ""
        previous_auto = output_edit.property("_autoOutputValue")
        current = output_edit.text().strip()
        if not current or current == (previous_auto or ""):
            output_edit.setText(suggested)
            output_edit.setProperty("_autoOutputValue", suggested)

    # ---- 配置管理 ----

    def _refresh_cfg_status(self):
        products = self._load_products()
        self._populate_product_combos(products)
        if products:
            self.cfg_status.setText(f"已加载 {len(products)} 个品类模板")
        else:
            self.cfg_status.setText("未找到配置文件")

    def _load_products(self):
        """读取品类配置，返回 [(显示名, key)]。显示名优先取 config 内 display_name，缺省用 key。"""
        path = self.config_mgr.resolve_config("product_configs.json")
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            return []
        products = cfg.get("products", cfg)
        if not isinstance(products, dict):
            return []
        result = []
        for key, data in products.items():
            if isinstance(data, dict) and data.get("display_name"):
                result.append((data["display_name"], key))
            else:
                result.append((key, key))
        return result

    def _populate_product_combos(self, products):
        """把品类填充到四个分析页的下拉框，userData 存稳定 key。"""
        combos = [self.s1_product, self.s2_product, self.s12_product, self.batch_product]
        for combo in combos:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("请选择品类…")
            combo.setItemData(0, QColor("#8F959E"), Qt.ItemDataRole.ForegroundRole)
            for display, key in products:
                combo.addItem(display, userData=key)
            combo.blockSignals(False)

    def _import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择新的产品配置文件", "", "JSON (*.json);;All Files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("JSON 顶层必须是对象")
        except Exception as e:
            QMessageBox.warning(self, "格式错误", f"无法解析为有效 JSON:\n{e}")
            return
        target = self.config_mgr.resolve_config("product_configs.json")
        try:
            shutil.copy2(path, target)
            self._refresh_cfg_status()
            QMessageBox.information(self, "导入成功", f"配置已更新:\n{target}")
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))

    def _export_config(self):
        source = self.config_mgr.resolve_config("product_configs.json")
        if not os.path.exists(source):
            QMessageBox.warning(self, "提示", "当前没有可导出的配置文件。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出配置文件", "product_configs.json", "JSON (*.json)")
        if not path:
            return
        try:
            shutil.copy2(source, path)
            QMessageBox.information(self, "导出成功", f"配置已保存到:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    # ---- 脚本执行 ----

    def _build_env(self):
        env = self.config_mgr.get_env_dict()
        env["CONFIG_FILE"] = self.config_mgr.resolve_config("product_configs.json")
        return env

    def _run(self, script, log_area, env_overrides=None, run_btn=None):
        if self.runner.is_running() or self.runner.is_any_running():
            log_area.append("[提示] 当前有任务正在运行，请等待完成。")
            return False
        log_area.clear()
        try:
            self.runner.log_signal.disconnect()
        except TypeError:
            pass
        try:
            self.runner.finished_signal.disconnect()
        except TypeError:
            pass
        self.runner.log_signal.connect(log_area.append)

        def _done(code):
            log_area.append(f"\n[完成] 退出码: {code}")
            log_area.set_status("ok" if code == 0 else "error")
            if run_btn is not None:
                set_running_state(run_btn, False)

        self.runner.finished_signal.connect(_done)
        if run_btn is not None:
            set_running_state(run_btn, True)
        log_area.set_status("running")
        env = self._build_env()
        if env_overrides:
            env.update(env_overrides)
        script_path = os.path.join(self.config_mgr.get_script_dir(), script)
        return self.runner.run_script(script_path, env_extra=env)

    def _run_step1(self):
        inp = self.s1_input.text().strip()
        if not inp:
            self.log_s1.append("[提示] 请先选择「输入文件」")
            return
        prod = self.s1_product.currentData()
        if not prod:
            self.log_s1.setPlainText("请先选择分析品类。")
            return
        overrides = {
            "RAW_INPUT_FILE": inp,
            "STEP1_OUTPUT_FILE": self.s1_output.text().strip() or default_output(inp, "_AI处理"),
            "CURRENT_PRODUCT": prod,
        }
        out = self.s1_output.text().strip()
        if out:
            overrides["STEP1_OUTPUT_FILE"] = out
        sheets = self.s1_sheets.text().strip()
        if sheets:
            overrides["TARGET_SHEETS"] = sheets
        self._run("comments_step_1.py", self.log_s1, overrides, run_btn=self.run_btn1)

    def _run_step2(self):
        inp = self.s2_input.text().strip()
        if not inp:
            self.log_s2.append("[提示] 请先选择「标签文件」")
            return
        prod = self.s2_product.currentData()
        if not prod:
            self.log_s2.setPlainText("请先选择一个分析品类。")
            return
        overrides = {
            "STEP1_OUTPUT_FILE": inp,
            "STEP2_OUTPUT_FILE": self.s2_output.text().strip() or default_output(inp, "_AI总结"),
            "CURRENT_PRODUCT": prod,
        }
        sheets = self.s2_sheets.text().strip()
        if sheets:
            overrides["TARGET_SHEETS"] = sheets
        self._run("comments_step_2.py", self.log_s2, overrides, run_btn=self.run_btn2)

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

    def _set_running(self, running, tab="full"):
        """切换按钮状态：running=True 时禁用执行按钮、启用停止按钮。"""
        if tab == "full":
            self.stop_btn3.setEnabled(running)
            set_running_state(self.run_btn3, running)
        else:
            self.stop_btn4.setEnabled(running)
            set_running_state(self.run_btn4, running)

    def _run_full(self):
        if self.runner.is_running() or self.runner.is_any_running():
            self.log_s12.append("[提示] 当前有任务正在运行，请等待完成。")
            return
        inp = self.s12_input.text().strip()
        if not inp:
            self.log_s12.append("[提示] 请先选择「输入文件」")
            return
        prod = self.s12_product.currentData()
        if not prod:
            self.log_s12.setPlainText("请先选择分析品类。")
            return

        p = Path(inp)
        out_dir = str(p.parent)
        step1_path = os.path.join(out_dir, f"{p.stem}_AI处理{p.suffix}")
        step2_path = os.path.join(out_dir, f"{p.stem}_AI全流程{p.suffix}")

        self._full_overrides = {
            "RAW_INPUT_FILE": inp,
            "CURRENT_PRODUCT": prod,
            "STEP1_OUTPUT_FILE": step1_path,
            "STEP2_OUTPUT_FILE": step2_path,
        }
        sheets = self.s12_sheets.text().strip()
        if sheets:
            self._full_overrides["TARGET_SHEETS"] = sheets

        self._clear_stop()
        self._set_running(True, "full")
        self.log_s12.clear()
        self.log_s12.set_status("running")
        self.log_s12.append("=== 全流程开始 ===\n")
        self.log_s12.append("→ Step 1: AI特征提取...")
        self._full_run_step1()

    def _full_run_step1(self):
        try:
            self.runner.finished_signal.disconnect()
        except TypeError:
            pass
        self.runner.finished_signal.connect(self._full_on_step1_done)
        env = self._build_env()
        env.update(self._full_overrides)
        script_path = os.path.join(self.config_mgr.get_script_dir(), "comments_step_1.py")
        self.runner.run_script(script_path, env_extra=env)

    def _full_on_step1_done(self, code):
        try:
            self.runner.finished_signal.disconnect(self._full_on_step1_done)
        except TypeError:
            pass
        if self._is_stopped():
            self.log_s12.append("\n[停止] 用户中止。")
            self.log_s12.set_status("error")
            self._set_running(False, "full")
            return
        if code != 0:
            self.log_s12.append(f"✗ Step 1 失败 (退出码: {code})")
            self.log_s12.set_status("error")
            self._set_running(False, "full")
            return
        self.log_s12.append("✓ Step 1 完成")
        self.log_s12.append("→ Step 2: AI归类总结...")
        self._full_run_step2()

    def _full_run_step2(self):
        try:
            self.runner.finished_signal.disconnect()
        except TypeError:
            pass
        self.runner.finished_signal.connect(self._full_on_step2_done)
        env = self._build_env()
        env.update(self._full_overrides)
        script_path = os.path.join(self.config_mgr.get_script_dir(), "comments_step_2.py")
        self.runner.run_script(script_path, env_extra=env)

    def _full_on_step2_done(self, code):
        try:
            self.runner.finished_signal.disconnect(self._full_on_step2_done)
        except TypeError:
            pass
        if code != 0:
            self.log_s12.append(f"✗ Step 2 失败 (退出码: {code})")
            self.log_s12.set_status("error")
        else:
            self.log_s12.append("✓ Step 2 完成\n\n=== 全流程完成 ===")
            self.log_s12.set_status("ok")
        self._set_running(False, "full")

    # ---- 批量处理 ----

    def _batch_add_file(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择评论文件", "", "Excel (*.xlsx *.xls)")
        if paths:
            existing = self.batch_files.toPlainText().strip()
            new_text = "\n".join(paths)
            if existing:
                self.batch_files.setPlainText(existing + "\n" + new_text)
            else:
                self.batch_files.setPlainText(new_text)

    def _run_batch(self):
        if self.runner.is_running() or self.runner.is_any_running():
            self.log_batch.append("[提示] 当前有任务正在运行，请等待完成。")
            return
        files_text = self.batch_files.toPlainText().strip()
        if not files_text:
            self.log_batch.setPlainText("请先添加输入文件。")
            return
        prod = self.batch_product.currentData()
        if not prod:
            self.log_batch.setPlainText("请先选择分析品类。")
            return
        file_list = [f.strip() for f in files_text.splitlines() if f.strip()]
        if not file_list:
            self.log_batch.setPlainText("文件列表为空。")
            return

        self._clear_stop()
        self._set_running(True, "batch")
        self.log_batch.clear()
        self.log_batch.set_status("running")
        self.log_batch.append(f"=== 批量处理开始，共 {len(file_list)} 个文件 ===\n")

        self._batch_queue = list(file_list)
        self._batch_idx = 0
        self._batch_total = len(file_list)
        self._batch_prod = prod
        self._batch_sheets = self.batch_sheets.text().strip()
        self._batch_output_dir = self.batch_output_dir.text().strip()
        self._batch_current_overrides = {}
        self._batch_next_file()

    def _batch_next_file(self):
        if self._is_stopped():
            self.log_batch.append(f"\n[停止] 用户中止，已完成 {self._batch_idx}/{self._batch_total} 个文件。")
            self.log_batch.set_status("error")
            self._set_running(False, "batch")
            return
        if self._batch_idx >= self._batch_total:
            self.log_batch.append(f"\n{'='*50}\n全部 {self._batch_total} 个文件处理完成！")
            self.log_batch.set_status("ok")
            self._set_running(False, "batch")
            return
        inp = self._batch_queue[self._batch_idx]
        self._batch_idx += 1
        idx = self._batch_idx
        self.log_batch.append(f"\n{'─'*50}")
        self.log_batch.append(f"[{idx}/{self._batch_total}] {os.path.basename(inp)}")
        if not os.path.exists(inp):
            self.log_batch.append("  ⚠ 文件不存在，跳过。")
            self._batch_next_file()
            return

        p = Path(inp)
        out_dir = self._batch_output_dir if self._batch_output_dir else str(p.parent)
        step1_path = os.path.join(out_dir, f"{p.stem}_AI处理{p.suffix}")
        step2_path = os.path.join(out_dir, f"{p.stem}_AI全流程{p.suffix}")

        self._batch_current_overrides = {
            "RAW_INPUT_FILE": inp,
            "CURRENT_PRODUCT": self._batch_prod,
            "STEP1_OUTPUT_FILE": step1_path,
            "STEP2_OUTPUT_FILE": step2_path,
        }
        if self._batch_sheets:
            self._batch_current_overrides["TARGET_SHEETS"] = self._batch_sheets
        self._batch_run_step1()

    def _batch_run_step1(self):
        self.log_batch.append("  → Step 1: AI特征提取...")
        try:
            self.runner.finished_signal.disconnect()
        except TypeError:
            pass
        self.runner.finished_signal.connect(self._batch_on_step1_done)
        env = self._build_env()
        env.update(self._batch_current_overrides)
        script_path = os.path.join(self.config_mgr.get_script_dir(), "comments_step_1.py")
        self.runner.run_script(script_path, env_extra=env)

    def _batch_on_step1_done(self, code):
        try:
            self.runner.finished_signal.disconnect(self._batch_on_step1_done)
        except TypeError:
            pass
        if self._is_stopped():
            self.log_batch.append(f"\n[停止] 用户中止，已完成 {self._batch_idx - 1}/{self._batch_total} 个文件。")
            self.log_batch.set_status("error")
            self._set_running(False, "batch")
            return
        if code != 0:
            self.log_batch.append(f"  ✗ Step 1 失败 (退出码: {code})，跳过此文件。")
            self._batch_next_file()
            return
        self.log_batch.append("  ✓ Step 1 完成")
        self._batch_run_step2()

    def _batch_run_step2(self):
        self.log_batch.append("  → Step 2: AI归类总结...")
        try:
            self.runner.finished_signal.disconnect()
        except TypeError:
            pass
        self.runner.finished_signal.connect(self._batch_on_step2_done)
        env = self._build_env()
        env.update(self._batch_current_overrides)
        script_path = os.path.join(self.config_mgr.get_script_dir(), "comments_step_2.py")
        self.runner.run_script(script_path, env_extra=env)

    def _batch_on_step2_done(self, code):
        try:
            self.runner.finished_signal.disconnect(self._batch_on_step2_done)
        except TypeError:
            pass
        if self._is_stopped():
            self.log_batch.append(f"\n[停止] 用户中止，已完成 {self._batch_idx - 1}/{self._batch_total} 个文件。")
            self.log_batch.set_status("error")
            self._set_running(False, "batch")
            return
        if code != 0:
            self.log_batch.append(f"  ✗ Step 2 失败 (退出码: {code})")
        else:
            self.log_batch.append("  ✓ Step 2 完成 → 全流程结束")
        self._batch_next_file()
