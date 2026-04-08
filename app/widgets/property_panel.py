"""
属性面板组件
"""

from typing import Optional
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from ..models.char_item import CharItem


class PropertyPanel(QWidget):
    """属性面板组件"""

    # 信号：属性变化
    char_changed = pyqtSignal(int, str)  # item_id, char
    bbox_changed = pyqtSignal(int, float, float, float, float)  # item_id, x, y, w, h

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_item: Optional[CharItem] = None
        self._updating = False  # 防止循环更新

        self._init_ui()

    def _init_ui(self):
        """初始化 UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        # 字符
        layout.addWidget(QLabel("字:"))
        self.char_edit = QLineEdit()
        self.char_edit.setFont(QFont("Arial", 16))
        self.char_edit.setMaxLength(1)
        self.char_edit.setFixedWidth(48)
        self.char_edit.textChanged.connect(self._on_char_changed)
        layout.addWidget(self.char_edit)

        # 位置
        layout.addWidget(QLabel("X:"))
        self.x_spin = QDoubleSpinBox()
        self.x_spin.setRange(0, 99999)
        self.x_spin.setDecimals(0)
        self.x_spin.setFixedWidth(90)
        self.x_spin.valueChanged.connect(self._on_position_changed)
        layout.addWidget(self.x_spin)

        layout.addWidget(QLabel("Y:"))
        self.y_spin = QDoubleSpinBox()
        self.y_spin.setRange(0, 99999)
        self.y_spin.setDecimals(0)
        self.y_spin.setFixedWidth(90)
        self.y_spin.valueChanged.connect(self._on_position_changed)
        layout.addWidget(self.y_spin)

        # 尺寸
        layout.addWidget(QLabel("W:"))
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(1, 99999)
        self.width_spin.setDecimals(0)
        self.width_spin.setFixedWidth(90)
        self.width_spin.valueChanged.connect(self._on_size_changed)
        layout.addWidget(self.width_spin)

        layout.addWidget(QLabel("H:"))
        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(1, 99999)
        self.height_spin.setDecimals(0)
        self.height_spin.setFixedWidth(90)
        self.height_spin.valueChanged.connect(self._on_size_changed)
        layout.addWidget(self.height_spin)

        # 信息
        self.info_label = QLabel("未选中字符")
        self.info_label.setStyleSheet("color: gray;")
        layout.addStretch(1)
        layout.addWidget(self.info_label)

        # 初始禁用
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool):
        """设置启用状态"""
        self.char_edit.setEnabled(enabled)
        self.x_spin.setEnabled(enabled)
        self.y_spin.setEnabled(enabled)
        self.width_spin.setEnabled(enabled)
        self.height_spin.setEnabled(enabled)

    def load_item(self, item: Optional[CharItem]):
        """加载字符项"""
        self._updating = True
        self.current_item = item

        if item:
            self._set_enabled(True)
            self.char_edit.setText(item.char)
            self.x_spin.setValue(item.x)
            self.y_spin.setValue(item.y)
            self.width_spin.setValue(item.width)
            self.height_spin.setValue(item.height)
            self.info_label.setText(f"ID: {item.id} | 列: {item.column} | 行: {item.row}")
            self.info_label.setStyleSheet("color: black;")
        else:
            self._set_enabled(False)
            self.char_edit.clear()
            self.x_spin.setValue(0)
            self.y_spin.setValue(0)
            self.width_spin.setValue(1)
            self.height_spin.setValue(1)
            self.info_label.setText("未选中字符")
            self.info_label.setStyleSheet("color: gray;")

        self._updating = False

    def _on_char_changed(self, text: str):
        """字符变化"""
        if self._updating or not self.current_item:
            return

        self.current_item.char = text
        self.char_changed.emit(self.current_item.id, text)

    def _on_position_changed(self):
        """位置变化"""
        if self._updating or not self.current_item:
            return

        x = self.x_spin.value()
        y = self.y_spin.value()

        self.current_item.x = x
        self.current_item.y = y

        self.bbox_changed.emit(
            self.current_item.id,
            x, y,
            self.current_item.width,
            self.current_item.height
        )

    def _on_size_changed(self):
        """尺寸变化"""
        if self._updating or not self.current_item:
            return

        width = self.width_spin.value()
        height = self.height_spin.value()

        self.current_item.width = width
        self.current_item.height = height

        self.bbox_changed.emit(
            self.current_item.id,
            self.current_item.x,
            self.current_item.y,
            width, height
        )

    def update_from_item(self, item: CharItem):
        """从字符项更新（不触发信号）"""
        if self.current_item and self.current_item.id == item.id:
            self._updating = True
            self.char_edit.setText(item.char)
            self.x_spin.setValue(item.x)
            self.y_spin.setValue(item.y)
            self.width_spin.setValue(item.width)
            self.height_spin.setValue(item.height)
            self._updating = False
