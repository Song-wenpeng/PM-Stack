"""Run isolated tests in a bounded subprocess and retain native crash diagnostics."""

import argparse
import datetime
import faulthandler
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def child(targets):
    # Only test processes suppress Windows' blocking crash dialog. Crashes still
    # produce nonzero exit codes and faulthandler output in the parent log.
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
    faulthandler.enable()
    faulthandler.dump_traceback_later(60, repeat=True)
    sys.path.insert(0, str(ROOT))
    from tests import support
    suite = (unittest.defaultTestLoader.loadTestsFromNames(targets) if targets
             else unittest.defaultTestLoader.discover(str(ROOT / "tests"),
                                                       top_level_dir=str(ROOT)))
    try:
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        support.cleanup_qt_widgets()
        faulthandler.cancel_dump_traceback_later()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="*", help="Optional unittest module/class/test names")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return child(args.targets)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    logs = ROOT / ".runtime-local" / "test-logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    log_path = logs / f"tests-{stamp}.log"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", QT_QPA_PLATFORM="offscreen")
    command = [sys.executable, "-X", "faulthandler", str(Path(__file__).resolve()),
               "--child", *args.targets]
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log,
                                   stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=args.timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            # This is the test child we started, never a user's PM Stack process.
            process.kill()
            process.wait()
            log.write(f"\nTest child stopped: {type(exc).__name__}\n")
            code = 124 if isinstance(exc, subprocess.TimeoutExpired) else 130
    print(log_path.read_text(encoding="utf-8"), end="")
    print(f"Test process exit code: {code}; log: {log_path}")
    return code if 0 <= code <= 255 else 1


if __name__ == "__main__":
    raise SystemExit(main())
