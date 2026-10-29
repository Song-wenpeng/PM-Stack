# -*- coding: utf-8 -*-
"""GitHub 插件更新器 — 检查远程 Release 并下载插件包"""

import os
import json
import hashlib
import re
import shutil
import stat
import uuid
import zipfile
import tempfile
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path, PurePosixPath
from PyQt6.QtCore import QObject, pyqtSignal


GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
MAX_DOWNLOAD_BYTES = 250 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 5000
MAX_EXTRACTED_BYTES = 500 * 1024 * 1024

# 包内清单：声明插件版本、兼容的主程序版本下限与每个文件的 sha256。
MANIFEST_NAME = "manifest.json"
MANIFEST_FORMAT = 1
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


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


def verify_staged_tree(stage_dir, current_version=""):
    """校验已解压的更新包：完整性、兼容性与未声明载荷。

    只校验完整性与兼容性，不校验发布者身份——项目没有密钥基础设施，
    无法在本地做签名验证，因此不声称「已签名校验」。
    """
    stage = Path(stage_dir).resolve()
    manifest_path = stage / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError(
            f"更新包缺少 {MANIFEST_NAME}，无法校验完整性与兼容性。发布者需要在包内提供 "
            f"format={MANIFEST_FORMAT}、plugin_version、min_app_version 与 files（每个文件的 sha256）。")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"更新包清单无法解析：{exc}") from None
    if not isinstance(manifest, dict):
        raise ValueError("更新包清单必须是 JSON 对象")
    if manifest.get("format") != MANIFEST_FORMAT:
        raise ValueError(
            f"更新包清单格式不受支持：{manifest.get('format')!r}（当前支持 {MANIFEST_FORMAT}）")
    plugin_version = str(manifest.get("plugin_version") or "").strip()
    if not plugin_version:
        raise ValueError("更新包清单缺少 plugin_version")
    minimum = str(manifest.get("min_app_version") or "").strip()
    if minimum:
        if not current_version:
            raise ValueError("无法确认当前主程序版本，拒绝安装声明了 min_app_version 的插件包")
        if _parse_version(minimum) > _parse_version(current_version):
            raise ValueError(
                f"插件包要求主程序 {minimum} 及以上，当前 {current_version}；请先更新主程序。")
    declared = manifest.get("files")
    if not isinstance(declared, dict) or not declared:
        raise ValueError("更新包清单缺少 files 摘要列表")

    actual = {}
    for path in sorted(stage.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(stage).as_posix()
        if relative == MANIFEST_NAME:
            continue
        actual[relative] = _digest(path)

    missing = sorted(set(declared) - set(actual))
    if missing:
        raise ValueError(f"更新包缺少清单声明的文件：{'、'.join(missing[:5])}")
    undeclared = sorted(set(actual) - set(declared))
    if undeclared:
        raise ValueError(f"更新包含清单未声明的文件：{'、'.join(undeclared[:5])}")
    mismatched = sorted(name for name, value in declared.items()
                        if not (isinstance(value, str) and SHA256_RE.fullmatch(value.lower())
                                and value.lower() == actual[name]))
    if mismatched:
        raise ValueError(
            f"更新包文件校验失败，可能已损坏或被篡改：{'、'.join(mismatched[:5])}")
    return {"plugin_version": plugin_version, "min_app_version": minimum,
            "file_count": len(actual)}


def _merge_staged_tree(stage_dir, plugin_dir):
    """把暂存树合并进插件目录，作为一个事务；返回可供提交或回滚的日志。

    被替换的原文件先移到插件目录同级的隐藏回滚目录：同卷避免跨卷改名失败，
    不在插件目录内避免被模块扫描读到。调用方成功后提交，失败则整体回滚，
    不会留下半新半旧、无法启动的插件集。
    """
    stage = Path(stage_dir).resolve()
    destination = Path(plugin_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    journal = {"rollback_root": None, "moved": [], "created": [], "dirs": []}

    try:
        for source in sorted(stage.rglob("*")):
            relative = source.relative_to(stage)
            if relative.as_posix() == MANIFEST_NAME:
                continue  # 清单是元数据，不属于插件载荷
            target = destination / relative
            if source.is_dir():
                if not target.exists():
                    target.mkdir(parents=True, exist_ok=True)
                    journal["dirs"].append(target)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            if journal["rollback_root"] is None:
                journal["rollback_root"] = destination.parent / f".pmstack-rollback-{uuid.uuid4().hex}"
                journal["rollback_root"].mkdir(parents=True, exist_ok=True)
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
                if target.exists():
                    backup = journal["rollback_root"] / relative
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, backup)
                    journal["moved"].append((backup, target))
                else:
                    journal["created"].append(target)
                os.replace(temp_path, target)
                temp_path = None
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
    except BaseException:
        # 合并中途失败必须自己回滚：日志只存在于本函数内，调用方拿不到。
        _rollback_merge(journal)
        raise
    return journal


def _commit_merge(journal):
    root = journal.get("rollback_root") if journal else None
    if root is not None:
        shutil.rmtree(root, ignore_errors=True)


def _rollback_merge(journal):
    if not journal:
        return
    errors = []
    for backup, target in reversed(journal.get("moved", [])):
        if not backup.exists():
            continue  # 已恢复的条目允许再次回滚，不删除已恢复的原件。
        try:
            # replace 本身原子覆盖，不能先删除目标再尝试恢复。
            os.replace(backup, target)
        except OSError as exc:
            errors.append(f"{target}: {exc}")
    for created in reversed(journal.get("created", [])):
        try:
            created.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"{created}: {exc}")
    for directory in reversed(journal.get("dirs", [])):
        try:
            directory.rmdir()
        except OSError:
            pass
    root = journal.get("rollback_root")
    if errors:
        # 恢复受阻时这里可能是旧插件的唯一副本，必须保留以便重试/人工恢复。
        raise OSError(f"回滚未完成；原文件备份保留在 {root}。请关闭占用程序后恢复。"
                      + "；".join(errors))
    if root is not None:
        shutil.rmtree(root, ignore_errors=True)


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
        self._current_version = current_ver
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
                # 找到第一个 zip asset，以及与之同名的 .sha256 校验资产
                assets = data.get("assets", [])
                download_url = None
                zip_name = None
                for asset in assets:
                    name = asset.get("name", "")
                    if name.endswith(".zip"):
                        download_url = asset.get("browser_download_url")
                        zip_name = name
                        break
                checksum_url = None
                if zip_name:
                    for asset in assets:
                        if asset.get("name") == zip_name + ".sha256":
                            checksum_url = asset.get("browser_download_url")
                            break
                if not download_url:
                    self._last_download_url = None
                    self._last_checksum_url = None
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
                self._last_checksum_url = checksum_url
                self._last_remote_ver = remote_ver
            else:
                self.check_finished.emit(False, f"已是最新版本 ({current_ver})")
                self._last_download_url = None
                self._last_checksum_url = None

        except urllib.error.URLError as e:
            self.check_finished.emit(False, f"网络错误，跳过更新检查: {e.reason}")
        except Exception as e:
            self.check_finished.emit(False, f"更新检查失败: {e}")

    def _verify_checksum_asset(self, zip_path):
        """Release 提供同名 .sha256 资产时校验整包摘要；返回可读说明。"""
        url = getattr(self, "_last_checksum_url", None)
        if not url:
            return "（本次 Release 未提供 .sha256 资产，整包真实性仅依赖 HTTPS 传输；已按包内清单逐文件校验摘要）"
        req = urllib.request.Request(url, headers={"User-Agent": "PMStack-Updater"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read(4096).decode("utf-8", errors="replace")
        parts = text.split()
        expected = parts[0].lower() if parts else ""
        if not SHA256_RE.fullmatch(expected):
            raise ValueError(".sha256 资产内容不是有效的 SHA-256 摘要")
        if expected != _digest(zip_path):
            raise ValueError("插件包整体 SHA-256 与 Release 提供的 .sha256 不一致，可能已损坏或被替换")
        return "（已用 Release 的 .sha256 资产校验整包摘要）"

    def _download_thread(self, asset_url: str, plugin_dir: str):
        tmp_zip = None
        stage_dir = None
        journal = None
        merge_started = False
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

            checksum_note = self._verify_checksum_asset(tmp_zip)
            self.progress.emit("下载完成，正在安全校验并解压...")

            plugin_path = Path(plugin_dir).resolve()
            plugin_path.parent.mkdir(parents=True, exist_ok=True)
            stage_dir = tempfile.mkdtemp(
                prefix=".pmstack-update-stage-", dir=plugin_path.parent
            )
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                _safe_extract_zip(zf, stage_dir)
            # 先校验再安装：损坏、不兼容或夹带未声明文件的包不会碰到插件目录。
            info = verify_staged_tree(stage_dir, getattr(self, "_current_version", ""))
            self.progress.emit(
                f"校验通过（插件 {info['plugin_version']}，{info['file_count']} 个文件），正在安装...")

            merge_started = True
            journal = _merge_staged_tree(stage_dir, plugin_path)

            # 保存版本信息
            ver_file = plugin_path / "version.json"
            ver_info = {
                "last_updated": info["plugin_version"],
                "plugin_version": info["plugin_version"],
                "min_app_version": info["min_app_version"],
                "file_count": info["file_count"],
                "installed_at": datetime.now().isoformat(timespec="seconds"),
            }
            _atomic_write_json(ver_file, ver_info)

            _commit_merge(journal)
            journal = None
            self.download_finished.emit(
                True,
                f"插件 {info['plugin_version']} 更新完成，请重启应用加载新模块。{checksum_note}")

        except Exception as e:
            if journal is not None:
                try:
                    _rollback_merge(journal)
                except OSError as rollback_error:
                    self.download_finished.emit(False, f"插件更新失败: {e}；{rollback_error}")
                else:
                    self.download_finished.emit(
                        False, f"插件更新失败，已回滚到更新前状态: {e}")
            elif merge_started:
                self.download_finished.emit(False, f"插件安装失败: {e}")
            else:
                self.download_finished.emit(False, f"插件更新失败，未改动插件目录: {e}")
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
