#!/usr/bin/env python3
"""
批量处理《普觉国师碑铭帖》。

默认行为：
- 扫描 王羲之-行书-普觉国师碑铭帖/fatie-*.jpg
- 跳过已经存在 .debug/<stem>/chars.json 的页面
- 从左/右边栏 OCR 提取释文，去掉固定前缀「王字/集王字 普觉国师碑」
- 自动检测主图大字列，按释文拆字，生成 chars.json/result.json/words/*.txt/words/*.webp
- 将新生成的字形记录写入 ocr_output/glyphs.sqlite

边栏 OCR 有误时，可以传入 JSON 覆盖：
{
  "fatie-002": "下一页校正后的释文"
}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr.api_client import OCRAPIClient  # noqa: E402
from ocr.char_splitter import CharSplitter, SplitMethod  # noqa: E402
from ocr.recognizer import CalligraphyOCR  # noqa: E402


DEFAULT_WORK_DIR = "王羲之-行书-普觉国师碑铭帖"
WORK_TITLE = "普觉国师碑铭帖"
AUTHOR = "王羲之"
FONT = "行书"
PREFIX_MARKER = "普覺國師碑"

CHAR_NORMALIZE = str.maketrans(
    {
        "觉": "覺",
        "国": "國",
        "师": "師",
        "丽": "麗",
        "华": "華",
        "铭": "銘",
        "溪": "溪",
        "写": "字",
        "遥": "遙",
    }
)

OCR_TEXT_FIXES = {
    "王宁": "王字",
    "王宇": "王字",
    "集王宁": "集王字",
    "普宽": "普覺",
    "普党": "普覺",
    "晋覺國師碑": "普覺國師碑",
    "晉覺國師碑": "普覺國師碑",
    "曾覺國師碑": "普覺國師碑",
    "國帅": "國師",
    "國師埤": "國師碑",
    "述智": "迦智",
    "迦皆": "迦智",
    "朝列太夫": "朝列大夫",
    "國學太司成": "國學大司成",
    "书法欣赏": "",
    "書法欣賞": "",
}


@dataclass
class PageResult:
    stem: str
    text: str
    chars: list[dict]
    parsed_results: list[dict]
    char_results: list[dict]
    ids_to_delete: list[str]


def clean_ocr_text(raw: str) -> str:
    """清洗边栏 OCR 文本，只保留要用的汉字，并做少量常见误识别修正。"""
    text = raw or ""
    for bad, good in OCR_TEXT_FIXES.items():
        text = text.replace(bad, good)
    text = text.translate(CHAR_NORMALIZE)
    # 去掉网址、水印、拉丁字母、标点和空白；边栏正文只需要汉字。
    text = "".join(re.findall(r"[\u3400-\u9fff\uf900-\ufaff]", text))
    for bad, good in OCR_TEXT_FIXES.items():
        text = text.replace(bad.translate(CHAR_NORMALIZE), good.translate(CHAR_NORMALIZE))
    return text


def strip_fixed_prefix(text: str) -> str:
    """去掉边栏固定前缀，保留当前页大字对应释文。"""
    text = clean_ocr_text(text)
    marker = PREFIX_MARKER
    idx = text.find(marker)
    if idx >= 0:
        suffix = text[idx + len(marker) :]
        if idx == 0 and len(suffix) <= 2:
            return text
        return suffix
    loose = re.search(r"[\u3400-\u9fff]{1,4}覺國師碑", text)
    if loose:
        suffix = text[loose.end() :]
        if loose.start() == 0 and len(suffix) <= 2:
            return text
        if suffix:
            return suffix
    for prefix in ("集王字", "王字"):
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def parse_page_spec(spec: str) -> set[str]:
    """解析 000,001,009-012 形式的页码参数。"""
    stems: set[str] = set()
    if not spec:
        return stems
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = [p.strip() for p in part.split("-", 1)]
            start, end = int(left), int(right)
            if end < start:
                start, end = end, start
            for i in range(start, end + 1):
                stems.add(f"fatie-{i:03d}")
        else:
            stems.add(f"fatie-{int(part):03d}" if part.isdigit() else part)
    return stems


def has_chars_json(image_path: Path) -> bool:
    return (image_path.parent / ".debug" / image_path.stem / "chars.json").exists()


def load_transcription_overrides(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("transcriptions JSON 必须是对象：{stem: text}")
    return {str(k): strip_fixed_prefix(str(v)) for k, v in data.items()}


def detect_main_region(image: np.ndarray) -> tuple[int, int, int, int]:
    """检测黑底拓片主区域，排除左右白色释文栏。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dark = gray < 85
    xfrac = dark.mean(axis=0)
    xs = np.where(xfrac > 0.35)[0]
    if len(xs) == 0:
        return (0, 0, image.shape[1], image.shape[0])
    return (int(xs.min()), 0, int(xs.max() + 1), image.shape[0])


