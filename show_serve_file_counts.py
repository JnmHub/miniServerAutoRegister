#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from upload_management_file import ZeaburAuthFileManager


@dataclass(frozen=True)
class ServeRow:
    line_no: int
    server_ip: str
    cpa_port: str
    cpa_key: str
    workers: int
    server_config: str


@dataclass(frozen=True)
class CountResult:
    row: ServeRow
    count: Optional[int]
    error: str


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show auth file counts for each row in serve_list.csv.",
    )
    parser.add_argument(
        "--serve-list",
        default="serve_list.csv",
        help="CSV file path, default: serve_list.csv",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated server IPs to include",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=0,
        help="Maximum concurrent count requests, default: all selected rows",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Per-request timeout seconds, default: 15",
    )
    return parser.parse_args(argv)


def _normalize_path(script_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return script_dir / path


def _load_rows(csv_path: Path) -> list[ServeRow]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"serve list not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = ("服务器ip", "cpa端口", "cpa管理员key", "线程")
        missing = [name for name in required if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"serve list missing columns: {', '.join(missing)}")

        rows: list[ServeRow] = []
        for line_no, raw in enumerate(reader, start=2):
            if not raw or not any(str(value or "").strip() for value in raw.values()):
                continue

            server_ip = str(raw.get("服务器ip") or "").strip()
            cpa_port = str(raw.get("cpa端口") or "").strip()
            cpa_key = str(raw.get("cpa管理员key") or "").strip()
            workers_text = str(raw.get("线程") or "").strip()
            server_config = str(raw.get("服务器配置") or "").strip()

            if not server_ip or not cpa_port or not cpa_key:
                raise ValueError(f"line {line_no}: missing required CSV values")

            try:
                workers = max(1, int(workers_text))
            except ValueError as exc:
                raise ValueError(f"line {line_no}: invalid 线程={workers_text!r}") from exc

            rows.append(
                ServeRow(
                    line_no=line_no,
                    server_ip=server_ip,
                    cpa_port=cpa_port,
                    cpa_key=cpa_key,
                    workers=workers,
                    server_config=server_config,
                )
            )

    if not rows:
        raise ValueError(f"serve list has no runnable rows: {csv_path}")
    return rows


def _filter_rows(rows: list[ServeRow], only_text: str) -> list[ServeRow]:
    selected = {item.strip() for item in only_text.split(",") if item.strip()}
    if not selected:
        return rows
    return [row for row in rows if row.server_ip in selected]


def _fetch_count(row: ServeRow, timeout: float) -> CountResult:
    base_url = f"http://{row.server_ip}:{row.cpa_port}"
    try:
        manager = ZeaburAuthFileManager(base_url, row.cpa_key, timeout=timeout)
        count = manager.count_files(strict=True)
        return CountResult(row=row, count=count, error="")
    except Exception as exc:
        return CountResult(row=row, count=None, error=str(exc))


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    script_dir = Path(__file__).resolve().parent
    serve_list_path = _normalize_path(script_dir, args.serve_list)

    try:
        rows = _load_rows(serve_list_path)
        rows = _filter_rows(rows, args.only)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    if not rows:
        print("[ERROR] No rows matched the current filter.")
        return 1

    requested_parallel = int(args.max_parallel or 0)
    if requested_parallel <= 0:
        max_parallel = len(rows)
    else:
        max_parallel = max(1, min(requested_parallel, len(rows)))
    timeout = max(1.0, float(args.timeout or 15.0))

    print(f"[INFO] Serve list: {serve_list_path}")
    print(f"[INFO] Rows selected: {len(rows)}")
    print(f"[INFO] Max parallel: {max_parallel}")
    print(f"[INFO] Timeout: {timeout:.1f}s")
    print()

    results: list[CountResult] = []
    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        future_map = {pool.submit(_fetch_count, row, timeout): row for row in rows}
        for future in as_completed(future_map):
            result = future.result()
            results.append(result)
            if result.error:
                print(f"[FAIL] {result.row.server_ip} -> {result.error}")
            else:
                print(
                    f"[ OK ] {result.row.server_ip} "
                    f"cfg={result.row.server_config or '-'} "
                    f"workers={result.row.workers} files={result.count}"
                )

    print()
    print("服务器IP\t配置\t线程\t文件数量\t状态")
    total_count = 0
    success = 0
    failed = 0
    for result in sorted(results, key=lambda item: item.row.line_no):
        if result.count is None:
            failed += 1
            count_text = "-"
            status_text = f"FAIL: {result.error}"
        else:
            success += 1
            total_count += result.count
            count_text = str(result.count)
            status_text = "OK"
        print(
            f"{result.row.server_ip}\t"
            f"{result.row.server_config or '-'}\t"
            f"{result.row.workers}\t"
            f"{count_text}\t"
            f"{status_text}"
        )

    print()
    print(
        f"Finished. Total={len(results)} Success={success} Failed={failed} "
        f"FileCountSum={total_count}"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
