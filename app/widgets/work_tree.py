""" 
字帖页面选择树（包含已识别列表）

用途：
- 启动时扫描项目根目录下的字帖图片（各作品目录下的 fatie-*.jpg）
- 扫描 <字帖目录>/.debug/<stem>/result.json 的识别结果
- 点击树节点即可快速加载对应图片/缓存
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional, List

from PyQt5.QtCore import Qt, pyqtSignal, QEvent
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QAbstractItemView,
    QMenu,
    QAction,
)


class WorkTreeWidget(QWidget):
    """左侧树状结构：字帖/已识别"""

    # payload:
    # - {"kind": "work_dir", "dir_path": str}
    # - {"kind": "work_image"|"recognized", "image_path": str, "cache_path": str|None}
    item_activated = pyqtSignal(dict)
    visibility_changed = pyqtSignal(bool)
    # 批量删除图片：list of image_path
    items_deleted = pyqtSignal(list)

    def __init__(self, project_root: Path, parent=None):
        super().__init__(parent)
        self.project_root = Path(project_root)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(self._on_item_activated)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(6)
        layout.addWidget(self.tree, 1)

        self._root_recognized: Optional[QTreeWidgetItem] = None
        self._root_works: Optional[QTreeWidgetItem] = None

        # image_abs_path -> tree item
        self._image_item_map: Dict[str, QTreeWidgetItem] = {}
        # dir_abs_path -> tree item
        self._dir_item_map: Dict[str, QTreeWidgetItem] = {}

        # 展开/折叠状态（折叠时隐藏 tree 并收窄宽度）
        self._collapsed = False

        # 防止内部 setCurrentItem 触发 currentItemChanged 导致循环
        self._suppress_activation = False

        self.rebuild()

    def set_collapsed(self, collapsed: bool):
        """折叠/展开字帖树"""
        self._collapsed = bool(collapsed)
        visible = not self._collapsed
        self.tree.setVisible(visible)

        if visible:
            self.setMinimumWidth(220)
            self.setMaximumWidth(360)
        else:
            # 折叠时尽量收窄（只留一条灰条）
            self.setMinimumWidth(28)
            self.setMaximumWidth(28)

        self.visibility_changed.emit(visible)

    def toggle_collapsed(self):
        self.set_collapsed(not self._collapsed)

    def ensure_visible(self):
        """确保树可见（不自动折叠）"""
        if self._collapsed:
            self.set_collapsed(False)

    def select_image(self, image_path: str):
        """在树中选中并定位到图片节点"""
        if not image_path:
            return
        self.ensure_visible()

        key = str(Path(image_path).resolve())
        item = self._image_item_map.get(key)
        if not item:
            return

        # 展开父节点
        p = item.parent()
        while p is not None:
            p.setExpanded(True)
            p = p.parent()

        self._suppress_activation = True
        try:
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)
        finally:
            self._suppress_activation = False

    def rebuild(self):
        """重建整棵树"""
        # 记录展开状态与当前选中项，避免刷新后折叠/跳走
        expanded_dirs = set()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            payload = top.data(0, Qt.UserRole)
            if top.isExpanded() and isinstance(payload, dict) and payload.get("kind") == "work_dir":
                dp = payload.get("dir_path")
                if dp:
                    expanded_dirs.add(str(Path(dp).resolve()))

        selected = None
        cur = self.tree.currentItem()
        if cur is not None:
            payload = cur.data(0, Qt.UserRole)
            if isinstance(payload, dict):
                selected = payload

        self.tree.clear()
        self._image_item_map.clear()
        self._dir_item_map.clear()

        # 直接展示字帖目录树（作品目录 -> 图片），识别过的图片打标记
        self._populate_works_as_top_level()

        # 恢复展开状态
        for dp in expanded_dirs:
            node = self._dir_item_map.get(dp)
            if node:
                node.setExpanded(True)

        # 恢复选中项
        if isinstance(selected, dict):
            kind = selected.get("kind")
            if kind in ("work_image", "recognized"):
                self.select_image(selected.get("image_path") or "")
            elif kind == "work_dir":
                dp = selected.get("dir_path")
                if dp:
                    node = self._dir_item_map.get(str(Path(dp).resolve()))
                    if node:
                        self.ensure_visible()
                        self._suppress_activation = True
                        try:
                            self.tree.setCurrentItem(node)
                            self.tree.scrollToItem(node)
                        finally:
                            self._suppress_activation = False

    def refresh_recognized(self):
        """刷新识别标记（识别状态变化后重建树即可）"""
        self.rebuild()

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int):
        payload = item.data(0, Qt.UserRole)
        if isinstance(payload, dict) and payload.get("kind") in ("work_dir", "work_image", "recognized"):
            self.item_activated.emit(payload)

    def _on_current_item_changed(self, current: Optional[QTreeWidgetItem], previous: Optional[QTreeWidgetItem]):
        if self._suppress_activation or current is None:
            return
        payload = current.data(0, Qt.UserRole)
        if isinstance(payload, dict) and payload.get("kind") in ("work_dir", "work_image", "recognized"):
            self.item_activated.emit(payload)

    def _on_item_activated(self, item: QTreeWidgetItem, _col: int):
        payload = item.data(0, Qt.UserRole)
        if isinstance(payload, dict) and payload.get("kind") in ("work_dir", "work_image", "recognized"):
            self.item_activated.emit(payload)

    def eventFilter(self, obj, event):
        if obj is self.tree and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                self._delete_selected_items()
                return True
        return super().eventFilter(obj, event)

    def _on_context_menu(self, pos):
        """右键菜单"""
        item = self.tree.itemAt(pos)
        if item is None:
            return
        payload = item.data(0, Qt.UserRole)
        if not isinstance(payload, dict):
            return

        kind = payload.get("kind")
        menu = QMenu(self)

        if kind == "work_dir":
            dir_path = payload.get("dir_path", "")
            if not dir_path:
                return
            open_action = QAction("打开所在文件夹", self)
            open_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(dir_path)))
            menu.addAction(open_action)

            words_dir = str(Path(dir_path) / "words")
            words_action = QAction("展示 Words 文件夹", self)
            words_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(words_dir)))
            menu.addAction(words_action)

        elif kind in ("work_image", "recognized"):
            image_path = payload.get("image_path", "")
            if not image_path:
                return
            dir_path = str(Path(image_path).parent)
            stem = Path(image_path).stem

            open_action = QAction("打开所在文件夹", self)
            open_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(dir_path)))
            menu.addAction(open_action)

            debug_dir = str(Path(dir_path) / ".debug" / stem)
            debug_action = QAction("展示 debug", self)
            debug_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(debug_dir)))
            menu.addAction(debug_action)

            words_dir = str(Path(dir_path) / "words")
            words_action = QAction("展示 Words 文件夹", self)
            words_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(words_dir)))
            menu.addAction(words_action)

        else:
            return

        if menu.actions():
            menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def _delete_selected_items(self):
        """收集当前选中的图片节点并发出删除信号（不删除目录节点）"""
        selected = self.tree.selectedItems()
        image_paths = []
        for item in selected:
            payload = item.data(0, Qt.UserRole)
            if isinstance(payload, dict) and payload.get("kind") in ("work_image", "recognized"):
                image_path = payload.get("image_path")
                if image_path:
                    image_paths.append(image_path)
        if image_paths:
            self.items_deleted.emit(image_paths)

    def _build_recognized_index(self) -> Dict[str, Dict[str, Any]]:
        """构建已完成索引：image_abs_path -> {cache_path, total_chars}

        判定规则：对应图片存在 `.debug/<stem>/chars.json` 即视为完成。
        """
        idx: Dict[str, Dict[str, Any]] = {}

        for work_dir in [p for p in self.project_root.iterdir() if p.is_dir()]:
            debug_dir = work_dir / ".debug"
            if not debug_dir.exists():
                continue

            for chars_path in debug_dir.glob("*/chars.json"):
                try:
                    with open(chars_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue

                if not isinstance(data, list):
                    continue

                total_chars = len(data)

                # 推导图片路径：<字帖目录>/<stem>.(jpg/jpeg/png/bmp/webp)
                stem = chars_path.parent.name
                found = None
                for ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
                    cand = work_dir / f"{stem}{ext}"
                    if cand.exists():
                        found = str(cand.resolve())
                        break
                if not found:
                    continue
                image_abs = found
                idx[image_abs] = {
                    "cache_path": str(chars_path.resolve()),
                    "total_chars": total_chars,
                }

        return idx

    def _has_fatie_images(self, work_dir: Path) -> bool:
        """检查目录是否包含 fatie-* 图片（支持 jpg/jpeg/png/bmp/webp）"""
        for ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
            if any(work_dir.glob(f"fatie-*{ext}")):
                return True
        return False

    def _list_fatie_images(self, work_dir: Path) -> list:
        """列出目录下所有 fatie-* 图片（支持 jpg/jpeg/png/bmp/webp）"""
        imgs = []
        for ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
            imgs.extend(work_dir.glob(f"fatie-*{ext}"))
        return sorted(imgs, key=lambda p: p.name)

    def _populate_works_as_top_level(self):
        # 过滤掉非字帖目录
        ignore = {
            "ocr",
            "ocr_output",
            "app",
            "__pycache__",
            ".git",
            ".idea",
            ".vscode",
        }

        recognized = self._build_recognized_index()

        work_dirs = []
        for p in self.project_root.iterdir():
            if not p.is_dir():
                continue
            if p.name in ignore:
                continue
            # 字帖目录：包含至少一个 fatie-* 图片（支持 jpg/jpeg/png/bmp/webp）
            if self._has_fatie_images(p):
                work_dirs.append(p)

        if not work_dirs:
            self.tree.addTopLevelItem(QTreeWidgetItem(["(未发现字帖目录)"]))
            return

        for wd in sorted(work_dirs, key=lambda p: p.name):
            # 作品目录直接作为顶层节点
            imgs = self._list_fatie_images(wd)
            total = len(imgs)
            done = 0
            for img in imgs:
                if str(img.resolve()) in recognized:
                    done += 1
            percent = 0
            if total > 0:
                percent = int(round(done * 100 / total))

            wnode = QTreeWidgetItem([f"{wd.name} ({percent}%)"])
            wnode.setData(
                0,
                Qt.UserRole,
                {
                    "kind": "work_dir",
                    "dir_path": str(wd.resolve()),
                },
            )
            wnode.setExpanded(wd.name.startswith("怀仁集王羲之圣教序"))
            self.tree.addTopLevelItem(wnode)

            self._dir_item_map[str(wd.resolve())] = wnode

            for img in self._list_fatie_images(wd):
                image_abs = str(img.resolve())
                rec = recognized.get(image_abs)
                label = img.name
                if rec:
                    # 打标记：已识别
                    extra = ""
                    if isinstance(rec.get("total_chars"), int):
                        extra = f" | {rec['total_chars']}字"
                    label = f"{img.name}  [已识别]{extra}"

                inode = QTreeWidgetItem([label])
                inode.setData(
                    0,
                    Qt.UserRole,
                    {
                        "kind": "work_image" if not rec else "recognized",
                        "image_path": image_abs,
                        "cache_path": rec.get("cache_path") if rec else "",
                    },
                )
                wnode.addChild(inode)

                # 索引，用于快速定位
                self._image_item_map[image_abs] = inode
