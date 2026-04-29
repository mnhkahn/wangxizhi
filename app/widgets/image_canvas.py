"""
图片编辑画布组件
"""

from typing import List, Optional, Dict, Any
from PyQt5.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QGraphicsPixmapItem,
)
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import (
    QPixmap,
    QImage,
    QPen,
    QBrush,
    QColor,
    QFont,
    QTransform,
    QPainter,
    QCursor,
)
import cv2
import numpy as np


class HandleItem(QGraphicsRectItem):
    """边界框调整手柄"""

    def __init__(self, handle_pos: str, parent: "BBoxItem"):
        super().__init__(0, 0, parent.HANDLE_SIZE, parent.HANDLE_SIZE, parent)
        self.handle_pos = handle_pos

        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsRectItem.ItemIsSelectable, False)
        self.setFlag(QGraphicsRectItem.ItemIsMovable, False)
        self.setZValue(1000)

    def hoverEnterEvent(self, event):
        cursor_map = {
            "nw": Qt.SizeFDiagCursor,
            "se": Qt.SizeFDiagCursor,
            "ne": Qt.SizeBDiagCursor,
            "sw": Qt.SizeBDiagCursor,
            "n": Qt.SizeVerCursor,
            "s": Qt.SizeVerCursor,
            "e": Qt.SizeHorCursor,
            "w": Qt.SizeHorCursor,
        }
        self.setCursor(QCursor(cursor_map.get(self.handle_pos, Qt.ArrowCursor)))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        parent = self.parentItem()
        if isinstance(parent, BBoxItem):
            parent.start_resize(self.handle_pos, event.scenePos())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        parent = self.parentItem()
        if isinstance(parent, BBoxItem):
            parent.resize_to(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        parent = self.parentItem()
        if isinstance(parent, BBoxItem):
            parent.end_resize()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class BBoxItem(QGraphicsRectItem):
    """可编辑的边界框项"""

    # 调整手柄大小
    HANDLE_SIZE = 12
    MIN_SIZE = 8

    def __init__(self, x: float, y: float, width: float, height: float,
                 char: str = "", item_id: int = 0):
        # 使用 setPos + local rect(0,0,w,h) 的方式，避免移动后 bbox 计算错误
        super().__init__(0, 0, width, height)
        self.setPos(x, y)

        self.item_id = item_id
        self.char = char
        self._selected = False
        self._highlighted = False
        # 基础层级：用于重叠时保持稳定排序；选中时会临时置顶
        self._base_z = float(item_id)
        self._resizing = False
        self._resize_handle: str | None = None
        self._resize_start_scene_pos: QPointF | None = None
        self._resize_start_bbox: List[float] | None = None

        # 拖拽移动起始 bbox（用于提交撤销）
        self._move_start_bbox: List[float] | None = None

        # 设置默认样式
        self.setPen(QPen(QColor(0, 255, 0), 2))
        self.setBrush(QBrush(Qt.NoBrush))
        self.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsRectItem.ItemIsMovable, True)
        self.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)
        self.setZValue(self._base_z)

        # 字符标签
        self.label = QGraphicsTextItem(char, self)
        self.label.setDefaultTextColor(QColor(255, 0, 0))
        self.label.setFont(QFont("Arial", 12, QFont.Bold))
        self.label.setPos(0, -20)
        self.label.setZValue(10)

        # 调整手柄
        self.handles = []
        self._create_handles()

    def _create_handles(self):
        """创建调整手柄"""
        handle_brush = QBrush(QColor(255, 255, 255))
        handle_pen = QPen(QColor(0, 0, 0), 1)

        for pos in ["nw", "n", "ne", "e", "se", "s", "sw", "w"]:
            handle = HandleItem(pos, self)
            handle.setBrush(handle_brush)
            handle.setPen(handle_pen)
            handle.setVisible(False)
            self.handles.append(handle)

        self._update_handle_positions()

    def _update_handle_positions(self):
        """更新手柄位置"""
        rect = self.rect()
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        hs = self.HANDLE_SIZE / 2

        # 8个手柄位置: 左上、上、右上、右、右下、下、左下、左
        positions = [
            (x - hs, y - hs),           # 左上
            (x + w/2 - hs, y - hs),     # 上
            (x + w - hs, y - hs),       # 右上
            (x + w - hs, y + h/2 - hs), # 右
            (x + w - hs, y + h - hs),   # 右下
            (x + w/2 - hs, y + h - hs), # 下
            (x - hs, y + h - hs),       # 左下
            (x - hs, y + h/2 - hs),     # 左
        ]

        for handle, pos in zip(self.handles, positions):
            handle.setPos(*pos)

    def set_highlight(self, highlighted: bool):
        """设置高亮状态（column/row 可能未正确推断时加粗提醒）"""
        self._highlighted = highlighted
        self._apply_pen()

    def _apply_pen(self):
        """根据选中/高亮状态应用边框样式"""
        if self._selected:
            width = 4 if self._highlighted else 3
            self.setPen(QPen(QColor(255, 0, 0), width))
        else:
            if self._highlighted:
                self.setPen(QPen(QColor(255, 165, 0), 4))
            else:
                self.setPen(QPen(QColor(0, 255, 0), 2))

    def set_selected(self, selected: bool):
        """设置选中状态"""
        self._selected = selected
        if selected:
            # 选中置顶：避免 bbox 重叠时误操作到别的框
            self.setZValue(100000.0 + self._base_z)
            for handle in self.handles:
                handle.setVisible(True)
        else:
            self.setZValue(self._base_z)
            for handle in self.handles:
                handle.setVisible(False)
        self._apply_pen()

    def update_char(self, char: str):
        """更新字符"""
        self.char = char
        self.label.setPlainText(char)

    def update_bbox(self, x: float, y: float, width: float, height: float):
        """更新边界框"""
        self.setPos(x, y)
        self.setRect(0, 0, width, height)
        self.label.setPos(0, -20)
        self._update_handle_positions()

    def get_bbox(self) -> List[float]:
        """获取边界框 [x1, y1, x2, y2]"""
        rect = self.rect()
        sp = self.scenePos()
        x1 = float(sp.x() + rect.x())
        y1 = float(sp.y() + rect.y())
        x2 = float(x1 + rect.width())
        y2 = float(y1 + rect.height())
        return [x1, y1, x2, y2]

    def start_resize(self, handle_pos: str, scene_pos: QPointF):
        """开始调整大小"""
        self._resizing = True
        self._resize_handle = handle_pos
        self._resize_start_scene_pos = scene_pos
        self._resize_start_bbox = self.get_bbox()

    def _notify_bbox_committed(self, old_bbox: List[float], new_bbox: List[float]):
        """向所属 view 通知 bbox 变更（用于撤销栈）"""
        sc = self.scene()
        if not sc:
            return
        for v in sc.views():
            if hasattr(v, "_notify_bbox_committed"):
                v._notify_bbox_committed(self.item_id, old_bbox, new_bbox)

    def resize_to(self, scene_pos: QPointF):
        """调整到新位置"""
        if not self._resizing or not self._resize_handle or not self._resize_start_scene_pos or not self._resize_start_bbox:
            return

        dx = float(scene_pos.x() - self._resize_start_scene_pos.x())
        dy = float(scene_pos.y() - self._resize_start_scene_pos.y())
        x1, y1, x2, y2 = [float(v) for v in self._resize_start_bbox]

        h = self._resize_handle
        if h == "nw":
            x1 += dx
            y1 += dy
        elif h == "n":
            y1 += dy
        elif h == "ne":
            x2 += dx
            y1 += dy
        elif h == "e":
            x2 += dx
        elif h == "se":
            x2 += dx
            y2 += dy
        elif h == "s":
            y2 += dy
        elif h == "sw":
            x1 += dx
            y2 += dy
        elif h == "w":
            x1 += dx

        # 归一化 + 最小尺寸
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1

        if (x2 - x1) < self.MIN_SIZE:
            x2 = x1 + self.MIN_SIZE
        if (y2 - y1) < self.MIN_SIZE:
            y2 = y1 + self.MIN_SIZE

        self.setPos(x1, y1)
        self.setRect(0, 0, x2 - x1, y2 - y1)
        self._update_handle_positions()

        # 实时通知预览更新
        self._notify_bbox_live()

    def _notify_bbox_live(self):
        """实时通知 view：bbox 正在变化（用于预览跟随）"""
        sc = self.scene()
        if not sc:
            return
        bbox = self.get_bbox()
        for v in sc.views():
            if hasattr(v, "_notify_bbox_live"):
                v._notify_bbox_live(self.item_id, bbox)

    def end_resize(self):
        """结束调整大小"""
        if self._resize_start_bbox is not None:
            old_bbox = self._resize_start_bbox
            new_bbox = self.get_bbox()
            if any(abs(a - b) > 0.001 for a, b in zip(old_bbox, new_bbox)):
                self._notify_bbox_committed(old_bbox, new_bbox)

        self._resizing = False
        self._resize_handle = None
        self._resize_start_scene_pos = None
        self._resize_start_bbox = None

    def mousePressEvent(self, event):
        # 记录移动前 bbox
        self._move_start_bbox = self.get_bbox()
        return super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # 移动后提交 bbox 变化
        if self._move_start_bbox is not None:
            old_bbox = self._move_start_bbox
            new_bbox = self.get_bbox()
            if any(abs(a - b) > 0.001 for a, b in zip(old_bbox, new_bbox)):
                self._notify_bbox_committed(old_bbox, new_bbox)
        self._move_start_bbox = None
        return super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        """项目变化事件"""
        if change == QGraphicsRectItem.ItemPositionHasChanged:
            # 位置变化时更新手柄
            self._update_handle_positions()

            # 实时通知预览更新
            self._notify_bbox_live()
        return super().itemChange(change, value)


