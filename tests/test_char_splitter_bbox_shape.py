import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr.char_splitter import CharSplitter


class CharSplitterBBoxShapeTest(unittest.TestCase):
    def test_shrink_x_expands_narrow_content_toward_square_when_room_exists(self):
        image = np.full((100, 200, 3), 255, dtype=np.uint8)
        image[:, 98:102] = 0

        bbox = CharSplitter()._shrink_x(image, [0, 0, 200, 100])

        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        self.assertAlmostEqual(height, width, delta=1.0)
        self.assertLessEqual(bbox[0], 98)
        self.assertGreaterEqual(bbox[2], 102)

    def test_shrink_x_uses_full_column_when_height_exceeds_available_width(self):
        image = np.full((120, 100, 3), 255, dtype=np.uint8)
        image[:, 48:52] = 0

        bbox = CharSplitter()._shrink_x(image, [20, 0, 80, 120])

        self.assertEqual([20.0, 0.0, 80.0, 120.0], bbox)


if __name__ == "__main__":
    unittest.main()
