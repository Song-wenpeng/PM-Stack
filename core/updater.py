# -*- coding: utf-8 -*-
"""GitHub 插件更新器 — 检查远程 Release 并下载插件包"""

import os
import json
import shutil
import stat
import zipfile
import tempfile
import urllib.request
import urllib.error
from pathlib import Path, PurePosixPath
from PyQt6.QtCore import QObject, pyqtSignal


GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
MAX_DOWNLOAD_BYTES = 250 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 5000
MAX_EXTRACTED_BYTES = 500 * 1024 * 1024


def _parse_version(ver: str) -> tuple:
    """将 'v1.2.3' 或 '1.2.3' 解析为可比较的元组。"""
    ver = ver.lstrip("vV")
    parts = []
    for p in ver.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _is_zip_symlink(info):
    unix_mode = info.external_attr >> 16
    return stat.S_ISLNK(unix_mode)


def _safe_extract_zip(zip_file, target_dir):
    """Extract an update archive without traversal, links, or zip bombs."""
    root = Path(target_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    infos = zip_file.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise ValueError(f"更新包文件数超过限制 ({MAX_ARCHIVE_ENTRIES})")

    total_size = 0
    for info in infos:
        total_size += info.file_size
        if total_size > MAX_EXTRACTED_BYTES:
            raise ValueError("更新包解压后体积超过安全限制")
        if _is_zip_symlink(info):
            raise ValueError(f"更新包不允许包含符号链接: {info.filename}")

        normalized = info.filename.replace("\\", "/")
        member = PurePosixPath(normalized)
        if (
            not normalized
            or member.is_absolute()
            or any(part in ("", ".", "..") for part in member.parts)
            or (member.parts and ":" in member.parts[0])
        ):
            raise ValueError(f"更新包包含不安全路径: {info.filename}")

        target = root.joinpath(*member.parts).resolve()
        if os.path.commonpath([str(root), str(target)]) != str(root):
            raise ValueError(f"更新包路径越界: {info.filename}")

        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        with zip_file.open(info, "r") as source, open(target, "wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)


def _merge_staged_tree(stage_dir, plugin_dir):
    """Merge staged files with atomic replacement of each individual file."""
    stage = Path(stage_dir).resolve()
    destination = Path(plugin_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    for source in sorted(stage.rglob("*")):
        relative = source.relative_to(stage)
        target = destination / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".pmstack-update-",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as temp_file:
                temp_path = temp_file.name
            shutil.copy2(source, temp_path)
            os.replace(temp_path, target)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


def _atomic_write_json(path, payload):
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".pmstack-version-",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as temp_file:
            temp_path = temp_file.name
            json.dump(payload, temp_file, ensure_ascii=False, indent=2)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, destination)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


class Updater(QObject):
    """异步检查 GitHub Release 并下载插件包到 plugins/ 目录。"""

    check_finished = pyqtSignal(bool, str)   # (has_update, message)
    progress = pyqtSignal(str)               # 进度消息
    download_finished = pyqtSignal(bool, str) # (success, message)

    def __init__(self, parent=None):
        super().__init__(parent)

    # ---- 公开接口 ----

    def check_update(self, github_repo: str, current_ver: str):
        """检查是否有新版本。结果通过 check_finished 信号返回。

        Args:
            github_repo: 仓库路径，如 "username/pm-stack-modules"
            current_ver: 当前版本号，如 "v1.2.0"
        """
        import threading
        threading.Thread(
            target=self._check_thread,
            args=(github_repo, current_ver),
            daemon=True,
        ).start()

    def download_update(self, asset_url: str, plugin_dir: str):
        """下载 zip 并解压到 plugin_dir。结果通过 download_finished 信号返回。"""
        import threading
        threading.Thread(
            target=self._download_thread,
            args=(asset_url, plugin_dir),
            daemon=True,
        ).start()

    # ---- 内部线程 ----

    def _check_thread(self, github_repo: str, current_ver: str):
        try:
            url = GITHUB_API.format(owner=github_repo.split("/")[0],
                                     repo=github_repo.split("/")[1])
            req = urllib.request.Request(url, headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "PMStack-Updater",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            remote_ver = data.get("tag_name", "")
            remote_tuple = _parse_version(remote_ver)
            local_tuple = _parse_version(current_ver)

            if remote_tuple > local_tuple:
                # 找到第一个 zip asset
                download_url = None
                for asset in data.get("assets", []):
                    if asset["name"].endswith(".zip"):
                        download_url = asset["browser_download_url"]
                        break
                if not download_url:
                    self._last_download_url = None
                    self.check_finished.emit(
                        False, f"发现新版本 {remote_ver}，但 Release 中没有 ZIP 更新包"
                    )
                    return
                notes = data.get("body", "")[:200]
                msg = f"发现新版本 {remote_ver}（当前 {current_ver}）"
                if notes:
                    msg += f"\n更新说明: {notes}"
                self.check_finished.emit(True, msg)
                # 保存下载 URL 供后续使用
                self._last_download_url = download_url
                self._last_remote_ver = remote_ver
            else:
                self.check_finished.emit(False, f"已是最新版本 ({current_ver})")
                self._last_download_url = None

        except urllib.error.URLError as e:
            self.check_finished.emit(False, f"网络错误，跳过更新检查: {e.reason}")
        except Exception as e:
            self.check_finished.emit(False, f"更新检查失败: {e}")

    def _download_thread(self, asset_url: str, plugin_dir: str):
        tmp_zip = None
        stage_dir = None
        try:
            self.progress.emit("正在下载插件包...")
            with tempfile.NamedTemporaryFile(
                prefix="pmstack-plugin-", suffix=".zip", delete=False
            ) as temp_file:
                tmp_zip = temp_file.name

            req = urllib.request.Request(asset_url, headers={
                "User-Agent": "PMStack-Updater",
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                content_length = resp.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
                    raise ValueError("更新包下载体积超过安全限制")
                downloaded = 0
                with open(tmp_zip, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > MAX_DOWNLOAD_BYTES:
                            raise ValueError("更新包下载体积超过安全限制")
                        f.write(chunk)

            self.progress.emit("下载完成，正在安全校验并解压...")

            plugin_path = Path(plugin_dir).resolve()
            plugin_path.parent.mkdir(parents=True, exist_ok=True)
            stage_dir = tempfile.mkdtemp(
                prefix=".pmstack-update-stage-", dir=plugin_path.parent
            )
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                _safe_extract_zip(zf, stage_dir)
            _merge_staged_tree(stage_dir, plugin_path)

            # 保存版本信息
            ver_file = plugin_path / "version.json"
            ver_info = {"last_updated": self._last_remote_ver if hasattr(self, "_last_remote_ver") else "unknown"}
            _atomic_write_json(ver_file, ver_info)

            self.download_finished.emit(True, "插件更新完成，请重启应用加载新模块。")

        except Exception as e:
            self.download_finished.emit(False, f"下载失败: {e}")
        finally:
            if stage_dir:
                shutil.rmtree(stage_dir, ignore_errors=True)
            if tmp_zip and os.path.exists(tmp_zip):
                try:
                    os.remove(tmp_zip)
                except OSError:
                    pass

    # ---- 辅助 ----

    def get_last_download_url(self):
        return getattr(self, "_last_download_url", None)

    def get_local_plugin_version(self, plugin_dir: str) -> str:
        """读取本地插件版本。"""
        ver_file = os.path.join(plugin_dir, "version.json")
        if os.path.exists(ver_file):
            try:
                with open(ver_file, "r", encoding="utf-8") as f:
                    return json.load(f).get("last_updated", "")
            except Exception:
                pass
        return ""
