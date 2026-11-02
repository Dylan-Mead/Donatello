"""Two-phase planning and coding workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


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


class AssistantError(RuntimeError):
    """Raised when a request or model response cannot be processed safely."""


class ProjectManager:
    def __init__(self, provider: Any) -> None:
        self.provider = provider

    def plan(self, request: str) -> dict[str, Any]:
        response = self.provider.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a project manager for a software coding assistant. "
                        "Break the user's request into a small, ordered set of actionable coding tasks. "
                        'Return only JSON: {"tasks":[{"title":"...","description":"..."}]}. '
                        "Do not include markdown or extra fields."
                    ),
                },
                {"role": "user", "content": request},
            ],
            json_response=True,
        )
        try:
            result = json.loads(response.text)
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
    def __init__(self, provider: Any, test_timeout: int = MAX_TEST_TIMEOUT) -> None:
        self.provider = provider
        self.test_timeout = test_timeout

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
                    request_log.task(task["title"], time.monotonic() - started, written, str(error))
                raise
            if request_log:
                request_log.task(task["title"], time.monotonic() - started, written)
            results.append(result)
        return results

    def _execute_task(self, task: dict[str, Any], root: Path, written_out: list[str]) -> dict[str, Any]:
        context = _repository_context(root)
        response = self.provider.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a coding agent. Implement the assigned task in the provided repository. "
                        "Return only JSON with this shape: "
                        '{"summary":"...","files":[{"path":"relative/path","content":"complete UTF-8 file content"}],'
                        '"tests":[["python","-m","unittest"]]}. '
                        "Use repository-relative paths. Include only tests that should be run; "
                        "tests must use Python unittest or pytest. Do not return shell commands."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Task: {task['title']}\n{task['description']}\n\n"
                        f"Repository files:\n{context}"
                    ),
                },
            ],
            json_response=True,
        )
        changes = _parse_changes(response.text)
        tests = _validate_tests(changes.get("tests", []))
        written_out.extend(_apply_files(root, changes["files"]))
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
    return changes


def _apply_files(root: Path, files: list[dict[str, str]]) -> list[str]:
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

    written = []
    for relative, target, content in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(relative.as_posix())
    return written


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
