# -*- coding: utf-8 -*-
"""全局配置管理器 — 用户配置与安全密钥迁移。"""

import json
import os
import sys
import tempfile

from .secure_storage import SecretStorageError, protect_secret, unprotect_secret

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://api.siliconflow.cn/v1",
    "model_name": "deepseek-ai/DeepSeek-V3",
    "vision_api_key": "",
    "vision_base_url": "",
    "vision_model_name": "",
    "last_input_dir": "",
    "last_output_dir": "",
    # 主程序更新（HTTPS / 公司共享盘）
    "app_update_manifest": "",
    "auto_check_app_update": True,
    # 插件更新（GitHub Release ZIP）
    "github_repo": "",
    "auto_check_update": True,
    "current_version": "v1.10.2",
    "theme": "light",
}

SECRET_KEYS = ("api_key", "vision_api_key")
PROTECTED_SUFFIX = "_protected"
APP_CONFIG_DIR = "PM Stack"


class ConfigManager:
    def __init__(self, config_path=None):
        self._explicit_path = config_path is not None
        self._legacy_path = None
        if config_path is None:
            config_path = self._default_user_config_path()
            self._legacy_path = self._default_legacy_config_path()
        self._path = os.path.abspath(config_path)
        self._data = dict(DEFAULT_CONFIG)
        self._warnings = []
        self.load()

    @staticmethod
    def _app_root():
        return os.path.dirname(os.path.dirname(__file__))

    @staticmethod
    def _default_user_config_path():
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = os.path.join(os.path.expanduser("~"), ".pm-stack")
            return os.path.join(base, "config.json")
        return os.path.join(base, APP_CONFIG_DIR, "config.json")

    def _default_legacy_config_path(self):
        if getattr(sys, "frozen", False):
            return os.path.join(os.path.dirname(sys.executable), "config.json")
        return os.path.join(self._app_root(), "config.json")

    @staticmethod
    def _read_json(path):
        with open(path, "r", encoding="utf-8") as config_file:
            saved = json.load(config_file)
        if not isinstance(saved, dict):
            raise ValueError(f"配置文件必须是 JSON 对象: {path}")
        return saved

    def _merge_saved(self, saved):
        saved = dict(saved)
        plaintext_found = False
        restored = {}

        for key in SECRET_KEYS:
            protected_key = f"{key}{PROTECTED_SUFFIX}"
            protected_value = saved.pop(protected_key, "")
            plaintext_value = saved.pop(key, "")
            if protected_value:
                try:
                    restored[key] = unprotect_secret(protected_value)
                except SecretStorageError as exc:
                    self._warnings.append(f"无法读取 {key}: {exc}")
            elif plaintext_value:
                restored[key] = str(plaintext_value)
                plaintext_found = True

        self._data.update(saved)
        self._data.update(restored)
        return plaintext_found

    def load(self):
        plaintext_in_legacy = False
        plaintext_in_user = False

        # 先读取发行/项目默认配置，再由用户目录配置覆盖。
        if self._legacy_path and os.path.exists(self._legacy_path):
            plaintext_in_legacy = self._merge_saved(
                self._read_json(self._legacy_path)
            )
        elif getattr(sys, "frozen", False):
            bundled = os.path.join(sys._MEIPASS, "config.json")
            if os.path.exists(bundled):
                self._merge_saved(self._read_json(bundled))

        if os.path.exists(self._path):
            plaintext_in_user = self._merge_saved(self._read_json(self._path))

        # 旧版本明文密钥仅在成功写入 DPAPI 保护配置后才清理。
        if plaintext_in_legacy or plaintext_in_user:
            try:
                self.save()
            except (OSError, SecretStorageError) as exc:
                self._warnings.append(f"密钥安全迁移失败: {exc}")
            else:
                if plaintext_in_legacy and self._legacy_path != self._path:
                    self._sanitize_legacy_secrets(self._legacy_path)

    @staticmethod
    def _atomic_write_json(path, payload):
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".tmp",
                prefix=".pmstack-config-",
                dir=directory,
                delete=False,
            ) as temp_file:
                temp_path = temp_file.name
                json.dump(payload, temp_file, ensure_ascii=False, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _sanitize_legacy_secrets(self, path):
        try:
            payload = self._read_json(path)
            for key in SECRET_KEYS:
                payload[key] = ""
                payload.pop(f"{key}{PROTECTED_SUFFIX}", None)
            self._atomic_write_json(path, payload)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._warnings.append(f"无法清理旧配置中的明文密钥: {exc}")

    def save(self):
        payload = dict(self._data)
        for key in SECRET_KEYS:
            value = str(payload.pop(key, "") or "")
            protected_key = f"{key}{PROTECTED_SUFFIX}"
            if value:
                payload[protected_key] = protect_secret(value)
            else:
                payload.pop(protected_key, None)
        self._atomic_write_json(self._path, payload)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self.update({key: value})

    def update(self, values):
        previous = dict(self._data)
        self._data.update(values)
        try:
            self.save()
        except Exception:
            self._data = previous
            raise

    def get_all(self):
        return dict(self._data)

    def get_path(self):
        return self._path

    def get_warnings(self):
        return list(self._warnings)

    def get_script_dir(self):
        """获取脚本根目录（只读，用于定位 bundled 脚本）。

        EXE 模式：返回打包内置的 scripts/ 目录（sys._MEIPASS/scripts）
        源码模式：返回 PM Stack/scripts/ 目录
        """
        if getattr(sys, 'frozen', False):
            return os.path.join(sys._MEIPASS, "scripts")
        # 源码模式：core/ 的上一级是 PM Stack/，再拼 scripts/
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")

    def get_data_dir(self):
        """获取用户数据目录（可写，用于存放输出文件和用户配置）。

        EXE 模式：EXE 所在目录
        源码模式：PM Stack/ 目录
        """
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.dirname(__file__))

    def resolve_config(self, filename):
        """解析配置文件路径，支持用户覆盖内置默认。

        优先级：
          1. EXE 同目录下的同名文件（用户可编辑）
          2. 打包内置的默认文件（sys._MEIPASS/scripts/）
          3. 源码模式下的 APP/scripts/ 目录

        Args:
            filename: 配置文件名，如 "product_configs.json"

        Returns:
            配置文件的绝对路径
        """
        if getattr(sys, 'frozen', False):
            # EXE 模式：优先读 EXE 旁边的用户版本
            user_path = os.path.join(os.path.dirname(sys.executable), filename)
            if os.path.exists(user_path):
                return user_path
            # 回退到打包内置
            return os.path.join(sys._MEIPASS, "scripts", filename)
        # 源码模式：直接用 scripts 目录
        return os.path.join(self.get_script_dir(), filename)

    def get_plugin_dir(self):
        """获取外部插件目录路径（可写，用户可自由增删插件）。

        EXE 模式：EXE 同级的 plugins/ 目录
        源码模式：PM Stack/plugins/ 目录
        """
        if getattr(sys, 'frozen', False):
            return os.path.join(os.path.dirname(sys.executable), "plugins")
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")

    def get_app_update_manifest_source(self):
        """获取主程序 update.json 地址，用户配置优先于同目录更新通道。"""
        configured = str(self._data.get("app_update_manifest", "") or "").strip()
        if configured:
            return configured

        channel_path = os.path.join(self.get_data_dir(), "update-channel.json")
        if not os.path.exists(channel_path):
            return ""
        try:
            channel = self._read_json(channel_path)
            return str(channel.get("manifest_source", "") or "").strip()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._warnings.append(f"无法读取更新通道配置: {exc}")
            return ""

    def resolve_script(self, filename):
        """解析脚本路径，优先使用插件目录中的版本。

        优先级：
          1. plugins/scripts/ 目录（外部插件，可覆盖内置）
          2. 内置 scripts/ 目录（打包内置）

        Args:
            filename: 脚本文件名，如 "sales_number.py"

        Returns:
            脚本的绝对路径
        """
        plugin_script = os.path.join(self.get_plugin_dir(), "scripts", filename)
        if os.path.exists(plugin_script):
            return plugin_script
        return os.path.join(self.get_script_dir(), filename)

    def get_env_dict(self):
        """返回用于 subprocess 的环境变量字典"""
        env = dict(os.environ)
        if self._data.get("api_key"):
            env["API_KEY"] = self._data["api_key"]
        if self._data.get("base_url"):
            env["BASE_URL"] = self._data["base_url"]
        if self._data.get("model_name"):
            env["MODEL_NAME"] = self._data["model_name"]
        # 视觉模型（图片识别用）
        if self._data.get("vision_api_key"):
            env["VISION_API_KEY"] = self._data["vision_api_key"]
        if self._data.get("vision_base_url"):
            env["VISION_BASE_URL"] = self._data["vision_base_url"]
        if self._data.get("vision_model_name"):
            env["MODEL_VISION"] = self._data["vision_model_name"]
        return env