def _foreground_mask(image: np.ndarray) -> np.ndarray:
    """黑底白字/浅色字的前景 mask，过滤红色水印。"""
    b, g, r = cv2.split(image)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    red = (r > 120) & (r > g * 1.2) & (r > b * 1.2)
    mask = ((gray > 145) & (~red)).astype(np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def detect_main_columns(image: np.ndarray) -> list[list[float]]:
    """检测主图大字列，返回从右到左的列 bbox。"""
    x1, y1, x2, y2 = detect_main_region(image)
    roi = image[y1:y2, x1:x2]
    mask = _foreground_mask(roi)
    proj = mask.sum(axis=0).astype(float)
    if proj.size == 0 or proj.max() <= 0:
        return []
    smooth = np.convolve(proj, np.ones(35) / 35, mode="same")
    threshold = max(float(smooth.max()) * 0.16, 10.0)

    intervals: list[list[int]] = []
    inside = False
    start = 0
    for i, value in enumerate(smooth):
        if value > threshold and not inside:
            start = i
            inside = True
        if inside and (value <= threshold or i == len(smooth) - 1):
            end = i
            inside = False
            if end - start > 30:
                intervals.append([start + x1, end + x1])

    columns = []
    h, w = image.shape[:2]
    for cx1, cx2 in reversed(intervals):
        columns.append(
            [
                float(max(0, cx1 - 30)),
                0.0,
                float(min(w, cx2 + 30)),
                float(h),
            ]
        )
    return columns


def estimate_row_counts(image: np.ndarray, columns: list[list[float]]) -> list[int]:
    """估计每列字数，用于总字数不能均分时分配释文。"""
    counts = []
    h, w = image.shape[:2]
    for col in columns:
        x1, _, x2, _ = [int(round(v)) for v in col]
        x1 = max(0, min(w - 1, x1))
        x2 = max(0, min(w, x2))
        roi = image[:, x1:x2]
        mask = _foreground_mask(roi)
        proj = mask.sum(axis=1).astype(float)
        if proj.size == 0 or proj.max() <= 0:
            counts.append(0)
            continue
        smooth = np.convolve(proj, np.ones(25) / 25, mode="same")
        threshold = max(float(smooth.max()) * 0.12, 5.0)
        segments = []
        inside = False
        start = 0
        for i, value in enumerate(smooth):
            if value > threshold and not inside:
                start = i
                inside = True
            if inside and (value <= threshold or i == len(smooth) - 1):
                end = i
                inside = False
                if end - start > 20:
                    segments.append([start, end])
        merged: list[list[int]] = []
        for seg in segments:
            if merged and seg[0] - merged[-1][1] < 45:
                merged[-1][1] = seg[1]
            else:
                merged.append(seg)
        counts.append(len(merged))
    return counts


def distribute_counts(total_chars: int, column_count: int, row_estimates: list[int]) -> list[int]:
    """根据总字数和列数决定每列字数。"""
    if column_count <= 0:
        return []
    if total_chars <= 0:
        return [0] * column_count

    estimates = (row_estimates + [0] * column_count)[:column_count]
    if sum(estimates) == total_chars and all(v > 0 for v in estimates):
        return estimates

    if total_chars % column_count == 0:
        return [total_chars // column_count] * column_count

    min_count = 0 if total_chars < column_count else 1
    if sum(estimates) > 0:
        total_est = sum(max(v, 1) for v in estimates)
        raw = [max(min_count, int(round(total_chars * max(v, 1) / total_est))) for v in estimates]
    else:
        base = total_chars // column_count
        raw = [base] * column_count

    while sum(raw) < total_chars:
        idx = max(range(column_count), key=lambda i: estimates[i] if i < len(estimates) else 0)
        raw[idx] += 1
    while sum(raw) > total_chars:
        idx = max((i for i, v in enumerate(raw) if v > min_count), key=lambda i: raw[i])
        raw[idx] -= 1
    return raw


def split_text_by_counts(text: str, counts: Iterable[int]) -> list[str]:
    cols = []
    pos = 0
    for count in counts:
        cols.append(text[pos : pos + count])
        pos += count
    if pos != len(text):
        raise ValueError(f"释文长度 {len(text)} 与列字数 {list(counts)} 不匹配")
    return cols


def parse_ocr_text(api_result: dict) -> str:
    recognizer = CalligraphyOCR(output_dir=Path("/tmp/pujue_ocr_parse"))
    parsed = recognizer._parse_markdown_result(api_result)
    return "".join(str(item.get("text", "")) for item in parsed)


def ocr_side_transcription(image_path: Path, client: OCRAPIClient) -> tuple[str, str]:
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"无法读取图片: {image_path}")
    h, w = image.shape[:2]
    x1, _, x2, _ = detect_main_region(image)

    candidates: list[tuple[str, np.ndarray]] = []
    if x1 > 10:
        candidates.append(("left", image[:, :x1]))
    if w - x2 > 10:
        candidates.append(("right", image[:, x2:]))
    if not candidates:
        # 回退：左右各取 10%。
        sw = max(35, int(w * 0.1))
        candidates = [("left", image[:, :sw]), ("right", image[:, w - sw :])]

    best_side = ""
    best_text = ""
    best_score = -1
    for side, crop in candidates:
        scale = 4
        enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            cv2.imwrite(str(tmp_path), enlarged)
            raw = parse_ocr_text(client.recognize(str(tmp_path)))
            clean = strip_fixed_prefix(raw)
            score = len(clean) + (20 if PREFIX_MARKER in clean_ocr_text(raw) else 0)
            if score > best_score:
                best_side = side
                best_text = clean
                best_score = score
        finally:
            tmp_path.unlink(missing_ok=True)

    return best_side, best_text


def build_page(
    image_path: Path,
    text: str,
    splitter: CharSplitter,
    overwrite: bool = False,
) -> PageResult:
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"无法读取图片: {image_path}")
    h, w = image.shape[:2]

    columns = detect_main_columns(image)
    if not columns:
        raise RuntimeError("未检测到主图大字列")

    row_estimates = estimate_row_counts(image, columns)
    counts = distribute_counts(len(text), len(columns), row_estimates)
    column_texts = split_text_by_counts(text, counts)

    old_ids = []
    chars_path = image_path.parent / ".debug" / image_path.stem / "chars.json"
    if overwrite and chars_path.exists():
        try:
            old = json.loads(chars_path.read_text(encoding="utf-8"))
            if isinstance(old, list):
                old_ids = [str(c.get("id")) for c in old if c.get("id")]
        except Exception:
            old_ids = []

    chars = []
    parsed_results = []
    char_results = []
    global_index = 0
    work_dir_name = image_path.parent.name

    for col_idx, (col_bbox, col_text) in enumerate(zip(columns, column_texts)):
        char_bboxes, method = splitter.split_column(image, col_bbox, col_text, debug=False)
        if len(char_bboxes) != len(col_text):
            raise RuntimeError(
                f"{image_path.stem} 第 {col_idx} 列拆字失败：需要 {len(col_text)}，得到 {len(char_bboxes)}"
            )

        parsed_results.append(
            {
                "text": col_text,
                "bbox": [float(v) for v in col_bbox],
                "poly": [
                    [float(col_bbox[0]), float(col_bbox[1])],
                    [float(col_bbox[2]), float(col_bbox[1])],
                    [float(col_bbox[2]), float(col_bbox[3])],
                    [float(col_bbox[0]), float(col_bbox[3])],
                ],
            }
        )

        for row_idx, (ch, bbox) in enumerate(zip(col_text, char_bboxes)):
            rid = hashlib.md5(
                f"{ch}_{work_dir_name}_{image_path.name}_{col_idx}_{row_idx}".encode("utf-8")
            ).hexdigest()
            bbox_f = [float(v) for v in bbox]
            rec = {
                "id": rid,
                "uuid": rid,
                "char": ch,
                "font": FONT,
                "author": AUTHOR,
                "work": WORK_TITLE,
                "work_dir": work_dir_name,
                "bbox": bbox_f,
                "column": col_idx,
                "row": row_idx,
                "visible": True,
            }
            chars.append(rec)
            char_results.append(
                {
                    "char": ch,
                    "bbox": bbox_f,
                    "column": col_idx,
                    "row": row_idx,
                    "global_index": global_index,
                    "col_text": col_text,
                    "col_bbox": [float(v) for v in col_bbox],
                    "split_method": f"sidebar_ocr_{method}",
                }
            )
            global_index += 1

    return PageResult(
        stem=image_path.stem,
        text=text,
        chars=chars,
        parsed_results=parsed_results,
        char_results=char_results,
        ids_to_delete=old_ids,
    )


