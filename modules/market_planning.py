# -*- coding: utf-8 -*-
"""市场规划模块 — 产品字段提取、机会得分、类目筛选、数据进度"""

import os
import json
import tempfile
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QFormLayout, QLineEdit,
    QHBoxLayout, QFileDialog, QLabel, QComboBox, QCheckBox, QScrollArea,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt

from core.widgets import (
    Card, LogConsole, FileDropLineEdit, make_button, configure_combo,
    file_row, set_running_state, make_hint_label,
)

MODULE_INFO = {
    "name": "市场规划",
    "icon": "🎯",
    "category": "市场与产品规划",
    "order": 5,
    "description": "产品字段提取、机会得分、类目AI筛选、数据进度",
}


# ============================================================
# 对话框：添加类目
# ============================================================

class AddCategoryDialog(QDialog):
    """添加新产品类目。"""
    def __init__(self, config_path, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.setWindowTitle("添加产品类目")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("英文标识，如 socket_adapter")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("中文名称，如 插座适配器")

        layout.addRow("类目 Key:", self.key_edit)
        layout.addRow("类目名称:", self.name_edit)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        ok_btn = make_button("确定", "primary")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = make_button("取消")
        cancel_btn.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addRow(btns)

    def _on_ok(self):
        key = self.key_edit.text().strip()
        name = self.name_edit.text().strip()
        if not key or not name:
            QMessageBox.warning(self, "提示", "请填写完整。")
            return
        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        if key in config.get("products", {}):
            QMessageBox.warning(self, "提示", f"类目 '{key}' 已存在。")
            return
        config.setdefault("products", {})[key] = {
            "name": name,
            "target_fields": [],
            "field_config": {},
            "vision_allowed_fields": [],
            "vision_field_config": {},
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        self.accept()


# ============================================================
# 对话框：编辑字段
# ============================================================

class FieldEditorDialog(QDialog):
    """编辑某个类目的字段列表和提取规则。"""
    def __init__(self, config_path, product_key, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.product_key = product_key
        self.setWindowTitle(f"编辑字段 — {product_key}")
        self.setMinimumSize(720, 480)
        self._load()
        self._init_ui()

    def _load(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        self.product = config.get("products", {}).get(self.product_key, {})
        self.fields = list(self.product.get("target_fields", []))
        self.field_config = dict(self.product.get("field_config", {}))
        self.vision_allowed = list(self.product.get("vision_allowed_fields", []))
        self.vision_config = dict(self.product.get("vision_field_config", {}))

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        hint = make_hint_label(
            "字段名为提取结果列名；文本/图片提取规则用于指导 AI 如何识别该字段。")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["字段名", "文本提取规则", "允许图片识别", "图片提取规则"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)

        for field in self.fields:
            self._add_row(field)

        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        add_btn = make_button("+ 添加字段", "compact")
        add_btn.clicked.connect(lambda: self._add_row(""))
        del_btn = make_button("- 删除选中", "danger")
        del_btn.clicked.connect(self._del_selected)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        save_btn = make_button("保存", "primary")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _add_row(self, field_name):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(field_name))
        self.table.setItem(row, 1, QTableWidgetItem(
            self.field_config.get(field_name, "")))
        vision_chk = QCheckBox()
        vision_chk.setChecked(field_name in self.vision_allowed)
        self.table.setCellWidget(row, 2, vision_chk)
        self.table.setItem(row, 3, QTableWidgetItem(
            self.vision_config.get(field_name, "")))

    def _del_selected(self):
        rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()),
                      reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def _save(self):
        new_fields = []
        new_field_config = {}
        new_vision_allowed = []
        new_vision_config = {}

        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text().strip() if self.table.item(row, 0) else ""
            if not name:
                continue
            new_fields.append(name)

            text_rule = self.table.item(row, 1).text().strip() if self.table.item(row, 1) else ""
            if text_rule:
                new_field_config[name] = text_rule

            chk = self.table.cellWidget(row, 2)
            if isinstance(chk, QCheckBox) and chk.isChecked():
                new_vision_allowed.append(name)

            vision_rule = self.table.item(row, 3).text().strip() if self.table.item(row, 3) else ""
            if vision_rule:
                new_vision_config[name] = vision_rule

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        config["products"][self.product_key] = {
            "name": self.product.get("name", self.product_key),
            "target_fields": new_fields,
            "field_config": new_field_config,
            "vision_allowed_fields": new_vision_allowed,
            "vision_field_config": new_vision_config,
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        QMessageBox.information(self, "保存成功", f"已保存 {len(new_fields)} 个字段。")
        self.accept()


# ============================================================
# 主模块
# ============================================================

class ModuleWidget(QWidget):
    def __init__(self, config_mgr, runner):
        super().__init__()
        self.config_mgr = config_mgr
        self.runner = runner
        self._field_cbs = []
        self._init_ui()

    def _get_config_path(self):
        return self.config_mgr.resolve_config("product_field_config.json")

    def _load_products(self):
        path = self._get_config_path()
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("products", {})

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.setSpacing(14)
        tabs = QTabWidget()

        # ================= Tab 1: 字段提取 =================
        tab1 = QWidget()
        t1 = QVBoxLayout(tab1)
        t1.setContentsMargins(0, 0, 0, 0)
        t1.setSpacing(14)

        card1 = Card("产品字段提取（文本 + 视觉）",
                     "从商品描述/主图中用 AI 提取结构化字段（如插孔数、线长、材质等），可启用图片识别")
        form1 = QFormLayout()
        form1.setSpacing(10)

        self.tag_input = FileDropLineEdit(placeholder="选择或拖入商品数据 Excel 文件")
        form1.addRow("输入文件:", file_row(self.tag_input, "open", parent=self))

        self.tag_output = FileDropLineEdit(placeholder="留空则使用默认输出路径")
        form1.addRow("输出文件:", file_row(self.tag_output, "save", parent=self))

        self.tag_combo = configure_combo(QComboBox())
        self.tag_combo.setMinimumWidth(200)
        self._refresh_combo()
        self.tag_combo.currentIndexChanged.connect(self._on_combo_changed)

        add_cat_btn = make_button("+ 添加类目", "compact")
        add_cat_btn.clicked.connect(self._add_category)
        edit_field_btn = make_button("编辑字段", "compact")
        edit_field_btn.clicked.connect(self._edit_fields)

        combo_row = QHBoxLayout()
        combo_row.setSpacing(8)
        combo_row.addWidget(self.tag_combo)
        combo_row.addWidget(add_cat_btn)
        combo_row.addWidget(edit_field_btn)
        combo_row.addStretch()
        form1.addRow("产品类目:", combo_row)

        # 字段勾选区
        self._field_scroll = QScrollArea()
        self._field_scroll.setWidgetResizable(True)
        self._field_scroll.setMaximumHeight(130)
        self._field_container = QWidget()
        self._field_layout = QVBoxLayout(self._field_container)
        self._field_layout.setContentsMargins(4, 4, 4, 4)
        self._field_layout.setSpacing(4)
        self._field_scroll.setWidget(self._field_container)
        form1.addRow("提取字段:", self._field_scroll)

        sel_row = QHBoxLayout()
        sel_row.setSpacing(8)
        sel_all = make_button("全选", "compact")
        sel_all.clicked.connect(lambda: self._set_all_fields(True))
        sel_none = make_button("全不选", "compact")
        sel_none.clicked.connect(lambda: self._set_all_fields(False))
        sel_row.addStretch()
        sel_row.addWidget(sel_all)
        sel_row.addWidget(sel_none)
        form1.addRow(sel_row)

        self.vision_cb = QCheckBox("启用图片识别（需要配置视觉模型）")
        self.vision_cb.setChecked(True)
        form1.addRow(self.vision_cb)

        self._stop_file = os.path.join(tempfile.gettempdir(), "extract_stop.signal")
        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(10)
        self.run_btn1 = make_button("执行提取", "primary")
        self.run_btn1.clicked.connect(self._run_tagging)
        self.stop_btn1 = make_button("停止", "danger", "当前行处理完后保存并退出")
        self.stop_btn1.setEnabled(False)
        self.stop_btn1.clicked.connect(self._stop_extraction)
        btn_row1.addWidget(self.run_btn1)
        btn_row1.addWidget(self.stop_btn1)
        form1.addRow(btn_row1)
        card1.content_layout.addLayout(form1)
        t1.addWidget(card1)
        self.log1 = LogConsole()
        t1.addWidget(self.log1)
        t1.addStretch()
        tabs.addTab(tab1, "字段提取")

        self._refresh_field_cbs()

        # ================= Tab 2: 机会得分 =================
        tab2 = QWidget()
        t2 = QVBoxLayout(tab2)
        t2.setContentsMargins(0, 0, 0, 0)
        t2.setSpacing(14)

        card2 = Card("市场机会得分计算",
                     "选择包含市场数据 Excel 的文件夹，计算各细分市场的综合机会得分并输出汇总评分表")
        form2 = QFormLayout()
        form2.setSpacing(10)

        self.score_dir = FileDropLineEdit(want_dir=True, placeholder="市场数据 Excel 所在文件夹")
        form2.addRow("数据目录:", file_row(self.score_dir, "dir", parent=self))

        self.score_output = FileDropLineEdit(placeholder="留空则使用默认输出路径")
        form2.addRow("输出文件:", file_row(self.score_output, "save", parent=self))

        self.run_btn2 = make_button("计算得分", "primary")
        self.run_btn2.clicked.connect(self._run_scoring)
        form2.addRow(self.run_btn2)
        card2.content_layout.addLayout(form2)
        t2.addWidget(card2)
        self.log2 = LogConsole()
        t2.addWidget(self.log2)
        t2.addStretch()
        tabs.addTab(tab2, "机会得分")

        # ================= Tab 3: 类目筛选 =================
        tab3 = QWidget()
        t3 = QVBoxLayout(tab3)
        t3.setContentsMargins(0, 0, 0, 0)
        t3.setSpacing(14)

        card3 = Card("类目 AI 筛选",
                     "用 AI 对类目列表进行初筛，过滤掉不相关或不可进入的类目")
        form3 = QFormLayout()
        form3.setSpacing(10)

        self.cat_input = FileDropLineEdit(placeholder="选择或拖入类目数据 Excel 文件")
        form3.addRow("类目数据:", file_row(self.cat_input, "open", parent=self))

        self.cat_output = FileDropLineEdit(placeholder="留空则使用默认输出路径")
        form3.addRow("输出文件:", file_row(self.cat_output, "save", parent=self))

        self.run_btn3 = make_button("执行 AI 筛选", "primary")
        self.run_btn3.clicked.connect(self._run_category)
        form3.addRow(self.run_btn3)
        card3.content_layout.addLayout(form3)
        t3.addWidget(card3)
        self.log3 = LogConsole()
        t3.addWidget(self.log3)
        t3.addStretch()
        tabs.addTab(tab3, "类目筛选")

        # ================= Tab 4: 数据进度 =================
        tab4 = QWidget()
        t4 = QVBoxLayout(tab4)
        t4.setContentsMargins(0, 0, 0, 0)
        t4.setSpacing(14)

        card4 = Card("数据获取进度检查",
                     "对比全部 ID 列表与已爬取目录，统计各品类数据获取完成百分比")
        form4 = QFormLayout()
        form4.setSpacing(10)

        self.progress_ids = FileDropLineEdit(placeholder="全部 ID 列表（txt）")
        form4.addRow("全部ID文件:",
                     file_row(self.progress_ids, "open",
                              caption="选择 ID 列表",
                              filter_str="Text (*.txt);;All Files (*)", parent=self))

        self.progress_dir = FileDropLineEdit(want_dir=True, placeholder="已爬取数据所在目录")
        form4.addRow("已爬取目录:", file_row(self.progress_dir, "dir", parent=self))

        self.progress_ext = QLineEdit(".png")
        form4.addRow("文件扩展名:", self.progress_ext)

        self.run_btn4 = make_button("检查进度", "primary")
        self.run_btn4.clicked.connect(self._run_progress)
        form4.addRow(self.run_btn4)
        card4.content_layout.addLayout(form4)
        t4.addWidget(card4)
        self.log4 = LogConsole()
        t4.addWidget(self.log4)
        t4.addStretch()
        tabs.addTab(tab4, "数据进度")

        layout.addWidget(tabs)

    # ---- 字段复选框管理 ----

    def _refresh_combo(self):
        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        products = self._load_products()
        for key, info in products.items():
            self.tag_combo.addItem(f"{info.get('name', key)} ({key})", key)
        self.tag_combo.blockSignals(False)

    def _on_combo_changed(self):
        self._refresh_field_cbs()

    def _refresh_field_cbs(self):
        for cb in self._field_cbs:
            cb.setParent(None)
            cb.deleteLater()
        self._field_cbs = []

        # 清空旧行容器
        while self._field_layout.count():
            item = self._field_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        key = self.tag_combo.currentData()
        if not key:
            return
        products = self._load_products()
        product = products.get(key, {})
        fields = product.get("target_fields", [])

        row_widget = None
        row_layout = None
        for i, field in enumerate(fields):
            if i % 3 == 0:
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(12)
                self._field_layout.addWidget(row_widget)
            cb = QCheckBox(field)
            cb.setChecked(True)
            self._field_cbs.append(cb)
            row_layout.addWidget(cb)

        self._field_layout.addStretch()

    def _set_all_fields(self, checked):
        for cb in self._field_cbs:
            cb.setChecked(checked)

    def _get_selected_fields(self):
        return [cb.text() for cb in self._field_cbs if cb.isChecked()]

    # ---- 类目管理 ----

    def _add_category(self):
        dlg = AddCategoryDialog(self._get_config_path(), self)
        if dlg.exec():
            self._refresh_combo()
            self.tag_combo.setCurrentIndex(self.tag_combo.count() - 1)

    def _edit_fields(self):
        key = self.tag_combo.currentData()
        if not key:
            QMessageBox.warning(self, "提示", "请先选择一个类目。")
            return
        dlg = FieldEditorDialog(self._get_config_path(), key, self)
        if dlg.exec():
            self._refresh_field_cbs()

    # ---- 脚本执行 ----

    def _run(self, script, log_area, env_overrides=None, run_btn=None,
             finished_callback=None):
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
            if finished_callback is not None:
                finished_callback(code)

        self.runner.finished_signal.connect(_done)
        if run_btn is not None:
            set_running_state(run_btn, True)
        log_area.set_status("running")
        env = self.config_mgr.get_env_dict()
        if env_overrides:
            env.update(env_overrides)
        script_path = os.path.join(self.config_mgr.get_script_dir(), script)
        return self.runner.run_script(script_path, env_extra=env)

    def _run_tagging(self):
        inp = self.tag_input.text().strip()
        if not inp:
            self.log1.append("[提示] 请先选择「输入文件」")
            return
        selected = self._get_selected_fields()
        if not selected:
            QMessageBox.warning(self, "提示", "请至少勾选一个提取字段。")
            return
        env = {"INPUT_FILE": inp}
        out = self.tag_output.text().strip()
        if out:
            env["OUTPUT_FILE"] = out
        key = self.tag_combo.currentData()
        if key:
            env["CURRENT_PRODUCT"] = key
        env["CONFIG_FILE"] = self._get_config_path()
        env["FIELDS"] = ",".join(selected)
        env["ENABLE_VISION"] = "1" if self.vision_cb.isChecked() else "0"
        env["STOP_FILE"] = self._stop_file
        # 清除旧的停止信号
        if os.path.exists(self._stop_file):
            os.remove(self._stop_file)
        self.stop_btn1.setEnabled(True)
        started = self._run(
            "exstract_from_description.py", self.log1, env,
            run_btn=self.run_btn1, finished_callback=self._on_extraction_done,
        )
        if not started:
            self.stop_btn1.setEnabled(False)

    def _on_extraction_done(self, _code):
        self.stop_btn1.setEnabled(False)

    def _stop_extraction(self):
        """创建停止信号文件，通知脚本优雅退出。"""
        try:
            with open(self._stop_file, "w") as f:
                f.write("stop")
            self.log1.append("\n[停止] 正在停止，当前行处理完后将保存并退出...")
            self.stop_btn1.setEnabled(False)
        except Exception as e:
            self.log1.append(f"\n[错误] 无法创建停止信号: {e}")

    def _run_scoring(self):
        data_dir = self.score_dir.text().strip()
        output = self.score_output.text().strip()
        if not data_dir:
            self.log2.setPlainText("请先选择数据目录。")
            return
        env = {"MARKET_DATA_DIR": data_dir}
        if output:
            env["MARKET_OUTPUT_FILE"] = output
        self._run("欧洲市场规划/机会得分.py", self.log2, env, run_btn=self.run_btn2)

    def _run_category(self):
        inp = self.cat_input.text().strip()
        if not inp:
            self.log3.setPlainText("请先选择类目数据文件。")
            return
        env = {"CATEGORY_INPUT_FILE": inp}
        out = self.cat_output.text().strip()
        if out:
            env["CATEGORY_OUTPUT_FILE"] = out
            env["CATEGORY_CHECKPOINT_FILE"] = out
        self._run("欧洲市场规划/类目初筛.py", self.log3, env, run_btn=self.run_btn3)

    def _run_progress(self):
        ids_file = self.progress_ids.text().strip()
        data_dir = self.progress_dir.text().strip()
        if not ids_file or not data_dir:
            self.log4.setPlainText("请先选择全部ID文件和已爬取目录。")
            return
        env = {
            "PROGRESS_ALL_IDS_FILE": ids_file,
            "PROGRESS_DATA_FOLDER": data_dir,
            "PROGRESS_FILE_EXTENSION": self.progress_ext.text().strip() or ".png",
        }
        self._run("欧洲市场规划/数据获取进度.py", self.log4, env, run_btn=self.run_btn4)
