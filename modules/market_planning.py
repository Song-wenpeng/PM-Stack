# -*- coding: utf-8 -*-
"""市场规划模块 — 产品字段提取、机会得分、类目筛选、数据进度"""

import os
import json
import tempfile
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QFormLayout, QLineEdit,
    QHBoxLayout, QFileDialog, QLabel, QComboBox, QCheckBox, QScrollArea,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QAbstractItemView, QSpinBox, QSplitter,
)
from PyQt6.QtCore import Qt
from modules.field_template_panel import FieldTemplatePanel
from core.excel_choices import ChoiceEdit, ExcelChoices

from core.widgets import (
    Card, LogConsole, FileDropLineEdit, make_button, configure_combo,
    file_row, set_running_state, make_hint_label,
)

from core.task_ui import register_form, pin_actions, validated, mark_required, advanced_rows
from core.widgets import ScrollTabs, collapsible_log

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
        self.setProperty("workspacePage", True)
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
        tabs = ScrollTabs()

        # ================= Tab 1: 字段提取 =================
        tab1 = QWidget()
        tab1.setProperty("workspacePage", True)
        tab1_layout = QHBoxLayout(tab1)
        tab1_layout.setContentsMargins(0, 0, 0, 0)
        self.field_splitter = QSplitter(Qt.Orientation.Horizontal)
        tab1_layout.addWidget(self.field_splitter)
        field_left = QWidget()
        self.field_splitter.addWidget(field_left)
        self.template_panel = FieldTemplatePanel(self._get_config_path())
        self.template_panel.saved.connect(self._template_saved)
        self.field_splitter.addWidget(self.template_panel)
        self.field_splitter.setStretchFactor(0, 2)
        self.field_splitter.setStretchFactor(1, 1)
        self.template_panel.hide()
        t1 = QVBoxLayout(field_left)
        t1.setContentsMargins(0, 0, 0, 0)
        t1.setSpacing(14)

        card1 = Card("产品字段提取（文本 + 视觉）",
                     "从商品描述/主图中用 AI 提取结构化字段（如插孔数、线长、材质等），可启用图片识别")
        form1 = QFormLayout()
        form1.setSpacing(10)

        self.tag_input = FileDropLineEdit(placeholder="选择或拖入商品数据 Excel 文件")
        form1.addRow("输入文件:", file_row(self.tag_input, "open", parent=self))

        self.tag_output = FileDropLineEdit(placeholder="留空写回源文件；填写路径则另存副本")
        form1.addRow("输出文件:", file_row(self.tag_output, "save", parent=self))
        form1.addRow(QLabel("结果列放在 ASIN 后；过程信息写入“字段提取日志”。写回前自动备份，请关闭 Excel/WPS。"))

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
        self._field_scroll.setMinimumHeight(170)
        self._field_scroll.setMaximumHeight(220)
        self._field_container = QWidget()
        self._field_container.setObjectName("FieldGroup")
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
        self.field_search = QLineEdit()
        self.field_search.setPlaceholderText('搜索提取字段')
        self.field_search.textChanged.connect(self._filter_fields)
        sel_row.addWidget(self.field_search, 1)
        self.field_count = make_hint_label('')
        sel_row.addWidget(self.field_count)
        sel_row.addWidget(sel_all)
        sel_row.addWidget(sel_none)
        form1.addRow(sel_row)

        self.tag_filter_cb = QCheckBox('仅提取指定标签的行（默认所有行）')
        form1.addRow('提取范围:', self.tag_filter_cb)
        self.tag_filter_column = ChoiceEdit('打标')
        self.tag_filter_column.setPlaceholderText('选择或输入标签列名')
        self.tag_filter_value = QLineEdit('1')
        self.tag_filter_value.setPlaceholderText('填写要匹配的标签值，如 1')
        filter_row = QHBoxLayout()
        filter_row.addWidget(self.tag_filter_column, 1)
        filter_row.addWidget(QLabel('等于'))
        filter_row.addWidget(self.tag_filter_value, 1)
        form1.addRow('标签条件:', filter_row)
        for control in (self.tag_filter_column, self.tag_filter_value):
            control.setEnabled(False)
            self.tag_filter_cb.toggled.connect(control.setEnabled)
        self.tag_filter_choices = ExcelChoices(
            self.tag_input, [], [(self.tag_filter_column, None)], parent=self)

        self.vision_cb = QCheckBox("启用图片识别（需要配置视觉模型）")
        self.vision_cb.setChecked(True)
        form1.addRow(self.vision_cb)

        self.normalize_cb = QCheckBox('提取后自动归一化（统一格式与单位）')
        self.normalize_cb.setChecked(True)
        self.normalize_cb.setToolTip('按特征统计不同结果与频次，由文本模型批量建立映射，再修正对应行；无法确定的值保留原样。')
        form1.addRow(self.normalize_cb)

        self.fetch_cb = QCheckBox("自动补抓缺失的五点描述与主副图（边抓边提取）")
        self.fetch_cb.setChecked(True)
        self.fetch_cb.setToolTip(
            "输入表缺少或空着「五点描述」/图片列时，按「商品详情页链接」列实时抓取补齐后再提取；\n"
            "每个并发线程一个无头 Edge，不弹窗；抓取结果按 ASIN 缓存断点，重跑不重复抓；\n"
            "抓到的五点描述与 image_1..9 会一并写入输出 Excel。\n"
            "（默认开启；若输入表已备好五点描述与图片，可取消勾选跳过抓取。）")
        form1.addRow(self.fetch_cb)

        # 并发选项
        conc_row = QHBoxLayout()
        conc_row.setSpacing(8)
        self.fast_cb = QCheckBox("并发加速")
        self.fast_cb.setChecked(True)
        self.fast_cb.setToolTip("使用线程池并发处理，显著加快速度；支持断点续跑与失败标记")
        conc_row.addWidget(self.fast_cb)
        conc_row.addWidget(make_hint_label("并发数:"))
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 16)
        self.concurrency_spin.setValue(4)
        self.concurrency_spin.setToolTip("同时处理的行数，视觉模型较多时建议 2-4")
        conc_row.addWidget(self.concurrency_spin)
        conc_row.addStretch()
        form1.addRow(conc_row)

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
        register_form(form1)
        advanced_rows(form1, 8, 11, '图片识别、归一化、自动补抓与并发')
        self.extract_options_hint = make_hint_label('')
        form1.addRow(self.extract_options_hint)
        for option in (self.vision_cb, self.normalize_cb, self.fetch_cb, self.fast_cb):
            option.toggled.connect(self._update_extract_options)
        self.concurrency_spin.valueChanged.connect(self._update_extract_options)
        self._update_extract_options()
        card1.content_layout.addLayout(form1)
        t1.addWidget(card1)
        self.log1 = LogConsole()
        collapsible_log(t1, self.log1)
        t1.addStretch()
        self.field_splitter.insertWidget(0, pin_actions(field_left, self.run_btn1, self.stop_btn1))
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

        self.score_date = QLineEdit()
        self.score_date.setPlaceholderText("留空：使用运行当日")
        self.score_date.setToolTip("上架天数与新品判定都相对这个日期计算，格式 YYYY-MM-DD；"
                                   "留空表示按运行当日计算。")
        form2.addRow("分析基准日:", self.score_date)
        self.score_hint = make_hint_label('')
        self.score_hint.setTextFormat(Qt.TextFormat.PlainText)
        form2.addRow(self.score_hint)
        self.score_date.textChanged.connect(self._update_score_hint)
        self.score_output.textChanged.connect(self._update_score_hint)
        self._update_score_hint()

        self.run_btn2 = make_button("计算得分", "primary")
        self.run_btn2.clicked.connect(self._run_scoring)
        register_form(form2)
        card2.content_layout.addLayout(form2)
        t2.addWidget(card2)
        self.log2 = LogConsole()
        collapsible_log(t2, self.log2)
        t2.addStretch()
        tabs.addTab(pin_actions(tab2, self.run_btn2), "机会得分")

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

        self.cat_output = FileDropLineEdit(placeholder="留空：在输入旁另存“原名_类目筛选结果.xlsx”")
        form3.addRow("输出文件:", file_row(self.cat_output, "save", parent=self))
        self.cat_output_hint = make_hint_label('输入始终只读；断点独立保存在任务状态目录。')
        self.cat_output_hint.setTextFormat(Qt.TextFormat.PlainText)
        form3.addRow(self.cat_output_hint)
        self.cat_input.textChanged.connect(self._update_category_output_hint)
        self.cat_output.textChanged.connect(self._update_category_output_hint)

        self.run_btn3 = make_button("执行 AI 筛选", "primary")
        self.run_btn3.clicked.connect(self._run_category)
        self.stop_btn3 = make_button('停止')
        self.stop_btn3.setEnabled(False)
        self.stop_btn3.clicked.connect(self._stop_category)
        register_form(form3)
        card3.content_layout.addLayout(form3)
        t3.addWidget(card3)
        self.log3 = LogConsole()
        collapsible_log(t3, self.log3)
        t3.addStretch()
        tabs.addTab(pin_actions(tab3, self.run_btn3, self.stop_btn3), "类目筛选")

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
        register_form(form4)
        card4.content_layout.addLayout(form4)
        t4.addWidget(card4)
        self.log4 = LogConsole()
        collapsible_log(t4, self.log4)
        t4.addStretch()
        tabs.addTab(pin_actions(tab4, self.run_btn4), "数据进度")

        for field in (self.tag_input, self.score_dir, self.cat_input, self.progress_ids, self.progress_dir):
            mark_required(field)
        self._result_sources = {
            self.run_btn1: lambda: ([self.tag_output.text() or self.tag_input.text()], os.path.dirname(self.tag_input.text())),
            self.run_btn2: lambda: ([self.score_output.text()], self.score_dir.text()),
            self.run_btn3: lambda: ([self._category_output_path()], os.path.dirname(self.cat_input.text())),
            self.run_btn4: lambda: ([], self.progress_dir.text()),
        }
        layout.addWidget(tabs)

    def _update_extract_options(self, *_):
        self.extract_options_hint.setText(
            f'图片识别：{"开启" if self.vision_cb.isChecked() else "关闭"} · '
            f'自动补抓：{"开启" if self.fetch_cb.isChecked() else "关闭"} · '
            f'归一化：{"开启" if self.normalize_cb.isChecked() else "关闭"} · '
            f'并发：{self.concurrency_spin.value() if self.fast_cb.isChecked() or self.fetch_cb.isChecked() else 1}')

    def _filter_fields(self, *_):
        query = self.field_search.text().strip().casefold()
        for cb in self._field_cbs:
            cb.setVisible(not query or query in cb.text().casefold())
        for i in range(self._field_layout.count()):
            row = self._field_layout.itemAt(i).widget()
            if row is not None:
                row.setVisible(any(not cb.isHidden() for cb in row.findChildren(QCheckBox)))
        self._update_field_summary()

    def _update_field_summary(self, *_):
        self.field_count.setText(f'已选 {sum(cb.isChecked() for cb in self._field_cbs)} / {len(self._field_cbs)} 项')

    # ---- 字段复选框管理 ----

    def _refresh_combo(self):
        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        products = self._load_products()
        for key, info in products.items():
            self.tag_combo.addItem(info.get('name', key), key)
        self.tag_combo.blockSignals(False)

    def _on_combo_changed(self):
        key = self.tag_combo.currentData()
        if self.template_panel.isVisible():
            if not self.template_panel.open_product(key):
                self.tag_combo.blockSignals(True)
                self.tag_combo.setCurrentIndex(self.tag_combo.findData(self._selected_product))
                self.tag_combo.blockSignals(False)
                return
        self._selected_product = key
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
        self._selected_product = key
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
                row_widget.setObjectName("FieldGroup")
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(12)
                self._field_layout.addWidget(row_widget)
            cb = QCheckBox(field)
            cb.setChecked(True)
            self._field_cbs.append(cb)
            cb.toggled.connect(self._update_field_summary)
            row_layout.addWidget(cb)

        self._field_layout.addStretch()
        self._filter_fields()

    def _set_all_fields(self, checked):
        for cb in self._field_cbs:
            cb.setChecked(checked)

    def _get_selected_fields(self):
        return [cb.text() for cb in self._field_cbs if cb.isChecked()]

    # ---- 类目管理 ----

    def _add_category(self):
        if self.template_panel.open_product():
            self.field_splitter.setSizes([800, 420])

    def _edit_fields(self):
        key = self.tag_combo.currentData()
        if not key:
            QMessageBox.warning(self, "提示", "请先选择一个类目。")
            return
        if self.template_panel.open_product(key):
            self.field_splitter.setSizes([800, 420])

    def _template_saved(self, key):
        self._refresh_combo()
        self.tag_combo.setCurrentIndex(self.tag_combo.findData(key))
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
        bar = getattr(run_btn, '_task_bar', None)
        if bar is not None:
            paths, folder = self._result_sources[run_btn]()
            bar.begin(paths, folder)
            self.runner.log_signal.connect(bar.observe)

        def _done(code):
            log_area.append('处理完成' if code == 0 else f'处理失败（错误码 {code}），请查看上方日志。')
            if bar is not None:
                bar.finish(code, stopped=run_btn == self.run_btn1 and getattr(self, '_stop_requested', False))
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

    @validated(lambda s: [(s.tag_input, '输入文件')], "run_btn1")
    def _run_tagging(self):
        inp = self.tag_input.text().strip()
        if not inp:
            self.log1.append("[提示] 请先选择「输入文件」")
            return
        selected = self._get_selected_fields()
        if not selected:
            self.run_btn1._task_bar.summary.setText('请至少勾选一个提取字段。')
            self.field_search.setFocus()
            return
        env = {"INPUT_FILE": inp}
        filter_enabled = self.tag_filter_cb.isChecked()
        if filter_enabled:
            for control, title in ((self.tag_filter_column, '标签列'),
                                   (self.tag_filter_value, '标签值')):
                if not control.text().strip():
                    self.run_btn1._task_bar.summary.setText(f'请填写{title}。')
                    control.setFocus()
                    return
        env['EXTRACT_FILTER_ENABLED'] = '1' if filter_enabled else '0'
        env['EXTRACT_FILTER_COLUMN'] = self.tag_filter_column.text().strip()
        env['EXTRACT_FILTER_VALUE'] = self.tag_filter_value.text().strip()
        out = self.tag_output.text().strip()
        if out:
            env["OUTPUT_FILE"] = out
        key = self.tag_combo.currentData()
        if key:
            env["CURRENT_PRODUCT"] = key
        env["CONFIG_FILE"] = self._get_config_path()
        # Capture before the worker starts: later template saves affect only new runs.
        with open(self._get_config_path(), encoding='utf-8') as file:
            env['PRODUCT_CONFIG_SNAPSHOT'] = json.dumps(json.load(file), ensure_ascii=False)
        env["FIELDS"] = ",".join(selected)
        env["ENABLE_VISION"] = "1" if self.vision_cb.isChecked() else "0"
        env['EXTRACT_NORMALIZE'] = '1' if self.normalize_cb.isChecked() else '0'
        env['NORMALIZE_CONCURRENCY'] = str(min(4, self.concurrency_spin.value()) if self.fast_cb.isChecked() else 1)
        env["ENABLE_FETCH"] = "1" if self.fetch_cb.isChecked() else "0"
        env["STOP_FILE"] = self._stop_file
        # 清除旧的停止信号
        if os.path.exists(self._stop_file):
            os.remove(self._stop_file)
        # 根据并发选项选择脚本（补抓挂在并发版的工作线程里，勾选补抓时强制并发版）
        if self.fast_cb.isChecked() or self.fetch_cb.isChecked():
            script = "exstract_from_description_fast.py"
            env["EXTRACT_CONCURRENCY"] = str(self.concurrency_spin.value())
        else:
            script = "exstract_from_description.py"
        self._stop_requested = False
        self.stop_btn1.setEnabled(True)
        started = self._run(
            script, self.log1, env,
            run_btn=self.run_btn1, finished_callback=self._on_extraction_done,
        )
        if not started:
            self.stop_btn1.setEnabled(False)

    def _on_extraction_done(self, _code):
        self.stop_btn1.setEnabled(False)

    def _stop_extraction(self):
        self._stop_requested = True
        """创建停止信号文件，通知脚本优雅退出。"""
        try:
            with open(self._stop_file, "w") as f:
                f.write("stop")
            self.log1.append("\n[停止] 正在停止，当前行处理完后将保存并退出...")
            self.stop_btn1.setEnabled(False)
        except Exception as e:
            self.log1.append(f"\n[错误] 无法创建停止信号: {e}")

    def _update_score_hint(self, *_):
        from core.report_io import resolve_reference_date
        raw = self.score_date.text().strip()
        output = self.score_output.text().strip() or '脚本默认输出路径'
        try:
            stamp, source = resolve_reference_date(raw, label='分析基准日',
                                                   env_name='MARKET_ANALYSIS_DATE')
        except ValueError:
            self.score_hint.setText(f'分析基准日无法解析：{raw}。请使用 YYYY-MM-DD（如 2026-07-31），'
                                    f'或留空使用运行当日。')
            return
        self.score_hint.setText(f'分析基准日 {stamp:%Y-%m-%d}（{source}）；输出：{output}。'
                                f'得分是本次参与类目之间的相对分位，参与文件变化会影响分数。')

    @validated(lambda s: [(s.score_dir, '数据目录')], "run_btn2")
    def _run_scoring(self):
        from core.report_io import resolve_reference_date
        data_dir = self.score_dir.text().strip()
        output = self.score_output.text().strip()
        if not data_dir:
            self.log2.setPlainText("请先选择数据目录。")
            return
        # 基准日格式在启动前就拦下来，避免跑完整个目录才在日志里报错。
        try:
            resolve_reference_date(self.score_date.text(), label='分析基准日',
                                   env_name='MARKET_ANALYSIS_DATE')
        except ValueError as exc:
            self.log2.setPlainText(str(exc))
            self.run_btn2._task_bar.summary.setText(str(exc))
            return False
        env = {"MARKET_DATA_DIR": data_dir,
               "MARKET_ANALYSIS_DATE": self.score_date.text().strip()}
        if output:
            env["MARKET_OUTPUT_FILE"] = output
        self._run("欧洲市场规划/机会得分.py", self.log2, env, run_btn=self.run_btn2)

    def _category_output_path(self):
        from core.report_io import category_output_path
        inp = self.cat_input.text().strip()
        return str(category_output_path(inp, self.cat_output.text().strip())) if inp else ''

    def _update_category_output_hint(self, *_):
        output = self._category_output_path()
        self.cat_output_hint.setText('输入始终只读；断点独立保存。' + (f'实际输出：{output}' if output else '请选择输入文件。'))

    @validated(lambda s: [(s.cat_input, '类目数据文件')], "run_btn3")
    def _run_category(self):
        from core.report_io import category_checkpoint_path, category_state_dir, require_distinct
        from pathlib import Path
        import uuid
        inp = self.cat_input.text().strip()
        out = self._category_output_path()
        checkpoint = category_checkpoint_path(inp, os.getenv('CATEGORY_CHECKPOINT_FILE', ''))
        try:
            require_distinct(inp, out, checkpoint)
            if Path(out).suffix.lower() != '.xlsx' or checkpoint.suffix.lower() != '.json':
                raise ValueError('结果必须为.xlsx，独立断点必须为.json。')
        except ValueError as exc:
            self.log3.setPlainText(str(exc))
            self.run_btn3._task_bar.summary.setText(str(exc))
            return False
        if self.runner.is_running() or self.runner.is_any_running():
            self.log3.append('[提示] 当前有任务正在运行，请等待完成。')
            return False
        self._category_stop_file = category_state_dir() / ('stop-' + uuid.uuid4().hex + '.json')
        self._category_paths = (inp, out, checkpoint)
        self._category_stop_requested = False
        env = {'CATEGORY_INPUT_FILE': inp, 'CATEGORY_OUTPUT_FILE': out,
               'CATEGORY_CHECKPOINT_FILE': str(checkpoint),
               'CATEGORY_STOP_FILE': str(self._category_stop_file)}
        self.stop_btn3.setEnabled(True)
        started = self._run('欧洲市场规划/类目初筛.py', self.log3, env, run_btn=self.run_btn3,
                            finished_callback=self._on_category_done)
        if not started:
            self.stop_btn3.setEnabled(False)
        return started

    def _stop_category(self):
        from core.report_io import write_json, SafeWriteError
        try:
            write_json(self._category_stop_file, {'stop': True}, protected_paths=self._category_paths)
            self._category_stop_requested = True
            self.stop_btn3.setEnabled(False)
            self.log3.append('已请求停止；等待当前请求返回并安全保存断点/结果，请勿关窗。')
        except (ValueError, SafeWriteError) as exc:
            self.log3.append(str(exc))

    def _on_category_done(self, code):
        from pathlib import Path
        self.stop_btn3.setEnabled(False)
        # 本模块自己创建的停止信号文件用完即删，避免在状态目录里长期累积。
        stop_file = getattr(self, '_category_stop_file', None)
        if stop_file is not None:
            try:
                Path(stop_file).unlink(missing_ok=True)
            except OSError:
                pass
            self._category_stop_file = None
        if code == 130:
            self.run_btn3._task_bar.finish(code, stopped=True)
            self.log3.append('类目任务已停止，已处理行的结果及断点位置见摘要。')
        elif code == 2:
            self.run_btn3._task_bar.summary.setText('存在失败或待审项；已保存部分结果，可重新运行补评。')

    @validated(lambda s: [(s.progress_ids, '全部 ID 文件'), (s.progress_dir, '已爬取目录')], "run_btn4")
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
