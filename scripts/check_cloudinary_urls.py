#!/usr/bin/env python3
"""Check Cloudinary glyph image URLs referenced by glyphs.sqlite.

The database stores glyph ids, not full Cloudinary URLs.  This script builds
URLs with the same rule used by the uploader:

    https://res.cloudinary.com/<cloud>/image/upload/<folder>/words__<id>.webp

It uses HEAD requests first, and falls back to a 1-byte ranged GET only when a
server does not support HEAD.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_DB = Path("ocr_output/glyphs.sqlite")
DEFAULT_CLOUD_NAME = "cyeam"
DEFAULT_FOLDER = "mo"


@dataclass(frozen=True)
class GlyphRow:
    id: str
    char: str
    work_dir: str
    author: str
    font: str
    work_title: str
    url: str


@dataclass(frozen=True)
class CheckResult:
    glyph: GlyphRow
    status_code: int | None
    ok: bool
    method: str
    error: str
    elapsed_ms: int


def build_cloudinary_url(glyph_id: str, cloud_name: str, folder: str) -> str:
    public_id = f"words__{glyph_id}.webp"
    folder = folder.strip("/")
    path = f"{folder}/{public_id}" if folder else public_id
    return f"https://res.cloudinary.com/{cloud_name}/image/upload/{path}"


def load_glyphs(
    db_path: Path,
    cloud_name: str,
    folder: str,
    limit: int,
    ids: list[str],
) -> list[GlyphRow]:
    conn = sqlite3.connect(str(db_path))
    try:
        sql = """
            SELECT id, char, work_dir, author, font, work_title
              FROM glyphs
             WHERE id IS NOT NULL AND id != ''
        """
        params: list[str | int] = []
        if ids:
            placeholders = ",".join("?" for _ in ids)
            sql += f" AND id IN ({placeholders})"
            params.extend(ids)
        sql += " ORDER BY work_dir, id"
        if limit > 0 and not ids:
            sql += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    glyphs: list[GlyphRow] = []
    for row in rows:
        glyph_id = str(row[0])
        glyphs.append(
            GlyphRow(
                id=glyph_id,
                char=str(row[1] or ""),
                work_dir=str(row[2] or ""),
                author=str(row[3] or ""),
                font=str(row[4] or ""),
                work_title=str(row[5] or ""),
                url=build_cloudinary_url(glyph_id, cloud_name, folder),
            )
        )
    return glyphs


def _request_status(url: str, method: str, timeout: float) -> int:
    headers = {"User-Agent": "wangxizhi-cloudinary-check/1.0"}
    if method == "GET":
        headers["Range"] = "bytes=0-0"
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as e:
        return int(e.code)


def check_one(glyph: GlyphRow, timeout: float, retries: int, sleep_s: float) -> CheckResult:
    started = time.monotonic()
    method = "HEAD"
    last_error = ""
    status_code: int | None = None

    for attempt in range(retries + 1):
        try:
            status_code = _request_status(glyph.url, "HEAD", timeout)
            method = "HEAD"
            if status_code == 405:
                status_code = _request_status(glyph.url, "GET", timeout)
                method = "GET_RANGE"
            break
        except Exception as e:  # noqa: BLE001 - keep batch scan resilient
            last_error = str(e)
            if attempt < retries and sleep_s > 0:
                time.sleep(sleep_s)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    ok = status_code is not None and 200 <= status_code < 400
    return CheckResult(
        glyph=glyph,
        status_code=status_code,
        ok=ok,
        method=method,
        error=last_error if status_code is None else "",
        elapsed_ms=elapsed_ms,
    )


def ensure_cache_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cloudinary_url_checks (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            status_code INTEGER,
            ok INTEGER NOT NULL,
            method TEXT NOT NULL,
            error TEXT NOT NULL,
            elapsed_ms INTEGER NOT NULL,
            checked_at INTEGER NOT NULL
        )
        """
    )


def write_cache(db_path: Path, results: Iterable[CheckResult]) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_cache_table(conn)
        now = int(time.time())
        conn.executemany(
            """
            INSERT OR REPLACE INTO cloudinary_url_checks
                (id, url, status_code, ok, method, error, elapsed_ms, checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.glyph.id,
                    r.glyph.url,
                    r.status_code,
                    1 if r.ok else 0,
                    r.method,
                    r.error,
                    r.elapsed_ms,
                    now,
                )
                for r in results
            ],
        )
        conn.commit()
    finally:
        conn.close()


def write_csv(path: Path, results: list[CheckResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "id",
                "char",
                "work_dir",
                "author",
                "font",
                "work_title",
                "status_code",
                "ok",
                "method",
                "elapsed_ms",
                "error",
                "url",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r.glyph.id,
                    r.glyph.char,
                    r.glyph.work_dir,
                    r.glyph.author,
                    r.glyph.font,
                    r.glyph.work_title,
                    r.status_code if r.status_code is not None else "",
                    1 if r.ok else 0,
                    r.method,
                    r.elapsed_ms,
                    r.error,
                    r.glyph.url,
                ]
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 glyphs.sqlite 对应 Cloudinary 图片是否 404")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 路径")
    parser.add_argument("--cloud-name", default=DEFAULT_CLOUD_NAME, help="Cloudinary cloud name")
    parser.add_argument("--folder", default=DEFAULT_FOLDER, help="Cloudinary folder，如 mo")
    parser.add_argument("--concurrency", type=int, default=12, help="并发数")
    parser.add_argument("--timeout", type=float, default=8.0, help="单次请求超时秒数")
    parser.add_argument("--retries", type=int, default=1, help="失败重试次数")
    parser.add_argument("--retry-sleep", type=float, default=0.2, help="重试间隔秒数")
    parser.add_argument("--limit", type=int, default=0, help="最多检查多少条，0 表示全部")
    parser.add_argument("--id", action="append", default=[], help="只检查指定 glyph id，可重复传")
    parser.add_argument("--output", default="tmp/cloudinary_url_checks.csv", help="CSV 输出路径")
    parser.add_argument("--no-cache", action="store_true", help="不写回 SQLite 缓存表")
    parser.add_argument("--show-ok", action="store_true", help="终端也输出可访问记录")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"SQLite 不存在: {db_path}", file=sys.stderr)
        return 2

    glyphs = load_glyphs(db_path, args.cloud_name, args.folder, args.limit, list(args.id or []))
    if not glyphs:
        print("没有可检查的 glyph 记录")
        return 0

    concurrency = max(1, int(args.concurrency))
    results: list[CheckResult] = []
    total = len(glyphs)
    done = 0

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(check_one, glyph, float(args.timeout), int(args.retries), float(args.retry_sleep))
            for glyph in glyphs
        ]
        for fut in as_completed(futures):
            result = fut.result()
            results.append(result)
            done += 1
            status = result.status_code if result.status_code is not None else "ERR"
            if args.show_ok or not result.ok:
                print(f"[{done}/{total}] {status} {result.glyph.id} {result.glyph.char} {result.glyph.url}")

    results.sort(key=lambda r: (r.status_code is None, r.status_code or 0, r.glyph.work_dir, r.glyph.id))
    write_csv(Path(args.output), results)
    if not args.no_cache:
        write_cache(db_path, results)

    missing = [r for r in results if r.status_code == 404]
    failed = [r for r in results if not r.ok]
    print(f"检查完成: total={len(results)} ok={len(results)-len(failed)} failed={len(failed)} 404={len(missing)}")
    print(f"CSV: {args.output}")
    if not args.no_cache:
        print("SQLite cache table: cloudinary_url_checks")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
