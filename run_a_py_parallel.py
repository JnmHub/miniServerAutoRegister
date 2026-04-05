#!/usr/bin/env python3

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    script_dir = Path(__file__).resolve().parent
    targets = sorted(path for path in script_dir.glob("a*.py") if path.is_file())

    if not targets:
        print(f"[INFO] No files matched a*.py in {script_dir}.")
        return 1

    py_label = os.environ.get("RUN_A_PY_LABEL") or sys.executable

    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_dir = script_dir / ".run_a_py_logs" / f"{stamp}_{os.getpid()}"
    log_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Using Python: {py_label}")
    print(f"[INFO] Parallel mode: {len(targets)} files")
    print(f"[INFO] Logs directory: {log_dir}")

    pending: list[dict[str, object]] = []
    failed_to_start = 0

    for index, target in enumerate(targets, start=1):
        log_path = log_dir / f"{target.name}.log"
        started_at = time.monotonic()
        log_handle = None

        try:
            log_handle = log_path.open("w", encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, str(target), *argv],
                cwd=str(script_dir),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as exc:
            if log_handle is not None:
                log_handle.close()
            failed_to_start += 1
            print(f"[FAIL] {target.name} failed to start: {exc}")
            continue

        pending.append(
            {
                "name": target.name,
                "log_path": log_path,
                "log_handle": log_handle,
                "proc": proc,
                "started_at": started_at,
            }
        )
        print(f"[{index}/{len(targets)}] Started {target.name} -> {log_path.name}")

    success = 0
    failed = failed_to_start

    while pending:
        next_round: list[dict[str, object]] = []
        progressed = False

        for job in pending:
            proc = job["proc"]
            assert isinstance(proc, subprocess.Popen)

            return_code = proc.poll()
            if return_code is None:
                next_round.append(job)
                continue

            log_handle = job["log_handle"]
            assert hasattr(log_handle, "close")
            log_handle.close()

            started_at = job["started_at"]
            assert isinstance(started_at, float)
            elapsed = time.monotonic() - started_at

            name = str(job["name"])
            log_path = job["log_path"]

            if return_code == 0:
                success += 1
                print(f"[ OK ] {name} ({elapsed:.1f}s) -> {log_path}")
            else:
                failed += 1
                print(f"[FAIL] {name} ({elapsed:.1f}s) -> {log_path}")

            progressed = True

        pending = next_round

        if pending and not progressed:
            time.sleep(0.2)

    print()
    print(f"Finished. Total={len(targets)} Success={success} Failed={failed}")

    if failed > 0:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
