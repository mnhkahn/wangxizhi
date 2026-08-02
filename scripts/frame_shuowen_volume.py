#!/usr/bin/env python3
"""为单页版《说文广义》扫描图提取篆书字框。

卷二以后下载的是单页 WebP，版心由等宽竖线组成：从左向右第 0、2、4…
格是篆书列，奇数格是释文列。篆书列的字形间有明显的大留白，释文列则是
密排小字。脚本只生成/补充篆书框，绝不调用 OCR、也不写释文。
"""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


def grid_lines(gray: np.ndarray) -> list[int]:
    """从版心下半部的连续竖线恢复等宽网格边界。"""
    height, width = gray.shape
    top, bottom = int(height * 0.55), int(height * 0.93)
    projection = (gray[top:bottom] < 145).sum(axis=0)
    # 个别页底部压印较浅，0.28 会只剩外框；0.24 仍能用连续等距条件
    # 抑制正文笔画造成的短投影峰。
    def projected_lines(ratio: float) -> list[int]:
        candidates = np.where(projection >= (bottom - top) * ratio)[0]
        groups: list[list[int]] = []
        for x in candidates:
            if not groups or x - groups[-1][-1] > 3:
                groups.append([int(x)])
            else:
                groups[-1].append(int(x))
        return [int(round(np.mean(group))) for group in groups]

    raw = projected_lines(0.24)
    # 相邻竖线通常相距约 115px。极窄的装订线/页边线不参与标尺计算。
    gaps = [b - a for a, b in zip(raw, raw[1:]) if 80 <= b - a <= 160]
    if len(raw) < 4 or not gaps:
        # 少数正文页版线极淡，24% 的连续高度门槛只剩外框。直接降低门槛
        # 会把正文笔画当成竖线并在页面中段错开半格，因此在 108～122px
        # 的实测列距内拟合整齐的等距网格，以各拟合线附近的纵向墨量评分。
        faint_projection = (gray[top:bottom] < 175).sum(axis=0).astype(float)
        best_score = -1.0
        best_lines: list[int] = []
        for regular_pitch in range(108, 123):
            for offset in range(regular_pitch):
                expected = list(range(offset, width, regular_pitch))
                scored = [x for x in expected if 20 < x < width - 20]
                if len(scored) < 8:
                    continue
                values = [
                    float(faint_projection[max(0, x - 2):min(width, x + 3)].max())
                    for x in scored
                ]
                score = float(np.quantile(values, 0.30) + 0.30 * np.median(values))
                if score > best_score:
                    best_score = score
                    best_lines = [x for x in expected if 5 <= x <= width - 5]
        raw = best_lines
        gaps = [b - a for a, b in zip(raw, raw[1:]) if 80 <= b - a <= 160]
    if len(raw) < 4:
        raise ValueError("未能识别足够的版面竖线")
    if not gaps:
        raise ValueError("未能估计网格列宽")
    pitch = float(np.median(gaps))
    # 选择被最多实体竖线支持的起点。不能从页面外框起算：它与第一条
    # 网格线之间常有约半格的装订留白，直接补线会整体错半列。
    candidates: list[tuple[int, int]] = []
    for start in raw:
        expected = np.arange(start, width - 5, pitch)
        score = sum(any(abs(x - value) <= pitch * 0.24 for x in raw) for value in expected)
        candidates.append((score, start))
    start = max(candidates)[1]
    best: list[int] = [start]
    while best[0] - pitch > 20:
        expected = best[0] - pitch
        near = [x for x in raw if abs(x - expected) <= pitch * 0.24]
        best.insert(0, min(near, key=lambda x: abs(x - expected)) if near else int(round(expected)))
    # 右页最外侧的版框经常正好贴近图片边缘。旧条件 ``width - 35``
    # 会把它排除，导致最右篆书槽位整列漏掉（0092 就是这个情况）。
    # 这里仍只接受有实体竖线支撑的末端，避免无依据地向外推一格。
    while best[-1] + pitch <= width - 5:
        expected = best[-1] + pitch
        near = [x for x in raw if abs(x - expected) <= pitch * 0.24]
        if near:
            best.append(min(near, key=lambda x: abs(x - expected)))
        elif expected < width - 35:
            best.append(int(round(expected)))
        else:
            break
    # 裁掉超出实体版框的推测线，并去掉紧贴的重复/装订线。
    dedup: list[int] = []
    for x in best:
        if 5 <= x <= width - 5 and (not dedup or x - dedup[-1] >= pitch * 0.55):
            dedup.append(x)
    if len(dedup) < 4:
        raise ValueError("有效网格列不足")
    return dedup


