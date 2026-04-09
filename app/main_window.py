"""
主窗口
"""

import os
import json
from typing import Optional, List
from pathlib import Path
import uuid
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
    QLineEdit,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QIcon, QFont, QKeySequence
from PyQt5.QtWidgets import QStyle
from PyQt5.QtWidgets import QUndoStack, QUndoCommand

from .widgets.image_canvas import ImageCanvas
from .widgets.char_list import CharListWidget
from .widgets.property_panel import PropertyPanel
from .widgets.work_tree import WorkTreeWidget
from .widgets.char_preview import CharPreviewWidget
from .models.char_item import CharItem, CharItemManager


def export_glyphs_to_sqlite(sqlite_path: Path, items: list) -> int:
    """导出字形数据到 SQLite（线程安全：纯文件/DB 操作，不触碰 UI）。"""

    import sqlite3

    conn = sqlite3.connect(str(sqlite_path))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS "glyphs" (
                id TEXT PRIMARY KEY,
                char TEXT,
                work_dir TEXT,
                author TEXT,
                font TEXT,
                work_title TEXT
            )
        """
        )
        conn.commit()

        total = 0
        batch = []

        for item in items:
            if not isinstance(item, dict):
                continue
            gid = item.get("id")
            ch = item.get("char")
            work_dir = item.get("work_dir", "")
            author = item.get("author", "")
            font = item.get("font", "")
            work_title = item.get("work", "") or item.get("work_title", "")

            if not gid or not ch:
                continue

            batch.append(
                (
                    str(gid),
                    str(ch),
                    str(work_dir),
                    str(author),
                    str(font),
                    str(work_title),
                )
            )
            total += 1

            if len(batch) >= 2000:
                cur.executemany(
                    "INSERT OR REPLACE INTO glyphs (id, char, work_dir, author, font, work_title) VALUES (?,?,?,?,?,?)",
                    batch,
                )
                conn.commit()
                batch.clear()

        if batch:
            cur.executemany(
                "INSERT OR REPLACE INTO glyphs (id, char, work_dir, author, font, work_title) VALUES (?,?,?,?,?,?)",
                batch,
            )
            conn.commit()

        return total
    finally:
        conn.close()


def export_all_glyphs_sqlite(project_root: Path, progress_cb=None):
    """扫描所有字帖的 chars.json 并生成全量 glyphs.sqlite。

    progress_cb(done:int, total:int, message:str) 可选。
    """

    ocr_output = project_root / "ocr_output"
    ocr_output.mkdir(parents=True, exist_ok=True)

    sqlite_path = ocr_output / "glyphs.sqlite"

    chars_paths = []
    for work_dir in sorted([p for p in project_root.iterdir() if p.is_dir()], key=lambda p: p.name):
        debug_dir = work_dir / ".debug"
        if not debug_dir.exists():
            continue
        chars_paths.extend(sorted(debug_dir.glob("*/chars.json"), key=lambda p: str(p)))

    all_items = []
    total_files = len(chars_paths)
    for i, chars_path in enumerate(chars_paths, start=1):
        if callable(progress_cb):
            progress_cb(i, total_files, f"导出 SQLite：扫描 {i}/{total_files} {chars_path}")

        work_dir = chars_path.parent.parent.parent
        try:
            with open(chars_path, "r", encoding="utf-8") as f:
                chars = json.load(f)
        except Exception:
            continue

        if not isinstance(chars, list):
            continue

        for rec in chars:
            if not isinstance(rec, dict):
                continue
            if "work_dir" not in rec:
                rec["work_dir"] = work_dir.name
            all_items.append(rec)

    total = export_glyphs_to_sqlite(sqlite_path, all_items)
    return str(sqlite_path), total


def export_all_crops(project_root: Path, progress_cb=None):
    """扫描所有字帖的 chars.json 并裁剪导出 webp 到 <字帖目录>/words/。

    progress_cb(done:int, total:int, message:str) 可选。
    """

    import cv2
    import re

    def _sanitize_filename(name: str) -> str:
        # 保留中文/字母数字/下划线/短横线/点，其余替换为 '_'
        name = name.strip().replace(" ", "_")
        name = re.sub(r"[^0-9A-Za-z_\-\.\u4e00-\u9fff]+", "_", name)
        return name[:180] if len(name) > 180 else name

    tasks = []
    for work_dir in sorted([p for p in project_root.iterdir() if p.is_dir()], key=lambda p: p.name):
        debug_dir = work_dir / ".debug"
        if not debug_dir.exists():
            continue
        for chars_path in sorted(debug_dir.glob("*/chars.json"), key=lambda p: str(p)):
            stem = chars_path.parent.name
            image_abs = None
            for ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
                cand = work_dir / f"{stem}{ext}"
                if cand.exists():
                    image_abs = cand
                    break
            if image_abs is None:
                continue
            tasks.append((work_dir, stem, chars_path, image_abs))

    # 预统计总数（只统计 bbox 合法的记录，便于进度条准确）
    total = 0
    for work_dir, stem, chars_path, image_abs in tasks:
        try:
            with open(chars_path, "r", encoding="utf-8") as f:
                chars = json.load(f)
        except Exception:
            continue
        if not isinstance(chars, list):
            continue
        for rec in chars:
            if not isinstance(rec, dict):
                continue
            bbox = rec.get("bbox")
            if bbox and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                total += 1

    done = 0
    ok = 0
    fail = 0

    for work_dir, stem, chars_path, image_abs in tasks:
        try:
            with open(chars_path, "r", encoding="utf-8") as f:
                chars = json.load(f)
        except Exception:
            continue
        if not isinstance(chars, list):
            continue

        img = cv2.imread(str(image_abs))
        if img is None:
            continue

        h, w = img.shape[:2]
        out_dir = image_abs.parent / "words"
        out_dir.mkdir(parents=True, exist_ok=True)

        for rec in chars:
            if not isinstance(rec, dict):
                continue
            bbox = rec.get("bbox")
            ch = rec.get("char", "")
            rid = rec.get("id", "")
            row = rec.get("row", 0)
            col = rec.get("column", 0)

            if not bbox or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue

            done += 1
            try:
                x1, y1, x2, y2 = [int(float(v)) for v in bbox]
                x1 = max(0, min(w - 1, x1))
                y1 = max(0, min(h - 1, y1))
                x2 = max(0, min(w, x2))
                y2 = max(0, min(h, y2))
                if x2 <= x1 or y2 <= y1:
                    fail += 1
                    if callable(progress_cb):
                        progress_cb(done, total, f"导出图片 {done}/{total} [FAIL] {work_dir.name}/{stem} bbox 无效")
                    continue

                crop = img[y1:y2, x1:x2]
                base = str(rid) if rid else f"{row}_{col}_{ch}"
                filename = _sanitize_filename(base) + ".webp"
                out_path = out_dir / filename

                # 若存在同名文件，直接覆盖
                cv2.imwrite(str(out_path), crop, [cv2.IMWRITE_WEBP_QUALITY, 95])
                ok += 1
                if callable(progress_cb):
                    progress_cb(done, total, f"导出图片 {done}/{total} [OK] {work_dir.name}/words/{filename}")
            except Exception as e:
                fail += 1
                if callable(progress_cb):
                    progress_cb(done, total, f"导出图片 {done}/{total} [FAIL] {work_dir.name}/{stem} {str(e)[:120]}")

    return total, ok, fail


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
            # 识别后保存到 <字帖目录>/.debug/<stem>/{result.json,chars.json}
            result = ocr.recognize_image(
                self.image_path, save_result=True, debug=False, crop_chars=False
            )
            result["_from_cache"] = False
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class BatchOCRWorker(QThread):
    """批量 OCR 线程"""

    progress = pyqtSignal(
        int, int, str, bool, str
    )  # idx, total, image_path, ok, message
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
                    # 仅生成 result.json/chars.json
                    ocr.recognize_image(
                        path, save_result=True, debug=False, crop_chars=False
                    )
                    ok_count += 1
                    self.progress.emit(i, total, path, True, "")
                except Exception as e:
                    fail_count += 1
                    self.progress.emit(i, total, path, False, str(e)[:120])

            self.finished.emit(total, ok_count, fail_count)
        except Exception as e:
            self.error.emit(str(e))


class UploadWebPWorker(QThread):
    """批量上传 WebP（后台线程）"""

    progress = pyqtSignal(int, int, str, bool, str)  # idx, total, rel_path, ok, message
    finished = pyqtSignal(int, int, int, str)  # total, ok_count, fail_count, table_text
    error = pyqtSignal(str)

    def __init__(
        self,
        scan_root: str,
        cloud_name: str,
        api_key: str,
        api_secret: str,
        upload_preset: str,
        unsigned: bool,
        remote_folder: str,
        limit: int = 0,
        concurrency: int = 4,
        mock_upload: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.scan_root = scan_root
        self.cloud_name = cloud_name
        self.api_key = api_key
        self.api_secret = api_secret
        self.upload_preset = upload_preset
        self.unsigned = unsigned
        self.remote_folder = remote_folder
        self.limit = int(limit or 0)
        self.concurrency = int(concurrency or 4)
        self.mock_upload = bool(mock_upload)

    def run(self):
        try:
            import sys

            project_root = Path(__file__).parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))

            from upload_webp_cloudinary import collect_upload_items, upload_items

            root = Path(self.scan_root).expanduser().resolve()
            items = collect_upload_items(root, limit=0, keep_dirs=False)
            # 尽量只上传导出产物：*/words/*.webp
            items = [it for it in items if "/words/" in ("/" + it.rel_path.replace("\\", "/") + "/")]
            if self.limit and self.limit > 0:
                items = items[: self.limit]

            if not items:
                self.finished.emit(0, 0, 0, "")
                return

            # 进度回调
            results_holder = {"ok": 0, "fail": 0}

            def _cb(idx: int, total: int, item, result):
                if result.ok:
                    results_holder["ok"] += 1
                    ok = True
                    msg = result.url
                else:
                    results_holder["fail"] += 1
                    ok = False
                    msg = result.error
                self.progress.emit(idx, total, result.rel_path, ok, msg)

            results = upload_items(
                items=items,
                cloud_name=str(self.cloud_name),
                api_key=str(self.api_key),
                api_secret=str(self.api_secret),
                unsigned=bool(self.unsigned),
                upload_preset=str(self.upload_preset),
                folder=str(self.remote_folder or ""),
                timeout_s=600,
                concurrency=int(self.concurrency or 4),
                mock_upload=bool(self.mock_upload),
                progress_cb=_cb,
            )

            # 生成 summary 表格（纯文本）
            headers = ["#", "状态", "public_id", "文件", "URL(截断)", "错误(截断)"]
            rows = []
            for i, r in enumerate(results, start=1):
                rows.append(
                    [
                        str(i),
                        "OK" if r.ok else "FAIL",
                        str(r.public_id),
                        str(r.rel_path),
                        (r.url or "")[:120],
                        (r.error or "")[:120],
                    ]
                )

            # 本地实现一个简单等宽表格
            all_rows = [headers] + rows
            widths = [max(len(rr[i]) for rr in all_rows) for i in range(len(headers))]

            def _fmt(rr):
                return " | ".join(rr[i].ljust(widths[i]) for i in range(len(headers)))

            sep = "-+-".join("-" * w for w in widths)
            table = "\n".join([_fmt(headers), sep] + [_fmt(r) for r in rows])

            total = len(results)
            ok_cnt = sum(1 for r in results if r.ok)
            fail_cnt = total - ok_cnt
            self.finished.emit(total, ok_cnt, fail_cnt, table)
        except Exception as e:
            self.error.emit(str(e))


class ExportAllWorker(QThread):
    """全量导出（后台线程）：生成 glyphs.sqlite + 导出裁剪 webp。"""

    progress = pyqtSignal(int, int, str)  # done, total, message
    finished = pyqtSignal(str, int, int, int, int)  # sqlite_path, sqlite_total, crop_total, crop_ok, crop_fail
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            project_root = Path(__file__).parent.parent

            # 1) SQLite：先扫描（进度不一定准确，主要用于状态提示）
            self.progress.emit(0, 0, "正在导出 SQLite...")

            def _sqlite_cb(done: int, total: int, msg: str):
                # SQLite 阶段：不占用进度条，避免和图片导出混淆
                self.progress.emit(0, 0, msg)

            sqlite_path, sqlite_total = export_all_glyphs_sqlite(project_root, progress_cb=_sqlite_cb)

            # 2) 裁剪导出：使用可计数进度
            def _crop_cb(done: int, total: int, msg: str):
                self.progress.emit(int(done), int(total), str(msg))

            crop_total, crop_ok, crop_fail = export_all_crops(project_root, progress_cb=_crop_cb)

            self.finished.emit(str(sqlite_path), int(sqlite_total), int(crop_total), int(crop_ok), int(crop_fail))
        except Exception as e:
            self.error.emit(str(e))


class CharSearchWorker(QThread):
    """在所有 chars.json 中搜索单字并定位到对应原图（后台线程）。"""

    progress = pyqtSignal(int, int, str)  # idx, total, message
    found = pyqtSignal(str, str, str)  # image_path, chars_path, query_char
    not_found = pyqtSignal(str)  # query
    error = pyqtSignal(str)

    def __init__(self, query_char: str, parent=None):
        super().__init__(parent)
        self.query_char = (query_char or "").strip()[:1]

    def run(self):
        try:
            q = self.query_char
            if not q:
                self.not_found.emit("")
                return

            project_root = Path(__file__).parent.parent
            chars_paths = []
            for work_dir in sorted(
                [p for p in project_root.iterdir() if p.is_dir()], key=lambda p: p.name
            ):
                debug_dir = work_dir / ".debug"
                if not debug_dir.exists():
                    continue
                chars_paths.extend(sorted(debug_dir.glob("*/chars.json"), key=lambda p: str(p)))

            total = len(chars_paths)
            for i, chars_path in enumerate(chars_paths, start=1):
                if self.isInterruptionRequested():
                    return

                if i == 1 or i % 25 == 0:
                    self.progress.emit(i, total, f"搜索 {i}/{total} {chars_path}")

                try:
                    with open(chars_path, "r", encoding="utf-8") as f:
                        chars = json.load(f)
                except Exception:
                    continue
                if not isinstance(chars, list):
                    continue

                hit = False
                for rec in chars:
                    if not isinstance(rec, dict):
                        continue
                    if str(rec.get("char", "")) == q:
                        hit = True
                        break
                if not hit:
                    continue

                # chars.json 位于：<字帖目录>/.debug/<stem>/chars.json
                stem = chars_path.parent.name
                work_dir = chars_path.parent.parent.parent
                image_abs = None
                for ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
                    cand = work_dir / f"{stem}{ext}"
                    if cand.exists():
                        image_abs = cand
                        break

                if image_abs is not None:
                    self.found.emit(str(image_abs), str(chars_path), q)
                    return

            self.not_found.emit(q)
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

        # 每张图片一个：字体/作者
        self.current_font: str = "楷书"
        self.current_author: str = ""
        self.current_work: str = ""

        # 撤销栈（用于框拖拽/缩放等编辑）
        self.undo_stack = QUndoStack(self)

        self._init_ui()
        self._init_menu()
        self._init_toolbar()
        self._init_statusbar()
        self._connect_signals()

    def _inject_meta_defaults_from_folder(self, folder_name: str):
        """从字帖文件夹名推导 author/font/work 的默认值。

        支持格式：
        - 作者-字体-作品  (如：王羲之-行书-圣教序)
        - 作者-作品
        """
        if not folder_name or "-" not in folder_name:
            return

        parts = [p.strip() for p in folder_name.split("-") if p.strip()]
        if len(parts) < 2:
            return

        font_candidates = {"楷书", "行书", "草书", "篆书", "隶书"}

        if not self.current_author:
            self.current_author = parts[0]

        if parts[1] in font_candidates:
            # 仅当用户没主动改过字体时再注入
            if not self.current_font or self.current_font == "楷书":
                self.current_font = parts[1]
            if len(parts) >= 3 and not self.current_work:
                self.current_work = "-".join(parts[2:])
        else:
            if not self.current_work:
                self.current_work = "-".join(parts[1:])

    def _init_ui(self):
        """初始化 UI"""
        self.setWindowTitle("书法拆字编辑器")
        # macOS 下某些情况下 setGeometry 会被 Qt 重新计算覆盖，
        # 这里用 resize + setMinimumSize 保证窗口不会“缩成很小”。
        self.resize(1400, 900)
        self.setMinimumSize(1100, 700)

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

        # 右侧下方：图片编辑区 + 预览列（操作栏在预览上方）
        right_splitter = QSplitter(Qt.Horizontal)
        right_splitter.setChildrenCollapsible(False)

        self.image_canvas = ImageCanvas()
        right_splitter.addWidget(self.image_canvas)

        # 预览列：上方操作栏（字~H），下方预览
        preview_col = QWidget()
        preview_col_layout = QVBoxLayout(preview_col)
        preview_col_layout.setContentsMargins(0, 0, 0, 0)
        preview_col_layout.setSpacing(6)

        self.property_panel = PropertyPanel()
        # 操作栏每项一行（字体、作者、字、X、Y、W、H）
        self.property_panel.setMinimumHeight(240)
        self.property_panel.setMaximumHeight(320)
        preview_col_layout.addWidget(self.property_panel, 0)

        self.char_preview = CharPreviewWidget()
        preview_col_layout.addWidget(self.char_preview, 1)

        # 预览列宽度减半
        preview_col.setFixedWidth(180)
        right_splitter.addWidget(preview_col)

        right_splitter.setStretchFactor(0, 1)
        right_splitter.setStretchFactor(1, 0)
        right_splitter.setSizes([1280, 180])

        right_layout.addWidget(right_splitter, 1)

        splitter.addWidget(right_widget)

        # 设置分割比例：尽量把空间让给图片
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setChildrenCollapsible(False)
        # 默认隐藏字符列表
        self.char_list.setVisible(False)
        splitter.setSizes([280, 0, 1200])

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
        self.action_export_menu = export_action

        upload_action = QAction("上传(&U)", self)
        upload_action.setShortcut("Ctrl+U")
        upload_action.triggered.connect(self.upload_exported_webps)
        file_menu.addAction(upload_action)

        # 便于在运行时启用/禁用
        self.action_upload_menu = upload_action

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

        # 字帖最小化按钮（放在“识别”左侧）
        self.action_toggle_worktree = QAction(self)
        # 用目录图标区分
        self.action_toggle_worktree.setIcon(
            self.style().standardIcon(QStyle.SP_DirIcon)
        )
        self.action_toggle_worktree.setToolTip("折叠/展开字帖")
        self.action_toggle_worktree.setCheckable(True)
        self.action_toggle_worktree.setChecked(False)  # 默认不折叠
        self.action_toggle_worktree.toggled.connect(
            lambda checked: self.work_tree.set_collapsed(checked)
        )
        toolbar.addAction(self.action_toggle_worktree)

        # 字符列表最小化按钮（放在字帖按钮右边）
        self.action_toggle_charlist = QAction(self)
        # 用列表视图图标区分
        self.action_toggle_charlist.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        )
        self.action_toggle_charlist.setToolTip("显示/隐藏字符列表")
        self.action_toggle_charlist.setCheckable(True)
        self.action_toggle_charlist.setChecked(True)  # checked 表示隐藏（默认不展示）
        self.action_toggle_charlist.toggled.connect(self._toggle_char_list)
        toolbar.addAction(self.action_toggle_charlist)

        # 识别（强制调用 API 并刷新结果）
        toolbar.addAction(self.action_recognize)

        # 保存编辑（写回现有 json，不写 result.json）
        toolbar.addAction(self.action_save)

        # 导出
        export_action = QAction("导出", self)
        export_action.triggered.connect(self.export_chars)
        toolbar.addAction(export_action)
        self.action_export_toolbar = export_action

        # 上传（导出产物 webp）
        upload_action = QAction("上传", self)
        upload_action.triggered.connect(self.upload_exported_webps)
        toolbar.addAction(upload_action)

        self.action_upload_toolbar = upload_action

        # 搜索框（单字）：放在最右侧（上传按钮右边）
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜字：输入单字回车")
        self.search_edit.setFixedWidth(140)
        self.search_edit.returnPressed.connect(self.search_char)
        toolbar.addWidget(self.search_edit)

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

        self.upload_worker = None
        self.export_worker = None
        self.search_worker = None

    def _set_export_actions_enabled(self, enabled: bool) -> None:
        for a in [
            getattr(self, "action_export_menu", None),
            getattr(self, "action_export_toolbar", None),
        ]:
            if a is not None:
                try:
                    a.setEnabled(bool(enabled))
                except Exception:
                    pass

    def _set_upload_actions_enabled(self, enabled: bool) -> None:
        for a in [
            getattr(self, "action_upload_menu", None),
            getattr(self, "action_upload_toolbar", None),
        ]:
            if a is not None:
                try:
                    a.setEnabled(bool(enabled))
                except Exception:
                    pass

    def _resolve_upload_scan_root(self) -> str:
        """根据当前选择，决定扫描上传的根目录。"""

        sel = self._current_tree_selection or {}
        kind = sel.get("kind")
        if kind == "work_dir":
            dir_path = sel.get("dir_path") or ""
            if dir_path:
                return dir_path
        if kind in ("work_image", "recognized"):
            image_path = sel.get("image_path") or ""
            if image_path:
                return str(Path(image_path).parent)
        # 默认：项目根目录
        return str(Path(__file__).parent.parent)

    def _read_upload_config_from_env(self):
        """从环境变量（.env 已在 run_app.py 加载）读取上传配置。"""

        # 兼容用户描述的命名：appkey/token/remote-folder
        cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip() or os.environ.get(
            "CLOUD_NAME", ""
        ).strip()
        api_key = os.environ.get("CLOUDINARY_API_KEY", "").strip() or os.environ.get(
            "APPKEY", ""
        ).strip()
        api_secret = os.environ.get("CLOUDINARY_API_SECRET", "").strip() or os.environ.get(
            "TOKEN", ""
        ).strip()
        upload_preset = os.environ.get("CLOUDINARY_UPLOAD_PRESET", "").strip() or os.environ.get(
            "UPLOAD_PRESET", ""
        ).strip()
        remote_folder = os.environ.get("CLOUDINARY_FOLDER", "").strip() or os.environ.get(
            "REMOTE_FOLDER", ""
        ).strip()

        unsigned = False
        if (not api_key or not api_secret) and upload_preset:
            unsigned = True

        return cloud_name, api_key, api_secret, upload_preset, unsigned, remote_folder

    def upload_exported_webps(self):
        """批量上传导出的 webp（默认扫描 */words/*.webp）。"""

        if self.upload_worker and self.upload_worker.isRunning():
            self.status_label.setText("正在上传中，请稍候")
            return

        cloud_name, api_key, api_secret, upload_preset, unsigned, remote_folder = self._read_upload_config_from_env()
        mock_upload = str(os.environ.get("CLOUDINARY_MOCK_UPLOAD", "")).strip().lower() in (
            "1",
            "true",
            "yes",
        )

        if not mock_upload:
            if not cloud_name:
                QMessageBox.warning(
                    self,
                    "缺少配置",
                    "未配置 Cloudinary cloud_name：请在 .env 中设置 CLOUDINARY_CLOUD_NAME（或 CLOUD_NAME）",
                )
                return

            if unsigned:
                if not upload_preset:
                    QMessageBox.warning(
                        self,
                        "缺少配置",
                        "未配置 upload preset：请在 .env 中设置 CLOUDINARY_UPLOAD_PRESET（或 UPLOAD_PRESET）",
                    )
                    return
            else:
                if not api_key or not api_secret:
                    QMessageBox.warning(
                        self,
                        "缺少配置",
                        "未配置 appkey/token：请在 .env 中设置 CLOUDINARY_API_KEY 与 CLOUDINARY_API_SECRET（或 APPKEY/TOKEN）",
                    )
                    return
        else:
            # mock 模式下允许不配置真实凭证
            cloud_name = cloud_name or "mock"

        scan_root = self._resolve_upload_scan_root()

        self.status_label.setText("正在扫描并上传 webp...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # indeterminate，直到知道 total
        self._set_upload_actions_enabled(False)

        self.upload_worker = UploadWebPWorker(
            scan_root=scan_root,
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            upload_preset=upload_preset,
            unsigned=unsigned,
            remote_folder=remote_folder,
            limit=0,
            concurrency=4,
            mock_upload=mock_upload,
            parent=self,
        )
        self.upload_worker.progress.connect(self._on_upload_progress)
        self.upload_worker.finished.connect(self._on_upload_finished)
        self.upload_worker.error.connect(self._on_upload_error)
        self.upload_worker.start()

    def _on_upload_progress(self, idx: int, total: int, rel_path: str, ok: bool, message: str):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(idx)
        status = "OK" if ok else "FAIL"
        self.status_label.setText(f"上传 {idx}/{total} [{status}] {rel_path}")

    def _on_upload_finished(self, total: int, ok_count: int, fail_count: int, table_text: str):
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"上传完成：总数={total} 成功={ok_count} 失败={fail_count}")
        self._set_upload_actions_enabled(True)

        if total == 0:
            QMessageBox.information(self, "上传", "未找到可上传的 webp（仅匹配 */words/*.webp）")
            return

        box = QMessageBox(self)
        box.setWindowTitle("上传结果")
        box.setIcon(QMessageBox.Information if fail_count == 0 else QMessageBox.Warning)
        box.setText(f"上传完成：总数={total}，成功={ok_count}，失败={fail_count}")
        if table_text:
            box.setDetailedText(table_text)
        box.exec_()

    def _on_upload_error(self, message: str):
        self.progress_bar.setVisible(False)
        self._set_upload_actions_enabled(True)
        QMessageBox.warning(self, "上传失败", message)

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
        self.property_panel.font_changed.connect(self._on_property_font_changed)
        self.property_panel.author_changed.connect(self._on_property_author_changed)
        self.property_panel.work_changed.connect(self._on_property_work_changed)

    def open_image(self):
        """打开图片"""
        # 已移除“打开”入口：请从左侧字帖树选择图片
        QMessageBox.information(self, "提示", "请从左侧字帖树选择图片")
        return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片文件 (*.jpg *.jpeg *.png *.bmp);;所有文件 (*)"
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
        img = Path(image_path)
        return img.parent / ".debug" / img.stem / "result.json"

    def _cache_chars_path(self, image_path: str) -> Path:
        img = Path(image_path)
        return img.parent / ".debug" / img.stem / "chars.json"

    def _try_load_cache(self, image_path: str) -> bool:
        """尝试从缓存加载

        优先级：
        1) <字帖目录>/.debug/<stem>/chars.json（用户编辑后的结果）
        2) <字帖目录>/.debug/<stem>/result.json（OCR 原始结果）
        """

        project_root = Path(__file__).parent.parent

        # 1) 优先 chars.json（用户编辑后的结果）
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
                    uid = c.get("id")
                    char_results.append(
                        {
                            "id": i,
                            "uuid": str(uid or ""),
                            "char": c.get("char", ""),
                            "work_dir": c.get("work_dir", ""),
                            "bbox": c.get("bbox", [0, 0, 0, 0]),
                            "column": c.get("column", 0),
                            "row": c.get("row", 0),
                            # 说明：chars.json 不再保存 global_index，这里运行时补一个
                            "global_index": i,
                        }
                    )

                # recognized_text：按 column/row 拼接（column 0 为最右列，按 0,1,2... 即从右向左）
                def _order_key(x: dict):
                    try:
                        return (int(x.get("column", 0)), int(x.get("row", 0)))
                    except Exception:
                        return (0, 0)

                char_results_sorted = sorted(char_results, key=_order_key)
                for gi, r in enumerate(char_results_sorted):
                    r["global_index"] = gi
                recognized_text = "".join(
                    [x.get("char", "") for x in char_results_sorted]
                )
                total_chars = len(char_results_sorted)
                column_count = 0
                if total_chars:
                    try:
                        column_count = (
                            max([int(x.get("column", 0)) for x in char_results_sorted])
                            + 1
                        )
                    except Exception:
                        column_count = 0

                font = "楷书"
                author = ""
                work_title = ""
                if chars and isinstance(chars[0], dict):
                    # 新字段（英文）优先；兼容旧字段（中文）
                    font = chars[0].get("font") or chars[0].get("字体") or "楷书"
                    author = chars[0].get("author") or chars[0].get("作者") or ""
                    work_title = chars[0].get("work") or chars[0].get("作品") or ""

                # 若没有作者/字体/作品，尝试从字帖文件夹名推导：作者-字体-作品
                # 示例：王羲之-行书-圣教序
                folder = Path(image_path).parent.name
                if "-" in folder:
                    parts = [p.strip() for p in folder.split("-") if p.strip()]
                    if len(parts) >= 2:
                        author = author or parts[0]
                        # 第二段如果是字体，映射到字体；否则拼入作品
                        font_candidates = {"楷书", "行书", "草书", "篆书", "隶书"}
                        if parts[1] in font_candidates:
                            font = font or parts[1]
                            if len(parts) >= 3:
                                work_title = work_title or "-".join(parts[2:])
                        else:
                            work_title = work_title or "-".join(parts[1:])

                # image_path 尽量写成相对路径（与原 result.json 一致）
                try:
                    rel = str(
                        Path(image_path).resolve().relative_to(project_root.resolve())
                    )
                except Exception:
                    rel = str(Path(image_path))

                cached = {
                    "image_path": rel,
                    "char_results": char_results_sorted,
                    "recognized_text": recognized_text,
                    "total_chars": total_chars,
                    "column_count": column_count,
                    "font": font,
                    "author": author,
                    "work_title": work_title,
                    "_from_cache": True,
                    "_cache_path": str(chars_path),
                    "_cache_kind": "chars.json",
                }
                self._on_ocr_finished(cached)
                return True
            except Exception as e:
                self.status_label.setText(
                    f"chars.json 缓存加载失败：{e}；将尝试加载 result.json"
                )

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

        if (
            hasattr(self, "batch_worker")
            and self.batch_worker
            and self.batch_worker.isRunning()
        ):
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
        image_path = (
            sel.get("image_path") if kind in ("work_image", "recognized") else None
        )
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

        # 字体/作者/作品：加载时按第一个字展示
        self.current_font = result.get("font") or self.current_font or "楷书"
        self.current_author = result.get("author") or self.current_author or ""
        self.current_work = result.get("work_title") or self.current_work or ""

        # 若仍为空，尝试从字帖目录名注入默认值
        if self.current_image_path:
            self._inject_meta_defaults_from_folder(
                Path(self.current_image_path).parent.name
            )

        self.property_panel.set_image_meta(
            self.current_font, self.current_author, self.current_work, enabled=True
        )

        if result.get("_from_cache"):
            self.status_label.setText(
                f"已从缓存加载 {len(self.char_manager.items)} 个字符 ({result.get('_cache_path', '')})"
            )
            self._last_loaded_cache_path = result.get("_cache_path")
        else:
            self.status_label.setText(
                f"已识别并加载 {len(self.char_manager.items)} 个字符"
            )
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
            self.status_label.setText(
                f"已选中字帖：{Path(dir_path).name}（点击“识别”可批量识别）"
            )
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

    def _on_batch_progress(
        self, idx: int, total: int, image_path: str, ok: bool, message: str
    ):
        name = Path(image_path).name
        status = "OK" if ok else "FAIL"
        self.status_label.setText(f"批量识别 {idx}/{total} {status}: {name} {message}")

    def _on_batch_finished(self, total: int, ok_count: int, fail_count: int):
        self.status_label.setText(
            f"批量识别完成：成功 {ok_count}，失败 {fail_count}，共 {total}"
        )
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

        # 输出目录调整：<字帖目录>/.debug/<stem>/chars.json
        image_path = Path(self.current_image_path)
        out_dir = image_path.parent / ".debug" / image_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        chars_path = out_dir / "chars.json"

        # 只更新 chars.json（现有 json），不改 result.json
        # chars.json 格式与 recognizer.py 保存的一致（简化版）
        # 字帖目录名（仅用于生成 id）
        work_dir_name = image_path.parent.name if image_path.parent else ""
        image_name = image_path.name

        # 保存前确保 author/font/work 有默认值（来自字帖目录名）
        self._inject_meta_defaults_from_folder(work_dir_name)

        import hashlib

        char_data = []
        for r in sorted(self.char_manager.items, key=lambda x: (x.column, x.row)):
            # 使用 char+work_dir+column+row 生成 MD5 作为唯一 ID
            md5_input = f"{r.char}_{work_dir_name}_{r.column}_{r.row}"
            md5_hash = hashlib.md5(md5_input.encode("utf-8")).hexdigest()
            r.uuid = md5_hash
            char_data.append(
                {
                    "id": md5_hash,
                    "char": r.char,
                    # 元数据字段使用英文
                    "font": self.current_font or "楷书",
                    "author": self.current_author or "",
                    "work": self.current_work or "",
                    # 仅用于可追溯（不是“字帖”字段）：记录字帖目录名
                    "work_dir": work_dir_name,
                    "bbox": r.bbox,
                    "column": r.column,
                    "row": r.row,
                }
            )

        with open(chars_path, "w", encoding="utf-8") as f:
            json.dump(char_data, f, ensure_ascii=False, indent=2)

        # 同步写入 words/<stem>.txt（拆解后的文字）
        try:
            words_dir = image_path.parent / "words"
            words_dir.mkdir(parents=True, exist_ok=True)
            words_path = words_dir / f"{image_path.stem}.txt"
            recognized_text = "".join([x["char"] for x in char_data])
            with open(words_path, "w", encoding="utf-8") as wf:
                wf.write(recognized_text)
        except Exception as e:
            self.status_label.setText(f"已保存到 {chars_path}（写 words 失败：{e}）")
            return

        self.status_label.setText(f"已保存到 {chars_path}")

    def _on_ocr_error(self, error: str):
        """OCR 错误"""
        QMessageBox.warning(self, "OCR 错误", f"识别失败: {error}")
        self.status_label.setText("识别失败")

    def export_chars(self):
        """导出：全量导出所有字帖到 SQLite（无需选择目录）"""
        # 避免重复触发
        if getattr(self, "export_worker", None) is not None and self.export_worker.isRunning():
            return

        self.status_label.setText("正在导出...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # indeterminate，直到裁剪阶段拿到 total
        self._set_export_actions_enabled(False)

        self.export_worker = ExportAllWorker(parent=self)
        self.export_worker.progress.connect(self._on_export_progress)
        self.export_worker.finished.connect(self._on_export_finished)
        self.export_worker.error.connect(self._on_export_error)
        self.export_worker.start()

    def _on_export_progress(self, done: int, total: int, message: str):
        if int(total or 0) > 0:
            self.progress_bar.setRange(0, int(total))
            self.progress_bar.setValue(int(done))
        else:
            self.progress_bar.setRange(0, 0)
        self.status_label.setText(str(message or "正在导出..."))

    def _on_export_finished(
        self,
        sqlite_path: str,
        sqlite_total: int,
        crop_total: int,
        crop_ok: int,
        crop_fail: int,
    ):
        self.progress_bar.setVisible(False)
        self._set_export_actions_enabled(True)
        self.status_label.setText(
            f"导出完成：SQLite {sqlite_total} 条 -> {sqlite_path}；裁剪 {crop_ok}/{crop_total}（失败 {crop_fail}）"
        )

    def _on_export_error(self, message: str):
        self.progress_bar.setVisible(False)
        self._set_export_actions_enabled(True)
        QMessageBox.warning(self, "导出失败", message)

    def search_char(self):
        """在全量 chars.json 中搜索单字并跳转到对应图片。"""

        if not hasattr(self, "search_edit"):
            return

        raw = (self.search_edit.text() or "").strip()
        if not raw:
            return

        q = raw[:1]
        if raw != q:
            # 用户误输入多个字符时，自动截断成单字
            try:
                self.search_edit.setText(q)
            except Exception:
                pass

        # 若上一次搜索还在跑，先打断
        if getattr(self, "search_worker", None) is not None and self.search_worker.isRunning():
            try:
                self.search_worker.requestInterruption()
            except Exception:
                pass

        self.status_label.setText(f"正在搜索：{q}")
        try:
            self.search_edit.setEnabled(False)
        except Exception:
            pass

        self.search_worker = CharSearchWorker(q, parent=self)
        self.search_worker.progress.connect(self._on_search_progress)
        self.search_worker.found.connect(self._on_search_found)
        self.search_worker.not_found.connect(self._on_search_not_found)
        self.search_worker.error.connect(self._on_search_error)
        self.search_worker.start()

    def _on_search_progress(self, idx: int, total: int, message: str):
        # 不占用全局 progress_bar（避免和导出/上传进度冲突）
        if message:
            self.status_label.setText(str(message))

    def _on_search_found(self, image_path: str, chars_path: str, query_char: str):
        try:
            self.search_edit.setEnabled(True)
            self.search_edit.selectAll()
        except Exception:
            pass

        self.status_label.setText(f"已找到并跳转：{Path(image_path).name}")
        try:
            # 自动加载图片（内部会同步在目录树中选中）
            self._load_image(str(image_path))
            # 选中目标字（尽量模拟“鼠标点选”效果）
            q = (query_char or "").strip()[:1]
            if q:
                self._select_first_char_in_current_image(q)
        except Exception as e:
            QMessageBox.warning(self, "跳转失败", str(e))

    def _select_first_char_in_current_image(self, q: str) -> None:
        """在当前已加载图片的 char_manager 中选中第一个匹配字符。"""

        q = (q or "").strip()[:1]
        if not q:
            return

        if not getattr(self, "char_manager", None) or not self.char_manager.items:
            return

        candidates = [it for it in self.char_manager.items if (it.char or "") == q]
        if not candidates:
            return

        # 按阅读顺序（column 0 为最右列，row 从上到下）选第一个
        chosen = sorted(candidates, key=lambda x: (int(x.column or 0), int(x.row or 0), int(x.id or 0)))[0]

        try:
            self.char_list.select_item(chosen.id)
        except Exception:
            pass

        try:
            self._on_char_selected(chosen.id)
        except Exception:
            # 最差情况下至少把 bbox 选中
            try:
                self.image_canvas.select_bbox(chosen.id)
            except Exception:
                pass

    def _on_search_not_found(self, query: str):
        try:
            self.search_edit.setEnabled(True)
            self.search_edit.selectAll()
        except Exception:
            pass

        q = (query or "").strip()[:1]
        self.status_label.setText(f"未找到：{q}")
        if q:
            QMessageBox.information(self, "搜索", f"未在任何 chars.json 中找到：{q}")

    def _on_search_error(self, message: str):
        try:
            self.search_edit.setEnabled(True)
        except Exception:
            pass
        self.status_label.setText("搜索失败")
        QMessageBox.warning(self, "搜索失败", message)

    def _create_glyphs_table(self, cursor):
        """创建 glyphs 表"""
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS "glyphs" (
                id TEXT PRIMARY KEY,
                char TEXT,
                work_dir TEXT,
                author TEXT,
                font TEXT,
                work_title TEXT
            )
        """
        )

    def _export_glyphs_to_sqlite(self, sqlite_path, items):
        """导出字形数据到 SQLite"""
        return export_glyphs_to_sqlite(Path(sqlite_path), items)

    def _export_all_glyphs_sqlite(self):
        """扫描 ocr_output 并生成全量 glyphs.sqlite"""
        project_root = Path(__file__).parent.parent
        return export_all_glyphs_sqlite(project_root)

    def _export_all_crops(self):
        """扫描 ocr_output 并把裁剪后的单字图片写到对应字帖目录内。

        输出路径：
        - <字帖目录>/words/<id>.webp
        """
        project_root = Path(__file__).parent.parent
        return export_all_crops(project_root)

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

        # 生成 SQLite
        image_path = Path(self.current_image_path) if self.current_image_path else None
        work_name = image_path.parent.name if image_path and image_path.parent else ""
        image_name = image_path.name if image_path else ""

        def _make_id(item) -> str:
            return f"{work_name}_{image_name}_{item.row}_{item.column}_{item.char}"

        # 准备导出数据
        export_items = []
        for item in self.char_manager.items:
            export_items.append(
                {
                    "id": _make_id(item),
                    "char": item.char,
                    "work_dir": work_name,
                    "author": self.current_author,
                    "font": self.current_font,
                    "work": self.current_work,
                }
            )

        sqlite_path = Path(export_dir) / "glyphs.sqlite"
        self._export_glyphs_to_sqlite(sqlite_path, export_items)

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
                # 文件名避免使用过长 id，这里沿用可读形式
                filename = f"{item.char}_{item.id}.jpg"
                filepath = chars_dir / filename
                cv2.imwrite(str(filepath), char_img)

        # 保存元数据
        metadata_path = Path(export_dir) / "chars.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(
                self.char_manager.to_export_format(), f, ensure_ascii=False, indent=2
            )

        QMessageBox.information(
            self,
            "导出完成",
            f"已导出 {len(self.char_manager.items)} 个字符到:\n{export_dir}\n\nSQLite: {sqlite_path}",
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
            if (
                self.property_panel.current_item
                and self.property_panel.current_item.id == item_id
            ):
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
                bbox_item.update_bbox(
                    float(x1), float(y1), float(x2 - x1), float(y2 - y1)
                )
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

    def _on_property_bbox_changed(
        self, item_id: int, x: float, y: float, w: float, h: float
    ):
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

    def _on_property_font_changed(self, font: str):
        self.current_font = font or "楷书"

    def _on_property_author_changed(self, author: str):
        self.current_author = author or ""

    def _on_property_work_changed(self, work: str):
        self.current_work = work or ""

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
            if hasattr(self, "action_toggle_worktree"):
                self.action_toggle_worktree.blockSignals(True)
                self.action_toggle_worktree.setChecked(True)
                self.action_toggle_worktree.blockSignals(False)
            # 字符列表按当前状态决定宽度
            char_w = (
                0
                if (hasattr(self, "char_list") and not self.char_list.isVisible())
                else 160
            )
            self.main_splitter.setSizes([28, char_w, 1200])
        else:
            if hasattr(self, "action_toggle_worktree"):
                self.action_toggle_worktree.blockSignals(True)
                self.action_toggle_worktree.setChecked(False)
                self.action_toggle_worktree.blockSignals(False)
            char_w = (
                0
                if (hasattr(self, "char_list") and not self.char_list.isVisible())
                else 160
            )
            self.main_splitter.setSizes([280, char_w, 960])

    def _toggle_char_list(self, checked: bool):
        """显示/隐藏字符列表。checked=True 表示隐藏。"""
        hide = bool(checked)
        self.char_list.setVisible(not hide)

        if not hasattr(self, "main_splitter"):
            return

        # 维持当前字帖宽度：折叠时用更窄的 28，避免左侧灰条过宽
        work_w = 28 if getattr(self.work_tree, "_collapsed", False) else 280
        char_w = 0 if hide else 160
        right_w = 1200 if getattr(self.work_tree, "_collapsed", False) else 960
        self.main_splitter.setSizes([work_w, char_w, right_w])

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
            "- 导出单字图片",
        )

    def closeEvent(self, event):
        """关闭事件"""
        if self.ocr_worker and self.ocr_worker.isRunning():
            self.ocr_worker.terminate()
            self.ocr_worker.wait()
        event.accept()