def write_page_result(work_dir: Path, image_path: Path, result: PageResult) -> None:
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"无法读取图片: {image_path}")
    h, w = image.shape[:2]

    debug_dir = work_dir / ".debug" / image_path.stem
    words_dir = work_dir / "words"
    debug_dir.mkdir(parents=True, exist_ok=True)
    words_dir.mkdir(parents=True, exist_ok=True)

    (debug_dir / "chars.json").write_text(
        json.dumps(result.chars, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    full_result = {
        "image_path": str(image_path.resolve()),
        "image_info": {
            "width": w,
            "height": h,
            "channels": int(image.shape[2]),
            "dtype": str(image.dtype),
        },
        "recognized_text": result.text,
        "parsed_results": result.parsed_results,
        "char_results": result.char_results,
        "column_count": len(result.parsed_results),
        "total_chars": len(result.char_results),
        "timestamp": datetime.now().isoformat(),
    }
    (debug_dir / "result.json").write_text(
        json.dumps(full_result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (words_dir / f"{image_path.stem}.txt").write_text(result.text, encoding="utf-8")

    for rec in result.chars:
        x1, y1, x2, y2 = [int(round(float(v))) for v in rec["bbox"]]
        x1 = max(0, min(w - 1, x1))
        x2 = max(0, min(w, x2))
        y1 = max(0, min(h - 1, y1))
        y2 = max(0, min(h, y2))
        if x2 <= x1 or y2 <= y1:
            continue
        crop = image[y1:y2, x1:x2]
        cv2.imwrite(str(words_dir / f"{rec['id']}.webp"), crop, [cv2.IMWRITE_WEBP_QUALITY, 95])


def update_sqlite(project_root: Path, results: list[PageResult]) -> None:
    if not results:
        return
    sqlite_path = project_root / "ocr_output" / "glyphs.sqlite"
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
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
        delete_ids = [rid for res in results for rid in res.ids_to_delete]
        if delete_ids:
            cur.executemany("DELETE FROM glyphs WHERE id = ?", [(rid,) for rid in delete_ids])
        rows = [
            (c["id"], c["char"], c["work_dir"], c["author"], c["font"], c["work"])
            for res in results
            for c in res.chars
            if c.get("visible") is not False
        ]
        cur.executemany(
            "INSERT OR REPLACE INTO glyphs (id, char, work_dir, author, font, work_title) VALUES (?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def iter_images(work_dir: Path, pages: set[str], start: str, end: str, limit: int | None) -> list[Path]:
    images = sorted(work_dir.glob("fatie-*.jpg"), key=lambda p: p.name)
    if pages:
        images = [p for p in images if p.stem in pages]
    if start:
        images = [p for p in images if p.stem >= f"fatie-{int(start):03d}"]
    if end:
        images = [p for p in images if p.stem <= f"fatie-{int(end):03d}"]
    if limit is not None:
        images = images[:limit]
    return images


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(description="批量处理《普觉国师碑铭帖》")
    parser.add_argument("--work-dir", default=DEFAULT_WORK_DIR, help="字帖目录")
    parser.add_argument("--pages", default="", help="页码，如 000,001,009-012")
    parser.add_argument("--start", default="", help="起始页码，如 002")
    parser.add_argument("--end", default="", help="结束页码，如 127")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少张候选图片")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有 chars.json")
    parser.add_argument("--dry-run", action="store_true", help="只列出会处理/跳过的页面，不调用 OCR，不写文件")
    parser.add_argument("--no-sqlite", action="store_true", help="不更新 ocr_output/glyphs.sqlite")
    parser.add_argument("--transcriptions-json", type=Path, default=None, help="按 stem 覆盖释文的 JSON")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    work_dir = Path(args.work_dir)
    if not work_dir.is_absolute():
        work_dir = project_root / work_dir
    if not work_dir.exists():
        print(f"目录不存在: {work_dir}", file=sys.stderr)
        return 1

    pages = parse_page_spec(args.pages)
    overrides = load_transcription_overrides(args.transcriptions_json)
    images = iter_images(work_dir, pages, args.start, args.end, None)
    if not images:
        print("没有找到待处理图片")
        return 1

    existing = [p for p in images if has_chars_json(p)]
    all_candidates = [p for p in images if args.overwrite or not has_chars_json(p)]
    candidates = all_candidates[: args.limit] if args.limit is not None else all_candidates

    print(f"图片总数: {len(images)}")
    print(f"已有 chars.json: {len(existing)}")
    if existing and not args.overwrite:
        print("跳过页:", ", ".join(p.stem for p in existing if not args.overwrite))
    if args.limit is not None and len(all_candidates) > len(candidates):
        print(f"候选总数: {len(all_candidates)}，本次限量处理: {len(candidates)}")
    print(f"待处理: {len(candidates)}")
    if args.dry_run:
        if candidates:
            print("将处理:", ", ".join(p.stem for p in candidates))
        return 0

    client = OCRAPIClient()
    splitter = CharSplitter(method=SplitMethod.HYBRID, min_char_height=40, margin_ratio=0.03)
    processed: list[PageResult] = []
    failed: list[str] = []

    for idx, image_path in enumerate(candidates, start=1):
        try:
            if image_path.stem in overrides:
                side = "override"
                text = overrides[image_path.stem]
            else:
                side, text = ocr_side_transcription(image_path, client)
            if not text:
                raise RuntimeError("边栏 OCR 没有提取到有效释文")
            result = build_page(image_path, text, splitter, overwrite=args.overwrite)
            write_page_result(work_dir, image_path, result)
            processed.append(result)
            print(f"[{idx}/{len(candidates)}] OK {image_path.name} side={side} chars={len(result.chars)} text={text}")
        except Exception as exc:
            failed.append(f"{image_path.stem}: {exc}")
            print(f"[{idx}/{len(candidates)}] FAIL {image_path.name}: {exc}")

    if not args.no_sqlite and processed:
        update_sqlite(project_root, processed)
        print(f"SQLite 已更新: {sum(len(r.chars) for r in processed)} 条")

    print(f"完成：成功 {len(processed)}，失败 {len(failed)}，跳过 {len(existing) if not args.overwrite else 0}")
    if failed:
        print("失败列表:")
        for item in failed:
            print("  " + item)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