def active_runs(gray: np.ndarray, x1: int, x2: int) -> list[tuple[int, int]]:
    """提取篆书列中间隔明显的大字墨迹段。"""
    height, _ = gray.shape
    top, bottom = int(height * 0.16), int(height * 0.90)
    # 跳过竖线附近，以免框线本身把整列连起来。
    crop = gray[top:bottom, x1 + 16:x2 - 16]
    active = (crop < 130).sum(axis=1) >= 3
    # 修补字形内部的短小白缝，保留字与字之间约 50px 以上的大留白。
    for _ in range(12):
        active[1:-1] |= active[:-2] & active[2:]
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(active):
        if value and start is None:
            start = index
        if start is not None and (not value or index == len(active) - 1):
            end = index if not value else index + 1
            if end - start >= 75:
                runs.append((top + start, top + end))
            start = None
    return runs


def is_double_text_column(gray: np.ndarray, x1: int, x2: int) -> bool:
    """判断网格槽是否为左右两条密排小字的释文列。"""
    height, _ = gray.shape
    crop = gray[int(height * 0.16):int(height * 0.90), x1 + 16:x2 - 16]
    if crop.size == 0 or crop.shape[1] < 20:
        return False
    ink = crop < 170
    width = ink.shape[1]
    bands = [
        float(ink[:, int(width * index / 5):int(width * (index + 1) / 5)].mean())
        for index in range(5)
    ]
    sides = (bands[1] + bands[3]) / 2
    # 双栏小字在槽位中线处有稳定竖向留白；篆字即使左右分体，中部笔画
    # 密度通常不会低到两侧平均值的 0.58 以下。
    return sides >= 0.08 and bands[2] < sides * 0.58


def seed_columns(entries: list[dict]) -> list[tuple[float, list[float]]]:
    """取得确认过的篆书列中心及该列已有字的纵向中心。"""
    # 早期批次偶尔把右侧双栏释文框成一个很宽的“大框”。这类框不能再
    # 作为种子，否则固定槽位补框会沿整条释文列继续制造误框（卷七 0090）。
    # 正常篆字框宽约 90～105px；这里略放宽以兼容手工框。
    entries = [
        item for item in entries
        if 35 <= item["bbox"][2] - item["bbox"][0] <= 140
        and 55 <= item["bbox"][3] - item["bbox"][1] <= 240
    ]
    values = sorted((item["bbox"][0] + item["bbox"][2]) / 2 for item in entries)
    groups: list[list[float]] = []
    for value in values:
        if not groups or value - groups[-1][-1] > 150:
            groups.append([value])
        else:
            groups[-1].append(value)
    result: list[tuple[float, list[float]]] = []
    for group in groups:
        center = sum(group) / len(group)
        rows = sorted(
            (item["bbox"][1] + item["bbox"][3]) / 2
            for item in entries
            if abs((item["bbox"][0] + item["bbox"][2]) / 2 - center) <= 78
        )
        result.append((center, rows))
    return result


