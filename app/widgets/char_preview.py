""" 
右侧预览框：显示当前选中字符的裁剪预览和信息。
"""

from __future__ import annotations

from typing import Optional, List

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QSizePolicy


class CharPreviewWidget(QWidget):
    """字符预览组件"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # 由外层容器固定宽度；这里保持可扩展，避免与外层 fixedWidth 冲突

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.char_label = QLabel("(未选中)")
        self.char_label.setFont(QFont("Arial", 28, QFont.Bold))
        self.char_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.char_label.setFixedHeight(44)
        layout.addWidget(self.char_label)

        self.image_label = QLabel()
        self.image_label.setFrameShape(QFrame.Box)
        self.image_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.image_label.setMinimumHeight(220)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.image_label, 1)

        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: gray;")
        # 固定信息区高度，避免内容变化导致预览区整体抖动
        self.info_label.setFixedHeight(54)
        layout.addWidget(self.info_label)

        layout.addStretch(0)

        self.clear()

        # 记录最近一次内容，便于 resize 时重绘占满
        self._last_image_bgr: Optional[np.ndarray] = None
        self._last_char: str = ""
        self._last_bbox: List[float] = []
        self._last_meta: str = ""
        self._pending_rerender = False

    def clear(self):
        self.char_label.setText("(未选中)")
        self.image_label.clear()
        self.info_label.setText("")
        self._last_image_bgr = None
        self._last_char = ""
        self._last_bbox = []
        self._last_meta = ""

    def update_preview(self, image_bgr: Optional[np.ndarray], char: str, bbox: List[float], meta: str = ""):
        """更新预览内容"""
        self._last_image_bgr = image_bgr
        self._last_char = char
        self._last_bbox = bbox
        self._last_meta = meta

        self.char_label.setText(char or "")

        if image_bgr is None or not bbox:
            self.image_label.clear()
            self.info_label.setText(meta)
            return

        h, w = image_bgr.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in bbox]
        x1 = max(0, min(w - 1, x1))
        y1 = max(0, min(h - 1, y1))
        x2 = max(0, min(w, x2))
        y2 = max(0, min(h, y2))

        if x2 <= x1 or y2 <= y1:
            self.image_label.clear()
            self.info_label.setText(meta)
            return

        crop = image_bgr[y1:y2, x1:x2]
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        ch = rgb.shape[2]
        qimg = QImage(rgb.data, rgb.shape[1], rgb.shape[0], ch * rgb.shape[1], QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        # 预览不截断：保持比例“完整展示”（可能出现留白）
        pix = pix.scaled(
            self.image_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(pix)

        info = f"bbox: [{x1}, {y1}, {x2}, {y2}]"
        if meta:
            info = meta + "\n" + info
        self.info_label.setText(info)

    def resizeEvent(self, event):
        # 当预览框尺寸变化（例如 minimize / 窗口缩放）时，按新尺寸重新渲染。
        # 这里用 singleShot(0) 等待布局稳定，避免拿到旧 size。
        if self._last_image_bgr is not None and self._last_bbox and not self._pending_rerender:
            self._pending_rerender = True

            def _rerender():
                self._pending_rerender = False
                if self._last_image_bgr is not None and self._last_bbox:
                    self.update_preview(self._last_image_bgr, self._last_char, self._last_bbox, meta=self._last_meta)

            QTimer.singleShot(0, _rerender)
        return super().resizeEvent(event)
