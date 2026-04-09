"""
字符数据模型
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class CharItem:
    """字符项数据模型"""

    id: int
    char: str
    uuid: str = ""  # 持久化 id（写入 chars.json）
    bbox: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])  # [x1, y1, x2, y2]
    column: int = 0
    row: int = 0
    global_index: int = 0
    split_method: str = ""

    @property
    def x(self) -> float:
        return self.bbox[0]

    @x.setter
    def x(self, value: float):
        self.bbox[0] = value

    @property
    def y(self) -> float:
        return self.bbox[1]

    @y.setter
    def y(self, value: float):
        self.bbox[1] = value

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @width.setter
    def width(self, value: float):
        self.bbox[2] = self.bbox[0] + value

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @height.setter
    def height(self, value: float):
        self.bbox[3] = self.bbox[1] + value

    @property
    def rect(self) -> tuple:
        """返回 (x, y, width, height) 格式"""
        return (self.x, self.y, self.width, self.height)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.uuid if self.uuid else str(self.id),
            "uuid": self.uuid,
            "char": self.char,
            "bbox": self.bbox.copy(),
            "column": self.column,
            "row": self.row,
            "global_index": self.global_index,
            "split_method": self.split_method,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CharItem":
        """从字典创建"""
        # 处理 id 字段：如果是字符串（如 MD5），存入 uuid；数值型存入 id
        raw_id = data.get("id", 0)
        uuid_val = data.get("uuid", "")
        if isinstance(raw_id, str):
            # MD5/UUID 格式的 id，存入 uuid
            uuid_val = raw_id
            item_id = 0  # 运行时由 manager 分配
        else:
            item_id = raw_id
        return cls(
            id=item_id,
            uuid=uuid_val,
            char=data.get("char", ""),
            bbox=data.get("bbox", [0, 0, 0, 0]).copy(),
            column=data.get("column", 0),
            row=data.get("row", 0),
            global_index=data.get("global_index", 0),
            split_method=data.get("split_method", ""),
        )


class CharItemManager:
    """字符项管理器"""

    def __init__(self):
        self.items: List[CharItem] = []
        self._next_id = 0

    def add_item(self, item: CharItem) -> CharItem:
        """添加字符项"""
        item.id = self._next_id
        self._next_id += 1
        self.items.append(item)
        return item

    def remove_item(self, item_id: int) -> Optional[CharItem]:
        """移除字符项"""
        for i, item in enumerate(self.items):
            if item.id == item_id:
                return self.items.pop(i)
        return None

    def get_item(self, item_id: int) -> Optional[CharItem]:
        """获取字符项"""
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def clear(self):
        """清空所有项"""
        self.items.clear()
        self._next_id = 0

    def load_from_ocr_result(self, result: Dict[str, Any]):
        """从 OCR 结果加载"""
        self.clear()
        char_results = result.get("char_results", [])
        for i, char_data in enumerate(char_results):
            item = CharItem(
                id=i,
                uuid=str(char_data.get("uuid") or ""),
                char=char_data.get("char", ""),
                bbox=char_data.get("bbox", [0, 0, 0, 0]).copy(),
                column=char_data.get("column", 0),
                row=char_data.get("row", 0),
                global_index=char_data.get("global_index", 0),
                split_method=char_data.get("split_method", ""),
            )
            self.items.append(item)
        self._next_id = len(self.items)

    def to_export_format(self) -> List[Dict[str, Any]]:
        """导出为字典列表"""
        return [item.to_dict() for item in self.items]
