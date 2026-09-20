"""Controls for importing a local review workbook into the common collection UI."""
import json
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox, QFileDialog
from core.widgets import FileDropLineEdit, make_button, configure_combo

class ExcelImportOptions(QWidget):
    def __init__(self, config_mgr, parent=None):
        super().__init__(parent)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        row=QHBoxLayout()
        self.path=FileDropLineEdit(placeholder="选择或拖入卖家精灵 / PM Stack 评论 .xlsx")
        row.addWidget(self.path,1)
        button=make_button("选择文件")
        button.clicked.connect(self.browse)
        row.addWidget(button)
        layout.addLayout(row)
        options=QHBoxLayout()
        self.ai=QCheckBox("导入后提取标签")
        self.ai.setChecked(True)
        options.addWidget(self.ai)
        self.category=configure_combo(QComboBox())
        self.configs={}
        try:
            with open(config_mgr.resolve_config("product_configs.json"),encoding="utf-8") as stream:
                self.configs=json.load(stream)
            for key,value in self.configs.items():
                self.category.addItem(value.get("display_name",key)+" · "+value.get("product_desc","")[:35],key)
            index=self.category.findData("power strip")
            if index>=0: self.category.setCurrentIndex(index)
        except (OSError,ValueError,TypeError):
            self.category.addItem("请在设置中配置品类模板","")
        options.addWidget(self.category,1)
        self.sync=QCheckBox("完成后同步云端")
        self.sync.setChecked(True)
        options.addWidget(self.sync)
        layout.addLayout(options)
        hint=QLabel("读取“内容”原文；保留评论链接、变体和来源。相同评论自动去重，相同模板标签自动复用。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def browse(self):
        path,_=QFileDialog.getOpenFileName(self,"选择评论 Excel","","Excel (*.xlsx)")
        if path: self.path.setText(path)
