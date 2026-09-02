"""
主窗口
"""

import os
import json
import time
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
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QFileSystemWatcher, QTimer
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
        # 清空旧数据，避免残留过期记录
        cur.execute("DELETE FROM glyphs")
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


def export_all_glyphs_sqlite(
    project_root: Path, progress_cb=None, scope_work_dir: Optional[Path] = None
):
    """扫描字帖的 chars.json 并生成 glyphs.sqlite。

    ``scope_work_dir`` 有值时只导出该字帖；否则导出项目内全部字帖。

    progress_cb(done:int, total:int, message:str) 可选。
    """

    ocr_output = project_root / "ocr_output"
    ocr_output.mkdir(parents=True, exist_ok=True)

    sqlite_name = "glyphs.sqlite"
    if scope_work_dir is not None:
        sqlite_name = f"glyphs-{scope_work_dir.name}.sqlite"
    sqlite_path = ocr_output / sqlite_name

    chars_paths = []
    work_dirs = [scope_work_dir] if scope_work_dir is not None else sorted(
        [p for p in project_root.iterdir() if p.is_dir()], key=lambda p: p.name
    )
    for work_dir in work_dirs:
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
            if rec.get("visible") is False:
                continue
            if "work_dir" not in rec:
                rec["work_dir"] = work_dir.name
            all_items.append(rec)

    total = export_glyphs_to_sqlite(sqlite_path, all_items)
    return str(sqlite_path), total


