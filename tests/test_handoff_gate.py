"""Exercise the handoff CLI against isolated, real Git repositories.

Run with ``python tests/test_handoff_gate.py -v``.  No application
imports, Qt runtime, network access, or developer Git configuration are needed.
"""

import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).resolve().parents[1] / "tools" / "handoff.py"
GIT = shutil.which("git")
RECORD = "handoffs/current-task.md"


@unittest.skipUnless(GIT, "Git is required for the handoff CLI tests")
class GitSandboxTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="handoff gate ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "project"
        self.repo.mkdir()
        isolated_home = self.root / "home"
        isolated_home.mkdir()
        # Inherited Git overrides could point at the real checkout or load
        # user credentials/configuration. Every subprocess uses this sandbox.
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("GIT_")
        }
        self.env.update(
            HOME=str(isolated_home),
            USERPROFILE=str(isolated_home),
            XDG_CONFIG_HOME=str(isolated_home / "config"),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_TERMINAL_PROMPT="0",
            GIT_AUTHOR_NAME="Handoff Test",
            GIT_AUTHOR_EMAIL="handoff-test@example.invalid",
            GIT_COMMITTER_NAME="Handoff Test",
            GIT_COMMITTER_EMAIL="handoff-test@example.invalid",
            PYTHONUTF8="1",
            PYTHONIOENCODING="utf-8",
            PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
        )
        self.git("init")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.quotePath", "false")
        self.write("app.py", "VALUE = 1\n")
        self.write("README.md", "# Example project\n")
        self.write("CURRENT.md", "# Current tasks\n")
        self.commit_all("Initial project")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def run_process(self, args, cwd=None):
        return subprocess.run(
            [str(arg) for arg in args],
            cwd=str(cwd or self.repo),
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

    def git(self, *args):
        result = self.run_process([GIT, *args])
        self.assertEqual(result.returncode, 0, self.output(result))
        return result

    def cli(self, command="check", *args, repo=None):
        return self.run_process(
            [sys.executable, CLI, command, "--repo", repo or self.repo, *args]
        )

    @staticmethod
    def output(result):
        return "stdout:\n{}\nstderr:\n{}".format(result.stdout, result.stderr)

    def assert_exit(self, expected, result):
        self.assertEqual(result.returncode, expected, self.output(result))

    def write(self, relative, text):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit_all(self, message):
        self.git("add", "--all")
        self.git("commit", "-m", message)

    def record_text(self, paths, result="通过", reason=None, next_step=None):
        verification = "- 命令：python -m unittest tests.test_app\n- 结果：{}\n".format(result)
        if reason is not None:
            verification += "- 原因：{}\n".format(reason)
        return (
            "# Example task\n\n"
            "## 接手信息\n\n"
            "- 状态：进行中\n"
            "- 更新日期与时区：2026-10-25（Asia/Shanghai）\n"
            "- 负责人 / 集成人：Test Agent\n"
            "- 工作目录（绝对路径）：{}\n"
            "- 分支 / 起点 HEAD / 当前 HEAD：main / abc / dirty\n\n"
            "## 当前现场\n\n"
            "- 已完成：更新任务范围内的实现。\n"
            "- 未完成：等待集成人核对变更和验证结果。\n\n"
            "## 验证证据\n\n{}\n"
            "## 接手后的第一步\n\n{}\n\n"
            "## 变更文件\n\n{}\n"
        ).format(
            self.repo,
            verification,
            next_step or "1. 核对 app.py 的变更并确认验收结果。",
            "\n".join("- `{}`".format(path) for path in paths),
        )

    def add_record(self, paths, **kwargs):
        self.write(RECORD, self.record_text(paths, **kwargs))
        self.write(
            "CURRENT.md",
            "# Current tasks\n\n- [Example task]({})\n".format(RECORD),
        )


class HandoffGateTests(GitSandboxTestCase):
    def test_clean_repository_passes(self):
        self.assert_exit(0, self.cli())

    def test_code_change_without_handoff_fails(self):
        self.write("app.py", "VALUE = 2\n")
        result = self.cli()
        self.assert_exit(1, result)
        self.assertIn("app.py", result.stdout + result.stderr)

    def test_documentation_only_change_passes(self):
        self.write("README.md", "# Updated project usage\n")
        self.assert_exit(0, self.cli())

    def test_scoped_handoff_with_index_link_passes(self):
        self.write("app.py", "VALUE = 2\n")
        self.add_record(["app.py"])
        self.assert_exit(0, self.cli())

    def test_unlinked_handoff_fails_when_current_exists(self):
        self.write("app.py", "VALUE = 2\n")
        self.write(RECORD, self.record_text(["app.py"]))
        self.assert_exit(1, self.cli())

    def test_repository_without_current_can_use_local_handoff(self):
        self.git("rm", "CURRENT.md")
        self.commit_all("Legacy branch without task index")
        self.write("app.py", "VALUE = 2\n")
        self.write(RECORD, self.record_text(["app.py"]))
        self.assert_exit(0, self.cli())

    def test_staged_check_reads_staged_record_not_better_worktree(self):
        self.write("app.py", "VALUE = 2\n")
        self.add_record(["app.py"])
        self.write(RECORD, "# Task\n\nTODO\n")
        self.git("add", "--all")
        self.write(RECORD, self.record_text(["app.py"]))
        self.assert_exit(1, self.cli("check", "--staged"))
        self.assert_exit(0, self.cli())

    def test_staged_check_requires_staged_index_link(self):
        self.write("app.py", "VALUE = 2\n")
        self.write(RECORD, self.record_text(["app.py"]))
        self.git("add", "app.py", RECORD)
        self.write("CURRENT.md", "# Tasks\n\n- [Task]({})\n".format(RECORD))
        self.assert_exit(1, self.cli("check", "--staged"))
        self.assert_exit(0, self.cli())

    def test_unstaged_code_is_not_part_of_staged_check(self):
        self.write("app.py", "VALUE = 2\n")
        self.write("README.md", "# Updated usage\n")
        self.git("add", "README.md")
        self.assert_exit(0, self.cli("check", "--staged"))
        self.assert_exit(1, self.cli())

    def test_deleted_code_requires_handoff(self):
        (self.repo / "app.py").unlink()
        self.assert_exit(1, self.cli())
        self.add_record(["app.py"])
        self.assert_exit(0, self.cli())

    def test_rename_preserves_spaces_and_unicode_in_scope(self):
        renamed = "modules/中文 名称.py"
        (self.repo / "modules").mkdir()
        self.git("mv", "app.py", renamed)
        self.assert_exit(1, self.cli())
        self.add_record(["app.py", renamed])
        self.assert_exit(0, self.cli())

    def test_untracked_code_is_in_default_check(self):
        self.write("new_feature.py", "def feature():\n    return 1\n")
        self.assert_exit(1, self.cli())
        self.add_record(["new_feature.py"])
        self.assert_exit(0, self.cli())

    def test_base_check_reads_head_not_better_worktree(self):
        self.write("app.py", "VALUE = 2\n")
        self.add_record(["app.py"])
        self.write(RECORD, "# Incomplete committed task\n\nTODO\n")
        self.commit_all("Code with incomplete handoff")
        self.write(RECORD, self.record_text(["app.py"]))
        self.assert_exit(1, self.cli("check", "--base", self.base))

    def test_base_check_accepts_committed_scope_with_dirty_worktree(self):
        self.write("app.py", "VALUE = 2\n")
        self.add_record(["app.py"])
        self.commit_all("Code with complete handoff")
        self.write(RECORD, "# Work in progress\n\nTODO\n")
        self.write("unrelated.py", "VALUE = 3\n")
        self.assert_exit(0, self.cli("check", "--base", self.base))

    def test_untouched_old_handoffs_do_not_block_new_task(self):
        self.write("handoffs/old-task.md", "# Historic task\n\nTODO\n")
        self.commit_all("Preserve legacy handoff format")
        self.write("app.py", "VALUE = 2\n")
        self.add_record(["app.py"])
        self.assert_exit(0, self.cli())

    def test_unchanged_old_record_cannot_cover_new_code_changes(self):
        self.add_record(["app.py"])
        self.commit_all("Record the previous task")
        self.write("app.py", "VALUE = 2\n")
        self.assert_exit(1, self.cli())

    def test_placeholder_values_are_rejected(self):
        self.write("app.py", "VALUE = 2\n")
        for placeholder in ("TODO", "待填写", "<填写下一步>"):
            with self.subTest(placeholder=placeholder):
                self.add_record(["app.py"], next_step=placeholder)
                self.assert_exit(1, self.cli())

    def test_not_run_verification_requires_reason(self):
        self.write("app.py", "VALUE = 2\n")
        self.add_record(["app.py"], result="未执行")
        self.assert_exit(1, self.cli())
        self.add_record(
            ["app.py"],
            result="未执行",
            reason="当前隔离环境没有本任务所需的测试依赖，待集成人验证。",
        )
        self.assert_exit(0, self.cli())

    def test_empty_owner_cannot_consume_the_following_field(self):
        self.write("app.py", "VALUE = 2\n")
        self.add_record(["app.py"])
        self.write(
            RECORD,
            self.record_text(["app.py"]).replace(
                "- 负责人 / 集成人：Test Agent", "- 负责人 / 集成人："
            ),
        )
        self.assert_exit(1, self.cli())

    def test_empty_command_cannot_consume_the_result_field(self):
        self.write("app.py", "VALUE = 2\n")
        self.add_record(["app.py"])
        self.write(
            RECORD,
            self.record_text(["app.py"]).replace(
                "- 命令：python -m unittest tests.test_app", "- 命令："
            ),
        )
        self.assert_exit(1, self.cli())

    def test_worktree_handoff_cannot_follow_an_external_symlink(self):
        self.write("app.py", "VALUE = 2\n")
        self.write("CURRENT.md", "# Tasks\n\n- [Task]({})\n".format(RECORD))
        outside = self.root / "external-record.md"
        outside.write_text(self.record_text(["app.py"]), encoding="utf-8")
        linked_record = self.repo / RECORD
        linked_record.parent.mkdir()
        try:
            linked_record.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("Symlink creation is unavailable: {}".format(exc))
        self.assert_exit(1, self.cli())
        self.assert_exit(1, self.cli("validate", "--record", RECORD))

    def test_scope_must_cover_every_changed_code_file(self):
        self.write("app.py", "VALUE = 2\n")
        self.write("second.py", "VALUE = 3\n")
        self.add_record(["app.py"])
        result = self.cli()
        self.assert_exit(1, result)
        self.assertIn("second.py", result.stdout + result.stderr)
        self.add_record(["app.py", "second.py"])
        self.assert_exit(0, self.cli())

    def test_bad_revision_is_an_explicit_git_error(self):
        result = self.cli("check", "--base", "missing-handoff-test-revision")
        self.assert_exit(2, result)
        self.assertTrue((result.stdout + result.stderr).strip())
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_non_repository_is_an_explicit_git_error(self):
        outside = self.root / "not a repository"
        outside.mkdir()
        for command in ("status", "check"):
            with self.subTest(command=command):
                result = self.cli(command, repo=outside)
                self.assert_exit(2, result)
                self.assertTrue((result.stdout + result.stderr).strip())
                self.assertNotIn("Traceback", result.stdout + result.stderr)


class HandoffHookTests(GitSandboxTestCase):
    def setUp(self):
        super().setUp()
        source_hooks = CLI.parents[1] / ".githooks"
        if os.name == "nt":
            # The real hook can find the main checkout's known Python runtime
            # on Windows, where python3 may otherwise be an app alias.
            self.hooks = source_hooks
        else:
            # Never chmod files in the real checkout. Copy the exact hook and
            # checker into a temporary helper root, then set its execute bit.
            helper_root = self.root / "shared hook helper"
            self.hooks = helper_root / ".githooks"
            self.hooks.mkdir(parents=True)
            (helper_root / "tools").mkdir()
            shutil.copy2(CLI, helper_root / "tools" / "handoff.py")
            hook = self.hooks / "pre-commit"
            shutil.copy2(source_hooks / "pre-commit", hook)
            hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.git("config", "core.hooksPath", str(self.hooks))

    def commit_attempt(self, message):
        return self.run_process([GIT, "commit", "-m", message])

    def test_real_commit_rejects_staged_code_without_handoff(self):
        self.write("app.py", "VALUE = 2\n")
        self.git("add", "app.py")
        attempt = self.commit_attempt("Must be blocked by handoff hook")
        self.assertNotEqual(attempt.returncode, 0, self.output(attempt))
        self.assertIn("app.py", attempt.stdout + attempt.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.base)

    def test_real_commit_accepts_staged_record_and_current_link(self):
        self.write("app.py", "VALUE = 2\n")
        self.add_record(["app.py"])
        self.git("add", "--all")
        attempt = self.commit_attempt("Complete task with handoff")
        self.assert_exit(0, attempt)
        self.assertNotEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.base)

    def test_shared_hook_checks_the_linked_worktree_index(self):
        linked = self.root / "linked worktree"
        self.git("worktree", "add", "-b", "linked-task", str(linked), self.base)
        # The original worktree's index is clean. Checking that index by
        # mistake would allow this undocumented linked-worktree commit.
        self.repo = linked
        self.write("app.py", "VALUE = 2\n")
        self.git("add", "app.py")
        attempt = self.commit_attempt("Linked worktree must be blocked")
        self.assertNotEqual(attempt.returncode, 0, self.output(attempt))
        self.assertIn("app.py", attempt.stdout + attempt.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.base)
        self.add_record(["app.py"])
        self.git("add", "--all")
        self.assert_exit(0, self.commit_attempt("Linked worktree with handoff"))


if __name__ == "__main__":
    unittest.main()
