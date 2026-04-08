"""
主窗口
"""

import os
import json
from typing import Optional, List
from pathlib import Path
from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QFileDialog,
    QMessageBox,
    QStatusBar,
    QToolBar,
    QAction,
    QProgressBar,
    QLabel,
    QApplication,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QIcon, QFont

from .widgets.image_canvas import ImageCanvas
from .widgets.char_list import CharListWidget
from .widgets.property_panel import PropertyPanel
from .models.char_item import CharItem, CharItemManager


class OCRWorker(QThread):
    """OCR 处理线程"""

    finished = pyqtSignal(dict)  # 处理完成
    error = pyqtSignal(str)  # 处理错误

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path

    def run(self):
        try:
            import sys
            # 添加项目根目录到路径
            project_root = Path(__file__).parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))

            from ocr import CalligraphyOCR

            ocr = CalligraphyOCR()
            # 识别后保存到 ocr_output/<stem>/result.json，方便下次直接加载
            result = ocr.recognize_image(self.image_path, save_result=True, debug=False)
            result["_from_cache"] = False
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()

        self.char_manager = CharItemManager()
        self.current_image_path: Optional[str] = None
        self.ocr_worker: Optional[OCRWorker] = None
        self._last_loaded_cache_path: Optional[str] = None

        self._init_ui()
        self._init_menu()
        self._init_toolbar()
        self._init_statusbar()
        self._connect_signals()

    def _init_ui(self):
        """初始化 UI"""
        self.setWindowTitle("书法拆字编辑器")
        self.setGeometry(100, 100, 1400, 900)

        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局：左侧字符列表 + 右侧(属性面板在上 + 图片在下)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(6)

        splitter = QSplitter(Qt.Horizontal)

        # 左侧：字符列表
        self.char_list = CharListWidget()
        self.char_list.setMinimumWidth(160)
        self.char_list.setMaximumWidth(260)
        splitter.addWidget(self.char_list)

        # 右侧：属性面板（上）+ 图片画布（下）
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.property_panel = PropertyPanel()
        self.property_panel.setMinimumHeight(44)
        self.property_panel.setMaximumHeight(72)
        right_layout.addWidget(self.property_panel, 0)

        self.image_canvas = ImageCanvas()
        right_layout.addWidget(self.image_canvas, 1)

        splitter.addWidget(right_widget)

        # 设置分割比例：尽量把空间让给图片
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 1180])

        main_layout.addWidget(splitter, 1)

    def _init_menu(self):
        """初始化菜单"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")

        open_action = QAction("打开(&O)", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_image)
        file_menu.addAction(open_action)

        recognize_action = QAction("识别(&R)", self)
        recognize_action.setShortcut("Ctrl+R")
        recognize_action.triggered.connect(self.recognize_image)
        file_menu.addAction(recognize_action)

        save_action = QAction("保存编辑(&S)", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_edits)
        file_menu.addAction(save_action)

        file_menu.addSeparator()

        export_action = QAction("导出(&E)", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.export_chars)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 编辑菜单
        edit_menu = menubar.addMenu("编辑(&E)")

        undo_action = QAction("撤销(&U)", self)
        undo_action.setShortcut("Ctrl+Z")
        edit_menu.addAction(undo_action)

        redo_action = QAction("重做(&R)", self)
        redo_action.setShortcut("Ctrl+Y")
        edit_menu.addAction(redo_action)

        edit_menu.addSeparator()

        delete_action = QAction("删除(&D)", self)
        delete_action.setShortcut("Delete")
        edit_menu.addAction(delete_action)

        # 视图菜单
        view_menu = menubar.addMenu("视图(&V)")

        zoom_in_action = QAction("放大(&I)", self)
        zoom_in_action.setShortcut("Ctrl++")
        zoom_in_action.triggered.connect(self.image_canvas.zoom_in)
        view_menu.addAction(zoom_in_action)

        zoom_out_action = QAction("缩小(&O)", self)
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(self.image_canvas.zoom_out)
        view_menu.addAction(zoom_out_action)

        reset_view_action = QAction("重置视图(&R)", self)
        reset_view_action.setShortcut("Ctrl+0")
        reset_view_action.triggered.connect(self.image_canvas.reset_view)
        view_menu.addAction(reset_view_action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _init_toolbar(self):
        """初始化工具栏"""
        toolbar = self.addToolBar("主工具栏")
        toolbar.setMovable(False)

        # 打开
        open_action = QAction("打开", self)
        open_action.triggered.connect(self.open_image)
        toolbar.addAction(open_action)

        # 识别（强制调用 API 并刷新结果）
        recognize_action = QAction("识别", self)
        recognize_action.triggered.connect(self.recognize_image)
        toolbar.addAction(recognize_action)

        # 保存编辑（写回现有 json，不写 result.json）
        save_action = QAction("保存", self)
        save_action.triggered.connect(self.save_edits)
        toolbar.addAction(save_action)

        # 导出
        export_action = QAction("导出", self)
        export_action.triggered.connect(self.export_chars)
        toolbar.addAction(export_action)

        toolbar.addSeparator()

        # 放大
        zoom_in_action = QAction("放大", self)
        zoom_in_action.triggered.connect(self.image_canvas.zoom_in)
        toolbar.addAction(zoom_in_action)

        # 缩小
        zoom_out_action = QAction("缩小", self)
        zoom_out_action.triggered.connect(self.image_canvas.zoom_out)
        toolbar.addAction(zoom_out_action)

        # 重置
        reset_action = QAction("重置", self)
        reset_action.triggered.connect(self.image_canvas.reset_view)
        toolbar.addAction(reset_action)

    def _init_statusbar(self):
        """初始化状态栏"""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)

        self.status_label = QLabel("就绪")
        self.statusbar.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.statusbar.addPermanentWidget(self.progress_bar)

    def _connect_signals(self):
        """连接信号"""
        # 字符列表信号
        self.char_list.char_selected.connect(self._on_char_selected)
        self.char_list.char_double_clicked.connect(self._on_char_double_clicked)

        # 图片画布信号
        self.image_canvas.selection_changed.connect(self._on_canvas_selection_changed)
        self.image_canvas.bbox_updated.connect(self._on_bbox_updated)

        # 属性面板信号
        self.property_panel.char_changed.connect(self._on_property_char_changed)
        self.property_panel.bbox_changed.connect(self._on_property_bbox_changed)

    def open_image(self):
        """打开图片"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片",
            "",
            "图片文件 (*.jpg *.jpeg *.png *.bmp);;所有文件 (*)"
        )

        if file_path:
            self._load_image(file_path)

    def _load_image(self, image_path: str):
        """加载图片（优先从缓存加载结果，不自动调用 API）"""
        self.current_image_path = image_path

        # 加载图片
        if not self.image_canvas.load_image(image_path):
            QMessageBox.warning(self, "错误", f"无法加载图片: {image_path}")
            return

        # 尝试从缓存加载
        if self._try_load_cache(image_path):
            return

        self.status_label.setText("已打开图片（未发现缓存），请点击“识别”")

    def _cache_result_path(self, image_path: str) -> Path:
        project_root = Path(__file__).parent.parent
        return project_root / "ocr_output" / Path(image_path).stem / "result.json"

    def _cache_chars_path(self, image_path: str) -> Path:
        project_root = Path(__file__).parent.parent
        return project_root / "ocr_output" / Path(image_path).stem / "chars.json"

    def _try_load_cache(self, image_path: str) -> bool:
        """尝试从 ocr_output 缓存加载"""
        cache_path = self._cache_result_path(image_path)
        if not cache_path.exists():
            return False

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            cached["_from_cache"] = True
            cached["_cache_path"] = str(cache_path)
            self._on_ocr_finished(cached)
            return True
        except Exception as e:
            self.status_label.setText(f"缓存加载失败：{e}；可点击“识别”重新生成")
            return False

    def recognize_image(self):
        """点击“识别”：强制调用在线 API 并刷新 result.json"""
        if not self.current_image_path:
            QMessageBox.information(self, "提示", "请先打开一张图片")
            return

        if self.ocr_worker and self.ocr_worker.isRunning():
            QMessageBox.information(self, "提示", "正在识别中，请稍候")
            return

        self.status_label.setText("正在识别（调用 API）...")
        self.ocr_worker = OCRWorker(self.current_image_path)
        self.ocr_worker.finished.connect(self._on_ocr_finished)
        self.ocr_worker.error.connect(self._on_ocr_error)
        self.ocr_worker.start()

    def _on_ocr_finished(self, result: dict):
        """OCR 完成"""
        # 加载字符项
        self.char_manager.load_from_ocr_result(result)
        self.char_list.load_items(self.char_manager.items)

        # 清除现有边界框
        self.image_canvas.clear_bboxes()

        # 添加边界框
        for item in self.char_manager.items:
            x, y, x2, y2 = item.bbox
            self.image_canvas.add_bbox(x, y, x2 - x, y2 - y, item.char, item.id)

        if result.get("_from_cache"):
            self.status_label.setText(
                f"已从缓存加载 {len(self.char_manager.items)} 个字符 ({result.get('_cache_path', '')})"
            )
            self._last_loaded_cache_path = result.get("_cache_path")
        else:
            self.status_label.setText(f"已识别并加载 {len(self.char_manager.items)} 个字符")
            self._last_loaded_cache_path = None

    def save_edits(self):
        """点击“保存”：将当前编辑结果写回现有 json（不写 result.json）"""
        if not self.current_image_path:
            QMessageBox.information(self, "提示", "请先打开一张图片")
            return

        if not self.char_manager.items:
            QMessageBox.information(self, "提示", "当前没有可保存的字符数据")
            return

        out_dir = Path(__file__).parent.parent / "ocr_output" / Path(self.current_image_path).stem
        out_dir.mkdir(parents=True, exist_ok=True)

        chars_path = out_dir / "chars.json"

        # 只更新 chars.json（现有 json），不改 result.json
        # chars.json 格式与 recognizer.py 保存的一致（简化版）
        char_data = []
        for r in sorted(self.char_manager.items, key=lambda x: x.global_index):
            char_data.append(
                {
                    "id": r.id,
                    "char": r.char,
                    "bbox": r.bbox,
                    "column": r.column,
                    "row": r.row,
                    "global_index": r.global_index,
                }
            )

        with open(chars_path, "w", encoding="utf-8") as f:
            json.dump(char_data, f, ensure_ascii=False, indent=2)

        QMessageBox.information(self, "保存完成", f"已保存编辑结果到：\n{chars_path}")

    def _on_ocr_error(self, error: str):
        """OCR 错误"""
        QMessageBox.warning(self, "OCR 错误", f"识别失败: {error}")
        self.status_label.setText("识别失败")

    def export_chars(self):
        """导出字符"""
        if not self.char_manager.items:
            QMessageBox.warning(self, "警告", "没有可导出的字符")
            return

        # 选择导出目录
        export_dir = QFileDialog.getExistingDirectory(
            self,
            "选择导出目录",
            ""
        )

        if export_dir:
            self._do_export(export_dir)

    def _do_export(self, export_dir: str):
        """执行导出"""
        import cv2

        # 获取原图
        image = self.image_canvas.get_cv_image()
        if image is None:
            QMessageBox.warning(self, "错误", "没有加载图片")
            return

        # 创建导出目录
        chars_dir = Path(export_dir) / "chars"
        chars_dir.mkdir(parents=True, exist_ok=True)

        # 裁剪并保存每个字符
        for item in self.char_manager.items:
            x1, y1, x2, y2 = [int(v) for v in item.bbox]

            # 边界检查
            h, w = image.shape[:2]
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(w, x2)
            y2 = min(h, y2)

            if x2 > x1 and y2 > y1:
                char_img = image[y1:y2, x1:x2]
                filename = f"{item.char}_{item.id}.jpg"
                filepath = chars_dir / filename
                cv2.imwrite(str(filepath), char_img)

        # 保存元数据
        metadata_path = Path(export_dir) / "chars.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(self.char_manager.to_export_format(), f, ensure_ascii=False, indent=2)

        QMessageBox.information(
            self,
            "导出完成",
            f"已导出 {len(self.char_manager.items)} 个字符到:\n{export_dir}"
        )

    def _on_char_selected(self, item_id: int):
        """字符列表选中"""
        self.image_canvas.select_bbox(item_id)

        item = self.char_manager.get_item(item_id)
        if item:
            self.property_panel.load_item(item)

    def _on_char_double_clicked(self, item_id: int):
        """字符列表双击"""
        # 聚焦到字符输入框
        self.property_panel.char_edit.setFocus()
        self.property_panel.char_edit.selectAll()

    def _on_canvas_selection_changed(self, item_id: int):
        """画布选中变化"""
        if item_id >= 0:
            self.char_list.select_item(item_id)
            item = self.char_manager.get_item(item_id)
            if item:
                self.property_panel.load_item(item)
        else:
            self.property_panel.load_item(None)

    def _on_bbox_updated(self, item_id: int, bbox: list):
        """边界框更新"""
        item = self.char_manager.get_item(item_id)
        if item:
            item.bbox = bbox

    def _on_property_char_changed(self, item_id: int, char: str):
        """属性面板字符变化"""
        item = self.char_manager.get_item(item_id)
        if item:
            item.char = char
            self.char_list.update_item_char(item_id, char)

            # 更新画布上的标签
            for bbox_item in self.image_canvas.bbox_items:
                if bbox_item.item_id == item_id:
                    bbox_item.update_char(char)
                    break

    def _on_property_bbox_changed(self, item_id: int, x: float, y: float, w: float, h: float):
        """属性面板边界框变化"""
        item = self.char_manager.get_item(item_id)
        if item:
            item.bbox = [x, y, x + w, y + h]

            # 更新画布上的边界框
            for bbox_item in self.image_canvas.bbox_items:
                if bbox_item.item_id == item_id:
                    bbox_item.update_bbox(x, y, w, h)
                    break

    def show_about(self):
        """显示关于对话框"""
        QMessageBox.about(
            self,
            "关于",
            "书法拆字编辑器 v1.0.0\n\n"
            "用于书法作品的文字识别和单字拆分编辑。\n\n"
            "功能:\n"
            "- 自动识别书法文字\n"
            "- 可视化编辑边界框\n"
            "- 导出单字图片"
        )

    def closeEvent(self, event):
        """关闭事件"""
        if self.ocr_worker and self.ocr_worker.isRunning():
            self.ocr_worker.terminate()
            self.ocr_worker.wait()
        event.accept()
