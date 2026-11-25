#!/usr/bin/env python3
"""批量提取《说文广义》的篆书框，并补齐每列对应的释文首字。

页面框来自固定网格及篆书字形间的大留白。释文使用项目桌面版同一套
Layout Parsing OCR；它只写进篆书框的 ``char`` 字段，不给释文另画框。
已有 ``chars.json`` 始终先备份，且 OCR 覆盖后立刻还原既有框。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocr.recognizer import CalligraphyOCR
from extract_shuowen_grid import page_boundaries
from propose_shuowen_seal_boxes import proposal_boxes_by_gaps


def chinese(text: str) -> str:
    """只保留汉字，便于排除 OCR 的标点和拉丁字符。"""
    return "".join(c for c in text if "一" <= c <= "鿿")


def save_grid(image_path: Path, debug_dir: Path) -> dict[str, Any]:
    """按竖线切出两页网格，并保存清单和裁剪图。"""
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(image_path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    pages = page_boundaries(gray)
    crops_dir = debug_dir / "grid" / "columns"
    crops_dir.mkdir(parents=True, exist_ok=True)
    columns: list[dict[str, Any]] = []
    for page, boundaries in enumerate(pages):
        for column, (x1, x2) in enumerate(zip(boundaries, boundaries[1:])):
            name = f"page-{page}-column-{column:02d}.jpg"
            cv2.imwrite(str(crops_dir / name), image[:, x1:x2])
            columns.append({
                "page": page,
                "column": column,
                "bbox": [x1, 0, x2, image.shape[0]],
                "image": f"columns/{name}",
            })
    manifest: dict[str, Any] = {"source": str(image_path), "pages": pages, "columns": columns}
    grid_dir = debug_dir / "grid"
    grid_dir.mkdir(parents=True, exist_ok=True)
    (grid_dir / "columns.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def frame_entries(proposals: list[dict[str, Any]], work_dir: Path) -> list[dict[str, Any]]:
    """把候选框转成桌面版可直接读取的 chars.json 项。"""
    entries: list[dict[str, Any]] = []
    for row, proposal in enumerate(proposals):
        identifier = uuid.uuid4().hex
        entries.append({
            "id": identifier,
            "uuid": identifier,
            "char": "",
            "font": "篆书",
            "author": "程德洽",
            "work": "说文广义-高清",
            "work_dir": str(work_dir),
            "bbox": proposal["bbox"],
            "column": int(proposal["page"]) * 100 + int(proposal["grid_column"]),
            "row": row,
            "visible": True,
        })
    return entries


def grouped_frames(entries: list[dict[str, Any]], cells: dict[tuple[int, int], list[int]]) -> dict[tuple[int, int], list[dict[str, Any]]]:
    """按框中心所在的网格格子归类；同一列的所有异体共用一条释文。"""
    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for entry in entries:
        x1, _, x2, _ = entry["bbox"]
        center = (x1 + x2) / 2
        matches = [(key, bbox) for key, bbox in cells.items() if bbox[0] <= center <= bbox[2]]
        if not matches:
            continue
        key = min(matches, key=lambda item: abs((item[1][0] + item[1][2]) / 2 - center))[0]
        groups.setdefault(key, []).append(entry)
    return groups


def choose_gloss(
    seal_cell: tuple[int, int],
    cells: dict[tuple[int, int], list[int]],
    parsed: list[dict[str, Any]],
) -> dict[str, Any]:
    """取篆书格物理左侧的主释文列首字，略过同格内的声训窄列。

    每格内可能有两列字。离篆书格最近（x 最大）的文字列是主释文，另一列
    常是反切/声训；故只取最靠右的候选。跨书脊时，右页第 0 格转到左页末格。
    """
    page, column = seal_cell
    target = (page, column - 1)
    if target not in cells and column == 0:
        previous = [key for key in cells if key[0] == page - 1]
        if previous:
            target = (page - 1, max(key[1] for key in previous))
    target_box = cells.get(target)
    candidates: list[dict[str, Any]] = []
    if target_box:
        for item in parsed:
            text = chinese(str(item.get("text", "")))
            bbox = item.get("bbox", [])
            if len(bbox) != 4 or not text:
                continue
            center_x = (float(bbox[0]) + float(bbox[2])) / 2
            if target_box[0] <= center_x <= target_box[2] and float(bbox[1]) >= 1000:
                candidates.append({"text": text, "bbox": bbox})
    # 某些左页的最外侧列按反向版式排，释文在篆书格右边；左侧格没有
    # 有效文字时，取右邻格中最贴近篆书（x 最小）的主释文列。
    if not candidates:
        opposite = (page, column + 1)
        if opposite not in cells:
            next_page = [key for key in cells if key[0] == page + 1]
            if next_page:
                opposite = (page + 1, min(key[1] for key in next_page))
        opposite_box = cells.get(opposite)
        if opposite_box:
            right_candidates: list[dict[str, Any]] = []
            for item in parsed:
                text = chinese(str(item.get("text", "")))
                bbox = item.get("bbox", [])
                if len(bbox) != 4 or not text:
                    continue
                center_x = (float(bbox[0]) + float(bbox[2])) / 2
                if opposite_box[0] <= center_x <= opposite_box[2] and float(bbox[1]) >= 1000:
                    right_candidates.append({"text": text, "bbox": bbox})
            right_candidates.sort(key=lambda item: float(item["bbox"][0]))
            if right_candidates:
                candidates = right_candidates
                target = opposite
    # 识别器偶尔没有把文字块归到精确网格。此时只在篆书格左边找最近列。
    if not candidates:
        seal_left = cells[seal_cell][0]
        for item in parsed:
            text = chinese(str(item.get("text", "")))
            bbox = item.get("bbox", [])
            if len(bbox) != 4 or not text or float(bbox[1]) < 1000:
                continue
            if float(bbox[2]) <= seal_left:
                candidates.append({"text": text, "bbox": bbox})
    candidates.sort(key=lambda item: float(item["bbox"][0]), reverse=True)
    selected = candidates[0] if candidates else {"text": "", "bbox": []}
    return {
        "seal_cell": [page, column],
        "target_cell": list(target),
        "char": selected["text"][:1],
        "source_text": selected["text"],
        "source_bbox": selected["bbox"],
        "ignored_texts": [item["text"] for item in candidates[1:]],
    }


def page_crop_ocr(image_path: Path, x1: int, x2: int) -> list[dict[str, Any]]:
    """对 OCR 漏掉的一整页半幅补做一次识别，并把坐标还原到原图。"""
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    assert image is not None
    crop = image[:, x1:x2]
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        cv2.imwrite(str(temporary_path), crop)
        # 这里不走 recognize_image：那条整页路径会针对边缘再发起很多次
        # 滑窗请求。半页补识别只需一次 API 调用，速度适合批处理。
        ocr = CalligraphyOCR()
        response = ocr.api_client.recognize(str(temporary_path))
        result = ocr._filter_garbage_columns(
            ocr._merge_overlapping_columns(ocr._deduplicate_columns(ocr._parse_markdown_result(response)))
        )
        restored: list[dict[str, Any]] = []
        for item in result:
            bbox = item.get("bbox", [])
            if len(bbox) != 4:
                continue
            copy = dict(item)
            copy["bbox"] = [bbox[0] + x1, bbox[1], bbox[2] + x1, bbox[3]]
            restored.append(copy)
        return restored
    finally:
        temporary_path.unlink(missing_ok=True)


def process_page(work_dir: Path, page_number: int) -> dict[str, Any]:
    image_path = work_dir / f"fatie-{page_number:03d}.jpg"
    debug_dir = work_dir / ".debug" / image_path.stem
    debug_dir.mkdir(parents=True, exist_ok=True)
    chars_path = debug_dir / "chars.json"
    backups_dir = debug_dir / "backups"
    backups_dir.mkdir(exist_ok=True)

    # 原有标注只作为输入：先备份，OCR 覆盖后也恢复原框。
    had_existing = chars_path.exists()
    if had_existing:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        preserved_path = backups_dir / f"chars-before-batch-{stamp}.json"
        shutil.copy2(chars_path, preserved_path)
        entries = json.loads(chars_path.read_text())
    else:
        entries = []

    manifest = save_grid(image_path, debug_dir)
    gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    assert gray is not None
    proposals = proposal_boxes_by_gaps(gray, manifest)
    (debug_dir / "seal-proposals.json").write_text(json.dumps(proposals, ensure_ascii=False, indent=2) + "\n")
    preview = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    assert preview is not None
    for proposal in proposals:
        x1, y1, x2, y2 = map(int, proposal["bbox"])
        cv2.rectangle(preview, (x1, y1), (x2, y2), (0, 0, 255), 12)
    cv2.imwrite(str(debug_dir / "seal-proposals-preview.jpg"), preview)
    if not entries:
        entries = frame_entries(proposals, work_dir)
        chars_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")

    # 调用的正是桌面版同一个 OCR 类。它会重写 chars.json，因此以内存中的
    # entries 恢复当前框；不依赖 debug 目录内的临时文件，以免被接口结果清理。
    try:
        CalligraphyOCR().recognize_image(str(image_path), save_result=True, debug=False, crop_chars=False)
    finally:
        chars_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")

    result = json.loads((debug_dir / "result.json").read_text())
    cells = {(int(item["page"]), int(item["column"])): item["bbox"] for item in manifest["columns"]}
    groups = grouped_frames(entries, cells)
    parsed = list(result.get("parsed_results", []))
    # 整页接口有时只返回右半页。若某个篆书列左侧的目标格没有任何文字块，
    # 对该半页裁剪再识别一次；这是同一项目 OCR，只是避免双页扫描互相干扰。
    pages_to_supplement: set[int] = set()
    for seal_cell in groups:
        page, column = seal_cell
        target = (page, column - 1)
        if target not in cells and column == 0:
            previous = [key for key in cells if key[0] == page - 1]
            if previous:
                target = (page - 1, max(key[1] for key in previous))
        target_box = cells.get(target)
        if not target_box:
            continue
        found = any(
            len(item.get("bbox", [])) == 4
            and chinese(str(item.get("text", "")))
            and target_box[0] <= (float(item["bbox"][0]) + float(item["bbox"][2])) / 2 <= target_box[2]
            for item in parsed
        )
        if not found:
            pages_to_supplement.add(target[0])
    for page in sorted(pages_to_supplement):
        page_cells = [bbox for (cell_page, _), bbox in cells.items() if cell_page == page]
        parsed.extend(page_crop_ocr(image_path, min(bbox[0] for bbox in page_cells), max(bbox[2] for bbox in page_cells)))
    audit: list[dict[str, Any]] = []
    for cell, group in groups.items():
        label = choose_gloss(cell, cells, parsed)
        audit.append(label | {"frame_count": len(group)})
        # 已有人手填过的释文不改；其余同列统一用 OCR 首字。
        if label["char"]:
            for entry in group:
                if not str(entry.get("char", "")).strip():
                    entry["char"] = label["char"]
    chars_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
    (debug_dir / "gloss-labels.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    empty = sum(not str(item.get("char", "")).strip() for item in entries)
    return {"page": page_number, "frames": len(entries), "empty_glosses": empty, "existing_frames": had_existing}


def main() -> None:
    parser = argparse.ArgumentParser(description="批量提取《说文广义》篆书框及释文")
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--start", type=int, default=27)
    parser.add_argument("--end", type=int, default=87)
    args = parser.parse_args()
    summaries = []
    for number in range(args.start, args.end + 1):
        print(f"[开始] fatie-{number:03d}", flush=True)
        try:
            summary = process_page(args.work_dir, number)
        except Exception as error:
            # 单页接口超时或扫描异常不能终止整个批次；保留错误以便回查。
            summary = {
                "page": number,
                "frames": 0,
                "empty_glosses": 0,
                "existing_frames": False,
                "error": f"{type(error).__name__}: {error}",
            }
            print(f"[失败] fatie-{number:03d}: {summary['error']}", flush=True)
        summaries.append(summary)
        if "error" not in summary:
            print(f"[完成] fatie-{number:03d}: {summary['frames']} 框，空释文 {summary['empty_glosses']}", flush=True)
    report = args.work_dir / ".debug" / f"batch-{args.start:03d}-{args.end:03d}-report.json"
    report.write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n")
    print(f"批处理完成：{report}")


if __name__ == "__main__":
    main()
