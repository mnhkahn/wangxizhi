#!/usr/bin/env python3
"""批量扫描并直接上传本地 WebP 到 Cloudinary。

特性：
- 递归扫描目录下所有 .webp（大小写不敏感）
- 支持 `--limit` 控制上传数量
- 直接调用 Cloudinary Upload API
- 上传过程显示进度条
- 最终输出 summary 表格

认证方式（两种择一）：
1) Signed upload（推荐）：提供 `--cloud-name`、`--api-key`、`--api-secret`
2) Unsigned upload：提供 `--cloud-name`、`--upload-preset` 并使用 `--unsigned`

依赖：`cloudinary`（Cloudinary 官方 Python SDK）。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple


MAX_FILES_PER_BATCH = 50


@dataclass
class UploadItem:
    abs_path: Path
    rel_path: str
    size_bytes: int
    public_id: str


@dataclass
class UploadResult:
    rel_path: str
    abs_path: str
    size_bytes: int
    public_id: str
    ok: bool
    url: str
    error: str


def collect_upload_items(root: Path, limit: int = 0, keep_dirs: bool = False) -> List[UploadItem]:
    """扫描 root 下的 webp，返回用于上传的条目列表。"""

    root = root.expanduser().resolve()
    webps = sorted(_iter_webp_files(root))
    if limit and limit > 0:
        webps = webps[:limit]

    items: List[UploadItem] = []
    for p in webps:
        rel = _safe_rel_path(p, root)
        try:
            st = p.stat()
            size = int(st.st_size)
        except OSError:
            size = -1
        public_id = _compute_public_id(rel, keep_dirs=keep_dirs)
        items.append(UploadItem(abs_path=p, rel_path=rel, size_bytes=size, public_id=public_id))
    return items


def upload_items(
    *,
    items: Sequence[UploadItem],
    cloud_name: str,
    api_key: str = "",
    api_secret: str = "",
    unsigned: bool = False,
    upload_preset: str = "",
    folder: str = "",
    timeout_s: int = 600,
    concurrency: int = 4,
    progress_cb: Optional[Any] = None,
) -> List[UploadResult]:
    """上传多个条目。

    progress_cb：可选回调，签名 progress_cb(idx:int, total:int, item:UploadItem, result:UploadResult)
    """

    total = len(items)
    if total == 0:
        return []

    # 并发度至少为 1
    try:
        concurrency_n = int(concurrency)
    except Exception:
        concurrency_n = 4
    concurrency_n = max(1, concurrency_n)

    # 预先配置一次（减少重复配置开销；并在多线程中保持一致）
    _cloudinary_configure(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret)

    results: List[Optional[UploadResult]] = [None] * total
    done_counter = 0
    done_lock = threading.Lock()

    def _task(i: int, it: UploadItem) -> Tuple[int, UploadItem, UploadResult]:
        ok, url, err = _cloudinary_upload_one(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            unsigned=unsigned,
            upload_preset=upload_preset,
            folder=folder,
            public_id=it.public_id,
            file_path=it.abs_path,
            timeout_s=timeout_s,
        )
        r = UploadResult(
            rel_path=it.rel_path,
            abs_path=str(it.abs_path),
            size_bytes=it.size_bytes,
            public_id=it.public_id,
            ok=ok,
            url=url,
            error=err,
        )
        return i, it, r

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency_n) as ex:
        futures = [ex.submit(_task, i, it) for i, it in enumerate(items)]
        for fut in concurrent.futures.as_completed(futures):
            i, it, r = fut.result()
            results[i] = r
            if progress_cb:
                with done_lock:
                    done_counter += 1
                    done = done_counter
                try:
                    progress_cb(done, total, it, r)
                except Exception:
                    pass

    # mypy: results 填充完毕
    return [r for r in results if r is not None]


def _iter_webp_files(root: Path) -> Iterable[Path]:
    # rglob("*") + suffix check 比 rglob("*.webp") 更稳（处理大小写）
    for p in root.rglob("*"):
        try:
            if p.is_file() and p.suffix.lower() == ".webp":
                yield p
        except OSError:
            # 跳过权限/坏链接等异常
            continue


def _safe_rel_path(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
        return rel.as_posix()
    except ValueError:
        return path.name


def _compute_public_id(rel_path: str, keep_dirs: bool) -> str:
    # Cloudinary public_id 通常不需要扩展名
    base = rel_path
    if base.lower().endswith(".webp"):
        base = base[: -len(".webp")]
    if keep_dirs:
        # 使用 / 保持目录层级（Cloudinary 支持 public_id 包含 /）
        return base
    # 将目录分隔符压平，避免创建嵌套
    return base.replace("/", "__")


def _chunks(seq: Sequence[UploadItem], n: int) -> Iterable[List[UploadItem]]:
    for i in range(0, len(seq), n):
        yield list(seq[i : i + n])


def _human_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024.0 or u == units[-1]:
            if u == "B":
                return f"{int(f)}{u}"
            return f"{f:.1f}{u}"
        f /= 1024.0
    return f"{int(n)}B"


def _render_progress(done: int, total: int, extra: str) -> None:
    width = 30
    if total <= 0:
        total = 1
    ratio = min(max(done / total, 0.0), 1.0)
    filled = int(ratio * width)
    bar = "=" * filled + "-" * (width - filled)
    msg = f"[{bar}] {done}/{total} {extra}"
    # 仅覆盖当前行
    sys.stderr.write("\r" + msg[: max(0, shutil_get_terminal_width() - 1)])
    sys.stderr.flush()


def shutil_get_terminal_width() -> int:
    try:
        import shutil

        return shutil.get_terminal_size((120, 20)).columns
    except Exception:
        return 120


def _cloudinary_import():
    try:
        import cloudinary  # type: ignore
        import cloudinary.uploader  # type: ignore

        return cloudinary
    except Exception as e:
        raise RuntimeError(
            "未安装 Cloudinary 官方 Python 包：请执行 `pip install cloudinary`"
        ) from e


def _cloudinary_configure(
    *,
    cloud_name: str,
    api_key: str,
    api_secret: str,
) -> Any:
    cloudinary = _cloudinary_import()
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key or None,
        api_secret=api_secret or None,
        secure=True,
    )
    return cloudinary


def _cloudinary_upload_one(
    *,
    cloud_name: str,
    api_key: str,
    api_secret: str,
    unsigned: bool,
    upload_preset: str,
    folder: str,
    public_id: str,
    file_path: Path,
    timeout_s: int,
) -> Tuple[bool, str, str]:
    """上传单个文件，返回 (ok, url, error)。"""

    if unsigned and not upload_preset:
        return False, "", "unsigned 上传必须提供 upload_preset（--upload-preset 或 CLOUDINARY_UPLOAD_PRESET）"
    if (not unsigned) and (not api_key or not api_secret):
        return False, "", "signed 上传必须提供 api_key/api_secret"

    cloudinary = _cloudinary_configure(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
    )

    options: dict = {
        "folder": folder or None,
        "public_id": public_id or None,
        "resource_type": "image",
        "timeout": timeout_s,
    }
    # 清理 None（SDK 会把 None 也透传）
    options = {k: v for k, v in options.items() if v is not None}

    try:
        if unsigned:
            resp = cloudinary.uploader.unsigned_upload(str(file_path), upload_preset, **options)
        else:
            resp = cloudinary.uploader.upload(str(file_path), **options)

        url = str(resp.get("secure_url") or resp.get("url") or "")
        if not url:
            return False, "", "Cloudinary 返回缺少 url"
        return True, url, ""
    except Exception as e:
        return False, "", str(e)


def _format_table(rows: List[List[str]], headers: List[str]) -> str:
    all_rows = [headers] + rows
    widths = [max(len(r[i]) for r in all_rows) if all_rows else 0 for i in range(len(headers))]

    def fmt_row(r: List[str]) -> str:
        return " | ".join(r[i].ljust(widths[i]) for i in range(len(headers)))

    sep = "-+-".join("-" * w for w in widths)
    out = [fmt_row(headers), sep]
    out.extend(fmt_row(r) for r in rows)
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="扫描本地 WebP 并批量上传到 Cloudinary")
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="扫描根目录（默认当前目录）",
    )
    parser.add_argument(
        "--folder",
        "--remote-folder",
        dest="folder",
        default=os.environ.get("CLOUDINARY_FOLDER", ""),
        help="Cloudinary 目标文件夹（可选；也可用环境变量 CLOUDINARY_FOLDER）",
    )
    parser.add_argument(
        "--cloud-name",
        default=os.environ.get("CLOUDINARY_CLOUD_NAME", ""),
        help="Cloudinary cloud_name（也可用环境变量 CLOUDINARY_CLOUD_NAME）",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CLOUDINARY_API_KEY", ""),
        help="Cloudinary api_key（signed 上传；也可用环境变量 CLOUDINARY_API_KEY）",
    )
    parser.add_argument(
        "--api-secret",
        default=os.environ.get("CLOUDINARY_API_SECRET", ""),
        help="Cloudinary api_secret（signed 上传；也可用环境变量 CLOUDINARY_API_SECRET）",
    )
    parser.add_argument(
        "--upload-preset",
        default=os.environ.get("CLOUDINARY_UPLOAD_PRESET", ""),
        help="Cloudinary upload preset（unsigned 或 signed 均可用；也可用环境变量 CLOUDINARY_UPLOAD_PRESET）",
    )
    parser.add_argument(
        "--unsigned",
        action="store_true",
        help="使用 unsigned 上传（需 upload_preset；不需要 api_key/api_secret）",
    )
    parser.add_argument(
        "--keep-dirs",
        action="store_true",
        help="将相对路径保留到 public_id（默认会把目录压平成 __）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="最多处理多少个文件（0 表示不限制）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只扫描并输出汇总，不上传",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="单批次上传超时秒数（默认 600）",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="并发上传线程数（默认 4）",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        print(f"root 不存在：{root}", file=sys.stderr)
        return 2

    items = collect_upload_items(root, limit=int(args.limit or 0), keep_dirs=bool(args.keep_dirs))

    if not items:
        print("未找到 .webp 文件。")
        return 0

    total = len(items)
    started = time.time()

    if args.dry_run:
        results: List[UploadResult] = []
        for it in items:
            results.append(
                UploadResult(
                    rel_path=it.rel_path,
                    abs_path=str(it.abs_path),
                    size_bytes=it.size_bytes,
                    public_id=it.public_id,
                    ok=True,
                    url="(dry-run)",
                    error="",
                )
            )
    else:
        if not str(args.cloud_name).strip():
            print("缺少 Cloudinary cloud_name：请提供 --cloud-name 或设置 CLOUDINARY_CLOUD_NAME", file=sys.stderr)
            return 2

        ok_cnt = 0
        fail_cnt = 0

        def _cb(done: int, total_: int, _it: UploadItem, r: UploadResult):
            nonlocal ok_cnt, fail_cnt
            if r.ok:
                ok_cnt += 1
            else:
                fail_cnt += 1
            elapsed = max(0.001, time.time() - started)
            speed = done / elapsed
            extra = f"ok={ok_cnt} fail={fail_cnt} {speed:.1f}files/s"
            _render_progress(done, total_, extra)

        results = upload_items(
            items=items,
            cloud_name=str(args.cloud_name),
            api_key=str(args.api_key),
            api_secret=str(args.api_secret),
            unsigned=bool(args.unsigned),
            upload_preset=str(args.upload_preset),
            folder=str(args.folder or ""),
            timeout_s=int(args.timeout),
            concurrency=int(args.concurrency or 4),
            progress_cb=_cb,
        )

    # 结束进度条行
    if not args.dry_run:
        sys.stderr.write("\n")

    # 汇总表
    rows: List[List[str]] = []
    for idx, r in enumerate(results, start=1):
        rows.append(
            [
                str(idx),
                "OK" if r.ok else "FAIL",
                _human_bytes(r.size_bytes) if r.size_bytes >= 0 else "?",
                r.public_id,
                r.rel_path,
                (r.url or "")[:120],
                (r.error or "")[:120],
            ]
        )

    headers = ["#", "状态", "大小", "public_id", "文件", "URL(截断)", "错误(截断)"]
    print(_format_table(rows, headers))

    total_size = sum(r.size_bytes for r in results if r.size_bytes > 0)
    ok_final = sum(1 for r in results if r.ok)
    fail_final = sum(1 for r in results if not r.ok)
    print("")
    print(
        "总结："
        f"总数={len(results)}，成功={ok_final}，失败={fail_final}，"
        f"总大小={_human_bytes(total_size)}，"
        f"root={root}，folder={args.folder!r}"
        + ("（dry-run）" if args.dry_run else "")
    )

    return 0 if fail_final == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
