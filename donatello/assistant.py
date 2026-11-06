"""Two-phase planning and coding workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import architecture


IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}
MAX_CONTEXT_FILES = 80
MAX_FILE_BYTES = 30_000
MAX_CONTEXT_BYTES = 500_000
MAX_TEST_TIMEOUT = 300
DEFAULT_PLANNER_PROMPT = (
    "You are a project manager for a software coding assistant. "
    "Break the user's request into a small, ordered set of actionable coding tasks. "
    'Return only JSON: {"tasks":[{"title":"...","description":"..."}]}. '
    "Do not include markdown or extra fields. "
    "If the user requests changes, return a complete revised plan in the same JSON format. "
    "Consider any provided system architecture and component design document; if the "
    "request changes architecture, components, interfaces, or data flow, include a task "
    "to update it."
)
DEFAULT_CODER_PROMPT = (
    "You are a coding agent. Implement the assigned task in the provided repository. "
    "Return only JSON with this shape: "
    '{"summary":"...","files":[{"path":"relative/path","reason":"why this file is created or changed",'
    '"content":"complete UTF-8 file content"}],'
    '"tests":[["python","-m","unittest"]]}. '
    "Use repository-relative paths. Include only tests that should be run; "
    "tests must use Python unittest or pytest. Do not return shell commands. "
    "If the user requests changes, return a complete revised response in the same JSON format. "
    "If the task asks you to create or update the system architecture and component design "
    "document, or your changes affect architecture, components, interfaces, or data flow, "
    "include that document in your files list with the appropriate content."
)


class AssistantError(RuntimeError):
    """Raised when a request or model response cannot be processed safely."""


class ProjectManager:
    def __init__(self, provider: Any, system_prompt: str = DEFAULT_PLANNER_PROMPT) -> None:
        self.provider = provider
        self.system_prompt = system_prompt

    def plan(self, request: str, approver: Any = None, repo: Path | None = None) -> dict[str, Any]:
        """Plan a request; with an approver, revise the plan until the user approves it.

        When ``repo`` is given, the request is planned alongside the repository's
        system architecture and component design document (donatello/architecture.py),
        and the plan is guaranteed to include a task to create that document if it
        does not exist yet.
        """
        user_content = request
        if repo is not None:
            user_content = f"{request}\n\n{architecture.context_block(repo)}"
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]
        while True:
            response = self.provider.complete(messages, json_response=True)
            plan = self._parse_plan(response.text)
            if repo is not None and architecture.find(repo) is None:
                plan["tasks"].append(_architecture_document_task())
            feedback = approver.review("Proposed plan", _format_plan(plan, repo)) if approver else None
            if feedback is None:
                return plan
            messages += [
                {"role": "assistant", "content": response.text},
                {
                    "role": "user",
                    "content": (
                        "The user did not approve this plan and suggested these changes:\n"
                        f"{feedback}\n\nReturn a complete revised plan in the same JSON format."
                    ),
                },
            ]

    def _parse_plan(self, text: str) -> dict[str, Any]:
        try:
            result = json.loads(text)
        except json.JSONDecodeError as error:
            raise AssistantError(f"Project manager returned invalid JSON: {error}") from error
        tasks = result.get("tasks") if isinstance(result, dict) else None
        if not isinstance(tasks, list) or not tasks:
            raise AssistantError("Project manager response must contain a non-empty tasks array")
        for task in tasks:
            if (
                not isinstance(task, dict)
                or not isinstance(task.get("title"), str)
                or not task["title"].strip()
                or not isinstance(task.get("description"), str)
                or not task["description"].strip()
            ):
                raise AssistantError("Every task must have a non-empty title and description")
        return {"tasks": tasks}


class CodingAgent:
    def __init__(
        self,
        provider: Any,
        test_timeout: int = MAX_TEST_TIMEOUT,
        system_prompt: str = DEFAULT_CODER_PROMPT,
        approver: Any = None,
    ) -> None:
        self.provider = provider
        self.system_prompt = system_prompt
        self.test_timeout = test_timeout
        self.approver = approver

    def execute_plan(
        self, plan: dict[str, Any], repository: Path, request_log: Any = None
    ) -> list[dict[str, Any]]:
        root = repository.resolve(strict=True)
        if not root.is_dir():
            raise AssistantError(f"Repository is not a directory: {root}")
        results = []
        for task in plan["tasks"]:
            started = time.monotonic()
            written: list[str] = []
            try:
                result = self._execute_task(task, root, written)
            except Exception as error:
                if request_log:
                    request_log.task(
                        task["title"], time.monotonic() - started, _absolute(root, written), str(error)
                    )
                raise
            if request_log:
                request_log.task(task["title"], time.monotonic() - started, _absolute(root, written))
            results.append(result)
        return results

    def _execute_task(self, task: dict[str, Any], root: Path, written_out: list[str]) -> dict[str, Any]:
        context = _repository_context(root)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    f"Task: {task['title']}\n{task['description']}\n\n"
                    f"{architecture.context_block(root)}\n\n"
                    f"Repository files:\n{context}"
                ),
            },
        ]
        while True:
            response = self.provider.complete(messages, json_response=True)
            changes = _parse_changes(response.text)
            tests = _validate_tests(changes.get("tests", []))
            targets = _resolve_targets(root, changes["files"])
            feedback = (
                self.approver.review(
                    f"Proposed action: {task['title']}",
                    _format_proposal(task, changes, targets, tests, root),
                )
                if self.approver
                else None
            )
            if feedback is None:
                break
            messages += [
                {"role": "assistant", "content": response.text},
                {
                    "role": "user",
                    "content": (
                        "The user did not approve these changes and suggested:\n"
                        f"{feedback}\n\nReturn a complete revised response in the same JSON format."
                    ),
                },
            ]
        written_out.extend(_write_targets(targets))
        test_results = [
            self._run_test(root, command)
            for command in tests
        ]
        return {
            "task": task["title"],
            "summary": changes.get("summary", ""),
            "files": list(written_out),
            "tests": test_results,
        }

    def _run_test(self, root: Path, command: list[str]) -> dict[str, Any]:
        try:
            result = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=self.test_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            return {"command": command, "passed": False, "output": str(error)}
        return {
            "command": command,
            "passed": result.returncode == 0,
            "output": (result.stdout + result.stderr)[-10_000:],
        }


def _absolute(root: Path, relative_paths: list[str]) -> list[str]:
    return [str(root / path) for path in relative_paths]


def benchmark(provider_factory: Any, models: list[str], prompt: str) -> list[dict[str, Any]]:
    messages = [
        {
            "role": "system",
            "content": "Answer the coding request briefly and return valid JSON with a non-empty answer field.",
        },
        {"role": "user", "content": prompt},
    ]
    results = []
    for model in models:
        try:
            response = provider_factory(model).complete(messages, json_response=True)
            try:
                parsed = json.loads(response.text)
                valid = isinstance(parsed, dict) and bool(parsed.get("answer"))
            except json.JSONDecodeError:
                valid = False
            results.append(
                {
                    "model": model,
                    "seconds": response.duration_seconds,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "valid_response": valid,
                    "response": response.text,
                }
            )
        except Exception as error:
            results.append({"model": model, "error": str(error)})
    return results


def _parse_changes(text: str) -> dict[str, Any]:
    try:
        changes = json.loads(text)
    except json.JSONDecodeError as error:
        raise AssistantError(f"Coding agent returned invalid JSON: {error}") from error
    if not isinstance(changes, dict) or not isinstance(changes.get("files"), list):
        raise AssistantError("Coding agent response must contain a files array")
    for item in changes["files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(
            item.get("content"), str
        ):
            raise AssistantError("Each file change must have a path and string content")
        if "reason" in item and not isinstance(item["reason"], str):
            raise AssistantError("A file change reason must be a string")
    return changes


def _architecture_document_task() -> dict[str, str]:
    """A task guaranteeing the architecture document is created when missing.

    Donatello appends this to a plan whenever the target repository has no
    system architecture and component design document yet, so its creation is
    always proposed and reviewed like any other file change.
    """
    return {
        "title": "Create system architecture and component design document",
        "description": (
            f"Create {architecture.FILENAME} at the repository root describing this "
            "project's system architecture and component design, following the "
            "provided template and reflecting the repository as a whole."
        ),
    }


def _format_plan(plan: dict[str, Any], repo: Path | None = None) -> str:
    lines = [
        f"{number}. {task['title']}\n   {task['description']}"
        for number, task in enumerate(plan["tasks"], 1)
    ]
    if repo is not None:
        path, content = architecture.load(repo)
        relative = path.relative_to(repo).as_posix()
        status = "exists" if content is not None else "missing, will be created"
        lines.append(f"\nArchitecture document ({relative}): {status}")
    return "\n".join(lines)


def _format_proposal(
    task: dict[str, Any],
    changes: dict[str, Any],
    targets: list[tuple[Path, Path, str]],
    tests: list[list[str]],
    root: Path,
) -> str:
    lines = [f"Task: {task['title']}", f"Why: {task['description']}"]
    if changes.get("summary"):
        lines.append(f"Summary: {changes['summary']}")
    lines.append(f"Repository: {root}")
    arch_path, arch_content = architecture.load(root)
    arch_relative = arch_path.relative_to(root).as_posix()
    if arch_content is not None:
        lines += [
            "",
            f"Architecture document for comparison ({arch_relative}):",
            arch_content.rstrip("\n"),
        ]
    else:
        lines += ["", f"No architecture document yet; expected at {arch_relative} once created."]
    for item, (_, target, content) in zip(changes["files"], targets):
        verb = "OVERWRITE existing file" if target.exists() else "CREATE new file"
        lines += [
            "",
            f"{verb}: {target}",
            f"Why: {item.get('reason') or changes.get('summary') or task['description']}",
            "----- code -----",
            content.rstrip("\n"),
            "----- end code -----",
        ]
    if tests:
        lines += ["", f"RUN tests (working directory {root}):"]
        lines += [f"  {' '.join(command)}" for command in tests]
    return "\n".join(lines)


def _resolve_targets(root: Path, files: list[dict[str, str]]) -> list[tuple[Path, Path, str]]:
    targets = []
    for item in files:
        relative = Path(item["path"])
        if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            raise AssistantError(f"Unsafe repository path: {item['path']}")
        target = root.joinpath(relative)
        if not target.resolve(strict=False).is_relative_to(root):
            raise AssistantError(f"File path escapes the repository: {item['path']}")
        if target.exists() and not target.is_file():
            raise AssistantError(f"Not a regular file: {item['path']}")
        targets.append((relative, target, item["content"]))
    return targets


def _write_targets(targets: list[tuple[Path, Path, str]]) -> list[str]:
    written = []
    for relative, target, content in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(relative.as_posix())
    return written


def _apply_files(root: Path, files: list[dict[str, str]]) -> list[str]:
    return _write_targets(_resolve_targets(root, files))


_PYTHON_COMMAND_NAMES = {"python", "python3", sys.executable}
_SAFE_TEST_FLAGS = {"discover", "-v", "-q", "--verbose", "--quiet"}


def _validate_tests(tests: Any) -> list[list[str]]:
    if not isinstance(tests, list):
        raise AssistantError("Tests must be an array of argument arrays")
    validated = []
    for command in tests:
        if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
            raise AssistantError("Each test command must be an array of strings")
        normalized = _normalize_test_command(command)
        if normalized is None:
            raise AssistantError(
                "Only the standard Python unittest and pytest test commands are supported"
            )
        validated.append(normalized)
    return validated


def _normalize_test_command(command: list[str]) -> list[str] | None:
    """Rewrite a trusted unittest/pytest invocation to use sys.executable.

    Accepts the bare runner commands plus an optional trailing target (a test
    file, dotted module name, or a small allowlist of safe flags), so models
    that name the specific test they wrote are not rejected outright. Any
    other form (e.g. ``python -c ...``) is rejected.
    """
    if command and command[0] == "pytest":
        prefix, arguments = [sys.executable, "-m", "pytest"], command[1:]
    elif len(command) >= 3 and command[0] in _PYTHON_COMMAND_NAMES and command[1] == "-m" and command[2] in ("unittest", "pytest"):
        prefix, arguments = [sys.executable, "-m", command[2]], command[3:]
    else:
        return None
    if not arguments:
        return prefix + ["discover"] if prefix[-1] == "unittest" else prefix
    if not all(_is_safe_test_argument(argument) for argument in arguments):
        return None
    return prefix + arguments


def _is_safe_test_argument(argument: str) -> bool:
    if argument in _SAFE_TEST_FLAGS:
        return True
    if argument.startswith("-"):
        return False
    path = Path(argument)
    return not path.is_absolute() and not any(part in {"", ".", ".."} for part in path.parts)


def _repository_context(root: Path) -> str:
    chunks = []
    total_bytes = 0
    for current, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name for name in directories if name not in IGNORED_DIRECTORIES
        )
        for filename in sorted(filenames):
            path = Path(current, filename)
            if path.is_symlink():
                continue
            try:
                size = path.stat().st_size
                if size > MAX_FILE_BYTES or total_bytes + size > MAX_CONTEXT_BYTES:
                    continue
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            relative = path.relative_to(root).as_posix()
            chunks.append(f"--- {relative} ---\n{content}")
            total_bytes += size
            if len(chunks) >= MAX_CONTEXT_FILES:
                return "\n\n".join(chunks)
    return "\n\n".join(chunks) if chunks else "(repository is empty)"
