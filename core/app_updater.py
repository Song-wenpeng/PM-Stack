# -*- coding: utf-8 -*-
"""主程序更新：读取清单、下载 EXE、校验哈希并启动独立更新器。"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal


MAX_MANIFEST_BYTES = 512 * 1024
MAX_APP_DOWNLOAD_BYTES = 512 * 1024 * 1024
_VERSION_RE = re.compile(r"^[vV]?(\d+)(?:\.(\d+)){1,3}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class _HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """允许 GitHub 等 HTTPS 重定向，但禁止降级到明文 HTTP。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            raise urllib.error.URLError("更新下载重定向被拒绝：目标不是 HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_HTTPS_OPENER = urllib.request.build_opener(_HttpsOnlyRedirectHandler())


@dataclass(frozen=True)
class AppUpdateManifest:
    version: str
    url: str
    sha256: str
    size: int
    notes: str = ""
    mandatory: bool = False


def parse_version(version):
    """把 v1.10.0 规范化为四段数字元组。"""
    text = str(version or "").strip()
    if not _VERSION_RE.fullmatch(text):
        raise ValueError(f"版本号格式无效: {text or '<空>'}")
    parts = [int(part) for part in text.lstrip("vV").split(".")]
    return tuple((parts + [0, 0, 0, 0])[:4])


def _is_windows_path(source):
    return bool(re.match(r"^[A-Za-z]:[\\/]", source)) or source.startswith("\\\\")


def _local_path(source):
    source = str(source).strip().strip('"')
    parsed = urllib.parse.urlsplit(source)
    if parsed.scheme.lower() == "file":
        path = urllib.request.url2pathname(parsed.path)
        if parsed.netloc:
            path = "\\\\" + parsed.netloc + path.replace("/", "\\")
        return os.path.abspath(path)
    return os.path.abspath(os.path.expandvars(source))


def _source_kind(source):
    source = str(source or "").strip()
    if not source:
        raise ValueError("更新地址为空")
    parsed = urllib.parse.urlsplit(source)
    scheme = parsed.scheme.lower()
    if scheme == "https":
        return "https"
    if scheme == "http":
        raise ValueError("为保证更新安全，不允许使用 HTTP，请改用 HTTPS")
    if scheme == "file" or _is_windows_path(source) or not scheme:
        return "file"
    raise ValueError(f"不支持的更新地址协议: {scheme}")


def _normalized_https_url(source):
    parsed = urllib.parse.urlsplit(source)
    path = urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/%:@")
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)
    )


def _open_source(source, timeout=30):
    kind = _source_kind(source)
    if kind == "https":
        request = urllib.request.Request(
            _normalized_https_url(source),
            headers={"User-Agent": "PMStack-AppUpdater/1.0"},
        )
        response = _HTTPS_OPENER.open(request, timeout=timeout)
        if urllib.parse.urlsplit(response.geturl()).scheme.lower() != "https":
            response.close()
            raise urllib.error.URLError("更新下载最终地址不是 HTTPS")
        raw_length = response.headers.get("Content-Length")
        total = int(raw_length) if raw_length and raw_length.isdigit() else 0
        return response, total

    path = _local_path(source)
    stream = open(path, "rb")
    return stream, os.path.getsize(path)


def _read_limited(source, limit):
    stream, declared_size = _open_source(source)
    if declared_size and declared_size > limit:
        stream.close()
        raise ValueError("更新清单体积超过安全限制")
    chunks = []
    total = 0
    with stream:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError("更新清单体积超过安全限制")
            chunks.append(chunk)
    return b"".join(chunks)


def _resolve_asset_source(manifest_source, asset_source):
    asset_source = str(asset_source or "").strip()
    if not asset_source:
        raise ValueError("更新清单缺少 url")

    asset_kind = None
    try:
        asset_kind = _source_kind(asset_source)
    except ValueError:
        # 相对路径会在下方按清单位置解析。
        if urllib.parse.urlsplit(asset_source).scheme:
            raise

    if asset_kind == "https":
        return _normalized_https_url(asset_source)
    if asset_kind == "file" and (
        _is_windows_path(asset_source)
        or urllib.parse.urlsplit(asset_source).scheme.lower() == "file"
    ):
        return _local_path(asset_source)

    if _source_kind(manifest_source) == "https":
        resolved = urllib.parse.urljoin(
            _normalized_https_url(manifest_source), asset_source
        )
        if _source_kind(resolved) != "https":
            raise ValueError("更新文件必须使用 HTTPS")
        return _normalized_https_url(resolved)

    manifest_path = Path(_local_path(manifest_source))
    return str((manifest_path.parent / asset_source).resolve())


