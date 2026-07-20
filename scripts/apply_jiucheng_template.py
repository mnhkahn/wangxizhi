#!/usr/bin/env python3
"""按第三页的四列六字框型，批量校正《九成宫醴泉铭》字框与释文。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1] / "欧阳询-楷书-九成宫醴泉铭"

# 采用已核对的《全唐文》卷一四一通行释文；保留帖中使用的传统字形。
SOURCE = """維貞觀六年孟夏之月皇帝避暑乎九成之宮此則隋之仁壽宮也冠山抗殿絕壑為池跨水架楹分巖聳闕高閣周建長廊四起棟宇膠葛臺榭參差仰視則迢遞百尋下臨則崢嶸千仞珠璧交映金碧相輝照灼雲霞蔽虧日月觀其移山迴澗窮泰極侈以人從欲良足深尤至於炎景流金無鬱蒸之氣微風徐動有淒清之涼信安體之佳所誠養神之勝地漢之甘泉不能尚也皇帝爰在弱冠經營四方逮乎立年撫臨億兆始以武功壹海內終以文德懷遠人東越青丘南逾丹徼皆獻琛贄重譯來王西暨輪臺北拒玄闕並地列州縣人充編戶氣淑年和邇安遠肅群生咸遂靈貺畢臻雖藉二儀之功終資一人之慮遺身利物櫛風沐雨百姓為心憂勞成疾同堯肌之如臘甚禹足之胼胝針石屢加腠理猶滯爰居京室每避炎暑群下請建離宮庶可怡神養性聖上愛一夫之力惜十家之產深閉固拒未肯俯從以為隋氏舊宮營於曩代棄之則可惜毀之則重勞事貴因循何必改作於是斫雕為樸損之又損去其泰甚葺其頹壞雜丹墀以沙礫閒粉壁以塗泥玉砌接於土階茅茨續於瓊室仰觀壯麗可作鑒於既往俯察卑儉足垂訓於後昆此所謂至人無為大聖不作彼竭其力我享其功者也然昔之池沼咸引谷澗宮城之內本乏水源求而無之在乎一物既非人力所致聖心懷之不忘粵以四月甲申朔旬有六日己亥上及中宮歷覽臺觀閒步西城之陰躊躇高閣之下俯察厥土微覺有潤因而以杖導之有泉隨而湧出乃承以石檻引為一渠其清若鏡味甘如醴南注丹霄之右東流度於雙闕貫穿青瑣縈帶紫房激揚清波滌蕩瑕穢可以導養正性可以澄瑩心神鑒映群形潤生萬物同湛恩之不竭將玄澤之常流匪唯乾象之精蓋亦坤靈之寶謹按禮緯云王者刑殺當罪賞錫當功得禮之宜則醴泉出於闕庭鶡冠子曰聖人之德上及太清下及太寧中及萬靈則醴泉出瑞應圖曰王者純和飲食不貢獻則醴泉出飲之令人壽東觀漢紀曰光武中元元年醴泉出於京師飲之者痼疾皆愈然則神物之來寔扶明聖既可蠲兹沉痼又將延彼遐齡是以百辟卿士相趨動色我后固懷撝挹推而弗有雖休勿休不徒聞於往昔以祥為懼實取驗於當今斯乃上帝玄符天子令德豈臣之末學所能丕顯但職在記言屬兹書事不可使國之盛美有遺典策敢陳實錄爰勒斯銘其詞曰惟皇撫運奄壹寰宇千載膺期萬物斯覩功高大舜勤深伯禹絕後光前登三邁五握機蹈矩乃聖乃神武克禍亂文懷遠人書契未紀開闢不臣冠冕並襲琛贄咸陳大道無名上德不德玄功潛運幾深莫測鑿井而飲耕田而食靡謝天功安知帝力上天之載無臭無聲萬類資始品物流形隨感變質應德效靈介焉如響赫赫明明雜遝景福葳蕤繁祉雲氏龍官龜圖鳳紀日含五色烏呈三趾頌不輟工筆無停史上善降祥上智斯悅流謙潤下潺湲皎潔蓱旨醴甘冰凝鏡澈用之日新挹之無竭道隨時泰慶與泉流我后夕惕雖休弗休居崇茅宇樂不般遊黃屋非貴天下為憂人玩其華我取其實還淳反本代文以質居高思墜持滿戒溢念兹在兹永保貞吉"""

# 页图并非底本文字顺序；每项是该图最右列的首字起始位置。第 1、2 页保留人工校正。
PAGE_START = {
    3: "刑殺當罪賞錫", 4: "之勝地漢之甘", 5: "棄之則可惜", 6: "日月觀其移山",
    7: "闕庭鶡冠子曰", 8: "玄澤之常流", 9: "贄咸陳大道無", 10: "物流形隨感變",
    11: "州縣人充編戶", 12: "一人之慮遺身", 13: "成疾同堯肌之", 14: "京室每避炎暑",
    15: "深閉固拒未肯", 16: "棄之則可惜", 17: "損之又損去其", 18: "仰觀壯麗可作",
    19: "作彼竭其力我", 20: "其功者也然昔", 21: "無之在乎一物", 22: "歷覽臺觀閒步",
    23: "高閣之下俯察", 24: "乃承以石檻引", 25: "度於雙闕貫穿", 26: "養正性可以澄",
    27: "玄澤之常流", 28: "刑殺當罪賞錫", 29: "人之德上及太", 30: "者純和飲食不",
    31: "中元元年醴泉出", 32: "明聖既可蠲兹", 33: "我后固懷撝挹", 34: "實取驗於當今",
    35: "能丕顯但職在", 36: "陳實錄爰勒斯", 37: "斯覩功高大舜", 38: "聖乃神武克禍",
    39: "贄咸陳大道無", 40: "田而食靡謝天", 41: "物流形隨感變", 42: "蕤繁祉雲氏龍",
    43: "無停史上善降", 44: "凝鏡澈用之日", 45: "雖休弗休居崇", 46: "我取其實還淳",
}

SPECIAL_TEXT = {
    6: "月觀其移山迴澗窮泰極侈以人從欲良足深尤至於炎景流",
    7: "金無鬱蒸之氣微風徐動有淒清之涼信安體之佳所誠養神",
    # 第 25 页采用第 7 页已人工确认的 23 字框位：右上角留白。
    25: "度於雙闕貫穿青瑣縈帶紫房激揚清波滌蕩瑕穢可以導",
    31: "中元元年醴泉京師飲之者痼疾皆愈然則神物之來寔扶",
    34: "實取驗於當今斯乃上帝玄符天子令德豈臣之末學所",
    36: "陳實錄爰勒斯銘其詞曰惟皇撫運奄壹寰宇千載膺期萬",
    37: "物斯覩功高大舜勤深伯禹絕後光前登三邁五握機蹈矩乃",
    44: "凝鏡澈用之日新挹之無竭道隨時泰慶與泉流我后夕惕",
    12: "二儀之功終資一人之慮遺身利物櫛風沐雨百姓為心憂勞",
    15: "力惜十家之產深閉固拒未肯俯從以為隋氏舊宮營於曩代",
    18: "玉砌接於土階茅茨續於瓊室仰觀壯麗可作鑒於既往俯察",
    19: "卑儉足垂訓於後昆此所謂至人無為大聖不作彼竭其力我",
    20: "享其功者也然昔之池沼咸引谷澗宮城之內本乏水源求而",
    22: "朔旬有六日己亥上及中宮歷覽臺觀閒步西城之陰躊躇",
    47: "永保貞吉",
    48: "兼太子率更令勃海男臣歐陽詢奉勅書",
}

# 原始 OCR 会把相近字误读为下列字形；只用于在底本中定位，不会写入结果。
OCR_ALTERNATIVES = {
    "真": "貞", "千": "六", "益": "孟", "通": "逮", "閑": "闕", "鶉": "鶡",
    "手": "子", "關": "闕", "貴": "贄", "尊": "享", "虛": "良", "退": "足",
    "湄": "沼", "涇": "咸", "圖": "在", "學": "粵", "開": "閒", "蹟": "躊",
    "閣": "闕", "垂": "貫", "帶": "縈", "緜": "滌", "藥": "導", "效": "澄",
    "腴": "映", "悲": "湛", "國": "之", "軋": "乾", "仝": "象", "誰": "謹",
    "茶": "按", "作": "中", "主": "王", "京": "於", "痛": "痼", "龄": "齡",
    "御": "卿", "色": "我", "間": "聞", "祥": "懼", "惟": "實", "玄": "符",
    "待": "符", "今": "令", "憲": "慮", "菅": "葺", "金": "鑒", "松": "於",
    "謁": "竭", "服": "雕", "律": "樸",
}

# 第三页人工确认的外框，按当前图片宽高等比缩放。
X_TEMPLATE = ((304, 404), (200, 308), (100, 208), (8, 102))
TOP_INSET, BOTTOM_INSET = 6, 596
TEMPLATE_SIZE = (408, 602)
FIRST_SLOT = {25: 1}  # 第 25 页右上格为空，正文从右列第二格起。
SKIPPED_SLOTS = {22: {11}}  # 第 22 页第二列末格为空（四列字数为 6｜5｜6｜6）。

# 第 7 页改用原拓片：三列、每列八字，章法不同于其余的四列六字页。
PAGE_GRID = {7: (3, 8)}

# 第 31 页碑面有残损：第二列首格留白，缺字“出於”不录入。
PAGE_SLOTS = {
    31: (
        [(0, row, 6) for row in range(6)]
        + [(1, row, 6) for row in range(1, 6)]
        + [(2, row, 6) for row in range(6)]
        + [(3, row, 6) for row in range(6)]
    ),
    34: (
        [(0, row, 6) for row in range(6)]
        + [(1, row, 6) for row in (0, 1, 3, 4, 5)]
        + [(2, row, 6) for row in (0, 2, 3, 4, 5)]
        + [(3, row, 6) for row in range(6)]
    ),
    36: (
        [(0, row, 6) for row in range(6)]
        + [(1, row, 6) for row in (0, 1, 2, 3, 5)]
        + [(2, row, 6) for row in range(6)]
        + [(3, row, 6) for row in range(6)]
    ),
    37: (
        [(0, row, 6) for row in range(6)]
        + [(1, row, 6) for row in range(6)]
        + [(2, row, 7) for row in (0, 2, 3, 4, 5, 6)]
        + [(3, row, 6) for row in range(6)]
    ),
    44: (
        [(0, row, 6) for row in range(6)]
        + [(1, row, 6) for row in range(6)]
        + [(2, row, 6) for row in range(6)]
        + [(3, row, 6) for row in (0, 2, 3, 4, 5)]
    ),
}


def original_ocr_reading(page: int) -> str:
    """读取旧 result.json，按实际横坐标从右到左重建 OCR 的列顺序。"""
    path = ROOT / ".debug" / f"fatie-{page:03d}" / "result.json"
    data = json.loads(path.read_text())
    columns: dict[int, list[dict]] = {}
    for item in data.get("char_results", []):
        columns.setdefault(item["column"], []).append(item)
    ordered = sorted(
        columns.values(),
        key=lambda items: sum(item["bbox"][0] for item in items) / len(items),
        reverse=True,
    )
    return "".join(
        "".join(item["char"] for item in sorted(items, key=lambda item: item["row"]))
        for items in ordered
    )


def lcs_score(observed: str, candidate: str) -> int:
    """允许常见 OCR 误读的最长公共子序列得分。"""
    row = [0] * (len(candidate) + 1)
    for char in observed:
        previous = 0
        options = {char, OCR_ALTERNATIVES.get(char, char)}
        for index, target in enumerate(candidate, 1):
            old = row[index]
            row[index] = previous + 1 if target in options else max(row[index], row[index - 1])
            previous = old
    return row[-1]


def ocr_matched_text(page: int) -> str | None:
    observed = original_ocr_reading(page)
    if not observed:
        return None
    ranked = [(lcs_score(observed, SOURCE[index:index + 24]), index) for index in range(len(SOURCE) - 23)]
    best_score = max(score for score, _ in ranked)
    # 同分时取正文中更早的起点，避免因 OCR 漏一个首字而后移一格。
    start = min(index for score, index in ranked if score == best_score)
    return SOURCE[start:start + 24]


def page_text(page: int) -> str:
    if page in SPECIAL_TEXT:
        return SPECIAL_TEXT[page]
    if page >= 6:
        matched = ocr_matched_text(page)
        if matched:
            return matched
    start = PAGE_START[page]
    offset = SOURCE.index(start)
    return SOURCE[offset:offset + 24]


def make_records(page: int, text: str) -> list[dict]:
    image_name = f"fatie-{page:03d}.jpg"
    width, height = Image.open(ROOT / image_name).size
    records = []
    columns, rows = PAGE_GRID.get(page, (4, 6))
    if page in PAGE_SLOTS:
        slots = PAGE_SLOTS[page]
    else:
        slots = [
            (slot // rows, slot % rows, rows)
            for slot in range(FIRST_SLOT.get(page, 0), columns * rows)
            if slot not in SKIPPED_SLOTS.get(page, set())
        ]
    for char, (col, row, column_rows) in zip(text, slots):
        if (columns, rows) == (4, 6):
            x1, x2 = X_TEMPLATE[col]
            y1 = TOP_INSET if row == 0 else TEMPLATE_SIZE[1] * row / column_rows
            y2 = BOTTOM_INSET if row == column_rows - 1 else TEMPLATE_SIZE[1] * (row + 1) / column_rows
        else:
            # 原拓片已裁至碑面，保留少量内边距以免框到白边。
            # column=0 始终表示最右列；图像横坐标则从左向右递增。
            visual_col = columns - 1 - col
            x1 = TEMPLATE_SIZE[0] * (visual_col + 0.025) / columns
            x2 = TEMPLATE_SIZE[0] * (visual_col + 0.975) / columns
            y1 = TOP_INSET if row == 0 else TEMPLATE_SIZE[1] * row / rows
            y2 = BOTTOM_INSET if row == rows - 1 else TEMPLATE_SIZE[1] * (row + 1) / rows
        uid = hashlib.md5(
            f"{char}|{ROOT.name}|{image_name}|{col}|{row}".encode()
        ).hexdigest()
        records.append({
            "id": uid, "uuid": uid, "char": char, "font": "楷书", "author": "欧阳询",
            "work": "九成宫醴泉铭", "work_dir": ROOT.name,
            "bbox": [x1 * width / TEMPLATE_SIZE[0], y1 * height / TEMPLATE_SIZE[1],
                     x2 * width / TEMPLATE_SIZE[0], y2 * height / TEMPLATE_SIZE[1]],
            "column": col, "row": row, "visible": True,
        })
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="确认后写入 JSON 和释文文件")
    parser.add_argument("--from-page", type=int, default=3, help="从指定页开始处理")
    parser.add_argument("--to-page", type=int, default=48, help="处理到指定页")
    args = parser.parse_args()
    for page in range(args.from_page, args.to_page + 1):
        text = page_text(page)
        capacity = len(PAGE_SLOTS.get(page, [None] * 24))
        if len(text) > capacity:
            raise ValueError(f"第 {page} 页超过 {capacity} 字：{text}")
        records = make_records(page, text)
        print(f"{page:03d} {len(text):2d} {text}")
        if args.write:
            stem = f"fatie-{page:03d}"
            (ROOT / ".debug" / stem / "chars.json").write_text(
                json.dumps(records, ensure_ascii=False, indent=2) + "\n"
            )
            (ROOT / "words" / f"{stem}.txt").write_text(text + "\n")


if __name__ == "__main__":
    main()
