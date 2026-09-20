# -*- coding: utf-8 -*-
"""一键发布新版本：打包 EXE → 生成 update.json → 推送 GitHub → 创建 Release"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
MAIN_WINDOW = PROJECT_DIR / "core" / "main_window.py"
SPEC_TEMPLATE = list(PROJECT_DIR.glob("PM Stack V*.spec"))
DIST_EXE = PROJECT_DIR / "dist" / "PM Stack.exe"
DIST_UPDATER = PROJECT_DIR / "dist" / "PM Stack Updater.exe"
UPDATER_SPEC = PROJECT_DIR / "PM Stack Updater.spec"
UPDATE_JSON = PROJECT_DIR / "update.json"
UPDATE_CHANNEL = PROJECT_DIR / "update-channel.json"
RELEASE_DIR = PROJECT_DIR / "release"
RELEASE_CURRENT = RELEASE_DIR / "current"
RELEASE_ARCHIVE = RELEASE_DIR / "archive"
RELEASE_GUIDE = PROJECT_DIR / "发布更新指南.md"
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


def prepare_release_artifacts(version):
    """生成干净的当前分发目录、版本归档和首次分发压缩包。"""
    distribution_files = (
        (DIST_EXE, "PM Stack.exe"),
        (DIST_UPDATER, "PM Stack Updater.exe"),
        (UPDATE_CHANNEL, "update-channel.json"),
    )
    archive_files = distribution_files + (
        (UPDATE_JSON, "update.json"),
        (RELEASE_GUIDE, "发布更新指南.md"),
    )

    missing = [str(source) for source, _ in archive_files
               if not source.exists()]
    if missing:
        print("错误: 缺少发布文件:")
        for path in missing:
            print(f"  {path}")
        sys.exit(1)

    RELEASE_CURRENT.mkdir(parents=True, exist_ok=True)
    version_dir = RELEASE_ARCHIVE / version
    version_dir.mkdir(parents=True, exist_ok=True)

    for source, name in distribution_files:
        shutil.copy2(source, RELEASE_CURRENT / name)
    for source, name in archive_files:
        shutil.copy2(source, version_dir / name)

    zip_path = version_dir / f"PM Stack {version} 首次分发.zip"
    temp_zip = zip_path.with_name(zip_path.name + ".tmp")
    try:
        with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for _, name in distribution_files:
                archive.write(RELEASE_CURRENT / name, arcname=name)
        os.replace(temp_zip, zip_path)
    finally:
        if temp_zip.exists():
            temp_zip.unlink()

    return version_dir, zip_path


def main():
    if sys.version_info < (3, 12):
        raise RuntimeError("发布需要 Python 3.12+，请使用 .venv-review/Scripts/python.exe publish.py")
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

    print("\n[1/6] 更新版本号...")
    set_version(new_version)

    spec_file = None
    if SPEC_TEMPLATE:
        spec_file = PROJECT_DIR / f"PM Stack {new_version}.spec"
        if not spec_file.exists():
            current_spec = PROJECT_DIR / f"PM Stack {current}.spec"
            old_spec = (current_spec if current_spec.exists()
                        else max(SPEC_TEMPLATE,
                                 key=lambda path: path.stat().st_mtime))
            spec_text = old_spec.read_text(encoding="utf-8")
            spec_file.write_text(spec_text, encoding="utf-8")
            print(f"  基于 {old_spec.name} 创建 {spec_file.name}")

    print("\n[2/6] 打包主程序和更新器 (PyInstaller)...")
    pyinstaller_cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm"]
    if spec_file and spec_file.exists():
        pyinstaller_cmd.append(str(spec_file))
    else:
        pyinstaller_cmd.extend(["--onefile", "--noconsole", "--name", "PM Stack", "main.py"])
    run(pyinstaller_cmd)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm",
         str(UPDATER_SPEC)])

    if not DIST_EXE.exists() or not DIST_UPDATER.exists():
        print("错误: 打包后未找到主程序或更新器")
        sys.exit(1)
    print(f"  EXE 大小: {DIST_EXE.stat().st_size / 1024 / 1024:.1f} MB")

    print("\n[3/6] 生成 update.json...")
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

    print("\n[4/6] 整理分发文件...")
    version_dir, release_zip = prepare_release_artifacts(new_version)
    print(f"  当前分发目录: {RELEASE_CURRENT}")
    print(f"  版本归档目录: {version_dir}")
    print(f"  首次分发压缩包: {release_zip}")

    print("\n[5/6] 推送到 GitHub...")
    run(["git", "add", "core/main_window.py", "update.json"])
    if spec_file and spec_file.exists():
        run(["git", "add", str(spec_file)])
    run(["git", "commit", "-m", f"发布 {new_version}"])
    run(["git", "push"])

    print("\n[6/6] 创建 GitHub Release...")
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
    if release_zip.exists():
        print(f"  3. {release_zip}")
    print()
    input("按回车键退出...")


if __name__ == "__main__":
    main()
