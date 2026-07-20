"""
字符列表组件
"""

from typing import List
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QLineEdit,
    QHBoxLayout,
    QAbstractItemView,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from ..models.char_item import CharItem


class CharListWidget(QWidget):
    """字符列表组件"""

    # 信号：选中项变化
    char_selected = pyqtSignal(int)  # item_id
    char_double_clicked = pyqtSignal(int)  # item_id

    def __init__(self, parent=None):
        super().__init__(parent)

        self.items: List[CharItem] = []

        self._init_ui()

    def _init_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # 标题
        title = QLabel("字符列表")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(title)

        # 搜索框
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索字符...")
        self.search_edit.textChanged.connect(self._filter_items)
        layout.addWidget(self.search_edit)

        # 列表
        self.list_widget = QListWidget()
        self.list_widget.setFont(QFont("Arial", 14))
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget)

        # 统计信息
        self.stats_label = QLabel("共 0 个字符")
        layout.addWidget(self.stats_label)

    def load_items(self, items: List[CharItem]):
        """加载字符项"""
        self.items = items
        self._refresh_list()

    def _refresh_list(self):
        """刷新列表"""
        self.list_widget.clear()

        for item in self.items:
            list_item = QListWidgetItem(f"{item.char} (列{item.column}, 行{item.row})")
            list_item.setData(Qt.UserRole, item.id)
            self.list_widget.addItem(list_item)

        self.stats_label.setText(f"共 {len(self.items)} 个字符")

    def _filter_items(self, text: str):
        """过滤列表"""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            char_item = self.items[i] if i < len(self.items) else None

            if char_item:
                visible = text.lower() in char_item.char.lower()
                item.setHidden(not visible)

    def _on_item_clicked(self, item: QListWidgetItem):
        """点击项"""
        item_id = item.data(Qt.UserRole)
        self.char_selected.emit(item_id)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        """双击项"""
        item_id = item.data(Qt.UserRole)
        self.char_double_clicked.emit(item_id)

    def select_item(self, item_id: int):
        """选中项"""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == item_id:
                self.list_widget.setCurrentItem(item)
                self.list_widget.scrollToItem(item)
                break

    def update_item_char(self, item_id: int, char: str):
        """更新项字符"""
        for i, item in enumerate(self.items):
            if item.id == item_id:
                item.char = char
                list_item = self.list_widget.item(i)
                if list_item:
                    list_item.setText(f"{char} (列{item.column}, 行{item.row})")
                break

    def clear(self):
        """清空列表"""
        self.items.clear()
        self.list_widget.clear()
        self.stats_label.setText("共 0 个字符")
