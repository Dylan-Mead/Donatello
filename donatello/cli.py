"""Command-line interface for Donatello."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .approval import ApprovalCancelled, Approver
from .assistant import AssistantError, CodingAgent, ProjectManager, benchmark
from .config import load_config
from .requestlog import RequestLog
from .providers import FallbackProvider, OllamaProvider, OpenAICompatibleProvider, ProviderError


def _default_repo() -> Path:
    """Return the nearest enclosing git repository root, or the current directory."""
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def _resolve_request(args: argparse.Namespace) -> str:
    """Return the coding request text from the positional argument or --read.

    Exactly one of the positional "request" argument or "--read" must be
    given; "--read" reads the request text from a file instead of requiring
    it to be typed on the command line.
    """
    if args.request is not None and args.read is not None:
        raise ValueError("Provide a request argument or --read, not both")
    if args.read is not None:
        path = args.read.expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(f"Could not read request file: {error}") from error
        request = text.strip()
        if not request:
            raise ValueError(f"Request file is empty: {path}")
        return request
    if args.request is None or not args.request.strip():
        raise ValueError("A coding request is required, as an argument or via --read")
    return args.request


def _provider(model: str, args: argparse.Namespace) -> Any:
    primary = OllamaProvider(model=model, base_url=args.ollama_url)
    base_url = args.external_base_url or os.getenv("DONATELLO_EXTERNAL_BASE_URL")
    external_model = args.external_model or os.getenv("DONATELLO_EXTERNAL_MODEL")
    if base_url and external_model:
        return FallbackProvider(
            primary,
            OpenAICompatibleProvider(base_url, external_model),
        )
    return primary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="donatello", description="Local-first AI coding assistant")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--repo",
        type=Path,
        help="Path to the repository to work on (default: the repository containing the current directory)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("plan", "run"):
        command = subparsers.add_parser(name, parents=[common])
        command.add_argument("request", nargs="?", help="Coding request (omit if --read is given)")
        command.add_argument(
            "--read",
            type=Path,
            help="Read the coding request from this file instead of passing it on the command line",
        )
        command.add_argument("--config", help="Config file name in the configs folder (default: default)")
        command.add_argument("--model", help="Override the config's planner and coder models")
        command.add_argument("--ollama-url")
        command.add_argument("--external-base-url")
        command.add_argument("--external-model")
        if name == "run":
            command.add_argument(
                "--auto",
                action="store_true",
                help="Do not ask for approval before planning and file/test actions",
            )

    compare = subparsers.add_parser(
        "benchmark",
        parents=[common],
        help="Compare response time and JSON quality across Ollama models",
    )
    compare.add_argument("--models", nargs="+", required=True)
    compare.add_argument(
        "--prompt",
        default="Write a Python function that adds two integers.",
    )
    compare.add_argument("--ollama-url")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        args.repo = args.repo.expanduser() if args.repo else _default_repo()
        if not args.repo.is_dir():
            raise ValueError(f"Repository is not a directory: {args.repo}")
        if args.command == "benchmark":
            output = benchmark(
                lambda model: OllamaProvider(model=model, base_url=args.ollama_url),
                args.models,
                args.prompt,
            )
        else:
            args.request = _resolve_request(args)
            config = load_config(args.config)
            planner_provider = _provider(args.model or config.planner_model, args)
            coder_provider = _provider(args.model or config.coder_model, args)
            request_log = RequestLog()
            request_details = {
                "request": args.request,
                "arguments": {
                    key: str(value) if isinstance(value, Path) else value
                    for key, value in vars(args).items()
                    if key != "request"
                },
            }
            approver = Approver(auto=args.auto) if args.command == "run" else None
            started = time.monotonic()
            try:
                plan = ProjectManager(planner_provider, config.planner_system_prompt).plan(
                    args.request, repo=args.repo, approver=approver
                )
            except Exception as error:
                request_log.plan(None, time.monotonic() - started, str(error), request_details)
                raise
            request_log.plan(plan, time.monotonic() - started, request=request_details)
            if args.command == "plan":
                output = plan
            else:
                agent = CodingAgent(
                    coder_provider, system_prompt=config.coder_system_prompt, approver=approver
                )
                results = agent.execute_plan(plan, args.repo, request_log)
                output = {"plan": plan, "results": results}
        print(json.dumps(output, indent=2))
        if args.command == "run" and any(
            not test["passed"] for result in output["results"] for test in result["tests"]
        ):
            return 1
        if args.command == "benchmark" and any("error" in result for result in output):
            return 1
        return 0
    except (ApprovalCancelled, AssistantError, OSError, ProviderError, ValueError) as error:
        print(f"donatello: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
