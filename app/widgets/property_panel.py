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
    QComboBox,
    QCheckBox,
)
from PyQt5.QtCore import Qt, pyqtSignal
from ..models.char_item import CharItem
from ..utils.fonts import extended_cjk_font


class PropertyPanel(QWidget):
    """属性面板组件"""

    # 信号：属性变化
    char_changed = pyqtSignal(int, str)  # item_id, char
    bbox_changed = pyqtSignal(int, float, float, float, float)  # item_id, x, y, w, h
    font_changed = pyqtSignal(str)  # 字体（每张图）
    author_changed = pyqtSignal(str)  # 作者（每张图）
    work_changed = pyqtSignal(str)  # 作品（每张图）
    visible_changed = pyqtSignal(int, bool)  # item_id, visible
    row_changed = pyqtSignal(int, int)  # item_id, row
    column_changed = pyqtSignal(int, int)  # item_id, column

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_item: Optional[CharItem] = None
        self._updating = False  # 防止循环更新

        self._image_meta_enabled = False

        self._init_ui()

    def _init_ui(self):
        """初始化 UI"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        # 字体（单独一行）
        row_font = QHBoxLayout()
        row_font.setSpacing(10)
        row_font.addWidget(QLabel("字体:"))
        self.font_combo = QComboBox()
        self.font_combo.addItems(["楷书", "行书", "草书", "篆书", "隶书"])
        self.font_combo.currentTextChanged.connect(self._on_font_changed)
        row_font.addWidget(self.font_combo, 1)
        outer.addLayout(row_font)

        # 作者（单独一行）
        row_author = QHBoxLayout()
        row_author.setSpacing(10)
        row_author.addWidget(QLabel("作者:"))
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText("手动录入")
        self.author_edit.textChanged.connect(self._on_author_changed)
        row_author.addWidget(self.author_edit, 1)
        outer.addLayout(row_author)

        # 作品（单独一行）
        row_work = QHBoxLayout()
        row_work.setSpacing(10)
        row_work.addWidget(QLabel("作品:"))
        self.work_edit = QLineEdit()
        self.work_edit.setPlaceholderText("手动录入")
        self.work_edit.textChanged.connect(self._on_work_changed)
        row_work.addWidget(self.work_edit, 1)
        outer.addLayout(row_work)

        # 字（单独一行）
        row_char = QHBoxLayout()
        row_char.setSpacing(10)
        row_char.addWidget(QLabel("字:"))
        self.char_edit = QLineEdit()
        self.char_edit.setFont(extended_cjk_font(18))
        # CJK 扩展 B 及以后的字符在 UTF-16 中占两个 code unit；限制为 1 会
        # 导致此类单字无法完整输入。
        self.char_edit.setMaxLength(2)
        self.char_edit.setFixedWidth(64)
        self.char_edit.textChanged.connect(self._on_char_changed)
        row_char.addWidget(self.char_edit)
        self.info_label = QLabel("未选中字符")
        self.info_label.setStyleSheet("color: gray;")
        row_char.addStretch(1)
        row_char.addWidget(self.info_label)
        outer.addLayout(row_char)

        # X/Y（每行一个）
        row_x = QHBoxLayout()
        row_x.setSpacing(10)
        row_x.addWidget(QLabel("X:"))
        self.x_spin = QDoubleSpinBox()
        self.x_spin.setRange(0, 99999)
        self.x_spin.setDecimals(0)
        self.x_spin.valueChanged.connect(self._on_position_changed)
        row_x.addWidget(self.x_spin, 1)
        outer.addLayout(row_x)

        row_y = QHBoxLayout()
        row_y.setSpacing(10)
        row_y.addWidget(QLabel("Y:"))
        self.y_spin = QDoubleSpinBox()
        self.y_spin.setRange(0, 99999)
        self.y_spin.setDecimals(0)
        self.y_spin.valueChanged.connect(self._on_position_changed)
        row_y.addWidget(self.y_spin, 1)
        outer.addLayout(row_y)

        row_w = QHBoxLayout()
        row_w.setSpacing(10)
        row_w.addWidget(QLabel("W:"))
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(1, 99999)
        self.width_spin.setDecimals(0)
        self.width_spin.valueChanged.connect(self._on_size_changed)
        row_w.addWidget(self.width_spin, 1)
        outer.addLayout(row_w)

        row_h = QHBoxLayout()
        row_h.setSpacing(10)
        row_h.addWidget(QLabel("H:"))
        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(1, 99999)
        self.height_spin.setDecimals(0)
        self.height_spin.valueChanged.connect(self._on_size_changed)
        row_h.addWidget(self.height_spin, 1)
        outer.addLayout(row_h)

        # 列
        row_col = QHBoxLayout()
        row_col.setSpacing(10)
        row_col.addWidget(QLabel("列:"))
        self.column_spin = QSpinBox()
        self.column_spin.setRange(0, 99999)
        self.column_spin.valueChanged.connect(self._on_column_changed)
        row_col.addWidget(self.column_spin, 1)
        outer.addLayout(row_col)

        # 行
        row_row = QHBoxLayout()
        row_row.setSpacing(10)
        row_row.addWidget(QLabel("行:"))
        self.row_spin = QSpinBox()
        self.row_spin.setRange(0, 99999)
        self.row_spin.valueChanged.connect(self._on_row_changed)
        row_row.addWidget(self.row_spin, 1)
        outer.addLayout(row_row)

        # 可见性（参与导出）
        row_visible = QHBoxLayout()
        row_visible.setSpacing(10)
        self.visible_check = QCheckBox("可见（参与导出）")
        self.visible_check.setChecked(True)
        self.visible_check.stateChanged.connect(self._on_visible_changed)
        row_visible.addWidget(self.visible_check)
        outer.addLayout(row_visible)

        # 初始禁用
        self._set_item_enabled(False)
        self._set_meta_enabled(False)

    def _set_item_enabled(self, enabled: bool):
        """设置单字编辑启用状态"""
        self.char_edit.setEnabled(enabled)
        self.x_spin.setEnabled(enabled)
        self.y_spin.setEnabled(enabled)
        self.width_spin.setEnabled(enabled)
        self.height_spin.setEnabled(enabled)
        self.column_spin.setEnabled(enabled)
        self.row_spin.setEnabled(enabled)
        self.visible_check.setEnabled(enabled)

    def _set_meta_enabled(self, enabled: bool):
        """设置图片级元数据启用状态"""
        self._image_meta_enabled = enabled
        self.font_combo.setEnabled(enabled)
        self.author_edit.setEnabled(enabled)
        self.work_edit.setEnabled(enabled)

    def set_image_meta(self, font: str = "楷书", author: str = "", work: str = "", enabled: bool = True):
        """设置当前图片的字体/作者（不触发信号）"""
        self._updating = True
        self._set_meta_enabled(enabled)

        # 字体：若不在列表里，追加一个“自定义”项保持显示
        if font and font not in [self.font_combo.itemText(i) for i in range(self.font_combo.count())]:
            self.font_combo.addItem(font)
        if font:
            self.font_combo.setCurrentText(font)
        else:
            self.font_combo.setCurrentText("楷书")

        self.author_edit.setText(author or "")
        self.work_edit.setText(work or "")
        self._updating = False

    def load_item(self, item: Optional[CharItem]):
        """加载字符项"""
        self._updating = True
        self.current_item = item

        if item:
            self._set_item_enabled(True)
            self.char_edit.setText(item.char)
            self.x_spin.setValue(item.x)
            self.y_spin.setValue(item.y)
            self.width_spin.setValue(item.width)
            self.height_spin.setValue(item.height)
            self.column_spin.setValue(item.column)
            self.row_spin.setValue(item.row)
            self.visible_check.setChecked(item.visible)
            self.info_label.setText(f"ID: {item.id} | 列: {item.column} | 行: {item.row}")
            self.info_label.setStyleSheet("color: black;")
        else:
            self._set_item_enabled(False)
            self.char_edit.clear()
            self.x_spin.setValue(0)
            self.y_spin.setValue(0)
            self.width_spin.setValue(1)
            self.height_spin.setValue(1)
            self.column_spin.setValue(0)
            self.row_spin.setValue(0)
            self.visible_check.setChecked(True)
            self.info_label.setText("未选中字符")
            self.info_label.setStyleSheet("color: gray;")

        self._updating = False

    def _on_char_changed(self, text: str):
        """字符变化"""
        if self._updating or not self.current_item:
            return

        self.current_item.char = text
        self.char_changed.emit(self.current_item.id, text)

    def _on_font_changed(self, font: str):
        if self._updating or not self._image_meta_enabled:
            return
        self.font_changed.emit(font)

    def _on_author_changed(self, author: str):
        if self._updating or not self._image_meta_enabled:
            return
        self.author_changed.emit(author)

    def _on_work_changed(self, work: str):
        if self._updating or not self._image_meta_enabled:
            return
        self.work_changed.emit(work)

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

    def _on_visible_changed(self, state: int):
        """可见性变化"""
        if self._updating or not self.current_item:
            return
        visible = bool(state == Qt.Checked)
        self.current_item.visible = visible
        self.visible_changed.emit(self.current_item.id, visible)

    def _on_column_changed(self, value: int):
        """列变化"""
        if self._updating or not self.current_item:
            return
        self.current_item.column = value
        self.column_changed.emit(self.current_item.id, value)

    def _on_row_changed(self, value: int):
        """行变化"""
        if self._updating or not self.current_item:
            return
        self.current_item.row = value
        self.row_changed.emit(self.current_item.id, value)

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
