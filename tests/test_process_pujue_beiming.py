import sys
import unittest
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

spec = importlib.util.spec_from_file_location(
    "process_pujue_beiming",
    PROJECT_ROOT / "scripts" / "process_pujue_beiming.py",
)
process_pujue_beiming = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["process_pujue_beiming"] = process_pujue_beiming
spec.loader.exec_module(process_pujue_beiming)

distribute_counts = process_pujue_beiming.distribute_counts
parse_page_spec = process_pujue_beiming.parse_page_spec
split_text_by_counts = process_pujue_beiming.split_text_by_counts
strip_fixed_prefix = process_pujue_beiming.strip_fixed_prefix


class ProcessPujueBeimingTest(unittest.TestCase):
    def test_strip_fixed_prefix_cleans_common_sidebar_ocr_noise(self):
        raw = "王宁普覺國師碑高麗國華山曹溪宗麟角寺述智山下普覺國\n.com"

        self.assertEqual(
            "高麗國華山曹溪宗麟角寺迦智山下普覺國",
            strip_fixed_prefix(raw),
        )

    def test_strip_fixed_prefix_handles_misread_prefix_and_titles(self):
        self.assertEqual(
            "尊碑銘并序宣授朝列大夫遙授翰林直學",
            strip_fixed_prefix("王字晋覺國師碑尊碑銘并序宣授朝列太夫遥授翰林直學"),
        )
        self.assertEqual(
            "焉國尊諱見明字晦然後易名一然俗姓金氏",
            strip_fixed_prefix("王字曾覺國師碑焉國尊諱見明字晦然後易名一然俗姓金氏"),
        )
        self.assertEqual(
            "共仰當與一國共之於是",
            strip_fixed_prefix("一品覺國師碑共仰當與一國共之於是"),
        )
        self.assertEqual(
            "師上表固讓上復遣使牢請至三仍命上將軍",
            strip_fixed_prefix("上官覺國師碑師上表固讓上復遣使牢請至三仍命上將軍"),
        )

    def test_strip_fixed_prefix_keeps_title_page_text(self):
        self.assertEqual(
            "普覺國師碑銘",
            strip_fixed_prefix("集王字 普觉国师碑 普觉国师碑铭"),
        )
        self.assertEqual("普覺國師碑銘", strip_fixed_prefix("普觉国师碑铭"))

    def test_parse_page_spec_accepts_single_pages_and_ranges(self):
        self.assertEqual(
            {"fatie-000", "fatie-001", "fatie-009", "fatie-010", "fatie-011"},
            parse_page_spec("000,001,009-011"),
        )

    def test_distribute_counts_prefers_even_columns_when_text_divides(self):
        self.assertEqual([6, 6, 6], distribute_counts(18, 3, [5, 6, 6]))

    def test_distribute_counts_uses_estimates_when_they_match_total(self):
        self.assertEqual([5, 6, 6], distribute_counts(17, 3, [5, 6, 6]))

    def test_distribute_counts_handles_fewer_chars_than_columns(self):
        counts = distribute_counts(2, 3, [1, 1, 1])

        self.assertEqual(2, sum(counts))
        self.assertEqual(3, len(counts))
        self.assertTrue(all(count >= 0 for count in counts))

    def test_split_text_by_counts(self):
        self.assertEqual(["普覺", "國師碑", "銘"], split_text_by_counts("普覺國師碑銘", [2, 3, 1]))


if __name__ == "__main__":
    unittest.main()
