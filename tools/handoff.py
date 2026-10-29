"""Read-only Git handoff checks; no application imports or third-party packages."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import subprocess
import sys
from typing import List, Set


STATUSES = {"计划", "进行中", "待接手", "待确认", "受阻", "已完成"}
METADATA = (
    "状态", "更新日期与时区", "负责人 / 集成人", "工作目录（绝对路径）",
    "分支 / 起点 HEAD / 当前 HEAD",
)
SECTIONS = ("当前现场", "验证证据", "接手后的第一步", "变更文件")
DOCUMENT_SUFFIXES = {".md", ".rst", ".txt", ".pdf"}
CANONICAL_INDEX = Path(r"D:\PM Stack\PM Stack\CURRENT.md")
PLACEHOLDER = re.compile(r"\bTODO\b|待填写|<[^<>]*>", re.IGNORECASE)


class GitError(RuntimeError):
    """A Git command could not obtain the requested repository evidence."""


class ContentError(ValueError):
    """A checked text file could not be read as UTF-8."""


@dataclass(frozen=True)
class Change:
    status: str
    path: str


@dataclass
class RecordResult:
    path: str
    scope: Set[str] = field(default_factory=set)
    errors: List[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    changes: List[Change] = field(default_factory=list)
    records: List[str] = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors


def git(repo, *args, allowed_codes=(0,)):
    """Return raw stdout; filenames are decoded only after NUL splitting."""
    command = ["git", "--no-optional-locks", "-c", "core.quotepath=false",
               "-C", str(repo), *args]
    try:
        process = subprocess.run(command, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, check=False)
    except OSError as exc:
        raise GitError("Cannot execute Git: " + str(exc)) from exc
    if process.returncode not in allowed_codes:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise GitError("Git command failed (exit {}): {}{}".format(
            process.returncode, " ".join(args), ": " + detail if detail else ""))
    return process.stdout


def _utf8(data, label):
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ContentError(label + " is not valid UTF-8") from exc


def _git_text(repo, *args):
    try:
        return git(repo, *args).decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError as exc:
        raise GitError("Git output is not valid UTF-8") from exc


def resolve_repo(repo):
    """Resolve a directory inside a working tree to its actual root."""
    return Path(_git_text(repo, "rev-parse", "--show-toplevel")).resolve()


def _nul_paths(data):
    try:
        return [part.decode("utf-8") for part in data.split(b"\0") if part]
    except UnicodeDecodeError as exc:
        raise GitError("Git filename output is not valid UTF-8") from exc


def collect_changes(repo, staged=False, base=None):
    """Collect net changes in the requested snapshot; renames become D + A."""
    if staged and base is not None:
        raise ValueError("--staged and --base are mutually exclusive")
    args = ["diff", "--name-status", "-z", "--no-renames"]
    if staged:
        args += ["--cached"]
    elif base is not None:
        # Verify the revision as a commit before passing its object ID to diff.
        revision = _git_text(repo, "rev-parse", "--verify", "--end-of-options",
                             base + "^{commit}")
        args += [revision, "HEAD"]
    else:
        args += ["HEAD"]
    fields = _nul_paths(git(repo, *args, "--"))
    if len(fields) % 2:
        raise GitError("Unexpected NUL-delimited Git diff output")
    changes = [Change(fields[i], fields[i + 1]) for i in range(0, len(fields), 2)]
    if not staged and base is None:
        changes += [Change("?", path) for path in _nul_paths(
            git(repo, "ls-files", "--others", "--exclude-standard", "-z"))]
    return changes


class Snapshot:
    """Read only the selected worktree, index, or HEAD; never another worktree."""

    def __init__(self, repo, staged=False, base=None):
        self.repo = Path(repo)
        self.source = "index" if staged else "HEAD" if base is not None else "worktree"
        self._paths = None

    def read(self, path):
        if self.source == "worktree":
            target = self.repo.joinpath(*PurePosixPath(path).parts)
            try:
                if target.is_symlink():
                    raise ContentError("Symbolic-link handoff evidence is not allowed: " + path)
                target.resolve().relative_to(self.repo.resolve())
            except ValueError as exc:
                raise ContentError("Handoff evidence escapes the target repository: " + path) from exc
            except OSError as exc:
                raise ContentError("Cannot resolve {}: {}".format(path, exc)) from exc
            if not target.is_file():
                return None
            try:
                return _utf8(target.read_bytes(), path)
            except OSError as exc:
                raise ContentError("Cannot read {}: {}".format(path, exc)) from exc
        if self._paths is None:
            args = ("ls-files", "--cached", "-z") if self.source == "index" else (
                "ls-tree", "-r", "--name-only", "-z", "HEAD")
            self._paths = set(_nul_paths(git(self.repo, *args)))
        if path not in self._paths:
            return None
        spec = ":" + path if self.source == "index" else "HEAD:" + path
        return _utf8(git(self.repo, "show", spec), path)


def is_handoff(path):
    parts = PurePosixPath(path).parts
    return (len(parts) >= 2 and parts[0] == "handoffs"
            and parts[-1].lower().endswith(".md")
            and parts[-1].lower() not in {"template.md", "readme.md"})


def requires_handoff(path):
    """Documentation is exempt except requirements and automation/config roots."""
    parts = PurePosixPath(path).parts
    lower = path.lower()
    name = parts[-1].lower() if parts else ""
    if parts and parts[0].lower() in {".github", ".githooks"}:
        return True
    if name.startswith("requirements") and name.endswith(".txt"):
        return True
    if lower.startswith("docs/"):
        return False
    return PurePosixPath(path).suffix.lower() not in DOCUMENT_SUFFIXES


def valid_scope_path(path):
    """A scope entry must be an exact, canonical repository-relative Git path."""
    return bool(path and not path.startswith(("/", "\\"))
                and not PureWindowsPath(path).drive
                and "\\" not in path
                and not any(char in path for char in "*?[]\x00\r\n")
                and all(part not in {"", ".", ".."} for part in path.split("/")))


def _unquote(value):
    return value.strip().strip("`").strip()


def _meaningful(value):
    # Empty Markdown bullets and empty code fences are not section content.
    for line in value.splitlines():
        plain = re.sub(r"^\s*(?:[-*+]\s*|\d+[.)]\s*)", "", line).strip()
        if plain and not re.fullmatch(r"`{3,}|~{3,}|<!--.*?-->", plain):
            return True
    return False


def _markdown_sections(text):
    sections = {}
    current = None
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            kind = marker.group(1)[0]
            if fence is None:
                fence = kind
            elif fence == kind:
                fence = None
            if current is not None:
                sections[current].append(line)
            continue
        match = re.match(r"^##\s+(.+?)\s*#*\s*$", line) if fence is None else None
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}


def _field_values(text, name):
    return re.findall(r"^[ \t]*-[ \t]+" + re.escape(name)
                      + r"[ \t]*[：:][ \t]*(.*?)[ \t]*$",
                      text, flags=re.MULTILINE)


def validate_record(text, path):
    """Validate one Markdown record and return its exact declared file scope."""
    result = RecordResult(path)

    def error(message):
        result.errors.append(path + ": " + message)

    metadata = {}
    for name in METADATA:
        values = _field_values(text, name)
        if len(values) != 1:
            error("Expected exactly one metadata field: " + name)
            continue
        value = _unquote(values[0])
        metadata[name] = value
        if not value or PLACEHOLDER.search(value):
            error("Metadata is empty or contains a placeholder: " + name)
    status = metadata.get("状态")
    if status is not None and status not in STATUSES:
        error("Status must be exactly one of the six supported values")
    owner = metadata.get("负责人 / 集成人", "")
    if "待确认" in owner:
        error("Owner / integrator must name an actual responsible party")
    when = metadata.get("更新日期与时区")
    if when is not None:
        match = re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", when)
        try:
            if match is None:
                raise ValueError("missing date")
            date.fromisoformat(match.group(1))
        except ValueError:
            error("Update date must include a valid YYYY-MM-DD date")
    directory = metadata.get("工作目录（绝对路径）")
    if directory is not None and not (PurePosixPath(directory).is_absolute()
                                      or PureWindowsPath(directory).is_absolute()):
        error("Working directory must be an absolute path")

    sections = _markdown_sections(text)
    for name in SECTIONS:
        content = sections.get(name, "")
        if not _meaningful(content):
            error("Required section is missing or empty: " + name)
        elif PLACEHOLDER.search(content):
            error("Required section contains a placeholder: " + name)
    evidence = sections.get("验证证据", "")
    for name in ("命令", "结果"):
        values = _field_values(evidence, name)
        if not values or any(not _unquote(value) for value in values):
            error("Verification needs a nonempty field: " + name)
    if re.search(r"未执行|未运行|not\s+(?:run|executed)", evidence, re.IGNORECASE):
        reasons = _field_values(evidence, "原因")
        if not reasons or any(not _unquote(value) for value in reasons):
            error("Verification not run: provide a nonempty reason field")
    for line in sections.get("变更文件", "").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"\s*-\s+`([^`]+)`\s*", line)
        if match is None or not valid_scope_path(match.group(1)):
            error("File scope must list exact relative paths as '- `relative/path`'")
        else:
            result.scope.add(match.group(1))
    if not result.scope:
        error("File scope must contain at least one exact relative path")
    return result


def _check_records(snapshot, candidates, required_paths):
    result = ValidationResult()
    try:
        current = snapshot.read("CURRENT.md")
    except ContentError as exc:
        result.errors.append(str(exc))
        current = ""
    if current is None:
        result.warnings.append(
            "CURRENT.md is absent in the selected snapshot; record checks still apply. "
            "The coordinator maintains the canonical main-worktree index.")
    scope = set()
    for path in sorted(set(candidates)):
        result.records.append(path)
        try:
            content = snapshot.read(path)
        except ContentError as exc:
            result.errors.append(str(exc))
            continue
        if content is None:
            result.errors.append("Handoff record is missing from the selected snapshot: " + path)
            continue
        record = validate_record(content, path)
        reference = re.search(r"(?<![\w./\\-])" + re.escape(path)
                              + r"(?![\w./\\-])", current or "")
        if current is not None and reference is None:
            record.errors.append(path + ": CURRENT.md must reference this handoff record")
        result.errors.extend(record.errors)
        if not record.errors:
            scope.update(record.scope)
    for path in sorted(set(required_paths) - scope):
        result.errors.append("Code/build change is not covered by a valid changed handoff record: " + path)
    return result


def check_repository(repo, staged=False, base=None):
    """Check changed records and coverage, with all evidence from one snapshot."""
    repo = resolve_repo(repo)
    changes = collect_changes(repo, staged=staged, base=base)
    candidates = [change.path for change in changes
                  if change.status != "D" and is_handoff(change.path)]
    required = {change.path for change in changes if requires_handoff(change.path)}
    result = _check_records(Snapshot(repo, staged=staged, base=base), candidates, required)
    result.changes = changes
    if required and not candidates:
        result.errors.insert(0, "Code/build changes require a newly added or modified handoff record")
    if any(change.status.startswith("U") for change in changes):
        result.errors.insert(0, "Unresolved Git conflicts must be resolved before handoff")
    return result


def validate_named_record(repo, record, required_paths=()):
    """Validate a working-tree record for explicit future publication paths."""
    repo = resolve_repo(repo)
    result = ValidationResult()
    if not valid_scope_path(record) or not is_handoff(record):
        result.errors.append("--record must name a handoffs/*.md task record relative to the repository")
        return result
    required_paths = list(required_paths)
    for path in required_paths:
        if not valid_scope_path(path):
            result.errors.append("--require-path must be an exact repository-relative path: " + path)
    if result.errors:
        return result
    return _check_records(Snapshot(repo), [record], required_paths)


def show_status(repo):
    repo = resolve_repo(repo)
    branch = _git_text(repo, "rev-parse", "--abbrev-ref", "HEAD")
    head = _git_text(repo, "rev-parse", "HEAD")
    print("Repository: " + str(repo))
    print("Branch: " + branch)
    print("HEAD: " + head)
    print("Rules: {}{}".format(repo / "AGENTS.md", "" if (repo / "AGENTS.md").is_file() else " (absent)"))
    print("Index: {}{}".format(repo / "CURRENT.md", "" if (repo / "CURRENT.md").is_file() else " (absent)"))
    if not (repo / "CURRENT.md").is_file():
        print("Canonical local main index (navigation only): " + str(CANONICAL_INDEX))
    hook_setting = git(repo, "config", "--get", "core.hooksPath", allowed_codes=(0, 1))
    if hook_setting:
        hooks = Path(_utf8(hook_setting, "Git hooksPath").rstrip("\r\n"))
        if not hooks.is_absolute():
            hooks = repo / hooks
        print("Hooks path: " + str(hooks))
    else:
        hooks = Path(_git_text(repo, "rev-parse", "--git-path", "hooks"))
        if not hooks.is_absolute():
            hooks = repo / hooks
        print("Hooks path: {} (Git default; handoff hook not configured)".format(hooks))
    print("Pre-commit hook: " + ("present" if (hooks / "pre-commit").is_file() else "absent"))
    fields = _nul_paths(git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all"))
    print("Git status:")
    if not fields:
        print("  clean")
    index = 0
    unstaged = untracked = False
    while index < len(fields):
        entry = fields[index]
        code, path = entry[:2], entry[3:]
        index += 1
        if "R" in code or "C" in code:
            previous = fields[index]
            index += 1
            print("  {} {} -> {}".format(code, repr(previous), repr(path)))
        else:
            print("  {} {}".format(code, repr(path)))
        untracked |= code == "??"
        unstaged |= code != "??" and code[1] != " "
    if unstaged:
        print("NOTE: Unstaged changes exist; --staged will not include their contents.")
    if untracked:
        print("NOTE: Untracked files exist; default check includes non-ignored files, --staged does not.")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="Show read-only repository and handoff status")
    status.add_argument("--repo", default=".", help="Target working tree or directory inside it")
    check = commands.add_parser("check", help="Validate changed handoff records and code/build coverage")
    check.add_argument("--repo", default=".", help="Target working tree or directory inside it")
    mode = check.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="Read changes and all records only from the index")
    mode.add_argument("--base", metavar="REV", help="Check REV..HEAD changes and read records only from HEAD")
    validate = commands.add_parser("validate", help="Validate an explicit working-tree record before publication")
    validate.add_argument("--repo", default=".", help="Target working tree or directory inside it")
    validate.add_argument("--record", required=True, help="Repository-relative handoffs/*.md path")
    validate.add_argument("--require-path", action="append", default=[], metavar="PATH",
                          help="Future repository-relative path requiring scope coverage; repeatable")
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            return show_status(args.repo)
        result = (check_repository(args.repo, staged=args.staged, base=args.base)
                  if args.command == "check" else
                  validate_named_record(args.repo, args.record, args.require_path))
        for warning in result.warnings:
            print("NOTE: " + warning)
        for error in result.errors:
            print("ERROR: " + error)
        if not result.ok:
            print("Handoff check failed: {} error(s).".format(len(result.errors)))
            return 1
        print("Handoff check passed: {} change(s), {} record(s).".format(
            len(result.changes), len(result.records)))
        return 0
    except GitError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2
    except ContentError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
