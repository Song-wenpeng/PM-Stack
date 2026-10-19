"""Review import correction dialog."""
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QAbstractItemView,QHeaderView,QMessageBox,QInputDialog)
from core.widgets import make_button
from .store import ReviewStore
from .import_management import batches,change_batch
from .excel_import import filename_asin

class ImportManagerDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入记录 · 纠错 / 移除")
        self.resize(1000,550)
        layout=QVBoxLayout(self)
        hint=QLabel("按文件来源管理本地未同步导入。纠正归属会保留原文和标签；移除仅解除本批次的商品关联。每次操作先备份。")
        hint.setWordWrap(True);layout.addWidget(hint)
        self.table=QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels(["目标 ASIN","站点","来源文件","评论数"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        actions=QHBoxLayout()
        for title,callback in [("纠正目标 ASIN",lambda:self.change(True)),("移除此批次归属",lambda:self.change(False)),("刷新",self.refresh),("关闭",self.accept)]:
            button=make_button(title);button.clicked.connect(callback);actions.addWidget(button)
        layout.addLayout(actions)
        self.status=QLabel("");self.status.setWordWrap(True);layout.addWidget(self.status)
        self.refresh()

    def refresh(self):
        store=None
        try:
            store=ReviewStore();self.rows=batches(store)
            self.table.setRowCount(len(self.rows))
            for i,row in enumerate(self.rows):
                for j,value in enumerate([row["asin"],row["marketplace"],row["file"],len(row["ids"])]):
                    self.table.setItem(i,j,QTableWidgetItem(str(value)))
        except Exception as exc:
            QMessageBox.warning(self,"读取失败",str(exc))
        finally:
            if store:store.close()

    def change(self,move):
        index=self.table.currentRow()
        if not 0<=index<len(self.rows):return
        row=self.rows[index];destination=""
        if move:
            destination,ok=QInputDialog.getText(self,"纠正目标 ASIN","新的目标 ASIN：",text=filename_asin(row["file"]))
            if not ok:return
            destination=destination.strip().upper()
            if not destination:return
        action=f"改为关联 {destination}" if move else "移除这批评论在此商品下的归属"
        answer=QMessageBox.question(self,"确认导入纠错",
            f"文件：{row['file']}\n站点：{row['marketplace']}\n当前 ASIN：{row['asin']}\n涉及 {len(row['ids'])} 条评论，将{action}。\n\n其他文件和已知浏览器来源仍需要的关联会保留。原文与标签保留，操作前自动备份。",
            QMessageBox.StandardButton.Ok|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)
        if answer!=QMessageBox.StandardButton.Ok:return
        store=None
        try:
            store=ReviewStore();result=change_batch(store,row,destination)
            self.status.setText(f"已移除 {result['removed']} 条旧归属，关联目标 {result['associated']} 条；其他来源保留 {result['retained']} 条。备份：{result['backup']}")
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self,"未执行修改",str(exc))
        finally:
            if store:store.close()
