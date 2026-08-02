"""应用内罕见汉字字体。"""

from pathlib import Path

from PyQt5.QtGui import QFont, QFontDatabase


FONT_FILES = ["BabelStoneHan.ttf", "HanaMinB.otf", "Jigmo2.ttf"]
FONT_FAMILIES = ["BabelStone Han", "Hanazono Mincho B", "Jigmo2"]


def load_embedded_fonts() -> bool:
    """注册随应用分发的扩展汉字字体，返回是否成功。"""
    fonts_dir = (Path(__file__).parent.parent / "assets" / "fonts").resolve()
    loaded = True
    # 不使用 all(generator)：某个字体加载失败时仍应继续注册后续回退字体。
    for filename in FONT_FILES:
        path = fonts_dir / filename
        if not path.exists() or QFontDatabase.addApplicationFont(str(path)) == -1:
            loaded = False
    return loaded


def extended_cjk_font(point_size: int, bold: bool = False) -> QFont:
    """创建优先使用应用内扩展汉字字体的 QFont。"""
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSize(point_size)
    font.setBold(bold)
    return font
