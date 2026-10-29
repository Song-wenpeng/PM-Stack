"""Release preflight and staging never publish or absorb unrelated work."""

from tests import support  # Isolate temporary paths before importing application code.

import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import publish


_REAL_RUN = subprocess.run
_GIT = shutil.which("git")


@unittest.skipUnless(_GIT, "Git is required for isolated release preflight checks")
class PublishHandoffTests(unittest.TestCase):
    record_rel = "handoffs/release-test.md"
    current_version = "v1.11.5"
    next_version = "v1.11.6"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pm-stack-release-check-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / "repository"
        self.root.mkdir()
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                   GIT_TERMINAL_PROMPT="0")
        self.env_patch = mock.patch.dict(os.environ, env, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.git("init", "--quiet")
        self.git("config", "user.name", "Release test")
        self.git("config", "user.email", "release-test@example.invalid")
        self.git("config", "core.hooksPath", str(self.home / "no-hooks"))
        self.git("config", "core.autocrlf", "false")
        self.write(".gitignore", "dist/\nbuild/\n.runtime-local/\n")
        self.write("core/main_window.py", 'CURRENT_VERSION = "v1.11.5"\n')
        self.write("update.json", '{"version": "1.11.5"}\n')
        self.write("CURRENT.md", "[Release](handoffs/release-test.md)\n")
        self.write(self.record_rel, "# Release task\n\nBaseline record.\n")
        self.write("handoffs/TEMPLATE.md", "# Template\n")
        self.write("handoffs/README.md", "# Handoff instructions\n")
        self.write("handoffs/other-task.md", "# Another task\n")
        self.write("README.md", "# Project\n")
        self.write("tools/handoff.py", "# Commands are mocked in these tests.\n")
        self.write("PM Stack v1.11.5.spec", "# Current build specification\n")
        self.write("specs/archive/PM Stack v1.10.20.spec", "# Older specification\n")
        self.commit_baseline()
        self.write(self.record_rel, "# Release task\n\nReady for release preflight.\n")
        self.commands = []
        self.validate_code = 0
        self.check_code = 0
        paths = {
            "PROJECT_DIR": self.root,
            "MAIN_WINDOW": self.root / "core/main_window.py",
            "SPEC_ARCHIVE": self.root / "specs/archive",
            "DIST_EXE": self.root / "dist/PM Stack.exe",
            "DIST_UPDATER": self.root / "dist/PM Stack Updater.exe",
            "UPDATER_SPEC": self.root / "PM Stack Updater.spec",
            "UPDATE_JSON": self.root / "update.json",
            "UPDATE_CHANNEL": self.root / "update-channel.json",
            "RELEASE_DIR": self.root / "release",
            "RELEASE_CURRENT": self.root / "release/current",
            "RELEASE_ARCHIVE": self.root / "release/archive",
            "RELEASE_GUIDE": self.root / "docs/release.md",
            "GH_CLI": self.root / "unused-gh.exe",
        }
        self.paths_patch = mock.patch.multiple(publish, **paths)
        self.paths_patch.start()
        self.addCleanup(self.paths_patch.stop)

    def write(self, relative, content):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def git(self, *args):
        result = _REAL_RUN([_GIT, *args], cwd=self.root, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout.decode("utf-8")

    def commit_baseline(self):
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "Fixture baseline")

    def dispatch(self, command, **kwargs):
        """Run only local Git; never execute a build, network call, or validator."""
        args = [str(part) for part in command]
        self.commands.append(args)
        if len(args) >= 3 and Path(args[1]).name == "handoff.py":
            self.assertEqual(Path(args[0]).resolve(), Path(sys.executable).resolve())
            script = Path(args[1])
            if not script.is_absolute():
                script = Path(kwargs.get("cwd", Path.cwd())) / script
            self.assertEqual(script.resolve(), (self.root / "tools/handoff.py").resolve())
            self.assertIn(args[2], ("validate", "check"))
            code = self.validate_code if args[2] == "validate" else self.check_code
            text_output = bool(kwargs.get("text") or kwargs.get("encoding")
                               or kwargs.get("universal_newlines"))
            output = "invalid handoff fixture\n" if code else "handoff fixture OK\n"
            if not text_output:
                output = output.encode("utf-8")
            if kwargs.get("check") and code:
                raise subprocess.CalledProcessError(code, args, output=output,
                                                    stderr=output)
            return subprocess.CompletedProcess(args, code, stdout=output, stderr=output)
        if Path(args[0]).name.lower() in ("git", "git.exe"):
            self.assertFalse(set(args[1:]) & {"commit", "push", "fetch", "reset",
                                             "checkout", "switch", "clean"})
            return _REAL_RUN(command, **kwargs)
        raise AssertionError("Unexpected external command: {!r}".format(args))

    @contextlib.contextmanager
    def local_commands(self):
        with mock.patch.object(publish.subprocess, "run", side_effect=self.dispatch):
            yield

    def prepare(self, record=None):
        return publish.prepare_release_handoff(
            self.record_rel if record is None else record,
            self.current_version, self.next_version)

    def validator_command(self, operation):
        commands = [args for args in self.commands
                    if len(args) >= 3 and Path(args[1]).name == "handoff.py"
                    and args[2] == operation]
        self.assertEqual(len(commands), 1, commands)
        return commands[0]

    def handoff_options(self, operation):
        args = self.validator_command(operation)[3:]
        options = {}
        index = 0
        while index < len(args):
            flag = args[index]
            self.assertIn(flag, ("--repo", "--record", "--require-path", "--staged"))
            if flag == "--staged":
                value = True
                index += 1
            else:
                self.assertLess(index + 1, len(args), "Missing value for " + flag)
                value = args[index + 1]
                index += 2
            options.setdefault(flag, []).append(value)
        if "--repo" in options:
            self.assertEqual(len(options["--repo"]), 1)
            self.assertEqual(Path(options["--repo"][0]).resolve(), self.root.resolve())
        return options

    def required_paths(self):
        options = self.handoff_options("validate")
        self.assertEqual(options.get("--record"), [self.record_rel])
        self.assertNotIn("--staged", options)
        paths = options.get("--require-path", [])
        self.assertEqual(len(paths), len(set(paths)))
        return set(paths)

    def assert_no_release_changes(self):
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
        self.assertEqual((self.root / "core/main_window.py").read_text(encoding="utf-8"),
                         'CURRENT_VERSION = "v1.11.5"\n')
        self.assertEqual((self.root / "update.json").read_text(encoding="utf-8"),
                         '{"version": "1.11.5"}\n')
        self.assertFalse((self.root / "build").exists())
        self.assertFalse((self.root / "release").exists())

    def test_preflight_validates_new_spec_and_both_sides_of_archived_spec(self):
        self.write("CURRENT.md", "[Release](handoffs/release-test.md)\nUpdated index.\n")
        with self.local_commands():
            self.assertEqual(self.prepare(), (self.record_rel, True))
        self.assertEqual(self.required_paths(), {
            "core/main_window.py", "update.json", "PM Stack v1.11.6.spec",
            "PM Stack v1.11.5.spec", "specs/archive/PM Stack v1.11.5.spec",
        })
        self.assert_no_release_changes()
        self.assertTrue((self.root / "PM Stack v1.11.5.spec").exists())
        self.assertFalse((self.root / "PM Stack v1.11.6.spec").exists())

    def test_archived_template_requires_new_spec_but_no_nonexistent_old_spec(self):
        (self.root / "PM Stack v1.11.5.spec").unlink()
        self.commit_baseline()
        self.write(self.record_rel, "# Release task\n\nPreflight an archived template.\n")
        with self.local_commands():
            self.assertEqual(self.prepare(), (self.record_rel, False))
        self.assertEqual(self.required_paths(), {
            "core/main_window.py", "update.json", "PM Stack v1.11.6.spec",
        })
        self.assert_no_release_changes()

    def test_no_spec_template_accepts_absolute_record_and_only_requires_version_files(self):
        (self.root / "PM Stack v1.11.5.spec").unlink()
        (self.root / "specs/archive/PM Stack v1.10.20.spec").unlink()
        self.commit_baseline()
        self.write(self.record_rel, "# Release task\n\nPreflight without a spec.\n")
        with self.local_commands():
            self.assertEqual(self.prepare(str(self.root / self.record_rel)),
                             (self.record_rel, False))
        self.assertEqual(self.required_paths(), {"core/main_window.py", "update.json"})
        self.assert_no_release_changes()

    def test_rejects_outside_missing_template_and_readme_paths(self):
        outside = self.home / "outside.md"
        outside.write_text("# Outside\n", encoding="utf-8")
        for record in (str(outside), "../outside.md", "README.md", "handoffs",
                       "handoffs/missing.md", "handoffs/TEMPLATE.md", "handoffs/README.md"):
            with self.subTest(record=record), self.local_commands():
                with self.assertRaises(RuntimeError):
                    self.prepare(record)
        self.assert_no_release_changes()

    def test_rejects_record_symlink_escaping_repository(self):
        outside = self.home / "outside.md"
        outside.write_text("# Outside\n", encoding="utf-8")
        link = self.root / "handoffs/escaped.md"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("Creating symlinks is unavailable: {}".format(exc))
        with self.local_commands(), self.assertRaises(RuntimeError):
            self.prepare("handoffs/escaped.md")
        self.assert_no_release_changes()

    def test_rejects_nonempty_index_even_when_only_selected_record_is_staged(self):
        self.git("add", "--", self.record_rel)
        staged_before = self.git("diff", "--cached", "--name-only")
        with self.local_commands(), self.assertRaises(RuntimeError):
            self.prepare()
        self.assertEqual(self.git("diff", "--cached", "--name-only"), staged_before)

    def test_rejects_unrelated_tracked_edit_and_deletion(self):
        source = self.root / "core/main_window.py"
        baseline = source.read_bytes()
        for state in ("modified", "deleted"):
            with self.subTest(state=state):
                if state == "modified":
                    source.write_text('CURRENT_VERSION = "uncommitted"\n', encoding="utf-8")
                else:
                    source.unlink()
                with self.local_commands(), self.assertRaises(RuntimeError):
                    self.prepare()
                source.write_bytes(baseline)
        self.assert_no_release_changes()

    def test_rejects_unrelated_untracked_source_and_other_task_record(self):
        for path in ("scratch source.py", "handoffs/unrelated-new-task.md"):
            with self.subTest(path=path):
                target = self.write(path, "unrelated work\n")
                with self.local_commands(), self.assertRaises(RuntimeError):
                    self.prepare()
                target.unlink()
        self.write("handoffs/other-task.md", "# Another task\n\nUnrelated edit.\n")
        with self.local_commands(), self.assertRaises(RuntimeError):
            self.prepare()
        self.assert_no_release_changes()

    def test_ignored_build_and_runtime_files_do_not_block_preflight(self):
        self.write("dist/old-output.exe", "ignored output\n")
        self.write(".runtime-local/test.log", "ignored diagnostics\n")
        with self.local_commands():
            self.assertEqual(self.prepare(), (self.record_rel, False))
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_structural_validation_failure_is_runtime_error_before_mutation(self):
        self.validate_code = 1
        with self.local_commands(), self.assertRaises(RuntimeError):
            self.prepare()
        self.validator_command("validate")
        self.assert_no_release_changes()

    def test_staging_adds_only_selected_record_and_optional_index_before_check(self):
        self.write("CURRENT.md", "[Release](handoffs/release-test.md)\nUpdated index.\n")
        self.write("handoffs/other-task.md", "# Another task\n\nDo not stage this.\n")
        self.write("core/main_window.py", 'CURRENT_VERSION = "v1.11.6"\n')
        for index_changed in (False, True):
            with self.subTest(index_changed=index_changed):
                self.git("reset", "--quiet")
                self.git("add", "--", "core/main_window.py")
                self.commands.clear()
                with self.local_commands():
                    publish.stage_release_handoff(self.record_rel, index_changed)
                expected = {"core/main_window.py", self.record_rel}
                if index_changed:
                    expected.add("CURRENT.md")
                self.assertEqual(set(self.git("diff", "--cached", "--name-only").splitlines()),
                                 expected)
                additions = [cmd for cmd in self.commands
                             if Path(cmd[0]).name.lower() in ("git", "git.exe")
                             and "add" in cmd]
                self.assertTrue(additions)
                added_paths = []
                for command in additions:
                    offset = command.index("add")
                    self.assertEqual(command[offset + 1], "--")
                    added_paths.extend(command[offset + 2:])
                self.assertEqual(set(added_paths), expected - {"core/main_window.py"})
                options = self.handoff_options("check")
                self.assertEqual(options.get("--staged"), [True])
                self.assertNotIn("--record", options)
                self.assertNotIn("--require-path", options)
                self.assertLess(self.commands.index(additions[-1]),
                                self.commands.index(self.validator_command("check")))

    def test_failed_staged_check_aborts_without_unstaging_user_changes(self):
        self.write("core/main_window.py", 'CURRENT_VERSION = "v1.11.6"\n')
        self.git("add", "--", "core/main_window.py")
        self.check_code = 1
        with self.local_commands(), self.assertRaises(RuntimeError):
            publish.stage_release_handoff(self.record_rel, False)
        self.assertEqual(set(self.git("diff", "--cached", "--name-only").splitlines()),
                         {"core/main_window.py", self.record_rel})

    def test_main_requires_handoff_before_prompting_or_mutating(self):
        with mock.patch.object(sys, "argv", ["publish.py"]), \
                mock.patch.object(sys, "version_info", (3, 12)), \
                mock.patch.object(publish.os, "chdir"), \
                mock.patch("builtins.input") as prompt, \
                mock.patch.object(publish, "set_version") as set_version, \
                mock.patch.object(publish, "run") as run, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as stopped:
                publish.main()
        self.assertEqual(stopped.exception.code, 2)
        prompt.assert_not_called()
        set_version.assert_not_called()
        run.assert_not_called()

    def test_main_preflight_failure_precedes_version_build_and_network(self):
        with mock.patch.object(sys, "argv", ["publish.py", "--handoff", self.record_rel]), \
                mock.patch.object(sys, "version_info", (3, 12)), \
                mock.patch.object(publish.os, "chdir"), \
                mock.patch("builtins.input", side_effect=[self.next_version, "test notes"]), \
                mock.patch.object(publish, "prepare_release_handoff",
                                  side_effect=RuntimeError("preflight refused")) as prepare, \
                mock.patch.object(publish, "set_version") as set_version, \
                mock.patch.object(publish, "run") as run, \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                result = publish.main()
            except RuntimeError:
                pass
            except SystemExit as stopped:
                self.assertNotIn(stopped.code, (None, 0))
            else:
                self.assertEqual(result, 1)
        prepare.assert_called_once_with(self.record_rel, self.current_version, self.next_version)
        set_version.assert_not_called()
        run.assert_not_called()

    def test_main_preflights_before_version_and_checks_handoff_before_commit(self):
        events = []
        self.write("dist/PM Stack.exe", "synthetic executable")
        self.write("dist/PM Stack Updater.exe", "synthetic updater")

        def prepare(*args):
            events.append(("prepare", args))
            return self.record_rel, False

        def stage(*args):
            events.append(("stage", args))

        def run(command, **kwargs):
            args = [str(part) for part in command]
            events.append(("run", args))
            return subprocess.CompletedProcess(args, 0)

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(sys, "argv", ["publish.py", "--handoff", self.record_rel]))
            stack.enter_context(mock.patch.object(sys, "version_info", (3, 12)))
            stack.enter_context(mock.patch.object(publish.os, "chdir"))
            stack.enter_context(mock.patch("builtins.input", side_effect=[self.next_version, "notes", ""]))
            stack.enter_context(mock.patch.object(publish, "prepare_release_handoff", side_effect=prepare))
            stack.enter_context(mock.patch.object(publish, "set_version",
                                                  side_effect=lambda value: events.append(("version", value))))
            stack.enter_context(mock.patch.object(publish, "available_spec_templates", return_value=[]))
            stack.enter_context(mock.patch.object(publish, "archive_previous_spec", return_value=None))
            stack.enter_context(mock.patch.object(publish, "prepare_release_artifacts",
                                                  return_value=(self.root / "release/archive/test", self.root / "missing.zip")))
            stack.enter_context(mock.patch.object(publish, "stage_release_handoff", side_effect=stage))
            stack.enter_context(mock.patch.object(publish, "run", side_effect=run))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            publish.main()

        self.assertEqual(events[0], ("prepare", (self.record_rel, self.current_version, self.next_version)))
        version_index = next(index for index, event in enumerate(events) if event[0] == "version")
        stage_index = next(index for index, event in enumerate(events) if event[0] == "stage")
        commit_index = next(index for index, event in enumerate(events)
                            if event[0] == "run" and event[1][:2] == ["git", "commit"])
        self.assertLess(0, version_index)
        self.assertLess(version_index, stage_index)
        self.assertLess(stage_index, commit_index)
        self.assertEqual(events[stage_index], ("stage", (self.record_rel, False)))


if __name__ == "__main__":
    unittest.main()
