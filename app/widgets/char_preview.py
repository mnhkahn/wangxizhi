""" 
右侧预览框：显示当前选中字符的裁剪预览和信息。
"""

from __future__ import annotations

from typing import Optional, List

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame


class CharPreviewWidget(QWidget):
    """字符预览组件"""

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        title = QLabel("预览")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(title)

        self.char_label = QLabel("(未选中)")
        self.char_label.setFont(QFont("Arial", 28, QFont.Bold))
        self.char_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        layout.addWidget(self.char_label)

        self.image_label = QLabel()
        self.image_label.setFrameShape(QFrame.Box)
        self.image_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.image_label.setMinimumHeight(220)
        layout.addWidget(self.image_label, 1)

        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: gray;")
        layout.addWidget(self.info_label)

        layout.addStretch(0)

        self.clear()

    def clear(self):
        self.char_label.setText("(未选中)")
        self.image_label.clear()
        self.info_label.setText("")

    def update_preview(self, image_bgr: Optional[np.ndarray], char: str, bbox: List[float], meta: str = ""):
        """更新预览内容"""
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
        pix = pix.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(pix)

        info = f"bbox: [{x1}, {y1}, {x2}, {y2}]"
        if meta:
            info = meta + "\n" + info
        self.info_label.setText(info)

    def resizeEvent(self, event):
        # pixmap 缩放在上层调用时再触发，这里不强制重算（避免闪烁）
        return super().resizeEvent(event)