def export_all_crops(
    project_root: Path, progress_cb=None, scope_work_dir: Optional[Path] = None
):
    """扫描字帖的 chars.json 并裁剪导出 webp 到 <字帖目录>/words/。

    ``scope_work_dir`` 有值时只导出该字帖；否则导出项目内全部字帖。

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
    work_dirs = [scope_work_dir] if scope_work_dir is not None else sorted(
        [p for p in project_root.iterdir() if p.is_dir()], key=lambda p: p.name
    )
    for work_dir in work_dirs:
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

    # 预统计总数（只统计已填写汉字且 bbox 合法的记录，便于进度条准确）
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
            if rec.get("visible") is False:
                continue
            if not str(rec.get("char", "")).strip():
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
            if rec.get("visible") is False:
                continue
            bbox = rec.get("bbox")
            ch = rec.get("char", "")
            if not str(ch).strip():
                continue
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


def filter_labeled_word_upload_items(scan_root: Path, items: list) -> list:
    """只保留在 chars.json 中可见且已经填写汉字的单字图片。"""

    allowed_paths = set()
    for chars_path in scan_root.glob("**/.debug/*/chars.json"):
        try:
            with open(chars_path, "r", encoding="utf-8") as f:
                chars = json.load(f)
        except Exception:
            continue
        if not isinstance(chars, list):
            continue

        work_dir = chars_path.parent.parent.parent
        for rec in chars:
            if (
                not isinstance(rec, dict)
                or rec.get("visible") is False
                or not rec.get("id")
                or not str(rec.get("char", "")).strip()
            ):
                continue
            allowed_paths.add((work_dir / "words" / f"{rec['id']}.webp").resolve())

    return [it for it in items if it.abs_path.resolve() in allowed_paths]


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


class SplitCharsWorker(QThread):
    """拆字处理线程：重新计算 bbox，不修改字、id、author、font、work 等其他内容。"""

    progress = pyqtSignal(int, int, str, bool, str)  # idx, total, image_path, ok, message
    finished = pyqtSignal(int, int, int)  # total, ok_count, fail_count
    error = pyqtSignal(str)

    def __init__(self, image_paths: List[str], parent=None):
        super().__init__(parent)
        self.image_paths = image_paths

    def run(self):
        try:
            import sys
            from pathlib import Path
            from collections import defaultdict

            project_root = Path(__file__).parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))

            import cv2
            from ocr.char_splitter import CharSplitter, SplitMethod

            splitter = CharSplitter(method=SplitMethod.HYBRID, min_char_height=20)

            total = len(self.image_paths)
            ok_count = 0
            fail_count = 0

            for i, image_path in enumerate(self.image_paths, start=1):
                try:
                    ok, msg = self._split_single_image(image_path, splitter)
                    if ok:
                        ok_count += 1
                    else:
                        fail_count += 1
                    self.progress.emit(i, total, image_path, ok, msg)
                except Exception as e:
                    fail_count += 1
                    self.progress.emit(i, total, image_path, False, str(e)[:120])

            self.finished.emit(total, ok_count, fail_count)
        except Exception as e:
            self.error.emit(str(e))

    def _split_single_image(self, image_path: str, splitter) -> tuple:
        """对单张图片重新拆字，返回 (ok, message)。"""
        from pathlib import Path
        from collections import defaultdict
        import cv2

        img_path = Path(image_path)
        chars_path = img_path.parent / ".debug" / img_path.stem / "chars.json"

        if not chars_path.exists():
            return False, "chars.json 不存在"

        with open(chars_path, "r", encoding="utf-8") as f:
            chars = json.load(f)

        if not isinstance(chars, list) or not chars:
            return False, "chars.json 为空"

        image = cv2.imread(str(image_path))
        if image is None:
            return False, "无法加载图片"

        # 检测并裁剪黑色主体区域（去掉白色边框）
        from ocr.preprocess import detect_content_region
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        content_bbox = detect_content_region(gray)
        offset_x, offset_y = 0, 0
        if content_bbox is not None:
            cx1, cy1, cx2, cy2 = content_bbox
            image = image[cy1:cy2+1, cx1:cx2+1]
            offset_x, offset_y = cx1, cy1

        # 按 column 分组
        col_groups = defaultdict(list)
        for c in chars:
            col_groups[c.get("column", 0)].append(c)

        # 优先从 result.json 读取列 bbox（更可靠，不会被 resplit 污染）
        result_path = chars_path.parent / "result.json"
        col_bboxes_from_result = {}
        if result_path.exists():
            try:
                with open(result_path, "r", encoding="utf-8") as f:
                    result_data = json.load(f)
                parsed_results = result_data.get("parsed_results", [])
                if parsed_results:
                    # 过滤释文列（窄列）
                    widths = [c["bbox"][2] - c["bbox"][0] for c in parsed_results]
                    max_width = max(widths) if widths else 0
                    threshold = max(max_width * 0.5, 50)
                    valid_cols = [c for c in parsed_results if c["bbox"][2] - c["bbox"][0] >= threshold]
                    # 按 x_max 从大到小排序（从右到左），与 chars.json 的 column 编号对应
                    valid_cols.sort(key=lambda c: -c["bbox"][2])
                    if len(valid_cols) == len(col_groups):
                        for col_idx, col_data in enumerate(valid_cols):
                            col_bboxes_from_result[col_idx] = col_data["bbox"]
            except Exception:
                pass

        updated_count = 0

        for col_idx, items in col_groups.items():
            items.sort(key=lambda x: x.get("row", 0))
            text = "".join(c.get("char", "") for c in items)
            if not text:
                continue

            # 获取列 bbox
            if col_idx in col_bboxes_from_result:
                # 使用 result.json 的列 bbox（原图坐标）
                col_bbox = list(col_bboxes_from_result[col_idx])
                # 映射到裁剪图坐标
                if content_bbox is not None:
                    col_bbox = [
                        col_bbox[0] - offset_x,
                        col_bbox[1] - offset_y,
                        col_bbox[2] - offset_x,
                        col_bbox[3] - offset_y,
                    ]
            else:
                # 回退：从 chars.json 的字 bbox 计算列 bbox（已可能被污染）
                bboxes = [c.get("bbox", [0, 0, 0, 0]) for c in items]
                try:
                    x1 = min(b[0] for b in bboxes) - offset_x
                    y1 = min(b[1] for b in bboxes) - offset_y
                    x2 = max(b[2] for b in bboxes) - offset_x
                    y2 = max(b[3] for b in bboxes) - offset_y
                except Exception:
                    continue
                col_bbox = [float(x1), float(y1), float(x2), float(y2)]

            try:
                char_bboxes, method = splitter.split_column(
                    image, col_bbox, text, debug=False
                )
            except Exception:
                continue

            if len(char_bboxes) != len(items):
                continue

            for j, item in enumerate(items):
                b = char_bboxes[j]
                # 收紧 bbox，去掉白边（在裁剪图坐标下）
                from ocr.preprocess import tighten_char_bbox
                b = tighten_char_bbox(image, b, pad=3)
                # 把 bbox 映射回原图坐标
                item["bbox"] = [
                    float(b[0] + offset_x),
                    float(b[1] + offset_y),
                    float(b[2] + offset_x),
                    float(b[3] + offset_y),
                ]
                updated_count += 1

        # 保存
        with open(chars_path, "w", encoding="utf-8") as f:
            json.dump(chars, f, ensure_ascii=False, indent=2)

        return True, f"已更新 {updated_count} 个字的 bbox"


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
        selected_image: str = "",
        min_mtime: float = 0.0,
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
        self.selected_image = selected_image  # 选中的图片路径，用于精确过滤
        self.min_mtime = float(min_mtime or 0.0)

    def run(self):
        try:
            import sys

            project_root = Path(__file__).parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))

            from upload_webp_cloudinary import collect_upload_items, upload_items

            root = Path(self.scan_root).expanduser().resolve()
            items = collect_upload_items(root, limit=0, keep_dirs=False, min_mtime=self.min_mtime)
            # 尽量只上传导出产物：*/words/*.webp
            items = [it for it in items if "/words/" in ("/" + it.rel_path.replace("\\", "/") + "/")]
            items = filter_labeled_word_upload_items(root, items)

            # 如果指定了选中图片，读取对应的 chars.json 获取 id 列表进行过滤
            if self.selected_image:
                selected_stem = Path(self.selected_image).stem  # e.g., "fatie-001"
                chars_path = Path(self.selected_image).parent / ".debug" / selected_stem / "chars.json"
                allowed_ids = set()
                if chars_path.exists():
                    try:
                        import json
                        with open(chars_path, "r", encoding="utf-8") as f:
                            chars_data = json.load(f)
                        if isinstance(chars_data, list):
                            for rec in chars_data:
                                if (
                                    isinstance(rec, dict)
                                    and rec.get("id")
                                    and str(rec.get("char", "")).strip()
                                ):
                                    allowed_ids.add(rec["id"])
                    except Exception:
                        pass
                # 过滤：只保留文件名（不含扩展名）在 allowed_ids 中的项
                if allowed_ids:
                    items = [it for it in items if Path(it.rel_path).stem in allowed_ids]
                else:
                    # 如果读取失败或没有 id，不上传任何内容
                    items = []

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
                invalidate=True,
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

            # 写入上传日志
            try:
                log_dir = Path(__file__).parent.parent / "ocr_output"
                log_dir.mkdir(parents=True, exist_ok=True)
                log_path = log_dir / "upload_log.jsonl"
                log_entry = {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "scan_root": str(root),
                    "cloud_name": self.cloud_name,
                    "remote_folder": self.remote_folder,
                    "mock_upload": self.mock_upload,
                    "total": total,
                    "ok": ok_cnt,
                    "fail": fail_cnt,
                    "results": [
                        {
                            "rel_path": r.rel_path,
                            "public_id": r.public_id,
                            "ok": r.ok,
                            "url": r.url,
                            "error": r.error,
                        }
                        for r in results
                    ],
                }
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            except Exception:
                pass

            self.finished.emit(total, ok_cnt, fail_cnt, table)
        except Exception as e:
            self.error.emit(str(e))


class ExportAllWorker(QThread):
    """导出全部字帖的 glyphs.sqlite 与裁剪 webp。"""

    progress = pyqtSignal(int, int, str)  # done, total, message
    finished = pyqtSignal(str, int, int, int, int)  # sqlite_path, sqlite_total, crop_total, crop_ok, crop_fail
    error = pyqtSignal(str)

    def __init__(self, scope_work_dir: str = "", parent=None):
        super().__init__(parent)
        self.scope_work_dir = Path(scope_work_dir) if scope_work_dir else None

    def run(self):
        try:
            project_root = Path(__file__).parent.parent

            # 1) SQLite：先扫描（进度不一定准确，主要用于状态提示）
            scope_label = self.scope_work_dir.name if self.scope_work_dir else "全部字帖"
            self.progress.emit(0, 0, f"正在导出 SQLite：{scope_label}...")

            def _sqlite_cb(done: int, total: int, msg: str):
                # SQLite 阶段：不占用进度条，避免和图片导出混淆
                self.progress.emit(0, 0, msg)

            sqlite_path, sqlite_total = export_all_glyphs_sqlite(
                project_root, progress_cb=_sqlite_cb, scope_work_dir=self.scope_work_dir
            )

            # 2) 裁剪导出：使用可计数进度
            def _crop_cb(done: int, total: int, msg: str):
                self.progress.emit(int(done), int(total), str(msg))

            crop_total, crop_ok, crop_fail = export_all_crops(
                project_root, progress_cb=_crop_cb, scope_work_dir=self.scope_work_dir
            )

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

    APP_TITLE = "书法拆字编辑器"

    def __init__(self):
        super().__init__()

        self.char_manager = CharItemManager()
        self.current_image_path: Optional[str] = None
        self.ocr_worker: Optional[OCRWorker] = None
        self._last_loaded_cache_path: Optional[str] = None
        self._current_tree_selection: Optional[dict] = None
        # 编辑器内的框复制缓冲区；只保存必要字段，避免复用原框的持久化 uuid。
        self._bbox_clipboard: Optional[dict] = None
        self._has_unsaved_edits = False
        self._watched_chars_path: Optional[Path] = None
        self._last_internal_chars_signature: Optional[tuple] = None
        self._pending_external_chars_reload = False
        self._chars_watcher = QFileSystemWatcher(self)
        self._chars_watcher.fileChanged.connect(self._on_watched_chars_changed)
        self._chars_watcher.directoryChanged.connect(self._on_watched_chars_directory_changed)

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

    def _update_window_title(self):
        """在打开图片时将当前页文件名附加到窗口标题。"""
        if self.current_image_path:
            self.setWindowTitle(f"{self.APP_TITLE} · {Path(self.current_image_path).name}")
        else:
            self.setWindowTitle(self.APP_TITLE)

    def _init_ui(self):
        """初始化 UI"""
        self._update_window_title()
        # macOS 下某些情况下 setGeometry 会被 Qt 重新计算覆盖，
        # 这里用 resize + setMinimumSize 保证窗口不会"缩成很小"。
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

        copy_bbox_action = QAction("复制框(&C)", self)
        copy_bbox_action.setShortcut(QKeySequence.Copy)
        copy_bbox_action.triggered.connect(self.copy_selected_bbox)
        edit_menu.addAction(copy_bbox_action)

        paste_bbox_action = QAction("粘贴框(&P)", self)
        paste_bbox_action.setShortcut(QKeySequence.Paste)
        paste_bbox_action.triggered.connect(self.paste_bbox)
        edit_menu.addAction(paste_bbox_action)

        delete_action = QAction("删除(&D)", self)
        delete_action.setShortcuts([QKeySequence.Delete, QKeySequence("Backspace")])
        delete_action.triggered.connect(self.delete_selected_char)
        edit_menu.addAction(delete_action)

        # 视图菜单
        view_menu = menubar.addMenu("视图(&V)")

        self.action_previous_image = QAction("上一页", self)
        self.action_previous_image.setShortcut(QKeySequence("Ctrl+Up"))
        self.action_previous_image.setShortcutContext(Qt.ApplicationShortcut)
        self.action_previous_image.triggered.connect(
            lambda: self._navigate_work_tree_image(-1)
        )
        view_menu.addAction(self.action_previous_image)

        self.action_next_image = QAction("下一页", self)
        self.action_next_image.setShortcut(QKeySequence("Ctrl+Down"))
        self.action_next_image.setShortcutContext(Qt.ApplicationShortcut)
        self.action_next_image.triggered.connect(
            lambda: self._navigate_work_tree_image(1)
        )
        view_menu.addAction(self.action_next_image)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _init_toolbar(self):
        """初始化工具栏"""
        toolbar = self.addToolBar("主工具栏")
        toolbar.setMovable(False)

        # 字帖最小化按钮（放在"识别"左侧）
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

        # 拆字（重新计算 bbox，不调用 API，不修改字/id/author/font/work）
        self.action_split_chars = QAction("拆字", self)
        self.action_split_chars.triggered.connect(self.split_chars)
        toolbar.addAction(self.action_split_chars)

        # 保存编辑（写回现有 json，不写 result.json）
        toolbar.addAction(self.action_save)

        # 添加框
        add_bbox_action = QAction("添加框", self)
        add_bbox_action.triggered.connect(self.add_new_bbox)
        toolbar.addAction(add_bbox_action)

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

    def _resolve_upload_scan_root(self) -> tuple:
        """根据当前选择，决定扫描上传的根目录和选中的图片。

        Returns:
            tuple: (scan_root, selected_image)
            - scan_root: 扫描的根目录
            - selected_image: 如果选中了单张图片，返回其路径；否则返回空字符串
        """
        sel = self._current_tree_selection or {}
        kind = sel.get("kind")

        # 选中了字帖目录
        if kind == "work_dir":
            dir_path = sel.get("dir_path") or ""
            if dir_path:
                return (dir_path, "")

        # 选中了单张图片
        if kind in ("work_image", "recognized"):
            image_path = sel.get("image_path") or ""
            if image_path:
                return (str(Path(image_path).parent), image_path)

        # 默认：项目根目录
        return (str(Path(__file__).parent.parent), "")

    def _resolve_export_work_dir(self) -> Optional[Path]:
        """根据左侧选择确定导出范围；选中字帖或其中任一页时仅导出该字帖。"""
        sel = self._current_tree_selection or {}
        kind = sel.get("kind")
        if kind == "work_dir":
            dir_path = sel.get("dir_path") or ""
            if dir_path:
                return Path(dir_path)
        if kind in ("work_image", "recognized"):
            image_path = sel.get("image_path") or ""
            if image_path:
                return Path(image_path).parent
        return None

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

    def _last_upload_time_path(self) -> Path:
        return Path(__file__).parent.parent / "ocr_output" / "last_upload_time.txt"

    def _read_last_upload_time(self) -> float:
        """读取上次上传时间戳。没有记录则返回 20 分钟前。"""
        path = self._last_upload_time_path()
        if path.exists():
            try:
                return float(path.read_text(encoding="utf-8").strip())
            except Exception:
                pass
        return time.time() - 20 * 60

    def _write_last_upload_time(self, ts: float) -> None:
        """写入上次上传时间戳。"""
        try:
            path = self._last_upload_time_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(ts), encoding="utf-8")
        except Exception:
            pass

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

        scan_root, selected_image = self._resolve_upload_scan_root()

        # 先扫描，统计数量
        import sys
        project_root = Path(__file__).parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from upload_webp_cloudinary import collect_upload_items

        root = Path(scan_root).expanduser().resolve()
        all_items = collect_upload_items(root, limit=0, keep_dirs=False)
        all_items = [it for it in all_items if "/words/" in ("/" + it.rel_path.replace("\\", "/") + "/")]
        all_items = filter_labeled_word_upload_items(root, all_items)

        # 如果指定了选中图片，按 chars.json 的 id 过滤
        if selected_image:
            selected_stem = Path(selected_image).stem
            chars_path = Path(selected_image).parent / ".debug" / selected_stem / "chars.json"
            allowed_ids = set()
            if chars_path.exists():
                try:
                    with open(chars_path, "r", encoding="utf-8") as f:
                        chars_data = json.load(f)
                    if isinstance(chars_data, list):
                        for rec in chars_data:
                            if (
                                isinstance(rec, dict)
                                and rec.get("id")
                                and str(rec.get("char", "")).strip()
                            ):
                                allowed_ids.add(rec["id"])
                except Exception:
                    pass
            if allowed_ids:
                all_items = [it for it in all_items if Path(it.rel_path).stem in allowed_ids]
            else:
                all_items = []

        if not all_items:
            QMessageBox.information(self, "上传", "未找到可上传的 webp（仅匹配 */words/*.webp）")
            return

        # 读取上次上传时间
        last_upload_time = self._read_last_upload_time()
        last_upload_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_upload_time))
        recent_items = [it for it in all_items if it.abs_path.stat().st_mtime >= last_upload_time]

        # 按字帖分组
        def _group(items):
            groups = {}
            for it in items:
                parts = it.rel_path.replace("\\", "/").split("/")
                work = parts[0] if parts else it.rel_path
                groups[work] = groups.get(work, 0) + 1
            return groups

        all_groups = _group(all_items)
        recent_groups = _group(recent_items)

        def _fmt(groups, total):
            lines = [f"总计: {total} 张"]
            if groups:
                lines.append("")
                for k, v in sorted(groups.items()):
                    lines.append(f"  {k}: {v} 张")
            return "\n".join(lines)

        all_text = _fmt(all_groups, len(all_items))
        recent_text = _fmt(recent_groups, len(recent_items))

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("选择上传方式")
        scope_label = (
            Path(scan_root).name
            if scan_root != str(Path(__file__).parent.parent)
            else "全部字帖"
        )
        msg_box.setText(f"请选择要上传的文件范围（当前：{scope_label}）：")
        info = f"【当前范围内全部上传】\n{all_text}\n\n【当前范围内增量上传】\n上次上传时间: {last_upload_str}\n{recent_text}"
        msg_box.setInformativeText(info)

        btn_all_label = "上传当前字帖" if scope_label != "全部字帖" else "全量上传"
        btn_all = msg_box.addButton(btn_all_label, QMessageBox.AcceptRole)
        btn_recent = msg_box.addButton("增量上传", QMessageBox.AcceptRole)
        btn_cancel = msg_box.addButton("取消", QMessageBox.RejectRole)

        msg_box.exec_()

        if msg_box.clickedButton() == btn_cancel:
            return
        elif msg_box.clickedButton() == btn_recent:
            since_minutes = -1  # 特殊标记：使用 last_upload_time
            if not recent_items:
                QMessageBox.information(self, "上传", f"{last_upload_str} 之后没有新增或修改的 webp")
                return
        else:
            since_minutes = 0

        # 构建状态文本
        if selected_image:
            status_text = f"正在上传单页: {Path(selected_image).name}"
        elif scan_root != str(Path(__file__).parent.parent):
            status_text = f"正在上传字帖: {Path(scan_root).name}"
        else:
            status_text = "正在扫描并上传所有 webp..."
        self.status_label.setText(status_text)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self._set_upload_actions_enabled(False)

        # 根据选择决定 min_mtime
        min_mtime = float(last_upload_time if since_minutes == -1 else 0.0)
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
            selected_image=selected_image,
            min_mtime=min_mtime,
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

        # 有成功上传的，更新上次上传时间
        if ok_count > 0:
            self._write_last_upload_time(time.time())

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
        self.work_tree.items_deleted.connect(self._on_tree_items_deleted)

        # 字符列表信号
        self.char_list.char_selected.connect(self._on_char_selected)
        self.char_list.char_double_clicked.connect(self._on_char_double_clicked)

        # 图片画布信号
        self.image_canvas.selection_changed.connect(self._on_canvas_selection_changed)
        self.image_canvas.bbox_updated.connect(self._on_bbox_updated)
        self.image_canvas.bbox_edit_committed.connect(self._on_bbox_edit_committed)
        self.image_canvas.item_deleted.connect(self._on_canvas_item_deleted)
        self.image_canvas.items_deleted.connect(self._on_canvas_items_deleted)

        # 属性面板信号
        self.property_panel.char_changed.connect(self._on_property_char_changed)
        self.property_panel.batch_char_changed.connect(self._on_property_batch_char_changed)
        self.property_panel.bbox_changed.connect(self._on_property_bbox_changed)
        self.property_panel.font_changed.connect(self._on_property_font_changed)
        self.property_panel.author_changed.connect(self._on_property_author_changed)
        self.property_panel.work_changed.connect(self._on_property_work_changed)
        self.property_panel.visible_changed.connect(self._on_property_visible_changed)
        self.property_panel.row_changed.connect(self._on_property_row_changed)
        self.property_panel.column_changed.connect(self._on_property_column_changed)

        # 预览框上传
        self.char_preview.upload_requested.connect(self._on_preview_upload_requested)

    def open_image(self):
        """打开图片"""
        # 已移除"打开"入口：请从左侧字帖树选择图片
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
        self._has_unsaved_edits = False

        # 在字帖树中高亮当前图片（不折叠树）
        if hasattr(self, "work_tree"):
            self.work_tree.select_image(image_path)

        # 加载图片
        if not self.image_canvas.load_image(image_path):
            QMessageBox.warning(self, "错误", f"无法加载图片: {image_path}")
            return

        # 页面已切换，先清掉上一页的字符状态和预览。成功加载本页的
        # chars.json/result.json 后，_on_ocr_finished 会选中本页左下角的字。
        self.char_manager.clear()
        self.char_list.clear()
        self.property_panel.load_item(None)
        self.char_preview.clear()

        self._update_window_title()

        self._watch_current_chars_file()

        # 尝试从缓存加载
        if self._try_load_cache(image_path):
            return

        self.status_label.setText('已打开图片（未发现缓存），请点击"识别"')

    @staticmethod
    def _file_signature(path: Path) -> Optional[tuple]:
        """返回用于判断文件是否实际改变的稳定标识。"""
        try:
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def _watch_current_chars_file(self):
        """只监听当前页 chars.json，外部编辑后同步回画布。"""
        old_paths = self._chars_watcher.files() + self._chars_watcher.directories()
        if old_paths:
            self._chars_watcher.removePaths(old_paths)

        self._watched_chars_path = None
        if not self.current_image_path:
            return

        chars_path = self._cache_chars_path(self.current_image_path)
        if chars_path.parent.exists():
            self._chars_watcher.addPath(str(chars_path.parent))
        if chars_path.exists():
            self._chars_watcher.addPath(str(chars_path))
            self._watched_chars_path = chars_path

    def _on_watched_chars_changed(self, _path: str):
        self._schedule_external_chars_reload()

    def _on_watched_chars_directory_changed(self, _path: str):
        self._schedule_external_chars_reload()

    def _schedule_external_chars_reload(self):
        """等待外部编辑器完成写入（包括临时文件替换）后再读取。"""
        if self._pending_external_chars_reload or not self.current_image_path:
            return
        self._pending_external_chars_reload = True
        QTimer.singleShot(150, self._reload_external_chars_if_changed)

    def _reload_external_chars_if_changed(self):
        self._pending_external_chars_reload = False
        if not self.current_image_path:
            return

        chars_path = self._cache_chars_path(self.current_image_path)
        # 原子保存会先移除旧文件；短暂缺失时继续等待。
        if not chars_path.exists():
            QTimer.singleShot(150, self._schedule_external_chars_reload)
            return

        self._watch_current_chars_file()
        signature = self._file_signature(chars_path)
        if signature is None or signature == self._last_internal_chars_signature:
            return

        if self._has_unsaved_edits:
            choice = QMessageBox.question(
                self,
                "检测到外部修改",
                "当前页的 chars.json 已在外部被修改。\n\n"
                "重新载入会丢弃编辑器中尚未保存的修改。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if choice != QMessageBox.Yes:
                self.status_label.setText("保留编辑器中的未保存修改（外部文件未载入）")
                return

        if self._try_load_cache(self.current_image_path):
            self._has_unsaved_edits = False
            self._last_internal_chars_signature = None
            self.status_label.setText(f"已载入外部修改：{chars_path.name}")

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
                            "visible": c.get("visible", True),
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
                self._has_unsaved_edits = False
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
            self._has_unsaved_edits = False
            return True
        except Exception as e:
            self.status_label.setText(f'缓存加载失败：{e}；可点击"识别"重新生成')
            return False

    def split_chars(self):
        """点击"拆字"：
        - 若当前选中的是字帖目录：批量拆字该目录下所有图片
        - 若当前选中的是图片：拆字当前图片
        只重新计算 bbox，不修改字、id、author、font、work 等其他内容。
        """
        if (
            getattr(self, "split_worker", None)
            and self.split_worker
            and self.split_worker.isRunning()
        ):
            self.status_label.setText("正在拆字中，请稍候")
            return

        sel = self._current_tree_selection or {}
        kind = sel.get("kind")

        if kind == "work_dir":
            dir_path = sel.get("dir_path") or ""
            if not dir_path:
                self.status_label.setText("拆字失败：未获取到字帖目录")
                return
            self._split_work_dir(dir_path)
            return

        # 默认：拆字当前图片（或树中选中的图片）
        image_path = (
            sel.get("image_path") if kind in ("work_image", "recognized") else None
        )
        if not image_path:
            image_path = self.current_image_path
        if not image_path:
            self.status_label.setText("拆字失败：请先从左侧字帖树选择字帖或图片")
            return

        self.status_label.setText("正在拆字...")
        self.split_worker = SplitCharsWorker([image_path])
        self.split_worker.progress.connect(self._on_split_progress)
        self.split_worker.finished.connect(self._on_split_finished)
        self.split_worker.error.connect(self._on_split_error)
        self.split_worker.start()

    def _split_work_dir(self, dir_path: str):
        """批量拆字字帖目录"""
        from pathlib import Path

        wd = Path(dir_path)
        if not wd.exists() or not wd.is_dir():
            self.status_label.setText(f"拆字失败：目录不存在 {dir_path}")
            return

        # 收集所有图片
        images = []
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            images.extend(wd.glob(ext))
        images = sorted(images, key=lambda p: p.name)

        if not images:
            self.status_label.setText("拆字失败：目录下未找到图片")
            return

        self.status_label.setText(f"开始批量拆字：{wd.name}（{len(images)} 张）")
        self.split_worker = SplitCharsWorker([str(p) for p in images])
        self.split_worker.progress.connect(self._on_split_progress)
        self.split_worker.finished.connect(self._on_split_finished)
        self.split_worker.error.connect(self._on_split_error)
        self.split_worker.start()

    def _on_split_progress(
        self, idx: int, total: int, image_path: str, ok: bool, message: str
    ):
        name = Path(image_path).name
        status = "OK" if ok else "FAIL"
        self.status_label.setText(f"拆字 {idx}/{total} {status}: {name} {message}")

    def _on_split_finished(self, total: int, ok_count: int, fail_count: int):
        self.status_label.setText(
            f"拆字完成：成功 {ok_count}，失败 {fail_count}，共 {total}"
        )
        # 刷新当前图片显示
        if self.current_image_path:
            self._try_load_cache(self.current_image_path)
        if hasattr(self, "work_tree"):
            self.work_tree.refresh_recognized()

    def _on_split_error(self, error: str):
        self.status_label.setText(f"拆字异常：{error}")

    def recognize_image(self):
        """点击"识别"：
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

        # 同步不可见框的透明度
        for item in self.char_manager.items:
            if not item.visible:
                for bbox_item in self.image_canvas.bbox_items:
                    if bbox_item.item_id == item.id:
                        bbox_item.setOpacity(0.3)
                        break

        # 设置 column/row 映射，用于框的联动调整
        column_row_map = {item.id: (item.column, item.row) for item in self.char_manager.items}
        self.image_canvas.set_column_row_map(column_row_map)

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

        # 刷新左侧"已识别"列表
        if hasattr(self, "work_tree"):
            self.work_tree.refresh_recognized()

        self._select_bottom_left_char_in_current_image()

    def _select_bottom_left_char_in_current_image(self) -> None:
        """选中新页面左下角的字，使右侧单字预览始终对应当前页面。

        以边界框的真实位置为准：先取最左侧一列，再取该列最靠下的字。
        这样即使 chars.json 中的 column/row 被手工调整过，也仍符合页面上的
        "左下角"位置。
        """
        items = self.char_manager.items
        if not items:
            return

        valid_items = [
            item
            for item in items
            if len(item.bbox) == 4 and item.bbox[2] > item.bbox[0]
            and item.bbox[3] > item.bbox[1]
        ]
        if not valid_items:
            return

        # 同一竖列内的 x 中心允许有少量书写/识别偏差；用中位字宽作为容差，
        # 避免把同一列里略向右的字误判为另一列。
        widths = sorted(item.bbox[2] - item.bbox[0] for item in valid_items)
        median_width = widths[len(widths) // 2]
        left_x = min((item.bbox[0] + item.bbox[2]) / 2 for item in valid_items)
        left_column = [
            item
            for item in valid_items
            if (item.bbox[0] + item.bbox[2]) / 2 <= left_x + median_width
        ]
        chosen = max(
            left_column,
            key=lambda item: (item.bbox[1] + item.bbox[3], -item.id),
        )

        # select_bbox 会触发 selection_changed，继而同步属性面板和右侧预览。
        self.image_canvas.select_bbox(chosen.id)

    def _on_tree_item_activated(self, payload: dict):
        """点击左侧树节点快速加载"""
        self._current_tree_selection = payload

        kind = payload.get("kind")
        if kind == "work_dir":
            # 仅记录选择，不加载图片
            dir_path = payload.get("dir_path") or ""
            self.status_label.setText(
                f'已选中字帖：{Path(dir_path).name}（点击"识别"可批量识别）'
            )
            return

        image_path = payload.get("image_path") or ""
        if not image_path:
            return
        if not Path(image_path).exists():
            QMessageBox.warning(self, "错误", f"文件不存在: {image_path}")
            return
        self._load_image(image_path)

    def _navigate_work_tree_image(self, offset: int):
        """按左侧当前字帖目录的顺序切换上一页或下一页。"""
        if not self.current_image_path:
            self.status_label.setText("请先从左侧目录打开一张图片")
            return

        payload = self.work_tree.adjacent_image(self.current_image_path, offset)
        if payload is None:
            direction = "第一页" if offset < 0 else "最后一页"
            self.status_label.setText(f"当前已是该字帖的{direction}")
            return

        self._on_tree_item_activated(payload)

    def _on_tree_items_deleted(self, image_paths: list):
        """批量删除选中的图片（含缓存）"""
        if not image_paths:
            return

        names = [Path(p).name for p in image_paths]
        preview = "\n".join(names[:10])
        if len(names) > 10:
            preview += f"\n...等共 {len(names)} 个文件"

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除以下图片及其识别缓存吗？\n\n{preview}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        deleted = 0
        failed = []
        for image_path in image_paths:
            img = Path(image_path)
            try:
                # 删除图片文件
                if img.exists():
                    img.unlink()
                # 删除对应缓存目录
                debug_dir = img.parent / ".debug" / img.stem
                if debug_dir.exists():
                    import shutil
                    shutil.rmtree(debug_dir)
                deleted += 1
            except Exception as e:
                failed.append(f"{img.name}: {e}")

        # 如果当前打开的图片被删了，清空画布
        if self.current_image_path and self.current_image_path in image_paths:
            self.current_image_path = ""
            self._update_window_title()
            self.image_canvas.scene.clear()
            self.image_canvas.cv_image = None
            self.image_canvas.bbox_items.clear()
            self.image_canvas.selected_item = None
            self.char_manager.clear()
            self.char_list.load_items([])
            self.property_panel.load_item(None)

        self.work_tree.refresh_recognized()
        msg = f"已删除 {deleted} 个图片"
        if failed:
            msg += f"，失败 {len(failed)} 个"
        self.status_label.setText(msg)

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
        """点击"保存"：将当前编辑结果写回现有 json（不写 result.json）"""
        if not self.current_image_path:
            self.status_label.setText("保存失败：请先打开一张图片")
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

        ordered_items = sorted(self.char_manager.items, key=lambda x: (x.column, x.row))
        uuid_counts = {}
        for r in ordered_items:
            if r.uuid:
                uuid_counts[r.uuid] = uuid_counts.get(r.uuid, 0) + 1

        char_data = []
        for r in ordered_items:
            # 正常情况下保留既有 uuid，避免和已导出的 webp / SQLite / 云端对不上。
            # 但历史数据可能把同一个 id 复用给同页多个字；这种 id 会导致导出
            # 时文件互相覆盖，因此按字帖、页名、列、行和字内容重建稳定 id。
            if not r.uuid or uuid_counts.get(r.uuid, 0) > 1:
                md5_input = f"{r.char}_{work_dir_name}_{image_name}_{r.column}_{r.row}"
                r.uuid = hashlib.md5(md5_input.encode("utf-8")).hexdigest()
            char_data.append(
                {
                    "id": r.uuid,
                    "uuid": r.uuid,
                    "char": r.char,
                    # 元数据字段使用英文
                    "font": self.current_font or "楷书",
                    "author": self.current_author or "",
                    "work": self.current_work or "",
                    # 仅用于可追溯（不是"字帖"字段）：记录字帖目录名
                    "work_dir": work_dir_name,
                    "bbox": r.bbox,
                    "column": r.column,
                    "row": r.row,
                    "visible": r.visible,
                }
            )

        with open(chars_path, "w", encoding="utf-8") as f:
            json.dump(char_data, f, ensure_ascii=False, indent=2)
        self._last_internal_chars_signature = self._file_signature(chars_path)
        self._watch_current_chars_file()
        self._has_unsaved_edits = False

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
        """导出全部字帖，重建总库 glyphs.sqlite 与全部字图。"""
        # 避免重复触发
        if getattr(self, "export_worker", None) is not None and self.export_worker.isRunning():
            return

        # 导出始终覆盖全项目，确保总库 glyphs.sqlite 是完整索引。
        # 上传仍可根据左侧选择限定范围，二者互不影响。
        scope_work_dir = None
        self.status_label.setText("正在导出全部字帖...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # indeterminate，直到裁剪阶段拿到 total
        self._set_export_actions_enabled(False)

        self.export_worker = ExportAllWorker(
            scope_work_dir=str(scope_work_dir) if scope_work_dir else "", parent=self
        )
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
            # 选中目标字（尽量模拟"鼠标点选"效果）
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

        # 准备导出数据 - 使用 item.uuid（即 chars.json 中的 MD5 id）
        export_items = []
        for item in self.char_manager.items:
            # 优先使用 uuid（MD5 id），如果没有则使用运行时 id
            gid = item.uuid if item.uuid else str(item.id)
            export_items.append(
                {
                    "id": gid,
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
        # 列表选中后把键盘交给画布，使方向键能继续按版面移动选中字。
        self.image_canvas.setFocus()

        item = self.char_manager.get_item(item_id)
        if item:
            self.property_panel.load_item(item)
            self._update_preview(item)

    def _on_char_double_clicked(self, item_id: int):
        """字符列表双击"""
        # 聚焦到字符输入框
        self.property_panel.char_edit.setFocus()
        self.property_panel.char_edit.selectAll()

    def _compute_column_row(self, x: float, y: float, w: float, h: float) -> tuple:
        """根据位置推断新框的 column/row（基于已有框的空间分布）。"""
        existing = self.char_manager.items
        if not existing:
            return 0, 0

        cx = x + w / 2
        cy = y + h / 2

        # 按 column 分组，计算每列的平均中心 x
        from collections import defaultdict
        col_xs = defaultdict(list)
        for it in existing:
            col_xs[it.column].append(it.x + it.width / 2)
        col_avg_x = {c: sum(xs) / len(xs) for c, xs in col_xs.items()}

        # 找 x 最接近的列
        best_col = min(col_avg_x.keys(), key=lambda c: abs(cx - col_avg_x[c]))
        threshold_x = sum(it.width for it in existing) / len(existing) * 0.6
        if abs(cx - col_avg_x[best_col]) > threshold_x and cx < min(col_avg_x.values()):
            # 明显更靠左，视为新列
            best_col = max(col_avg_x.keys()) + 1

        # 在同列内推断 row
        same_col = [it for it in existing if it.column == best_col]
        if not same_col:
            return best_col, 0

        best_item = min(same_col, key=lambda it: abs(cy - (it.y + it.height / 2)))
        row = best_item.row
        threshold_y = sum(it.height for it in same_col) / len(same_col) * 0.5
        item_cy = best_item.y + best_item.height / 2
        if cy < item_cy - threshold_y:
            row -= 1
        elif cy > item_cy + threshold_y:
            row += 1

        return best_col, row

    def add_new_bbox(self):
        """在空白处添加一个与现有框平均大小相近的新框"""
        if not self.image_canvas.image_item:
            self.status_label.setText("请先打开一张图片")
            return

        # 1. 计算平均大小：取四个角上的框（不足四个则取全部）
        items = self.char_manager.items
        if not items:
            avg_w, avg_h = 60.0, 60.0
        elif len(items) <= 4:
            avg_w = sum(it.width for it in items) / len(items)
            avg_h = sum(it.height for it in items) / len(items)
        else:
            # 按中心点找四个角的框各一个
            centers = [(it.x + it.width / 2, it.y + it.height / 2, it) for it in items]
            corner_items = [
                min(centers, key=lambda t: t[0] + t[1])[2],   # 左上
                max(centers, key=lambda t: t[0] - t[1])[2],   # 右上
                max(centers, key=lambda t: t[1] - t[0])[2],   # 左下
                max(centers, key=lambda t: t[0] + t[1])[2],   # 右下
            ]
            avg_w = sum(it.width for it in corner_items) / len(corner_items)
            avg_h = sum(it.height for it in corner_items) / len(corner_items)

        scene_rect = self.image_canvas.scene.sceneRect()
        img_w, img_h = scene_rect.width(), scene_rect.height()

        # 2. 网格扫描找重叠最少的位置
        step_x = max(avg_w / 2, 20)
        step_y = max(avg_h / 2, 20)
        margin = 10

        best_pos = None
        best_overlap = float('inf')

        y = margin
        while y + avg_h + margin <= img_h:
            x = margin
            while x + avg_w + margin <= img_w:
                new_bbox = [x, y, x + avg_w, y + avg_h]
                total_overlap = 0.0
                for it in self.char_manager.items:
                    bx1, by1, bx2, by2 = it.bbox
                    ix1 = max(new_bbox[0], bx1)
                    iy1 = max(new_bbox[1], by1)
                    ix2 = min(new_bbox[2], bx2)
                    iy2 = min(new_bbox[3], by2)
                    if ix2 > ix1 and iy2 > iy1:
                        total_overlap += (ix2 - ix1) * (iy2 - iy1)

                if total_overlap == 0:
                    best_pos = (x, y)
                    best_overlap = 0
                    break
                elif total_overlap < best_overlap:
                    best_overlap = total_overlap
                    best_pos = (x, y)

                x += step_x
            if best_overlap == 0:
                break
            y += step_y

        if best_pos is None:
            best_pos = (img_w / 2 - avg_w / 2, img_h / 2 - avg_h / 2)

        x, y = best_pos
        column, row = self._compute_column_row(x, y, avg_w, avg_h)

        item = CharItem(
            id=0,
            char="",
            bbox=[x, y, x + avg_w, y + avg_h],
            column=column,
            row=row,
        )
        item = self.char_manager.add_item(item)

        self.image_canvas.add_bbox(x, y, avg_w, avg_h, item.char, item.id, highlight=(column == 0 and row == 0))
        self.char_list.load_items(self.char_manager.items)
        self.image_canvas.select_bbox(item.id)
        self.save_edits()
        self.status_label.setText(f"已添加新框并自动保存 (id={item.id}, 列{column}, 行{row})")

    def delete_selected_char(self):
        """删除当前选中的字符（框 / 列表项）"""
        if self.image_canvas.selected_items:
            self.image_canvas.delete_selected_bboxes()

    def copy_selected_bbox(self):
        """复制当前选中的单个框，供粘贴时生成一个独立的新框。"""
        if len(self.image_canvas.selected_items) != 1:
            self.status_label.setText("复制失败：请先选中一个框")
            return

        source_id = self.image_canvas.selected_items[0].item_id
        source = self.char_manager.get_item(source_id)
        if not source:
            self.status_label.setText("复制失败：找不到选中的框")
            return

        self._bbox_clipboard = {
            "char": source.char,
            "bbox": source.bbox.copy(),
            "column": source.column,
            "row": source.row,
            "visible": source.visible,
        }
        self.status_label.setText(f"已复制框：{source.char or '空字'}（列{source.column}，行{source.row}）")

    def paste_bbox(self):
        """在复制框下方的空白处粘贴，保留文字和列号并将行号加一。"""
        if not self._bbox_clipboard:
            self.status_label.setText("粘贴失败：请先复制一个框")
            return
        if not self.image_canvas.image_item:
            self.status_label.setText("粘贴失败：请先打开一张图片")
            return

        source_bbox = self._bbox_clipboard["bbox"]
        x1, y1, x2, y2 = [float(value) for value in source_bbox]
        width, height = x2 - x1, y2 - y1
        if width <= 0 or height <= 0:
            self.status_label.setText("粘贴失败：复制框尺寸无效")
            return

        image_rect = self.image_canvas.scene.sceneRect()
        step = max(height * 0.25, 8.0)
        candidate_y = y2 + max(height * 0.15, 8.0)
        pasted_bbox = None
        while candidate_y + height <= image_rect.bottom():
            candidate = [x1, candidate_y, x1 + width, candidate_y + height]
            overlaps = any(
                candidate[0] < item.bbox[2]
                and candidate[2] > item.bbox[0]
                and candidate[1] < item.bbox[3]
                and candidate[3] > item.bbox[1]
                for item in self.char_manager.items
            )
            if not overlaps:
                pasted_bbox = candidate
                break
            candidate_y += step

        if pasted_bbox is None:
            self.status_label.setText("粘贴失败：复制框下方没有足够的空白位置")
            return

        item = self.char_manager.add_item(CharItem(
            id=0,
            char=self._bbox_clipboard["char"],
            bbox=pasted_bbox,
            column=self._bbox_clipboard["column"],
            row=self._bbox_clipboard["row"] + 1,
            visible=self._bbox_clipboard["visible"],
        ))
        self.image_canvas.add_bbox(
            pasted_bbox[0], pasted_bbox[1], width, height, item.char, item.id,
            highlight=(item.column == 0 and item.row == 0),
        )
        self.image_canvas.set_column_row_map({
            current.id: (current.column, current.row)
            for current in self.char_manager.items
        })
        self.char_list.load_items(self.char_manager.items)
        self.image_canvas.select_bbox(item.id)
        self.save_edits()
        self.status_label.setText(f"已粘贴框并自动保存（列{item.column}，行{item.row}）")

    def _on_canvas_item_deleted(self, item_id: int):
        """画布删除字符后同步模型与列表"""
        self.char_manager.remove_item(item_id)
        self.char_list.load_items(self.char_manager.items)
        self.property_panel.load_item(None)
        if hasattr(self, "char_preview"):
            self.char_preview.clear()
        self.save_edits()
        self.status_label.setText(f"已删除字符并自动保存 (id={item_id})")

    def _on_canvas_items_deleted(self, item_ids: list):
        """画布批量删除字符后同步模型与列表"""
        for item_id in item_ids:
            self.char_manager.remove_item(item_id)
        self.char_list.load_items(self.char_manager.items)
        self.property_panel.load_item(None)
        if hasattr(self, "char_preview"):
            self.char_preview.clear()
        self.save_edits()
        self.status_label.setText(f"已删除 {len(item_ids)} 个字符并自动保存")

    def _on_canvas_selection_changed(self, item_id: int):
        """画布选中变化"""
        self.image_canvas.set_active_ruler_item(item_id if item_id >= 0 else None)
        if item_id >= 0:
            self.char_list.select_item(item_id)
            item = self.char_manager.get_item(item_id)
            if item:
                self.property_panel.load_item(item)
                self._update_preview(item)
        elif item_id == -2:
            # 多选状态
            selected_items = [
                self.char_manager.get_item(bbox.item_id)
                for bbox in self.image_canvas.selected_items
            ]
            self.property_panel.load_items(
                [item for item in selected_items if item is not None]
            )
            if hasattr(self, "char_preview"):
                self.char_preview.clear()
        else:
            self.property_panel.load_item(None)
            if hasattr(self, "char_preview"):
                self.char_preview.clear()

    def _on_bbox_updated(self, item_id: int, bbox: list):
        """边界框更新"""
        item = self.char_manager.get_item(item_id)
        if item:
            item.bbox = bbox
            # 只在更新当前选中框的预览时刷新，避免联动调整下方框导致预览跳动
            selected_ids = {b.item_id for b in self.image_canvas.selected_items}
            if item_id in selected_ids:
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

        self.image_canvas.refresh_column_ruler()

        # 更新属性面板（不触发信号）
        self.property_panel.update_from_item(item)
        self._update_preview(item)

    def _on_bbox_edit_committed(self, item_id: int, old_bbox: list, new_bbox: list):
        """画布提交 bbox 变更：推入撤销栈并自动保存"""

        class BBoxChangeCommand(QUndoCommand):
            def __init__(self, mw: "MainWindow", _item_id: int, _old: list, _new: list):
                super().__init__("调整框")
                self.mw = mw
                self.item_id = _item_id
                self.old = _old
                self.new = _new

            def undo(self):
                self.mw._apply_bbox(self.item_id, self.old)
                self.mw.save_edits()

            def redo(self):
                self.mw._apply_bbox(self.item_id, self.new)
                self.mw.save_edits()

        self.undo_stack.push(BBoxChangeCommand(self, item_id, old_bbox, new_bbox))
        self.save_edits()

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
            self.save_edits()

    def _on_property_batch_char_changed(self, item_ids: list, char: str):
        """把右侧面板输入的单字写入当前所有选框。"""
        if len(char) != 1:
            return

        selected_ids = set(item_ids)
        changed = 0
        for item in self.char_manager.items:
            if item.id not in selected_ids:
                continue
            item.char = char
            self.char_list.update_item_char(item.id, char)
            for bbox_item in self.image_canvas.bbox_items:
                if bbox_item.item_id == item.id:
                    bbox_item.update_char(char)
                    break
            changed += 1

        if changed:
            self.save_edits()
            self.status_label.setText(f"已批量写入“{char}”到 {changed} 个选框")

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

            self.image_canvas.refresh_column_ruler()

            self._update_preview(item)
            self.save_edits()

    def _on_property_font_changed(self, font: str):
        self.current_font = font or "楷书"
        self.save_edits()

    def _on_property_author_changed(self, author: str):
        self.current_author = author or ""
        self.save_edits()

    def _on_property_work_changed(self, work: str):
        self.current_work = work or ""
        self.save_edits()

    def _on_property_visible_changed(self, item_id: int, visible: bool):
        """属性面板可见性变化"""
        item = self.char_manager.get_item(item_id)
        if item:
            item.visible = visible
            # 同步画布视觉：不可见时降低透明度
            for bbox_item in self.image_canvas.bbox_items:
                if bbox_item.item_id == item_id:
                    if visible:
                        bbox_item.setOpacity(1.0)
                    else:
                        bbox_item.setOpacity(0.3)
                    break
            self.save_edits()

    def _on_property_row_changed(self, item_id: int, row: int):
        """属性面板行变化"""
        item = self.char_manager.get_item(item_id)
        if item:
            item.row = row
            self._sync_bbox_highlight(item)
            self.property_panel.load_item(item)
            self.save_edits()

    def _on_property_column_changed(self, item_id: int, column: int):
        """属性面板列变化"""
        item = self.char_manager.get_item(item_id)
        if item:
            item.column = column
            self.image_canvas.set_column_row_map({
                current.id: (current.column, current.row)
                for current in self.char_manager.items
            })
            self.image_canvas.set_active_ruler_item(item_id)
            self._sync_bbox_highlight(item)
            self.property_panel.load_item(item)
            self.save_edits()

    def _sync_bbox_highlight(self, item: CharItem):
        """同步画布高亮状态（row=column=0 时高亮）"""
        for bbox_item in self.image_canvas.bbox_items:
            if bbox_item.item_id == item.id:
                bbox_item.set_highlight(item.column == 0 and item.row == 0)
                break

    def _update_preview(self, item: CharItem):
        if not hasattr(self, "char_preview"):
            return
        img = self.image_canvas.get_cv_image()
        meta = f"id: {item.id} | 列{item.column} 行{item.row} | idx {item.global_index}"
        if self.current_image_path:
            uuid_val = item.uuid or str(item.id)
            webp_path = Path(self.current_image_path).parent / "words" / f"{uuid_val}.webp"
            if webp_path.exists():
                name = webp_path.name
                # 长文件名每隔 24 个字符插入换行，避免 QLabel 不换行
                if len(name) > 24:
                    name = "\n".join(name[i : i + 24] for i in range(0, len(name), 24))
                meta += f"\n已导出：{name}"
        self.char_preview.update_preview(img, item.char, item.bbox, meta=meta)

    def _on_preview_upload_requested(self):
        """预览框点击上传：只上传当前选中的单字"""
        if not self.current_image_path:
            QMessageBox.warning(self, "上传", "请先打开一张图片")
            return

        # 获取当前选中的字
        selected_bbox = self.image_canvas.selected_item
        if not selected_bbox:
            QMessageBox.warning(self, "上传", "请先选中一个字")
            return

        item = self.char_manager.get_item(selected_bbox.item_id)
        if not item:
            QMessageBox.warning(self, "上传", "未找到当前字的记录")
            return

        uuid_val = item.uuid or str(item.id)
        work_dir = Path(self.current_image_path).parent
        webp_path = work_dir / "words" / f"{uuid_val}.webp"
        if not webp_path.exists():
            QMessageBox.warning(self, "上传", f"未找到导出的 webp：{webp_path.name}\n请先导出再上传")
            return

        # 读取配置
        cloud_name, api_key, api_secret, upload_preset, unsigned, remote_folder = self._read_upload_config_from_env()
        if not cloud_name:
            QMessageBox.warning(self, "上传", "未配置 Cloudinary cloud_name")
            return

        # 上传
        self.status_label.setText(f"正在上传：{item.char} ({webp_path.name})")
        try:
            from upload_webp_cloudinary import collect_upload_items, upload_items, UploadItem

            # public_id 保持和批量上传一致：words__<uuid>
            public_id = f"words__{uuid_val}"
            it = UploadItem(
                abs_path=webp_path,
                rel_path=webp_path.name,
                size_bytes=webp_path.stat().st_size,
                public_id=public_id,
            )
            results = upload_items(
                items=[it],
                cloud_name=cloud_name,
                api_key=api_key,
                api_secret=api_secret,
                unsigned=unsigned,
                upload_preset=upload_preset,
                folder=remote_folder,
                timeout_s=60,
                concurrency=1,
            )
            r = results[0]
            if r.ok:
                self.status_label.setText(f"上传成功：{item.char} → {r.url}")
                QMessageBox.information(self, "上传成功", f"字：{item.char}\nURL：{r.url}")
            else:
                self.status_label.setText(f"上传失败：{r.error}")
                QMessageBox.warning(self, "上传失败", f"字：{item.char}\n错误：{r.error}")
                QMessageBox.warning(self, "上传失败", f"字：{item.char}\n错误：{r.error}")
        except Exception as e:
            self.status_label.setText(f"上传异常：{e}")
            QMessageBox.warning(self, "上传异常", str(e))

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