class ImageCanvas(QGraphicsView):
    """图片编辑画布"""

    # 信号：选中项变化
    selection_changed = pyqtSignal(int)  # item_id
    bbox_updated = pyqtSignal(int, list)  # item_id, bbox
    bbox_edit_committed = pyqtSignal(int, list, list)  # item_id, old_bbox, new_bbox
    item_deleted = pyqtSignal(int)  # item_id

    def __init__(self, parent=None):
        super().__init__(parent)

        # 创建场景
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # 图片项
        self.image_item: Optional[QGraphicsPixmapItem] = None
        self.cv_image: Optional[np.ndarray] = None

        # 边界框项
        self.bbox_items: List[BBoxItem] = []
        self.selected_item: Optional[BBoxItem] = None

        # bbox 编辑追踪（用于撤销）
        self._bbox_editing_id: Optional[int] = None
        self._bbox_edit_start: Optional[List[float]] = None

        # 视图设置
        self.setRenderHint(QPainter.Antialiasing)
        # 关闭 QGraphicsView 自带的拖拽模式，避免与 bbox 拖拽/缩放冲突。
        # 平移改用：鼠标中键拖拽。
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        # 平移状态
        self._panning = False
        self._pan_start = None

        # 缩放
        self.zoom_factor = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 10.0

    def _notify_bbox_committed(self, item_id: int, old_bbox: list, new_bbox: list):
        """由 BBoxItem/HandleItem 回调触发的提交"""
        self.bbox_edit_committed.emit(item_id, old_bbox, new_bbox)

    def _notify_bbox_live(self, item_id: int, bbox: list):
        """由 BBoxItem 回调触发的实时更新"""
        self.bbox_updated.emit(item_id, bbox)

    def load_image(self, image_path: str):
        """加载图片"""
        # 使用 OpenCV 读取图片
        self.cv_image = cv2.imread(image_path)
        if self.cv_image is None:
            return False

        # 转换为 RGB
        rgb_image = cv2.cvtColor(self.cv_image, cv2.COLOR_BGR2RGB)

        # 转换为 QImage（需要复制数据以避免引用问题）
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        self._q_image = QImage(rgb_image.copy().data, w, h, bytes_per_line, QImage.Format_RGB888)

        # 创建 QPixmap
        pixmap = QPixmap.fromImage(self._q_image)

        # 清除场景并添加图片
        self.scene.clear()
        self.image_item = self.scene.addPixmap(pixmap)
        self.scene.setSceneRect(0, 0, w, h)

        # 重置视图
        self.reset_view()
        self.bbox_items.clear()
        self.selected_item = None

        return True

    def load_from_array(self, image: np.ndarray):
        """从 numpy 数组加载图片"""
        self.cv_image = image.copy()

        # 转换为 RGB
        if len(image.shape) == 3:
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            rgb_image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)

        # 转换为 QImage
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        q_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)

        # 创建 QPixmap
        pixmap = QPixmap.fromImage(q_image)

        # 清除场景并添加图片
        self.scene.clear()
        self.image_item = self.scene.addPixmap(pixmap)
        self.scene.setSceneRect(0, 0, w, h)

        # 重置视图
        self.reset_view()
        self.bbox_items.clear()
        self.selected_item = None

    def reset_view(self):
        """重置视图"""
        self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.zoom_factor = 1.0

    def zoom_in(self):
        """放大"""
        if self.zoom_factor < self.max_zoom:
            self.zoom_factor *= 1.2
            self.scale(1.2, 1.2)

    def zoom_out(self):
        """缩小"""
        if self.zoom_factor > self.min_zoom:
            self.zoom_factor /= 1.2
            self.scale(1/1.2, 1/1.2)

    def wheelEvent(self, event):
        """滚轮事件：缩放"""
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
        else:
            super().wheelEvent(event)

    def _start_pan(self, event):
        self._panning = True
        self._pan_start = event.pos()
        self.setCursor(QCursor(Qt.ClosedHandCursor))

    def _end_pan(self):
        self._panning = False
        self._pan_start = None
        self.unsetCursor()

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def add_bbox(self, x: float, y: float, width: float, height: float,
                 char: str = "", item_id: int = 0, highlight: bool = False) -> BBoxItem:
        """添加边界框"""
        bbox = BBoxItem(x, y, width, height, char, item_id)
        if highlight:
            bbox.set_highlight(True)
        self.scene.addItem(bbox)
        self.bbox_items.append(bbox)
        return bbox

    def clear_bboxes(self):
        """清除所有边界框"""
        for bbox in self.bbox_items:
            self.scene.removeItem(bbox)
        self.bbox_items.clear()
        self.selected_item = None

    def select_bbox(self, item_id: int):
        """选中边界框"""
        # 取消之前的选中
        if self.selected_item:
            self.selected_item.set_selected(False)

        # 查找并选中新项
        for bbox in self.bbox_items:
            if bbox.item_id == item_id:
                bbox.set_selected(True)
                self.selected_item = bbox
                self.center_on_bbox(bbox)
                self.selection_changed.emit(item_id)
                return

    def center_on_bbox(self, bbox: BBoxItem):
        """居中显示边界框"""
        rect = bbox.sceneBoundingRect()
        self.centerOn(rect.center())

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        # 平移：中键拖拽
        # 说明：空格键不是 Qt 的 modifier（只包含 Ctrl/Shift/Alt/Meta），
        # 因此不使用 “Space + 左键” 作为平移手势，避免在 PyQt5 下报错。
        if event.button() == Qt.MiddleButton:
            self._start_pan(event)
            event.accept()
            return

        if event.button() == Qt.LeftButton:
            # 检查是否点击了边界框
            pos = self.mapToScene(event.pos())
            item = self.scene.itemAt(pos, self.transform())

            # 点击了手柄：选中其父级 bbox
            if isinstance(item, HandleItem):
                parent = item.parentItem()
                if isinstance(parent, BBoxItem):
                    if self.selected_item and self.selected_item != parent:
                        self.selected_item.set_selected(False)
                    parent.set_selected(True)
                    self.selected_item = parent
                    self.selection_changed.emit(parent.item_id)

                    # 记录开始 bbox（缩放）
                    self._bbox_editing_id = parent.item_id
                    self._bbox_edit_start = parent.get_bbox()

                    super().mousePressEvent(event)
                    return

            if isinstance(item, BBoxItem):
                # 点击了边界框
                if self.selected_item and self.selected_item != item:
                    self.selected_item.set_selected(False)
                item.set_selected(True)
                self.selected_item = item
                self.selection_changed.emit(item.item_id)

                # 记录开始 bbox（拖拽移动）
                self._bbox_editing_id = item.item_id
                self._bbox_edit_start = item.get_bbox()
            elif item == self.image_item or item is None:
                # 点击了图片空白区域
                if self.selected_item:
                    self.selected_item.set_selected(False)
                    self.selected_item = None
                    self.selection_changed.emit(-1)

                self._bbox_editing_id = None
                self._bbox_edit_start = None

        self.setFocus()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if self._panning:
            self._end_pan()
            event.accept()
            return

        if self.selected_item:
            # 通知边界框更新
            bbox = self.selected_item.get_bbox()
            self.bbox_updated.emit(self.selected_item.item_id, bbox)

            # 提交 bbox 变更（用于撤销）
            if (
                self._bbox_editing_id is not None
                and self._bbox_edit_start is not None
                and self._bbox_editing_id == self.selected_item.item_id
            ):
                old_bbox = self._bbox_edit_start
                new_bbox = bbox
                if any(abs(a - b) > 0.001 for a, b in zip(old_bbox, new_bbox)):
                    self.bbox_edit_committed.emit(self.selected_item.item_id, old_bbox, new_bbox)

        self._bbox_editing_id = None
        self._bbox_edit_start = None
        super().mouseReleaseEvent(event)

    def delete_selected_bbox(self):
        """删除当前选中的边界框"""
        if not self.selected_item:
            return
        item_id = self.selected_item.item_id
        self.scene.removeItem(self.selected_item)
        self.bbox_items.remove(self.selected_item)
        self.selected_item = None
        self.item_deleted.emit(item_id)
        self.selection_changed.emit(-1)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected_bbox()
            event.accept()
            return
        super().keyPressEvent(event)

    def get_cv_image(self) -> Optional[np.ndarray]:
        """获取 OpenCV 图像"""
        return self.cv_image
