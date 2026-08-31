# -*- coding: utf-8 -*-
"""PM Stack 独立更新器：等待主程序退出后安全替换并重启。"""

import argparse
import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


def _log_path():
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    path = Path(base) / "PM Stack" / "updater.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def log(message):
    try:
        with open(_log_path(), "a", encoding="utf-8") as output:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            output.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


def show_error(message):
    log(f"ERROR: {message}")
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(
            None, str(message), "PM Stack 更新失败", 0x10
        )


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def wait_for_process_exit(pid, timeout=120):
    if not pid or pid <= 0:
        return
    if os.name == "nt":
        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return
        try:
            result = ctypes.windll.kernel32.WaitForSingleObject(
                handle, int(timeout * 1000)
            )
            if result == 0x00000102:
                raise TimeoutError("等待主程序退出超时")
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
        return

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.25)
    raise TimeoutError("等待主程序退出超时")


def install_update(source, target, expected_sha256, restart=True):
    source = Path(source).resolve(strict=True)
    target = Path(target).resolve(strict=True)
    if source == target:
        raise ValueError("更新文件与主程序路径不能相同")
    if target.suffix.lower() != ".exe":
        raise ValueError("主程序目标必须是 EXE")
    if sha256_file(source) != expected_sha256.lower():
        raise ValueError("独立更新器二次 SHA-256 校验失败")

    stage = target.parent / f".{target.stem}.update-{os.getpid()}.tmp"
    backup = target.with_name(f"{target.stem}.previous{target.suffix}")
    try:
        with open(source, "rb") as incoming, open(stage, "wb") as output:
            shutil.copyfileobj(incoming, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if sha256_file(stage) != expected_sha256.lower():
            raise ValueError("目标目录暂存文件校验失败")

        if backup.exists():
            backup.unlink()
        os.replace(target, backup)
        try:
            os.replace(stage, target)
            if sha256_file(target) != expected_sha256.lower():
                raise ValueError("替换后的主程序校验失败")
            if restart:
                subprocess.Popen(
                    [str(target)], cwd=str(target.parent), close_fds=True
                )
        except Exception:
            if backup.exists():
                os.replace(backup, target)
            raise
        log(f"更新成功: {target}; 上一版本: {backup}")
        return str(backup)
    finally:
        if stage.exists():
            try:
                stage.unlink()
            except OSError:
                pass
        try:
            source.unlink()
        except OSError:
            pass


def build_parser():
    parser = argparse.ArgumentParser(description="PM Stack 独立更新器")
    parser.add_argument("--wait-pid", type=int, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha256", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        target = Path(args.target).resolve(strict=True)
        if getattr(sys, "frozen", False):
            helper_dir = Path(sys.executable).resolve().parent
            if target.parent != helper_dir:
                raise ValueError("更新器与主程序必须位于同一目录")
        log(f"开始安装 {args.version}: {target}")
        wait_for_process_exit(args.wait_pid)
        install_update(args.source, target, args.sha256, restart=True)
        return 0
    except Exception as exc:
        show_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