def propose(
    gray: np.ndarray,
    seeds: list[tuple[float, list[float]]] | None = None,
    forced_columns: set[int] | None = None,
) -> list[dict]:
    """按偶数网格列取得篆书槽位；每个留白分隔的大字生成一个框。"""
    lines = grid_lines(gray)
    height, width = gray.shape
    # 单页大多是篆、释文交替，但跨页或有合栏时会跳过一个网格槽；不能
    # 把奇偶性当作硬条件。篆书列至少有两个由大留白分隔的字形段，释文列
    # 通常没有这样的段，因此按字形段本身选择。
    run_map = {column: active_runs(gray, left, right) for column, (left, right) in enumerate(zip(lines, lines[1:]))}

    # 标准尺寸的旧误框也可能落在释文列（卷七 0017）。种子中心必须能
    # 映射到一个确有正常高度大字墨迹的网格槽，否则不允许触发固定槽补框。
    if seeds is not None:
        verified_seeds: list[tuple[float, list[float]]] = []
        centers = [(left + right) / 2 for left, right in zip(lines, lines[1:])]
        for seed in seeds:
            column = min(range(len(centers)), key=lambda index: abs(centers[index] - seed[0]))
            if abs(centers[column] - seed[0]) > 78:
                continue
            normal_heights = [
                y2 - y1 for y1, y2 in run_map[column]
                if 84 <= y2 - y1 <= 220
            ]
            if normal_heights and not is_double_text_column(gray, lines[column], lines[column + 1]):
                verified_seeds.append(seed)
        seeds = verified_seeds

    # 淡墨、虫蛀或扫描不均会让同一列里只剩一两个 ``active_runs``，从而
    # 整列被误判为释文列。对于这种规则版面，先从可靠的大字段估计纵向
    # 字距，再在篆书格（左起偶数格）逐个固定槽位复核。这样 0092 的两
    # 个淡字不会因笔画断裂而漏框。固定槽位只是补救：明显由留白识别出的
    # 非偶数篆书列仍保留在下面的普通路径中。
    all_centers = sorted(
        (y1 + y2) / 2
        for runs in run_map.values()
        for y1, y2 in runs
    )
    diffs = [b - a for a, b in zip(all_centers, all_centers[1:]) if 130 <= b - a <= 230]
    row_pitch = float(np.median(diffs)) if diffs else 0.0
    row_centers: list[float] = []
    if row_pitch:
        # 选连续字段最多的一列作为相位锚点。不能取全页最靠上的段：
        # 释文列偶尔会产生一个假大段，0092 中它会令所有框上移一格。
        anchor_runs = max(run_map.values(), key=len)
        anchor = (anchor_runs[0][0] + anchor_runs[0][1]) / 2
        while anchor - row_pitch >= height * 0.19:
            anchor -= row_pitch
        while anchor <= height * 0.84:
            row_centers.append(anchor)
            anchor += row_pitch

    def has_ink(center: float, left: int, right: int) -> bool:
        """固定槽位内是否确有一个大字（避免把空白槽也补成框）。"""
        box_width = min(104, right - left - 20)
        x1 = max(0, int(round((left + right) / 2 - box_width / 2)))
        x2 = min(width, x1 + box_width)
        y1 = max(0, int(round(center - 64)))
        y2 = min(height, y1 + 128)
        crop = gray[y1:y2, x1:x2]
        # 用较宽松的阈值只做“有无字”判断；框的位置仍来自固定格，
        # 不依赖被虫蛀打断的连续笔画。
        return crop.size > 0 and float(np.mean(crop < 170)) >= 0.08

    boxes: list[dict] = []
    def seed_for(center: float) -> tuple[float, list[float]] | None:
        if not seeds:
            return None
        candidates = [seed for seed in seeds if abs(center - seed[0]) <= 78]
        return min(candidates, key=lambda seed: abs(center - seed[0])) if candidates else None

    def is_seed_column(center: float) -> bool:
        return not seeds or seed_for(center) is not None

    def centers_for_column(seed: tuple[float, list[float]] | None) -> list[float]:
        """优先使用该列已确认字的行距，避免全页释文干扰行距。"""
        if seed and len(seed[1]) >= 2:
            known = seed[1]
            local_diffs = [b - a for a, b in zip(known, known[1:]) if 110 <= b - a <= 240]
            if local_diffs:
                local_pitch = float(np.median(local_diffs))
                anchor = known[0]
                while anchor - local_pitch >= height * 0.19:
                    anchor -= local_pitch
                values: list[float] = []
                # 最多向已有末字之后推一格；是否真实存在仍由 has_ink 决定。
                end = known[-1] + local_pitch
                while anchor <= end:
                    values.append(anchor)
                    anchor += local_pitch
                return values
        return row_centers

    # ``None`` 表示这一页从未有过人工框，可以用版格奇偶作初始提示；空列表
    # 表示“有旧框但全部因尺寸异常被判为不可信”，此时不能退回奇偶补框，
    # 否则会把卷七 0188 的所有双栏释文槽都框起来。
    if row_centers and (forced_columns or seeds is None or seeds):
        for column, (left, right) in enumerate(zip(lines, lines[1:])):
            if forced_columns is not None and column not in forced_columns:
                continue
            center = (left + right) / 2
            if forced_columns is None and is_double_text_column(gray, left, right):
                continue
            # 无历史框时沿用 092 的交替版格；有历史框时以历史篆书列为准。
            if forced_columns is not None:
                pass
            elif seeds is not None:
                if not is_seed_column(center):
                    continue
            elif column % 2:
                continue
            box_width = min(104, right - left - 20)
            x1 = max(0, int(round((left + right) / 2 - box_width / 2)))
            x2 = min(width, x1 + box_width)
            for row, row_center in enumerate(centers_for_column(seed_for(center))):
                if not has_ink(row_center, left, right):
                    continue
                y1 = max(0, int(round(row_center - 64)))
                y2 = min(height, y1 + 128)
                boxes.append({"column": column, "row": row, "bbox": [x1, y1, x2, y2]})
    for column, (left, right) in enumerate(zip(lines, lines[1:])):
        if forced_columns is not None and column not in forced_columns:
            continue
        if forced_columns is None and is_double_text_column(gray, left, right):
            continue
        # 无种子时也必须能发现整列漏框。释文或页边有时会连成一个极长
        # 墨迹段，不能把它算作篆字；只接受正常单字高度，并要求同列至少
        # 出现两个，以区别偶发污点和释文连片。
        runs = [run for run in run_map[column] if run[1] - run[0] <= 220]
        # 密排释文偶尔会被切成若干约 75px 的短段；篆字主体通常更高。
        # 中位高度 84px 能滤掉 0188 的释文列，同时保留 0017 等较小篆字。
        if len(runs) < 2 or float(np.median([y2 - y1 for y1, y2 in runs])) < 84:
            continue
        center = (left + right) / 2
        box_width = min(104, right - left - 20)
        x1 = max(0, int(round(center - box_width / 2)))
        x2 = min(width, int(round(center + box_width / 2)))
        for row, (y1, y2) in enumerate(runs):
            cy = (y1 + y2) / 2
            if any(
                item["column"] == column
                and abs((item["bbox"][1] + item["bbox"][3]) / 2 - cy) < 85
                for item in boxes
            ):
                continue
            # 包含完整笔势，但不吞进相邻字的留白。
            pad = max(5, int(round((y2 - y1) * 0.08)))
            y1, y2 = max(0, y1 - pad), min(height, y2 + pad)
            boxes.append({"column": column, "row": row, "bbox": [x1, y1, x2, y2]})

    # 淡墨列可能一个 active_run 都形成不了。若它位于已经确认的篆书列向
    # 外两格处，沿全页可靠行距逐槽检查；双栏释文已在上面排除。
    detected_columns = {item["column"] for item in boxes}
    extension_columns = [
        column for column in range(len(lines) - 1)
        if (forced_columns is None or column in forced_columns)
        and column not in detected_columns
        and (forced_columns is not None or not is_double_text_column(gray, lines[column], lines[column + 1]))
        and (column - 2 in detected_columns or column + 2 in detected_columns)
    ]
    for column in extension_columns:
        left, right = lines[column], lines[column + 1]
        box_width = min(104, right - left - 20)
        x1 = max(0, int(round((left + right) / 2 - box_width / 2)))
        x2 = min(width, x1 + box_width)
        for row, row_center in enumerate(row_centers):
            if not has_ink(row_center, left, right):
                continue
            y1 = max(0, int(round(row_center - 64)))
            y2 = min(height, y1 + 128)
            boxes.append({"column": column, "row": row, "bbox": [x1, y1, x2, y2]})
    return boxes


