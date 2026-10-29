# -*- coding: utf-8 -*-
"""产品矩阵模块 — 自由组合矩阵、销额透视矩阵"""

import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QFormLayout, QLineEdit,
    QComboBox,
)

from core.widgets import (
    Card, LogConsole, FileDropLineEdit, make_button, configure_combo,
    file_row, set_running_state, ScrollTabs, collapsible_log, action_row,
)

from core.task_ui import register_form, pin_actions, validated, advanced_rows, mark_required
from core.excel_choices import ChoiceEdit, ExcelChoices

MODULE_INFO = {
    "name": "产品矩阵",
    "icon": "🧩",
    "category": "市场与产品规划",
    "order": 4,
    "description": "自由组合矩阵、销额透视矩阵",
}


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

        # ================= Tab 2: 销额透视矩阵 =================
        tab6 = QWidget()
        t6 = QVBoxLayout(tab6)
        t6.setContentsMargins(0, 0, 0, 0)
        t6.setSpacing(14)
        card6 = Card("销额透视矩阵（双维交叉）",
                     "按两个维度交叉分析，生成销额数据透视表。可从元数据列取值或子表格指定月份列取值")
        form6 = QFormLayout()
        form6.setSpacing(10)

        self.matrix2_file = FileDropLineEdit(placeholder="选择或拖入 Excel 文件")
        form6.addRow("Excel文件:", file_row(self.matrix2_file, "open", parent=self))

        self.matrix2_sheet = ChoiceEdit()
        self.matrix2_sheet.setPlaceholderText("Sheet 名称")
        form6.addRow("Sheet名称:", self.matrix2_sheet)

        self.matrix2_filter = QLineEdit()
        self.matrix2_filter.setPlaceholderText("格式: 列名=值（可选，多个用 ; 分隔）")
        form6.addRow("筛选条件:", self.matrix2_filter)

        self.matrix2_row_col = ChoiceEdit()
        self.matrix2_row_col.setPlaceholderText("如: 三级分类")
        form6.addRow("纵向维度:", self.matrix2_row_col)

        self.matrix2_row_values = QLineEdit()
        self.matrix2_row_values.setPlaceholderText("逗号分隔，留空=全部")
        form6.addRow("纵向维度值:", self.matrix2_row_values)

        self.matrix2_col_col = ChoiceEdit()
        self.matrix2_col_col.setPlaceholderText("如: 插孔布局、有无USB")
        form6.addRow("横向维度:", self.matrix2_col_col)

        self.matrix2_col_values = QLineEdit()
        self.matrix2_col_values.setPlaceholderText("逗号分隔，留空=全部")
        form6.addRow("横向维度值:", self.matrix2_col_values)

        self.matrix2_value_col = ChoiceEdit()
        self.matrix2_value_col.setPlaceholderText("方式一：直接从元数据取值")
        form6.addRow("销额列名:", self.matrix2_value_col)

        self.matrix2_data_sheet = ChoiceEdit()
        self.matrix2_data_sheet.setPlaceholderText("方式二：子表格名（如 子体销额）")
        form6.addRow("数据子表格:", self.matrix2_data_sheet)

        self.matrix2_month_col = ChoiceEdit()
        self.matrix2_month_col.setPlaceholderText("月份列名（如 2025-12）")
        form6.addRow("月份列:", self.matrix2_month_col)

        self.matrix2_output = FileDropLineEdit(placeholder="输出 Excel 文件路径")
        form6.addRow("输出文件:", file_row(self.matrix2_output, "save", parent=self))

        self.run_btn6 = make_button("生成销额透视矩阵", "primary")
        self.run_btn6.clicked.connect(self._run_matrix2)
        register_form(form6)
        card6.content_layout.addLayout(form6)
        t6.addWidget(card6)
        self.matrix2_log = LogConsole()
        collapsible_log(t6, self.matrix2_log)
        t6.addStretch()
        tabs.addTab(pin_actions(tab6, self.run_btn6), "销额透视矩阵")
        tabs.setTabToolTip(tabs.count() - 1,
            "按两个维度交叉生成销额透视表，单元格显示销额总和/ASIN数/平均销额")

        self._excel_choices = [
            ExcelChoices(self.matrix2_file, [self.matrix2_sheet, self.matrix2_data_sheet],
                         [(f, self.matrix2_sheet) for f in (self.matrix2_row_col, self.matrix2_col_col, self.matrix2_value_col)]
                         + [(self.matrix2_month_col, self.matrix2_data_sheet)], self),
        ]
        for field in (self.matrix2_file, self.matrix2_sheet, self.matrix2_row_col, self.matrix2_col_col):
            mark_required(field)
        self._result_sources = {self.run_btn6: lambda: self.matrix2_output.text() or 'product_matrix.xlsx'}
        layout.addWidget(tabs)
        from core.matrix_workspace import MatrixWorkspace
        self.free_matrix = MatrixWorkspace(self)
        self.free_matrix.setProperty("workspacePage", True)
        tabs.insertTab(0, self.free_matrix, "自由组合矩阵")
        tabs.setCurrentWidget(self.free_matrix)
        self.matrix_tabs = tabs

    def open_dashboard_source(self, path):
        self.free_matrix.path.setText(path)
        self.free_matrix.sheets.setCurrentText('看板商品')
        self.free_matrix.read_data()
        self.matrix_tabs.setCurrentWidget(self.free_matrix)

    def _run(self, script, log_area, args=None, env_overrides=None, run_btn=None):
        """矩阵类脚本统一执行入口。"""
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
            output = self._result_sources[run_btn]().strip()
            bar.begin([output], os.path.dirname(os.path.abspath(output)))
            self.runner.log_signal.connect(bar.observe)

        def _done(code):
            log_area.append('处理完成' if code == 0 else f'处理失败（错误码 {code}），请查看上方日志。')
            if bar is not None:
                bar.finish(code)
            log_area.set_status("ok" if code == 0 else "error")
            if run_btn is not None:
                set_running_state(run_btn, False)

        self.runner.finished_signal.connect(_done)
        if run_btn is not None:
            set_running_state(run_btn, True)
        log_area.set_status("running")

        script_path = os.path.join(self.config_mgr.get_script_dir(), script)
        if env_overrides is not None:
            full_env = self.config_mgr.get_env_dict()
            full_env.update(env_overrides)
            return self.runner.run_script(script_path, env_extra=full_env)
        else:
            return self.runner.run_script(script_path, args)

    @validated(lambda s: [(s.matrix2_file, 'Excel 文件'), (s.matrix2_sheet, 'Sheet 名称'), (s.matrix2_row_col, '纵向维度'), (s.matrix2_col_col, '横向维度')] + ([(s.matrix2_value_col, '销额列名，或填写数据子表格和月份列')] if not (s.matrix2_data_sheet.text().strip() and s.matrix2_month_col.text().strip()) else []), "run_btn6")
    def _run_matrix2(self):
        """运行产品矩阵2（销额数据版）。"""
        f = self.matrix2_file.text().strip()
        s = self.matrix2_sheet.text().strip()
        row_col = self.matrix2_row_col.text().strip()
        col_col = self.matrix2_col_col.text().strip()
        value_col = self.matrix2_value_col.text().strip()
        o = self.matrix2_output.text().strip()

        data_sheet = self.matrix2_data_sheet.text().strip()
        month_col = self.matrix2_month_col.text().strip()
        use_data_sheet = bool(data_sheet and month_col)

        if not f or not s:
            self.matrix2_log.setPlainText("请填写 Excel 文件和 Sheet 名称。")
            return
        if not row_col or not col_col:
            self.matrix2_log.setPlainText("请填写纵向维度列名和横向维度列名。")
            return
        if not use_data_sheet and not value_col:
            self.matrix2_log.setPlainText("请填写销额列名，或填写数据子表格+月份列。")
            return

        from core.report_io import normalized_path, require_distinct
        try:
            output = normalized_path(o or 'product_matrix.xlsx')
            require_distinct(f, output)
            if output.suffix.lower() != '.xlsx':
                raise ValueError('矩阵输出必须为.xlsx文件')
        except ValueError as exc:
            self.matrix2_log.setPlainText(str(exc))
            self.run_btn6._task_bar.summary.setText(str(exc))
            return False

        args = ["--file", f, "--sheet", s]

        filter_text = self.matrix2_filter.text().strip()
        if filter_text:
            for expr in filter_text.split(';'):
                expr = expr.strip()
                if expr:
                    args += ["--filter", expr]

        args += ["--row-col", row_col]
        row_values = self.matrix2_row_values.text().strip()
        if row_values:
            args += ["--row-values", row_values]

        args += ["--col-col", col_col]
        col_values = self.matrix2_col_values.text().strip()
        if col_values:
            args += ["--col-values", col_values]

        if use_data_sheet:
            args += ["--data-sheet", data_sheet, "--month-col", month_col]
        if value_col:
            args += ["--value-col", value_col]

        args += ["--output", str(output)]

        self._run("product_matrix2.py", self.matrix2_log, args=args,
                  run_btn=self.run_btn6)

