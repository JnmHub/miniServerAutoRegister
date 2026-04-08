#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass(frozen=True)
class ServeRow:
    line_no: int
    server_ip: str
    cpa_port: str
    cpa_key: str
    workers: int
    server_config: str


@dataclass
class Job:
    row: ServeRow
    command: list[str]
    log_path: Path
    log_handle: TextIO
    proc: subprocess.Popen[str]
    started_at: float


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Read serve_list.csv and launch one local origin.py process per row.",
    )
    parser.add_argument(
        "--serve-list",
        default="serve_list.csv",
        help="CSV file path, default: serve_list.csv",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=0,
        help="Maximum concurrent origin.py processes; 0 means all rows at once",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated server IPs to include",
    )
    parser.add_argument(
        "--log-dir",
        default=".serve_list_logs",
        help="Log directory root, default: .serve_list_logs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without launching child processes",
    )
    return parser.parse_known_args(argv)


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

            if not server_ip:
                raise ValueError(f"line {line_no}: empty 服务器ip")
            if not cpa_port:
                raise ValueError(f"line {line_no}: empty cpa端口")
            if not cpa_key:
                raise ValueError(f"line {line_no}: empty cpa管理员key")

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


def _build_command(origin_path: Path, origin_args: list[str], row: ServeRow) -> list[str]:
    return [
        sys.executable,
        str(origin_path),
        *origin_args,
        "--cpa-base-url",
        f"http://{row.server_ip}:{row.cpa_port}",
        "--cpa-token",
        row.cpa_key,
        "--workers",
        str(row.workers),
    ]


def _write_log_preamble(handle: TextIO, row: ServeRow, command: list[str]) -> None:
    handle.write(f"line_no={row.line_no}\n")
    handle.write(f"server_ip={row.server_ip}\n")
    handle.write(f"cpa_base_url=http://{row.server_ip}:{row.cpa_port}\n")
    handle.write(f"workers={row.workers}\n")
    handle.write(f"server_config={row.server_config or '-'}\n")
    handle.write(f"command={shlex.join(command)}\n")
    handle.write("\n")
    handle.flush()


def main(argv: list[str]) -> int:
    args, origin_args = _parse_args(argv)
    script_dir = Path(__file__).resolve().parent
    origin_path = script_dir / "origin.py"

    if not origin_path.is_file():
        print(f"[ERROR] origin.py was not found: {origin_path}")
        return 1

    serve_list_path = _normalize_path(script_dir, args.serve_list)
    log_root = _normalize_path(script_dir, args.log_dir)

    try:
        rows = _load_rows(serve_list_path)
        rows = _filter_rows(rows, args.only)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    if not rows:
        print("[ERROR] No rows matched the current filter.")
        return 1

    max_parallel = args.max_parallel if args.max_parallel > 0 else len(rows)
    max_parallel = max(1, min(max_parallel, len(rows)))

    py_label = sys.executable
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_dir = log_root / f"{stamp}_{int(time.time() * 1000)}"

    print(f"[INFO] Using Python: {py_label}")
    print(f"[INFO] Entry: origin.py")
    print(f"[INFO] Serve list: {serve_list_path}")
    print(f"[INFO] Rows selected: {len(rows)}")
    print(f"[INFO] Max parallel: {max_parallel}")

    if args.dry_run:
        print("[INFO] Dry run mode")
        for index, row in enumerate(rows, start=1):
            command = _build_command(origin_path, origin_args, row)
            print(
                f"[{index}/{len(rows)}] {row.server_ip} "
                f"workers={row.workers} cfg={row.server_config or '-'}"
            )
            print(shlex.join(command))
        return 0

    log_dir.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] Logs directory: {log_dir}")

    pending = list(rows)
    active: list[Job] = []
    success = 0
    failed = 0
    started = 0

    while pending or active:
        while pending and len(active) < max_parallel:
            row = pending.pop(0)
            command = _build_command(origin_path, origin_args, row)
            log_path = log_dir / f"{row.server_ip}.log"

            try:
                log_handle = log_path.open("w", encoding="utf-8")
                _write_log_preamble(log_handle, row, command)
                proc = subprocess.Popen(
                    command,
                    cwd=str(script_dir),
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except OSError as exc:
                failed += 1
                print(f"[FAIL] {row.server_ip} failed to start: {exc}")
                continue

            started += 1
            active.append(
                Job(
                    row=row,
                    command=command,
                    log_path=log_path,
                    log_handle=log_handle,
                    proc=proc,
                    started_at=time.monotonic(),
                )
            )
            print(
                f"[{started}/{len(rows)}] START {row.server_ip} "
                f"workers={row.workers} cfg={row.server_config or '-'} "
                f"-> {log_path.name}"
            )

        next_active: list[Job] = []
        progressed = False

        for job in active:
            return_code = job.proc.poll()
            if return_code is None:
                next_active.append(job)
                continue

            job.log_handle.close()
            elapsed = time.monotonic() - job.started_at
            if return_code == 0:
                success += 1
                print(f"[ OK ] {job.row.server_ip} ({elapsed:.1f}s) -> {job.log_path}")
            else:
                failed += 1
                print(f"[FAIL] {job.row.server_ip} ({elapsed:.1f}s) -> {job.log_path}")
            progressed = True

        active = next_active

        if active and not progressed:
            time.sleep(0.2)

    print()
    print(f"Finished. Total={len(rows)} Success={success} Failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
