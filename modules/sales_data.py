# -*- coding: utf-8 -*-
"""销量数据模块 — 数据清洗、属性分组趋势、市场占比"""

import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QFormLayout, QLineEdit,
    QHBoxLayout, QComboBox, QLabel, QCheckBox, QSpinBox, QScrollArea,
    QStackedWidget, QButtonGroup, QMenu,
)
from PyQt6.QtCore import Qt

from core.widgets import (
    Card, LogConsole, FileDropLineEdit, make_button, configure_combo,
    file_row, set_running_state, make_hint_label, action_row,
    ScrollTabs, ActionBar, collapsible_log,
)

from core.task_ui import TaskBar, register_form, pin_actions, validated, mark_required, advanced_rows
from core.excel_choices import ChoiceEdit, ExcelChoices
from core.source_picker import browse_excel_source

MODULE_INFO = {
    "name": "销量数据",
    "icon": "📊",
    "category": "分析中心",
    "order": 2,
    "description": "数据清洗、属性分组趋势图、市场占比",
}

MAX_CROSS_FILTERS = 10


class ModuleWidget(QWidget):
    def __init__(self, config_mgr, runner):
        super().__init__()
        self.setProperty("workspacePage", True)
        self.config_mgr = config_mgr
        self.runner = runner
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.setSpacing(14)
        tabs = ScrollTabs()

        # ================= Tab 1: 数据清洗 =================
        tab1 = QWidget()
        tab1.setProperty("workspacePage", True)
        t1 = QVBoxLayout(tab1)
        t1.setContentsMargins(0, 0, 0, 0)
        t1.setSpacing(14)

        tab2 = QWidget()
        t2 = QVBoxLayout(tab2)
        t2.setContentsMargins(0, 0, 0, 0)
        t2.setSpacing(14)

        card_split = Card("销量拆分",
                          "选择一个 Excel 或文件夹；销量按原规则拆分，矫正销额按子体当月售价计算")
        form1 = QFormLayout()
        form1.setSpacing(10)
        self.split_input = FileDropLineEdit(placeholder="选择或拖入 Excel 文件 / 文件夹")
        source_row = QHBoxLayout()
        source_row.addWidget(self.split_input, 1)
        self.split_browse = make_button("浏览")
        source_menu = QMenu(self.split_browse)
        source_menu.addAction("选择 Excel 文件", lambda: self._browse_split_source(False))
        source_menu.addAction("选择文件夹", lambda: self._browse_split_source(True))
        self.split_browse.setMenu(source_menu)
        source_row.addWidget(self.split_browse)
        form1.addRow("源数据:", source_row)
        self.split_output = FileDropLineEdit(want_dir=True, placeholder="留空：各结果保存到对应源文件旁")
        form1.addRow("输出文件夹:", file_row(self.split_output, "dir", parent=self))
        card_split.content_layout.addLayout(form1)
        card_split.content_layout.addWidget(make_hint_label(
            "子体销售额_矫正 = 子体销量_矫正 × 源文件中该子体当月价格，保留两位小数。\n"
            "自动识别价格/售价列；缺失或无效时提示补齐。文件夹仅处理当前层级，自动跳过拆分结果和备份。"))
        self.run_btn1 = make_button("执行销量拆分", "primary")
        self.run_btn1.clicked.connect(self._run_split)

        card_trend = Card(
            "数据提取",
            "按 Excel 名单中的 ASIN 提取历史销量和销额；不选名单则提取全部 ASIN",
        )
        form2 = QFormLayout()
        form2.setSpacing(10)
        self.trend_folder = FileDropLineEdit(
            want_dir=True, placeholder="选择或拖入含 *_销量拆分.xlsx 的文件夹")
        form2.addRow("源数据:",
                     file_row(self.trend_folder, "dir", parent=self))

        self.trend_asin_file = FileDropLineEdit(placeholder="可选：含 ASIN 列的商品属性表或名单文件；留空提取全部 ASIN")
        form2.addRow("ASIN 名单文件:", file_row(self.trend_asin_file, "open", parent=self,
                     filter_str="Excel 工作簿 (*.xlsx *.xlsm)"))
        self.trend_asin_sheet = ChoiceEdit()
        self.trend_asin_sheet.setPlaceholderText("选择含 ASIN 列的工作表；留空读取第一个工作表")
        form2.addRow("名单工作表:", self.trend_asin_sheet)
        self.trend_asin_sheet.setEnabled(False)
        self.trend_asin_file.textChanged.connect(self._update_extract_scope)

        self.trend_volume_field = configure_combo(QComboBox())
        self.trend_volume_field.setEditable(True)
        self.trend_volume_field.addItems(["子体销量_矫正", "月销量", "子体销量"])
        form2.addRow("销量列:", self.trend_volume_field)

        self.trend_revenue_field = configure_combo(QComboBox())
        self.trend_revenue_field.setEditable(True)
        self.trend_revenue_field.addItems(
            ["子体销售额_矫正", "月销售额($)", "子体销售额($)"])
        form2.addRow("销额列:", self.trend_revenue_field)

        self.trend_output = FileDropLineEdit(
            placeholder="选择已有 Excel 或输入新 .xlsx 文件路径")
        self.trend_output.setToolTip(
            "同名历史 Sheet 会整体替换，其它 Sheet 保留；写入前自动备份原文件")
        form2.addRow("输出文件:",
                     file_row(self.trend_output, "save_no_confirm", parent=self,
                              filter_str="Excel 工作簿 (*.xlsx)"))

        sheet_row = QHBoxLayout()
        sheet_row.setSpacing(8)
        self.trend_output_volume_sheet = QLineEdit("历史销量")
        self.trend_output_volume_sheet.setPlaceholderText("历史销量 Sheet 名")
        self.trend_output_revenue_sheet = QLineEdit("历史销额")
        self.trend_output_revenue_sheet.setPlaceholderText("历史销额 Sheet 名")
        sheet_row.addWidget(QLabel("销量:"))
        sheet_row.addWidget(self.trend_output_volume_sheet)
        sheet_row.addWidget(QLabel("销额:"))
        sheet_row.addWidget(self.trend_output_revenue_sheet)
        form2.addRow("生成Sheet:", sheet_row)

        trend_btn_row = QHBoxLayout()
        trend_btn_row.setSpacing(10)
        self.run_btn2 = make_button("提取全部 ASIN", "primary")
        self.run_btn2.clicked.connect(self._run_extract_data)
        trend_btn_row.addWidget(self.run_btn2)
        trend_btn_row.addStretch()
        register_form(form2)
        card_trend.content_layout.addLayout(form2)
        card_trend.content_layout.addWidget(make_hint_label(
            "名单只提供 ASIN，不读取其中的销量或销额；结果保持名单顺序，未找到的 ASIN 保留空白行。\n"
            "输出文件的同名历史 Sheet 会整体替换，其它 Sheet 保留；写入前自动备份。"))
        t2.addWidget(card_trend)
        self.log2 = LogConsole()
        collapsible_log(t2, self.log2)
        t2.addStretch()

        card_fix = Card(
            "数据修正",
            "修正指定 ASIN + 年月的数据；保存前自动生成时间戳备份，并保留原工作簿结构",
        )
        form_fix = QFormLayout()
        form_fix.setSpacing(10)
        self.fix_folder = FileDropLineEdit(want_dir=True, placeholder="拆分结果所在文件夹")
        form_fix.addRow("拆分文件夹:", file_row(self.fix_folder, "dir", parent=self))

        self.fix_asin = QLineEdit()
        self.fix_asin.setPlaceholderText("如 B00DOMYL24")
        form_fix.addRow("ASIN:", self.fix_asin)

        self.fix_month = QLineEdit()
        self.fix_month.setPlaceholderText("如 2025-03")
        form_fix.addRow("年月:", self.fix_month)

        fix_row = QHBoxLayout()
        fix_row.setSpacing(8)
        self.fix_volume = QLineEdit()
        self.fix_volume.setPlaceholderText("新销量值")
        self.fix_revenue = QLineEdit()
        self.fix_revenue.setPlaceholderText("新销额值（可选）")
        fix_row.addWidget(self.fix_volume)
        fix_row.addWidget(self.fix_revenue)
        form_fix.addRow("修正值:", fix_row)

        self.run_fix = make_button("执行修正", "primary")
        self.run_fix.clicked.connect(self._run_fix)
        card_fix.content_layout.addLayout(form_fix)
        chooser = QHBoxLayout()
        self.clean_tasks = QButtonGroup(self)
        self.clean_tasks.setExclusive(True)
        for index, title in enumerate(("销量拆分", "数据修正")):
            button = make_button(title, "task")
            button.setCheckable(True)
            self.clean_tasks.addButton(button, index)
            chooser.addWidget(button)
        chooser.addStretch()
        t1.addLayout(chooser)
        self.clean_stack = QStackedWidget()
        for card in (card_split, card_fix):
            page = QWidget()
            content = QVBoxLayout(page)
            content.setContentsMargins(0, 0, 0, 0)
            content.addWidget(card)
            content.addStretch()
            scroll = QScrollArea()
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.clean_stack.addWidget(scroll)
        t1.addWidget(self.clean_stack, 1)
        self.log1 = LogConsole()
        self.clean_log_toggle = collapsible_log(t1, self.log1)
        self.clean_actions = TaskBar()
        for form in (form1, form_fix):
            register_form(form)
        self.clean_run_buttons = (self.run_btn1, self.run_fix)
        for button in self.clean_run_buttons:
            button.setMinimumWidth(150)
            button._task_bar = self.clean_actions
            button._task_log = self.log1
            self.clean_actions.row.addWidget(button)
        t1.addWidget(self.clean_actions)
        self.clean_tasks.idClicked.connect(self._select_clean_task)
        for field in (self.split_input, self.fix_folder):
            field.textChanged.connect(self._update_clean_summary)
        self._select_clean_task(0)
        tabs.addTab(tab1, "数据清洗")
        tabs.addTab(pin_actions(tab2, self.run_btn2), "数据提取")

        # ================= Tab 3: 交叉属性 =================
        tab4 = QWidget()
        t4 = QVBoxLayout(tab4)
        t4.setContentsMargins(0, 0, 0, 0)
        t4.setSpacing(14)

        card4 = Card("交叉属性趋势（多条件筛选）",
                     f"多筛选条件交叉分析，支持 1-{MAX_CROSS_FILTERS} 个条件动态组合，"
                     "可选双轴模式和导出数据")
        form4 = QFormLayout()
        form4.setSpacing(10)

        self.cross_file = FileDropLineEdit(placeholder="选择或拖入 Excel 文件")
        form4.addRow("Excel文件:", file_row(self.cross_file, "open", parent=self))

        self.cross_meta = ChoiceEdit()
        self.cross_meta.setPlaceholderText("包含品牌、颜色等商品属性；留空使用第一个工作表")
        self.cross_meta.setToolTip("用于筛选和分组，需包含 ASIN 及对应的商品属性列。")
        form4.addRow("商品属性表:", self.cross_meta)

        self.cross_data = ChoiceEdit()
        self.cross_data.setPlaceholderText("历史销量历史表名")
        form4.addRow("销量历史表:", self.cross_data)

        self.cross_data2 = ChoiceEdit()
        self.cross_data2.setPlaceholderText("如 子体销额（销额模式 / 均价模式 必填）")
        form4.addRow("销额历史表:", self.cross_data2)

        self.cross_trend_mode = configure_combo(QComboBox())
        self.cross_trend_mode.addItems(["销量趋势", "销额趋势", "销量&均价趋势"])
        self.cross_trend_mode.setToolTip(
            "选「销额趋势」或「销量&均价趋势」时需填写销额历史表（销额表），均价=销额/销量")
        form4.addRow("趋势模式:", self.cross_trend_mode)
        self.cross_mode_hint = make_hint_label("")
        form4.addRow(self.cross_mode_hint)
        self._cross_data_label = form4.labelForField(self.cross_data)
        self._cross_data2_label = form4.labelForField(self.cross_data2)
        self.cross_trend_mode.currentIndexChanged.connect(
            self._update_cross_mode_ui)
        self._update_cross_mode_ui(self.cross_trend_mode.currentIndex())

        self.cross_output = FileDropLineEdit(
            placeholder="留空默认: Excel父目录下「规划」文件夹，按筛选值+分组字段命名")
        form4.addRow("输出文件:", file_row(self.cross_output, "save", parent=self))

        self.cross_filter_count = QSpinBox()
        self.cross_filter_count.setRange(1, MAX_CROSS_FILTERS)
        self.cross_filter_count.setValue(2)
        self.cross_filter_count.valueChanged.connect(self._rebuild_filter_rows)
        form4.addRow("筛选条件数:", self.cross_filter_count)

        # 动态筛选条件容器（带滚动条）
        self.cross_filter_container = QWidget()
        self.cross_filter_layout = QFormLayout(self.cross_filter_container)
        self.cross_filter_layout.setContentsMargins(4, 4, 4, 4)
        scroll = QScrollArea()
        scroll.setWidget(self.cross_filter_container)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(122)
        form4.addRow(scroll)
        self.cross_filter_rows = []
        self._rebuild_filter_rows(2)

        self.cross_export = FileDropLineEdit(
            placeholder="留空默认: Excel父目录下「规划」文件夹，按筛选值+分组字段命名")
        form4.addRow("导出数据:", file_row(self.cross_export, "save", parent=self))

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.run_btn4 = make_button("生成趋势图", "primary")
        self.run_btn4.clicked.connect(self._run_cross_trend)
        btn_row.addWidget(self.run_btn4)
        self.export_btn4 = make_button("导出数据")
        self.export_btn4.clicked.connect(self._run_cross_export)
        btn_row.addWidget(self.export_btn4)
        btn_row.addStretch()
        register_form(form4)
        card4.content_layout.addLayout(form4)
        t4.addWidget(card4)
        self.log4 = LogConsole()
        collapsible_log(t4, self.log4)
        t4.addStretch()
        tabs.addTab(pin_actions(tab4, self.run_btn4, self.export_btn4), "交叉属性")

        # ================= Tab 4: 市场占比 =================
        tab5 = QWidget()
        t5 = QVBoxLayout(tab5)
        t5.setContentsMargins(0, 0, 0, 0)
        t5.setSpacing(14)

        card5 = Card("市场份额趋势图",
                     "按品牌/类别统计月度份额占比趋势，支持 Top N 展示和份额数据导出")
        form5 = QFormLayout()
        form5.setSpacing(10)

        self.share_file = FileDropLineEdit(placeholder="选择或拖入 Excel 文件")
        form5.addRow("Excel文件:", file_row(self.share_file, "open", parent=self))

        self.share_meta = ChoiceEdit()
        self.share_meta.setPlaceholderText("包含品牌、颜色等商品属性；留空使用第一个工作表")
        self.share_meta.setToolTip("用于筛选和分组，需包含 ASIN 及对应的商品属性列。")
        form5.addRow("商品属性表:", self.share_meta)

        self.share_data = ChoiceEdit()
        self.share_data.setPlaceholderText("选择每月销量所在的工作表")
        form5.addRow("销量历史表:", self.share_data)

        self.share_brand_col = ChoiceEdit()
        self.share_brand_col.setPlaceholderText("如: 品牌、线长、颜色、使用场景")
        form5.addRow("分组列名:", self.share_brand_col)

        self.share_top = QSpinBox()
        self.share_top.setRange(2, 20)
        self.share_top.setValue(8)
        form5.addRow("展示Top N:", self.share_top)

        self.share_filter = QLineEdit()
        self.share_filter.setPlaceholderText("格式: 列名=值（可选，多个用 ; 分隔）")
        form5.addRow("筛选条件:", self.share_filter)

        self.share_output = FileDropLineEdit(placeholder="输出图片路径（可选）")
        form5.addRow("输出文件:",
                     file_row(self.share_output, "save",
                              filter_str="PNG (*.png)", parent=self))

        self.share_dpi = QSpinBox()
        self.share_dpi.setRange(72, 400)
        self.share_dpi.setValue(200)
        form5.addRow("DPI:", self.share_dpi)

        self.share_export = QCheckBox("同时输出占比数据表（Excel格式）")
        form5.addRow(self.share_export)

        self.run_btn5 = make_button("生成市场占比图", "primary")
        self.run_btn5.clicked.connect(self._run_brand_share)
        register_form(form5)
        card5.content_layout.addLayout(form5)
        t5.addWidget(card5)
        self.log5 = LogConsole()
        collapsible_log(t5, self.log5)
        t5.addStretch()
        tabs.addTab(pin_actions(tab5, self.run_btn5), "市场占比")

        self._excel_choices = [
            ExcelChoices(self.trend_asin_file, [self.trend_asin_sheet], parent=self),
            ExcelChoices(self.share_file, [self.share_meta, self.share_data], [(self.share_brand_col, self.share_meta)], self),
        ]
        self._cross_choices = ExcelChoices(self.cross_file, [self.cross_meta, self.cross_data, self.cross_data2], parent=self)
        self._excel_choices.append(self._cross_choices)
        self.cross_meta.textChanged.connect(self._refresh_cross_columns)
        self._cross_choices.metadata_changed.connect(self._refresh_cross_columns)
        for field in (self.split_input, self.fix_folder, self.fix_asin, self.fix_month,
                      self.trend_folder, self.trend_output, self.cross_file, self.share_file, self.share_data, self.share_brand_col):
            mark_required(field)
        self._result_sources = {
            self.run_btn1: self._split_result_sources,
            self.run_fix: lambda: ([], self.fix_folder.text()),
            self.run_btn2: lambda: ([self.trend_output.text()], os.path.dirname(self.trend_output.text())),
            self.run_btn4: lambda: ([self.cross_output.text() or self._cross_default_path('.png')], os.path.dirname(self.cross_file.text())),
            self.export_btn4: lambda: ([self.cross_export.text() or self._cross_default_path('.xlsx')], os.path.dirname(self.cross_file.text())),
            self.run_btn5: lambda: ([self.share_output.text() or f'brand_share_{self.share_brand_col.text()}.png'], os.path.dirname(self.share_file.text())),
        }
        layout.addWidget(tabs)

    def _refresh_cross_columns(self, *_):
        meta = self._cross_choices.metadata
        sheet = self.cross_meta.text().strip() or next(iter(meta), '')
        for field, _value in self.cross_filter_rows:
            field.set_choices(meta.get(sheet, []))

    def _select_clean_task(self, index):
        self.clean_stack.setCurrentIndex(index)
        self.clean_tasks.button(index).setChecked(True)
        for i, button in enumerate(self.clean_run_buttons):
            button.setVisible(i == index)
        self._update_clean_summary()

    def _update_clean_summary(self, *_):
        index = self.clean_stack.currentIndex()
        path = (self.split_input, self.fix_folder)[index].text().strip()
        self.clean_actions.summary.setText(
            (os.path.basename(path.rstrip("/\\")) if path else "选择数据后即可开始")
            + (" · 保存前自动备份" if index == 1 else " · 默认保存到源数据旁"))
        if self.runner is None or not self.runner.is_running():
            self.clean_run_buttons[index].setEnabled(bool(path))

    # ================================================================
    # 脚本执行（业务逻辑保持不变）
    # ================================================================

    def _run(self, script, log_area, args=None, run_btn=None):
        """统一执行入口。"""
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
                bar.finish(code)
            log_area.set_status("ok" if code == 0 else "error")
            if run_btn is not None:
                set_running_state(run_btn, False)
            if run_btn in self.clean_run_buttons:
                for button in self.clean_tasks.buttons():
                    button.setEnabled(True)
                self.clean_run_buttons[self.clean_stack.currentIndex()].setEnabled(True)

        self.runner.finished_signal.connect(_done)
        if run_btn is not None:
            set_running_state(run_btn, True)
        if run_btn in self.clean_run_buttons:
            for button in self.clean_tasks.buttons():
                button.setEnabled(False)
        log_area.set_status("running")
        script_path = os.path.join(self.config_mgr.get_script_dir(), script)
        return self.runner.run_script(
            script_path, args, self.config_mgr.get_env_dict()
        )

    def _browse_split_source(self, want_dir=False):
        path = browse_excel_source(self, self.split_input.text().strip(), want_dir)
        if path:
            self.split_input.setText(path)

    def _split_result_sources(self):
        path = self.split_input.text().strip()
        folder = self.split_output.text().strip() or (path if os.path.isdir(path) else os.path.dirname(path))
        return [], folder

    @validated(lambda s: [(s.split_input, '源数据')], "run_btn1")
    def _run_split(self):
        args = [self.split_input.text().strip(), "--yes"]
        if self.split_output.text().strip():
            args.extend(["--output-dir", self.split_output.text().strip()])
        self._run("batch_sales_split.py", self.log1, args, run_btn=self.run_btn1)

    def _update_extract_scope(self, *_):
        specified = bool(self.trend_asin_file.text().strip())
        self.trend_asin_sheet.setEnabled(specified)
        self.run_btn2.setText("提取名单 ASIN" if specified else "提取全部 ASIN")

    @validated(lambda s: [(s.trend_folder, '源数据文件夹'), (s.trend_volume_field, '销量列'),
                          (s.trend_revenue_field, '销额列'), (s.trend_output, '输出文件'),
                          (s.trend_output_volume_sheet, '生成销量 Sheet'),
                          (s.trend_output_revenue_sheet, '生成销额 Sheet')], "run_btn2")
    def _run_extract_data(self):
        args = ["--folder", self.trend_folder.text().strip(),
                "--volume-field", self.trend_volume_field.currentText().strip(),
                "--revenue-field", self.trend_revenue_field.currentText().strip(),
                "--output", self.trend_output.text().strip(),
                "--output-volume-sheet", self.trend_output_volume_sheet.text().strip(),
                "--output-revenue-sheet", self.trend_output_revenue_sheet.text().strip()]
        if self.trend_asin_file.text().strip():
            args.extend(["--asin-file", self.trend_asin_file.text().strip()])
            if self.trend_asin_sheet.text().strip():
                args.extend(["--asin-sheet", self.trend_asin_sheet.text().strip()])
        self._run("extract_history_data.py", self.log2, args, run_btn=self.run_btn2)

    def _rebuild_filter_rows(self, count):
        """根据筛选条件数量重建输入行。"""
        previous_values = [
            (col_edit.text(), val_edit.text())
            for col_edit, val_edit in getattr(self, "cross_filter_rows", [])
        ]
        for row_widget, _, _ in getattr(self, '_cross_row_widgets', []):
            row_widget.setParent(None)
            row_widget.deleteLater()
        self.cross_filter_rows = []
        self._cross_row_widgets = []
        for i in range(count):
            col_edit = ChoiceEdit()
            col_edit.setPlaceholderText("属性列名")
            eq_label = QLabel("=")
            eq_label.setFixedWidth(16)
            eq_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val_edit = QLineEdit()
            val_edit.setPlaceholderText("具体值，多值用英文逗号分隔（留空=按此分组）")
            if i < len(previous_values):
                col_edit.setText(previous_values[i][0])
                val_edit.setText(previous_values[i][1])
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(6)
            row_layout.addWidget(QLabel(f"条件 {i+1}:"))
            row_layout.addWidget(col_edit, stretch=1)
            row_layout.addWidget(eq_label)
            row_layout.addWidget(val_edit, stretch=1)
            self.cross_filter_layout.addRow(row_widget)
            self.cross_filter_rows.append((col_edit, val_edit))
            col_edit.textChanged.connect(lambda _=None, f=col_edit: f.setToolTip('留空跳过；选择列后可填写筛选值'))
            if hasattr(self, '_cross_choices'):
                col_edit.set_choices(self._cross_choices.metadata.get(self.cross_meta.text().strip() or next(iter(self._cross_choices.metadata), ''), []))
            self._cross_row_widgets.append((row_widget, col_edit, val_edit))

    def _update_cross_mode_ui(self, index):
        """按趋势模式标明必填 Sheet，同时保留两字段供数据导出使用。"""
        if index == 0:
            self._cross_data_label.setText("销量历史表 *:")
            self._cross_data2_label.setText("销额历史表:")
            self.cross_data.setPlaceholderText("每月销量数据（行：ASIN；列：月份）")
            self.cross_data2.setPlaceholderText("每月销售额数据（导出数据时需要）")
            hint = "销量趋势使用销量历史表；销额历史表仅在导出组合数据时需要。"
        elif index == 1:
            self._cross_data_label.setText("销量历史表:")
            self._cross_data2_label.setText("销额历史表 *:")
            self.cross_data.setPlaceholderText("每月销量数据（导出数据时需要）")
            self.cross_data2.setPlaceholderText("每月销售额数据（行：ASIN；列：月份）")
            hint = "销额趋势使用销额历史表；销量历史表仅在导出组合数据时需要。"
        else:
            self._cross_data_label.setText("销量历史表 *:")
            self._cross_data2_label.setText("销额历史表 *:")
            self.cross_data.setPlaceholderText("每月销量数据（行：ASIN；列：月份）")
            self.cross_data2.setPlaceholderText("每月销售额数据（行：ASIN；列：月份）")
            hint = "销量与均价趋势同时使用销量历史表和销额历史表，均价按销额 ÷ 销量计算。"
        self.cross_mode_hint.setText(hint)

    @staticmethod
    def _sanitize_filename(name):
        """清除 Windows 文件名非法字符，避免默认命名无法保存。"""
        for ch in '<>:"/\\|?*':
            name = name.replace(ch, '_')
        return name.strip().strip('.')

    def _cross_default_path(self, ext):
        """默认输出路径: 有值取筛选值，值留空时取分组字段名。"""
        f = self.cross_file.text().strip()
        if not f:
            return ""
        parts = []
        for col_edit, val_edit in self.cross_filter_rows:
            col = col_edit.text().strip()
            if not col:
                continue
            val = val_edit.text().strip()
            if val:
                parts.append(val)
            else:
                # 值留空表示按该列分组；保留列名可避免不同分组图重名覆盖。
                parts.append(col)
        name = self._sanitize_filename("_".join(parts)) or "交叉属性"
        folder = os.path.join(os.path.dirname(os.path.abspath(f)), "规划")
        return os.path.join(folder, f"{name}{ext}")

    @validated(lambda s: [(s.cross_file, 'Excel 文件')] + ([(s.cross_data, '销量历史表')] if s.cross_trend_mode.currentIndex() in (0, 2) else []) + ([(s.cross_data2, '销额历史表')] if s.cross_trend_mode.currentIndex() in (1, 2) else []), "run_btn4")
    def _run_cross_trend(self):
        f = self.cross_file.text().strip()
        ds = self.cross_data.text().strip()
        ds2 = self.cross_data2.text().strip()
        mode = self.cross_trend_mode.currentIndex()  # 0=销量, 1=销额, 2=销量&销额
        if not f:
            self.log4.append("[提示] 请先选择「Excel文件」")
            return
        if mode == 0:  # 销量趋势
            if not ds:
                self.log4.append("[提示] 请填写「销量历史表」名称")
                return
            args = ["--file", f, "--data-sheet", ds, "--chart-type", "line"]
        elif mode == 1:  # 销额趋势
            if not ds2:
                self.log4.append("错误: 销额趋势需要填写销额历史表（销额数据表）")
                return
            args = ["--file", f, "--data-sheet", ds2, "--chart-type", "line"]
        else:  # 销量&均价趋势（双轴）
            if not ds or not ds2:
                self.log4.append("错误: 双轴模式需要填写销量历史表和销额历史表")
                return
            args = ["--file", f, "--data-sheet", ds, "--data-sheet-2", ds2,
                    "--avg-price-only", "--chart-type", "line"]
        ms = self.cross_meta.text().strip()
        if ms:
            args += ["--meta-sheet", ms]
        group_col = ""
        for col_edit, val_edit in self.cross_filter_rows:
            col = col_edit.text().strip()
            val = val_edit.text().strip()
            if col and val:
                args += ["--filter", f"{col}={val}"]
            elif col and not val:
                group_col = col
        if group_col:
            args += ["--group-col", group_col]
        out = self.cross_output.text().strip() or self._cross_default_path(".png")
        if out:
            args += ["--output", out]
        self._run("trend_by_attribute.py", self.log4, args, run_btn=self.run_btn4)

    @validated(lambda s: [(s.cross_file, 'Excel 文件'), (s.cross_data, '销量历史表'), (s.cross_data2, '销额历史表')], "export_btn4")
    def _run_cross_export(self):
        """导出交叉属性数据。"""
        f = self.cross_file.text().strip()
        ds = self.cross_data.text().strip()
        ds2 = self.cross_data2.text().strip()
        export_path = self.cross_export.text().strip() or self._cross_default_path(".xlsx")

        if not f or not ds or not ds2 or not export_path:
            self.log4.append("错误: 导出数据需要填写 Excel文件、销量历史表 和 销额历史表")
            return

        args = ["--file", f, "--data-sheet", ds, "--data-sheet-2", ds2]
        ms = self.cross_meta.text().strip()
        if ms:
            args += ["--meta-sheet", ms]
        group_col = ""
        for col_edit, val_edit in self.cross_filter_rows:
            col = col_edit.text().strip()
            val = val_edit.text().strip()
            if col and val:
                args += ["--filter", f"{col}={val}"]
            elif col and not val:
                group_col = col
        if group_col:
            args += ["--group-col", group_col]
        args += ["--export-data", export_path, "--export-only"]
        self._run("trend_by_attribute.py", self.log4, args, run_btn=self.export_btn4)

    @validated(lambda s: [(s.fix_folder, '拆分文件夹'), (s.fix_asin, 'ASIN'), (s.fix_month, '年月')] + ([(s.fix_volume, '新销量或新销额')] if not s.fix_revenue.text().strip() else []), "run_fix")
    def _run_fix(self):
        folder = self.fix_folder.text().strip()
        asin = self.fix_asin.text().strip()
        month = self.fix_month.text().strip()
        volume = self.fix_volume.text().strip()
        revenue = self.fix_revenue.text().strip()

        if not folder or not asin or not month:
            self.log1.append("[提示] 请填写「拆分文件夹」「ASIN」「年月」")
            return
        if not volume and not revenue:
            self.log1.append("[提示] 请至少填写「新销量值」或「新销额值」")
            return

        args = ["--folder", folder, "--asin", asin, "--month", month]
        if volume:
            args += ["--volume", volume]
        if revenue:
            args += ["--revenue", revenue]
        self._run("fix_sales_data.py", self.log1, args, run_btn=self.run_fix)

    @validated(lambda s: [(s.share_file, 'Excel 文件'), (s.share_data, '销量历史表'), (s.share_brand_col, '分组列名')], "run_btn5")
    def _run_brand_share(self):
        f = self.share_file.text().strip()
        ms = self.share_meta.text().strip()
        ds = self.share_data.text().strip()
        bc = self.share_brand_col.text().strip()
        if not f or not ds or not bc:
            self.log5.append("[提示] 请完整填写「Excel文件」「销量历史表」「分组列名」（商品属性表留空默认第一个）")
            return
        args = ["--file", f, "--meta-sheet", ms, "--data-sheet", ds, "--brand-col", bc]
        top = self.share_top.value()
        if top != 8:
            args += ["--top", str(top)]
        filter_text = self.share_filter.text().strip()
        if filter_text:
            for expr in filter_text.split(';'):
                expr = expr.strip()
                if expr:
                    args += ["--filter", expr]
        out = self.share_output.text().strip()
        if out:
            args += ["--output", out]
        dpi = self.share_dpi.value()
        if dpi != 200:
            args += ["--dpi", str(dpi)]
        if self.share_export.isChecked():
            args += ["--export-share"]
        self._run("brand_share_trend.py", self.log5, args, run_btn=self.run_btn5)
