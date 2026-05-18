import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr.recognizer import CalligraphyOCR


class RecognizerColumnFilteringTest(unittest.TestCase):
    def test_empty_wide_block_does_not_hide_narrow_main_columns(self):
        parsed_results = [
            {"text": "", "bbox": [0.0, 0.0, 179.0, 600.0]},
            {"text": "薄改環催造次歲規甘棠", "bbox": [187.392, 81.6, 234.496, 525.0]},
            {"text": "南寧納駕肥惻陰似息履", "bbox": [251.904, 81.0, 296.96, 524.4]},
            {"text": "宰手賊釋躭拓絳煒寵", "bbox": [317.44, 79.8, 363.52, 524.4]},
            {"text": "讀易口餒論車策頓盜", "bbox": [379.904, 80.4, 430.08, 526.2]},
            {"text": "尋求古察沉點逍遙", "bbox": [450.56, 78.6, 500.736, 523.2]},
            {"text": "驢慄石碣沙漠宣威我", "bbox": [528.384, 77.4, 581.632, 526.8]},
            {"text": "音属耳梦之幸即穑嗣", "bbox": [598.016, 76.8, 653.312, 527.4]},
            {"text": "銀秦垣箱譏滅迴傾丁", "bbox": [663.552, 76.8, 721.92, 527.4]},
            {"text": "門綿邈失魚孟豕省躬", "bbox": [732.16, 77.4, 783.36, 525.6]},
            {"text": "笙鼓瑟伊尹阿衡鷹", "bbox": [792.576, 76.2, 850.944, 525.6]},
            {"text": "Q", "bbox": [980.992, 546.0, 1016.832, 586.8]},
        ]
        image = np.full((600, 1024, 3), 255, dtype=np.uint8)

        chars = CalligraphyOCR()._split_columns_to_chars(parsed_results, image=image)

        self.assertGreater(len(chars), 0)
        self.assertEqual("笙", chars[0]["char"])
        self.assertNotIn("Q", "".join(c["char"] for c in chars))


if __name__ == "__main__":
    unittest.main()