def make_entry(box: dict, work_dir: Path) -> dict:
    identifier = uuid.uuid4().hex
    return {
        "id": identifier, "uuid": identifier, "char": "", "font": "篆书",
        "author": "程德洽", "work": "说文广义", "work_dir": str(work_dir),
        "bbox": box["bbox"], "column": box["column"], "row": box["row"], "visible": True,
    }


def preview(image: np.ndarray, boxes: list[dict], output: Path) -> None:
    canvas = image.copy()
    for item in boxes:
        x1, y1, x2, y2 = item["bbox"]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 220, 0), 4)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), canvas)


def process(
    work_dir: Path,
    image_path: Path,
    *,
    apply: bool,
    replace: bool,
    forced_columns: set[int] | None = None,
) -> tuple[int, int]:
    gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    color = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if gray is None or color is None:
        raise FileNotFoundError(image_path)
    debug = work_dir / ".debug" / image_path.stem
    debug.mkdir(parents=True, exist_ok=True)
    chars = debug / "chars.json"
    existing = json.loads(chars.read_text()) if chars.exists() else []
    seeds = seed_columns(existing)
    boxes = propose(gray, seeds if existing else None, forced_columns)
    (debug / "seal-proposals.json").write_text(json.dumps(boxes, ensure_ascii=False, indent=2) + "\n")
    preview(color, boxes, debug / "seal-proposals-preview.jpg")
    if apply:
        backups = debug / "backups"
        backups.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(chars, backups / f"chars-before-volume-frames-{stamp}.json") if chars.exists() else None
        if replace:
            entries = [make_entry(box, work_dir) for box in boxes]
        else:
            lines = grid_lines(gray)
            grid_centers = [(left + right) / 2 for left, right in zip(lines, lines[1:])]
            proposal_columns = {int(box["column"]) for box in boxes}
            entries = []
            for original in existing:
                item = dict(original)
                bbox = item["bbox"]
                center = (bbox[0] + bbox[2]) / 2
                column = min(range(len(grid_centers)), key=lambda index: abs(grid_centers[index] - center))
                if abs(grid_centers[column] - center) <= 78:
                    # 已有框（包括空标签框）一律保留。双栏判定只能用于阻止
                    # 新框生成，不能据此删除旧框：淡墨篆字列偶尔也会呈现
                    # 双峰密度，卷三、五、十二曾因此整列被误删。
                    empty = not item.get("char")
                    width = bbox[2] - bbox[0]
                    height = bbox[3] - bbox[1]
                    malformed = not (35 <= width <= 140 and 55 <= height <= 280)
                    if empty and malformed and column in proposal_columns:
                        continue
                    if "column" in item or "col" not in item:
                        item["column"] = column
                    if "col" in item:
                        item["col"] = column
                entries.append(item)
            for box in boxes:
                x1, y1, x2, y2 = box["bbox"]
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                # 新的固定格与早期手工框上下边界可能相差约 60px；仍远小于
                # 相邻字约 150px 的行距，因此 85px 可正确视为同一字而不串行。
                if any(abs((e["bbox"][0] + e["bbox"][2]) / 2 - cx) < 35 and abs((e["bbox"][1] + e["bbox"][3]) / 2 - cy) < 85 for e in entries):
                    continue
                entries.append(make_entry(box, work_dir))
        # 列号以页面左侧网格为 0；同列行号从上到下连续，杜绝追加后的重复。
        columns = sorted({int(item.get("column", item.get("col", 0))) for item in entries})
        for column in columns:
            members = sorted(
                (item for item in entries if int(item.get("column", item.get("col", 0))) == column),
                key=lambda item: (item["bbox"][1] + item["bbox"][3]) / 2,
            )
            for row, item in enumerate(members):
                item["row"] = row
        entries.sort(key=lambda item: (-int(item.get("column", item.get("col", 0))), item["row"]))
        chars.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
    return len(boxes), len(existing)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--replace", action="store_true", help="以新检测结果重建框；默认仅补框")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=9999)
    parser.add_argument("--columns", help="只处理指定网格列，例如 0,2,5,7")
    args = parser.parse_args()
    forced_columns = (
        {int(value) for value in args.columns.split(",")}
        if args.columns else None
    )
    for image in sorted(args.work_dir.glob("fatie-*.webp")):
        number = int(image.stem.split("-")[-1])
        if not args.start <= number <= args.end:
            continue
        try:
            found, existing = process(
                args.work_dir,
                image,
                apply=args.apply,
                replace=args.replace,
                forced_columns=forced_columns,
            )
            print(f"{image.stem}: 检出 {found}，原有 {existing}")
        except Exception as error:
            print(f"{image.stem}: 失败：{error}")


if __name__ == "__main__":
    main()
