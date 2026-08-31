# -*- coding: utf-8 -*-
"""脚本执行器 — 支持按脚本语义执行（EXE独立运行）+ subprocess 模式"""

import os
import sys
import io
import runpy
import threading
import traceback
from PyQt6.QtCore import QObject, pyqtSignal


class SignalStream(io.TextIOBase):
    def __init__(self, signal):
        super().__init__()
        self._signal = signal
        self._buffer = ""

    def writable(self):
        return True

    def write(self, text):
        if not text:
            return 0

        normalized = str(text).replace("\r", "\n")
        self._buffer += normalized
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                self._signal.emit(line)
        return len(text)

    def flush(self):
        if self._buffer:
            self._signal.emit(self._buffer)
            self._buffer = ""


class ScriptRunner(QObject):
    """在后台线程中执行脚本，通过信号输出日志。

    支持两种模式:
      - run_script(): 按脚本方式执行（EXE 模式，无需外部 Python）
      - run(): subprocess 调用（源码模式备用）
    """

    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(int)
    BUSY_EXIT_CODE = -2
    _execution_lock = threading.Lock()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._thread = None

    def is_running(self):
        thread_running = bool(self._thread and self._thread.is_alive())
        process_running = bool(
            self._process and self._process.poll() is None
        )
        return thread_running or process_running

    @classmethod
    def is_any_running(cls):
        return cls._execution_lock.locked()

    def run_script(self, script_path, args=None, env_extra=None):
        """按 ``python script.py ...`` 的语义执行脚本。

        Args:
            script_path: 脚本的绝对路径
            args: 命令行参数列表，如 ["--file", "data.xlsx"]
            env_extra: 额外的环境变量字典
        """
        script_path = os.path.abspath(script_path)
        if not os.path.exists(script_path):
            self.log_signal.emit(f"[错误] 脚本不存在: {script_path}")
            self.finished_signal.emit(-1)
            return False

        if self.is_running():
            self.log_signal.emit("[提示] 当前已有脚本正在运行，请等待完成后再执行。")
            self.finished_signal.emit(self.BUSY_EXIT_CODE)
            return False

        if not self._execution_lock.acquire(blocking=False):
            self.log_signal.emit("[提示] 其他模块正在运行任务，请等待完成后再执行。")
            self.finished_signal.emit(self.BUSY_EXIT_CODE)
            return False

        self._thread = threading.Thread(
            target=self._run_script_thread,
            args=(script_path, args or [], env_extra or {}),
            daemon=True,
        )
        try:
            self._thread.start()
        except Exception:
            self._execution_lock.release()
            raise
        return True

    def _run_script_thread(self, script_path, args, env_extra):
        script_path = os.path.abspath(script_path)
        script_dir = os.path.dirname(script_path)
        script_parent = os.path.dirname(script_dir)

        old_argv = sys.argv[:]
        old_path = sys.path[:]
        old_env = {k: os.environ.get(k) for k in env_extra}
        old_unbuffered = os.environ.get("PYTHONUNBUFFERED")
        old_stdout, old_stderr = sys.stdout, sys.stderr
        stream = SignalStream(self.log_signal)
        exit_code = -1

        try:
            sys.argv = [script_path] + list(args)
            sys.stdout = stream
            sys.stderr = stream

            # 设置 PYTHONUNBUFFERED 禁用输出缓冲，确保实时输出
            os.environ['PYTHONUNBUFFERED'] = '1'

            for k, v in env_extra.items():
                if v is not None:
                    os.environ[k] = str(v)

            # 让脚本内的相对 import / 同目录 import 能工作。
            for path in (script_dir, script_parent):
                if path and path not in sys.path:
                    sys.path.insert(0, path)

            runpy.run_path(script_path, run_name="__main__")
            exit_code = 0

        except SystemExit as e:
            if isinstance(e.code, int):
                exit_code = e.code
            elif e.code is None:
                exit_code = 0
            else:
                exit_code = 1
                print(e.code)
        except Exception as e:
            print(f"[错误] {e}")
            traceback.print_exc()
            exit_code = -1
        finally:
            stream.flush()
            sys.stdout, sys.stderr = old_stdout, old_stderr
            sys.argv = old_argv
            sys.path = old_path

            for k, old_value in old_env.items():
                if old_value is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = old_value

            if old_unbuffered is None:
                os.environ.pop("PYTHONUNBUFFERED", None)
            else:
                os.environ["PYTHONUNBUFFERED"] = old_unbuffered
            self._execution_lock.release()

        # 完成信号在全局状态恢复、执行锁释放后发送，串联任务可立即启动。
        self.finished_signal.emit(exit_code)

    # ---- subprocess 模式（备用）----

    def run(self, cmd, cwd=None, env=None):
        """subprocess 方式执行。"""
        if self.is_running():
            self.log_signal.emit("[提示] 当前已有脚本正在运行，请等待完成后再执行。")
            self.finished_signal.emit(self.BUSY_EXIT_CODE)
            return False
        self._thread = threading.Thread(
            target=self._run_thread, args=(cmd, cwd, env), daemon=True
        )
        self._thread.start()
        return True

    def _run_thread(self, cmd, cwd, env):
        import subprocess
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            for line in self._process.stdout:
                self.log_signal.emit(line.rstrip("\n"))
            self._process.wait()
            self.finished_signal.emit(self._process.returncode)
        except Exception as e:
            self.log_signal.emit(f"[错误] {e}")
            self.finished_signal.emit(-1)

    def cancel(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()
