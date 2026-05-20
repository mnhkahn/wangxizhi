import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

spec = importlib.util.spec_from_file_location(
    "fix_pujue_col_row",
    PROJECT_ROOT / "scripts" / "fix_pujue_col_row.py",
)
fix_pujue_col_row = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["fix_pujue_col_row"] = fix_pujue_col_row
spec.loader.exec_module(fix_pujue_col_row)

group_chars_by_bbox = fix_pujue_col_row.group_chars_by_bbox
parse_page_spec = fix_pujue_col_row.parse_page_spec
rebuild_result = fix_pujue_col_row.rebuild_result


class FixPujueColRowTest(unittest.TestCase):
    def test_parse_page_spec_keeps_order(self):
        self.assertEqual(
            ["fatie-000", "fatie-001", "fatie-002", "fatie-005"],
            parse_page_spec("000-002,005"),
        )

    def test_group_chars_by_bbox_reassigns_moved_character_to_left_column(self):
        chars = [
            {"char": "尊", "bbox": [760, 0, 1000, 300], "column": 0, "row": 0},
            {"char": "碑", "bbox": [760, 320, 1000, 620], "column": 0, "row": 1},
            {"char": "宣", "bbox": [430, 0, 690, 300], "column": 1, "row": 0},
            {"char": "夫", "bbox": [430, 320, 690, 620], "column": 1, "row": 1},
            {"char": "遙", "bbox": [80, 0, 350, 250], "column": 1, "row": 2},
            {"char": "授", "bbox": [80, 260, 350, 540], "column": 2, "row": 0},
        ]

        grouped = group_chars_by_bbox(chars)

        self.assertEqual(["尊碑", "宣夫", "遙授"], ["".join(c["char"] for c in col) for col in grouped])
        self.assertEqual((2, 0), (chars[4]["column"], chars[4]["row"]))
        self.assertEqual((2, 1), (chars[5]["column"], chars[5]["row"]))

    def test_group_chars_by_bbox_keeps_visible_false_items_in_text_order(self):
        chars = [
            {"char": "普", "bbox": [620, 0, 1040, 300], "visible": False},
            {"char": "覺", "bbox": [620, 320, 1040, 620], "visible": False},
            {"char": "師", "bbox": [80, 0, 560, 300], "visible": False},
        ]

        grouped = group_chars_by_bbox(chars)

        self.assertEqual(["普覺", "師"], ["".join(c["char"] for c in col) for col in grouped])
        self.assertEqual((0, 0), (chars[0]["column"], chars[0]["row"]))
        self.assertEqual((0, 1), (chars[1]["column"], chars[1]["row"]))
        self.assertEqual((1, 0), (chars[2]["column"], chars[2]["row"]))

    def test_rebuild_result_uses_grouped_text_and_column_metadata(self):
        chars = [
            {"char": "A", "bbox": [300, 0, 350, 50], "column": 0, "row": 0},
            {"char": "B", "bbox": [300, 60, 350, 110], "column": 0, "row": 1},
            {"char": "C", "bbox": [100, 0, 150, 50], "column": 1, "row": 0},
        ]
        grouped = group_chars_by_bbox(chars)

        result = rebuild_result({"image_info": {"width": 400}}, grouped)

        self.assertEqual("ABC", result["recognized_text"])
        self.assertEqual(2, result["column_count"])
        self.assertEqual([0, 0, 1], [c["column"] for c in result["char_results"]])
        self.assertEqual([0, 1, 0], [c["row"] for c in result["char_results"]])


if __name__ == "__main__":
    unittest.main()