def load_update_manifest(source):
    """从 HTTPS、UNC、盘符路径或 file:// 地址读取并校验更新清单。"""
    try:
        payload = json.loads(_read_limited(source, MAX_MANIFEST_BYTES))
    except json.JSONDecodeError as exc:
        raise ValueError(f"更新清单不是有效 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("更新清单必须是 JSON 对象")

    version = str(payload.get("version", "")).strip()
    parse_version(version)
    sha256 = str(payload.get("sha256", "")).strip().lower()
    if not _SHA256_RE.fullmatch(sha256):
        raise ValueError("更新清单 sha256 必须是 64 位十六进制")

    size = payload.get("size", 0)
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError("更新清单 size 必须是非负整数")
    if size > MAX_APP_DOWNLOAD_BYTES:
        raise ValueError("更新文件体积超过安全限制")

    mandatory = payload.get("mandatory", False)
    if not isinstance(mandatory, bool):
        raise ValueError("更新清单 mandatory 必须是布尔值")

    notes = str(payload.get("notes", ""))[:4000]
    return AppUpdateManifest(
        version=version,
        url=_resolve_asset_source(source, payload.get("url", "")),
        sha256=sha256,
        size=size,
        notes=notes,
        mandatory=mandatory,
    )


def download_verified_file(source, destination, expected_sha256,
                           expected_size=0, progress_callback=None):
    """流式下载到同目录临时文件，校验大小和 SHA-256 后原子落盘。"""
    if not _SHA256_RE.fullmatch(str(expected_sha256 or "")):
        raise ValueError("缺少有效的 SHA-256")
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    stream = None
    try:
        stream, declared_size = _open_source(source, timeout=60)
        total_hint = expected_size or declared_size
        if declared_size and declared_size > MAX_APP_DOWNLOAD_BYTES:
            raise ValueError("更新文件体积超过安全限制")
        if expected_size and declared_size and declared_size != expected_size:
            raise ValueError("更新文件大小与清单不一致")

        digest = hashlib.sha256()
        downloaded = 0
        opened = stream
        stream = None
        with opened, tempfile.NamedTemporaryFile(
            prefix=".pmstack-app-", suffix=".download",
            dir=destination.parent, delete=False,
        ) as output:
            temp_path = output.name
            while True:
                chunk = opened.read(1024 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MAX_APP_DOWNLOAD_BYTES:
                    raise ValueError("更新文件体积超过安全限制")
                output.write(chunk)
                digest.update(chunk)
                if progress_callback:
                    progress_callback(downloaded, total_hint)
            output.flush()
            os.fsync(output.fileno())

        if expected_size and downloaded != expected_size:
            raise ValueError("更新文件大小与清单不一致")
        if digest.hexdigest().lower() != expected_sha256.lower():
            raise ValueError("更新文件 SHA-256 校验失败")
        os.replace(temp_path, destination)
        temp_path = None
        return str(destination)
    finally:
        if stream is not None:
            stream.close()
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def launch_updater_helper(helper_path, downloaded_path, target_path,
                          wait_pid, version, sha256):
    helper = Path(helper_path).resolve()
    downloaded = Path(downloaded_path).resolve()
    target = Path(target_path).resolve()
    if not helper.is_file():
        raise FileNotFoundError(f"未找到独立更新器: {helper}")
    if not downloaded.is_file():
        raise FileNotFoundError(f"未找到已下载更新: {downloaded}")
    if not target.is_file():
        raise FileNotFoundError(f"未找到当前主程序: {target}")

    flags = 0
    if os.name == "nt":
        flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    return subprocess.Popen(
        [
            str(helper),
            "--wait-pid", str(int(wait_pid)),
            "--source", str(downloaded),
            "--target", str(target),
            "--version", str(version),
            "--sha256", str(sha256),
        ],
        cwd=str(target.parent),
        close_fds=True,
        creationflags=flags,
    )


class ApplicationUpdater(QObject):
    """主程序更新工作器；网络和文件操作均在后台线程执行。"""

    check_finished = pyqtSignal(bool, str)
    progress = pyqtSignal(int, str)
    download_finished = pyqtSignal(bool, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manifest = None
        self._checking = False
        self._downloading = False
        self._state_lock = threading.Lock()

    def get_manifest(self):
        return self._manifest

    def check_update(self, source, current_version):
        with self._state_lock:
            if self._checking:
                return False
            self._checking = True
        threading.Thread(
            target=self._check_thread,
            args=(source, current_version), daemon=True,
        ).start()
        return True

    def _check_thread(self, source, current_version):
        try:
            manifest = load_update_manifest(source)
            self._manifest = manifest
            if parse_version(manifest.version) > parse_version(current_version):
                message = f"发现主程序 {manifest.version}（当前 {current_version}）"
                if manifest.notes:
                    message += f"\n\n{manifest.notes}"
                self.check_finished.emit(True, message)
            else:
                self.check_finished.emit(
                    False, f"主程序已是最新版本 ({current_version})")
        except (OSError, ValueError, urllib.error.URLError) as exc:
            self._manifest = None
            self.check_finished.emit(False, f"主程序更新检查失败: {exc}")
        finally:
            with self._state_lock:
                self._checking = False

    def download_update(self):
        manifest = self._manifest
        if manifest is None:
            self.download_finished.emit(False, "没有可下载的主程序更新", "")
            return False
        with self._state_lock:
            if self._downloading:
                return False
            self._downloading = True
        threading.Thread(
            target=self._download_thread, args=(manifest,), daemon=True
        ).start()
        return True

    def _download_thread(self, manifest):
        try:
            base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
            update_dir = Path(base) / "PM Stack" / "updates"
            destination = update_dir / f"PM-Stack-{manifest.version}.exe.download"

            def report(downloaded, total):
                percent = int(downloaded * 100 / total) if total else 0
                size_text = f"{downloaded / 1024 / 1024:.1f} MB"
                if total:
                    size_text += f" / {total / 1024 / 1024:.1f} MB"
                self.progress.emit(percent, f"正在下载主程序：{size_text}")

            path = download_verified_file(
                manifest.url, destination, manifest.sha256,
                manifest.size, report,
            )
            self.progress.emit(100, "下载完成，SHA-256 校验通过")
            self.download_finished.emit(True, "主程序更新已下载并验证", path)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            self.download_finished.emit(False, f"主程序下载失败: {exc}", "")
        finally:
            with self._state_lock:
                self._downloading = False
