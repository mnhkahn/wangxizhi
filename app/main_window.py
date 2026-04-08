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
from PyQt5.QtGui import QIcon, QFont, QKeySequence
from PyQt5.QtWidgets import QUndoStack, QUndoCommand

from .widgets.image_canvas import ImageCanvas
from .widgets.char_list import CharListWidget
from .widgets.property_panel import PropertyPanel
from .widgets.work_tree import WorkTreeWidget
from .widgets.char_preview import CharPreviewWidget
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


class BatchOCRWorker(QThread):
    """批量 OCR 线程"""

    progress = pyqtSignal(int, int, str, bool, str)  # idx, total, image_path, ok, message
    finished = pyqtSignal(int, int, int)  # total, ok_count, fail_count
    error = pyqtSignal(str)

    def __init__(self, image_paths: List[str], parent=None):
        super().__init__(parent)
        self.image_paths = image_paths

    def run(self):
        try:
            # 与 OCRWorker 一致，确保能 import 到项目根
            import sys
            project_root = Path(__file__).parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))

            from ocr import CalligraphyOCR

            ocr = CalligraphyOCR()
            total = len(self.image_paths)
            ok_count = 0
            fail_count = 0

            for i, path in enumerate(self.image_paths, start=1):
                try:
                    ocr.recognize_image(path, save_result=True, debug=False)
                    ok_count += 1
                    self.progress.emit(i, total, path, True, "")
                except Exception as e:
                    fail_count += 1
                    self.progress.emit(i, total, path, False, str(e)[:120])

            self.finished.emit(total, ok_count, fail_count)
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
        self._current_tree_selection: Optional[dict] = None

        # 撤销栈（用于框拖拽/缩放等编辑）
        self.undo_stack = QUndoStack(self)

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
        self.main_splitter = splitter

        # 最左侧：字帖/已识别树
        self.work_tree = WorkTreeWidget(project_root=Path(__file__).parent.parent)
        self.work_tree.setMinimumWidth(220)
        self.work_tree.setMaximumWidth(360)
        splitter.addWidget(self.work_tree)

        # 左侧：字符列表
        self.char_list = CharListWidget()
        # 缩小一半：尽量让出空间给图片
        self.char_list.setMinimumWidth(120)
        self.char_list.setMaximumWidth(160)
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

        # 右侧下方：图片编辑区 + 预览框
        right_splitter = QSplitter(Qt.Horizontal)
        right_splitter.setChildrenCollapsible(False)

        self.image_canvas = ImageCanvas()
        right_splitter.addWidget(self.image_canvas)

        self.char_preview = CharPreviewWidget()
        self.char_preview.setMinimumWidth(220)
        self.char_preview.setMaximumWidth(420)
        right_splitter.addWidget(self.char_preview)

        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 1)
        right_splitter.setSizes([900, 300])

        right_layout.addWidget(right_splitter, 1)

        splitter.addWidget(right_widget)

        # 设置分割比例：尽量把空间让给图片
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([280, 160, 960])

        main_layout.addWidget(splitter, 1)

    def _init_menu(self):
        """初始化菜单"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")

        self.action_recognize = QAction("识别(&R)", self)
        self.action_recognize.setShortcut(QKeySequence.Refresh)
        self.action_recognize.triggered.connect(self.recognize_image)
        file_menu.addAction(self.action_recognize)

        self.action_save = QAction("保存编辑(&S)", self)
        # macOS 下会自动映射为 Cmd+S
        self.action_save.setShortcut(QKeySequence.Save)
        self.action_save.triggered.connect(self.save_edits)
        file_menu.addAction(self.action_save)

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

        self.action_undo = self.undo_stack.createUndoAction(self, "撤销(&U)")
        self.action_undo.setShortcut(QKeySequence.Undo)
        edit_menu.addAction(self.action_undo)

        self.action_redo = self.undo_stack.createRedoAction(self, "重做(&R)")
        self.action_redo.setShortcut(QKeySequence.Redo)
        edit_menu.addAction(self.action_redo)

        edit_menu.addSeparator()

        delete_action = QAction("删除(&D)", self)
        delete_action.setShortcut("Delete")
        edit_menu.addAction(delete_action)

        # 视图菜单（保留占位，避免后续扩展时找不到菜单）
        menubar.addMenu("视图(&V)")

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _init_toolbar(self):
        """初始化工具栏"""
        toolbar = self.addToolBar("主工具栏")
        toolbar.setMovable(False)

        # 识别（强制调用 API 并刷新结果）
        toolbar.addAction(self.action_recognize)

        # 保存编辑（写回现有 json，不写 result.json）
        toolbar.addAction(self.action_save)

        # 导出
        export_action = QAction("导出", self)
        export_action.triggered.connect(self.export_chars)
        toolbar.addAction(export_action)

        # 说明：放大/缩小/重置按钮已移除（画布缩放使用 Ctrl+滚轮）

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
        # 字帖树信号
        self.work_tree.item_activated.connect(self._on_tree_item_activated)
        self.work_tree.visibility_changed.connect(self._on_work_tree_visibility_changed)

        # 字符列表信号
        self.char_list.char_selected.connect(self._on_char_selected)
        self.char_list.char_double_clicked.connect(self._on_char_double_clicked)

        # 图片画布信号
        self.image_canvas.selection_changed.connect(self._on_canvas_selection_changed)
        self.image_canvas.bbox_updated.connect(self._on_bbox_updated)
        self.image_canvas.bbox_edit_committed.connect(self._on_bbox_edit_committed)

        # 属性面板信号
        self.property_panel.char_changed.connect(self._on_property_char_changed)
        self.property_panel.bbox_changed.connect(self._on_property_bbox_changed)

    def open_image(self):
        """打开图片"""
        # 已移除“打开”入口：请从左侧字帖树选择图片
        QMessageBox.information(self, "提示", "请从左侧字帖树选择图片")
        return

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

        # 在字帖树中高亮当前图片（不折叠树）
        if hasattr(self, "work_tree"):
            self.work_tree.select_image(image_path)

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
        """尝试从 ocr_output 缓存加载

        优先级：
        1) chars.json（用户编辑后的结果）
        2) result.json（OCR 原始结果）
        """

        project_root = Path(__file__).parent.parent

        # 1) 优先 chars.json
        chars_path = self._cache_chars_path(image_path)
        if chars_path.exists():
            try:
                with open(chars_path, "r", encoding="utf-8") as f:
                    chars = json.load(f)
                if not isinstance(chars, list):
                    raise ValueError("chars.json 不是数组")

                # 构造一个最小的 result dict 复用现有渲染/加载逻辑
                # char_results 字段沿用 recognizer 输出结构
                char_results = []
                for i, c in enumerate(chars):
                    if not isinstance(c, dict):
                        continue
                    char_results.append(
                        {
                            "id": c.get("id", i),
                            "char": c.get("char", ""),
                            "bbox": c.get("bbox", [0, 0, 0, 0]),
                            "column": c.get("column", 0),
                            "row": c.get("row", 0),
                            "global_index": c.get("global_index", i),
                        }
                    )

                # recognized_text：按 global_index 拼接
                char_results_sorted = sorted(char_results, key=lambda x: x.get("global_index", 0))
                recognized_text = "".join([x.get("char", "") for x in char_results_sorted])
                total_chars = len(char_results_sorted)
                column_count = 0
                if total_chars:
                    try:
                        column_count = max([int(x.get("column", 0)) for x in char_results_sorted]) + 1
                    except Exception:
                        column_count = 0

                # image_path 尽量写成相对路径（与原 result.json 一致）
                try:
                    rel = str(Path(image_path).resolve().relative_to(project_root.resolve()))
                except Exception:
                    rel = str(Path(image_path))

                cached = {
                    "image_path": rel,
                    "char_results": char_results_sorted,
                    "recognized_text": recognized_text,
                    "total_chars": total_chars,
                    "column_count": column_count,
                    "_from_cache": True,
                    "_cache_path": str(chars_path),
                    "_cache_kind": "chars.json",
                }
                self._on_ocr_finished(cached)
                return True
            except Exception as e:
                self.status_label.setText(f"chars.json 缓存加载失败：{e}；将尝试加载 result.json")

        # 2) 回退 result.json
        cache_path = self._cache_result_path(image_path)
        if not cache_path.exists():
            return False

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            cached["_from_cache"] = True
            cached["_cache_path"] = str(cache_path)
            cached["_cache_kind"] = "result.json"
            self._on_ocr_finished(cached)
            return True
        except Exception as e:
            self.status_label.setText(f"缓存加载失败：{e}；可点击“识别”重新生成")
            return False

    def recognize_image(self):
        """点击“识别”：
        - 若当前选中的是字帖目录：批量识别该目录下所有 fatie-*.jpg
        - 若当前选中的是图片：识别当前图片
        """

        if hasattr(self, "batch_worker") and self.batch_worker and self.batch_worker.isRunning():
            self.status_label.setText("正在批量识别中，请稍候")
            return
        if self.ocr_worker and self.ocr_worker.isRunning():
            self.status_label.setText("正在识别中，请稍候")
            return

        sel = self._current_tree_selection or {}
        kind = sel.get("kind")

        if kind == "work_dir":
            dir_path = sel.get("dir_path") or ""
            if not dir_path:
                self.status_label.setText("识别失败：未获取到字帖目录")
                return
            self._recognize_work_dir(dir_path)
            return

        # 默认：识别当前图片（或树中选中的图片）
        image_path = sel.get("image_path") if kind in ("work_image", "recognized") else None
        if not image_path:
            image_path = self.current_image_path
        if not image_path:
            self.status_label.setText("识别失败：请先从左侧字帖树选择字帖或图片")
            return

        self.status_label.setText("正在识别（调用 API）...")
        self.ocr_worker = OCRWorker(image_path)
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

        # 刷新左侧“已识别”列表
        if hasattr(self, "work_tree"):
            self.work_tree.refresh_recognized()

    def _on_tree_item_activated(self, payload: dict):
        """点击左侧树节点快速加载"""
        self._current_tree_selection = payload

        kind = payload.get("kind")
        if kind == "work_dir":
            # 仅记录选择，不加载图片
            dir_path = payload.get("dir_path") or ""
            self.status_label.setText(f"已选中字帖：{Path(dir_path).name}（点击“识别”可批量识别）")
            return

        image_path = payload.get("image_path") or ""
        if not image_path:
            return
        if not Path(image_path).exists():
            QMessageBox.warning(self, "错误", f"文件不存在: {image_path}")
            return
        self._load_image(image_path)

    def _recognize_work_dir(self, dir_path: str):
        """批量识别字帖目录"""
        from pathlib import Path

        wd = Path(dir_path)
        if not wd.exists() or not wd.is_dir():
            self.status_label.setText(f"识别失败：目录不存在 {dir_path}")
            return

        images = sorted(wd.glob("fatie-*.jpg"), key=lambda p: p.name)
        if not images:
            self.status_label.setText("识别失败：目录下未找到 fatie-*.jpg")
            return

        # 线程内会写 result.json 缓存
        self.status_label.setText(f"开始批量识别：{wd.name}（{len(images)} 张）")

        self.batch_worker = BatchOCRWorker([str(p) for p in images])
        self.batch_worker.progress.connect(self._on_batch_progress)
        self.batch_worker.finished.connect(self._on_batch_finished)
        self.batch_worker.error.connect(self._on_batch_error)
        self.batch_worker.start()

    def _on_batch_progress(self, idx: int, total: int, image_path: str, ok: bool, message: str):
        name = Path(image_path).name
        status = "OK" if ok else "FAIL"
        self.status_label.setText(f"批量识别 {idx}/{total} {status}: {name} {message}")

    def _on_batch_finished(self, total: int, ok_count: int, fail_count: int):
        self.status_label.setText(f"批量识别完成：成功 {ok_count}，失败 {fail_count}，共 {total}")
        if hasattr(self, "work_tree"):
            self.work_tree.refresh_recognized()

    def _on_batch_error(self, error: str):
        self.status_label.setText(f"批量识别异常：{error}")

    def save_edits(self):
        """点击“保存”：将当前编辑结果写回现有 json（不写 result.json）"""
        if not self.current_image_path:
            self.status_label.setText("保存失败：请先打开一张图片")
            return

        if not self.char_manager.items:
            self.status_label.setText("保存失败：当前没有可保存的字符数据")
            return

        project_root = Path(__file__).parent.parent
        out_dir = project_root / "ocr_output" / Path(self.current_image_path).stem
        out_dir.mkdir(parents=True, exist_ok=True)

        chars_path = out_dir / "chars.json"

        # 只更新 chars.json（现有 json），不改 result.json
        # chars.json 格式与 recognizer.py 保存的一致（简化版）
        image_path = Path(self.current_image_path)
        # work_name：字帖目录名
        try:
            work_name = image_path.parent.name
        except Exception:
            work_name = ""
        image_name = image_path.name

        def _make_id(item: CharItem) -> str:
            # 字帖名称_图片名称_行_列_字
            # 注意：这里 row/column 使用 UI/后处理后的值（从 0 开始）
            return f"{work_name}_{image_name}_{item.row}_{item.column}_{item.char}"

        char_data = []
        for r in sorted(self.char_manager.items, key=lambda x: x.global_index):
            char_data.append(
                {
                    "id": _make_id(r),
                    "char": r.char,
                    "bbox": r.bbox,
                    "column": r.column,
                    "row": r.row,
                    "global_index": r.global_index,
                }
            )

        with open(chars_path, "w", encoding="utf-8") as f:
            json.dump(char_data, f, ensure_ascii=False, indent=2)

        self.status_label.setText(f"已保存到 {chars_path}")

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
            self._update_preview(item)

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
                self._update_preview(item)
        else:
            self.property_panel.load_item(None)
            if hasattr(self, "char_preview"):
                self.char_preview.clear()

    def _on_bbox_updated(self, item_id: int, bbox: list):
        """边界框更新"""
        item = self.char_manager.get_item(item_id)
        if item:
            item.bbox = bbox
            self._update_preview(item)

            # 若当前属性面板正在显示该 item，同步更新数值（不触发信号）
            if self.property_panel.current_item and self.property_panel.current_item.id == item_id:
                self.property_panel.update_from_item(item)

    def _apply_bbox(self, item_id: int, bbox: list):
        """将 bbox 应用到模型 + 画布 + 面板"""
        item = self.char_manager.get_item(item_id)
        if not item:
            return
        item.bbox = bbox

        # 更新画布
        x1, y1, x2, y2 = bbox
        for bbox_item in self.image_canvas.bbox_items:
            if bbox_item.item_id == item_id:
                bbox_item.update_bbox(float(x1), float(y1), float(x2 - x1), float(y2 - y1))
                break

        # 更新属性面板（不触发信号）
        self.property_panel.update_from_item(item)
        self._update_preview(item)

    def _on_bbox_edit_committed(self, item_id: int, old_bbox: list, new_bbox: list):
        """画布提交 bbox 变更：推入撤销栈"""

        class BBoxChangeCommand(QUndoCommand):
            def __init__(self, mw: "MainWindow", _item_id: int, _old: list, _new: list):
                super().__init__("调整框")
                self.mw = mw
                self.item_id = _item_id
                self.old = _old
                self.new = _new

            def undo(self):
                self.mw._apply_bbox(self.item_id, self.old)

            def redo(self):
                self.mw._apply_bbox(self.item_id, self.new)

        self.undo_stack.push(BBoxChangeCommand(self, item_id, old_bbox, new_bbox))

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

            self._update_preview(item)

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

            self._update_preview(item)

    def _update_preview(self, item: CharItem):
        if not hasattr(self, "char_preview"):
            return
        img = self.image_canvas.get_cv_image()
        meta = f"id: {item.id} | 列{item.column} 行{item.row} | idx {item.global_index}"
        self.char_preview.update_preview(img, item.char, item.bbox, meta=meta)

    def _on_work_tree_visibility_changed(self, visible: bool):
        """字帖树折叠/展开后，调整 splitter 空间"""
        if not hasattr(self, "main_splitter"):
            return
        # 折叠时把左侧宽度压到最小，让空间给右侧
        if not visible:
            self.main_splitter.setSizes([44, 160, 1200])
        else:
            self.main_splitter.setSizes([280, 160, 960])

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
