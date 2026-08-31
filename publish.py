# -*- coding: utf-8 -*-
"""一键发布新版本：打包 EXE → 生成 update.json → 推送 GitHub → 创建 Release"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
MAIN_WINDOW = PROJECT_DIR / "core" / "main_window.py"
SPEC_TEMPLATE = list(PROJECT_DIR.glob("PM Stack V*.spec"))
DIST_EXE = PROJECT_DIR / "dist" / "PM Stack.exe"
UPDATE_JSON = PROJECT_DIR / "update.json"
GH_CLI = Path(r"D:\PM Stack\tools-gh\gh.exe")


def get_current_version():
    text = MAIN_WINDOW.read_text(encoding="utf-8")
    match = re.search(r'CURRENT_VERSION\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else None


def set_version(new_version):
    text = MAIN_WINDOW.read_text(encoding="utf-8")
    text = re.sub(
        r'CURRENT_VERSION\s*=\s*"[^"]+"',
        f'CURRENT_VERSION = "{new_version}"',
        text,
    )
    MAIN_WINDOW.write_text(text, encoding="utf-8")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def run(cmd, **kwargs):
    print(f"\n> {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"命令失败 (exit {result.returncode})，中止发布。")
        sys.exit(1)
    return result


def main():
    os.chdir(PROJECT_DIR)

    current = get_current_version()
    print(f"当前版本: {current}")

    new_version = input("请输入新版本号 (如 v1.10.3): ").strip()
    if not new_version:
        print("未输入版本号，取消。")
        return
    if not re.match(r"^v?\d+(\.\d+){1,3}$", new_version):
        print("版本号格式不正确，应为 v1.10.3 或 1.10.3 格式。")
        return
    if not new_version.startswith("v"):
        new_version = "v" + new_version

    notes = input("版本说明 (可留空): ").strip() or f"发布 {new_version}"

    print("\n[1/5] 更新版本号...")
    set_version(new_version)

    spec_file = None
    if SPEC_TEMPLATE:
        spec_file = PROJECT_DIR / f"PM Stack {new_version}.spec"
        if not spec_file.exists():
            old_spec = SPEC_TEMPLATE[-1]
            spec_text = old_spec.read_text(encoding="utf-8")
            spec_file.write_text(spec_text, encoding="utf-8")
            print(f"  基于 {old_spec.name} 创建 {spec_file.name}")

    print("\n[2/5] 打包 EXE (PyInstaller)...")
    pyinstaller_cmd = [sys.executable, "-m", "PyInstaller"]
    if spec_file and spec_file.exists():
        pyinstaller_cmd.append(str(spec_file))
    else:
        pyinstaller_cmd.extend(["--onefile", "--noconsole", "--name", "PM Stack", "main.py"])
    run(pyinstaller_cmd)

    if not DIST_EXE.exists():
        print("错误: 打包后未找到 dist/PM Stack.exe")
        sys.exit(1)
    print(f"  EXE 大小: {DIST_EXE.stat().st_size / 1024 / 1024:.1f} MB")

    print("\n[3/5] 生成 update.json...")
    manifest = {
        "version": new_version.lstrip("v"),
        "url": "PM Stack.exe",
        "sha256": sha256_file(DIST_EXE),
        "size": DIST_EXE.stat().st_size,
        "notes": notes,
    }
    UPDATE_JSON.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  SHA-256: {manifest['sha256']}")

    print("\n[4/5] 推送到 GitHub...")
    run(["git", "add", "core/main_window.py", "update.json"])
    if spec_file and spec_file.exists():
        run(["git", "add", str(spec_file)])
    run(["git", "commit", "-m", f"发布 {new_version}"])
    run(["git", "push"])

    print("\n[5/5] 创建 GitHub Release...")
    tag = new_version if new_version.startswith("v") else f"v{new_version}"
    run([
        str(GH_CLI), "release", "create", tag,
        "--title", f"PM Stack {new_version}",
        "--notes", notes,
        "--latest",
    ])

    print("\n" + "=" * 60)
    print(f"  {new_version} 已发布!")
    print("=" * 60)
    print(f"\n请在浏览器中打开以下页面，手动上传附件:")
    print(f"  https://github.com/Song-wenpeng/PM-Stack/releases/tag/{tag}")
    print(f"\n需要上传的文件:")
    print(f"  1. {DIST_EXE}")
    print(f"  2. {UPDATE_JSON}")
    release_zip = PROJECT_DIR / "release" / f"PM Stack {new_version} 首次分发.zip"
    if release_zip.exists():
        print(f"  3. {release_zip}")
    print()
    input("按回车键退出...")


if __name__ == "__main__":
    main()
