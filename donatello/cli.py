"""Command-line interface for Donatello."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .assistant import AssistantError, CodingAgent, ProjectManager, benchmark
from .requestlog import RequestLog
from .providers import FallbackProvider, OllamaProvider, OpenAICompatibleProvider, ProviderError


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
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("plan", "run"):
        command = subparsers.add_parser(name)
        command.add_argument("request", help="Coding request")
        command.add_argument("--model", default="qwen2.5-coder:7b")
        command.add_argument("--ollama-url")
        command.add_argument("--external-base-url")
        command.add_argument("--external-model")
        if name == "run":
            command.add_argument("--repo", required=True, type=Path)

    compare = subparsers.add_parser("benchmark", help="Compare response time and JSON quality across Ollama models")
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
        if args.command == "benchmark":
            output = benchmark(
                lambda model: OllamaProvider(model=model, base_url=args.ollama_url),
                args.models,
                args.prompt,
            )
        else:
            provider = _provider(args.model, args)
            request_log = RequestLog()
            started = time.monotonic()
            try:
                plan = ProjectManager(provider).plan(args.request)
            except Exception as error:
                request_log.plan(None, time.monotonic() - started, str(error))
                raise
            request_log.plan(plan, time.monotonic() - started)
            if args.command == "plan":
                output = plan
            else:
                results = CodingAgent(provider).execute_plan(plan, args.repo, request_log)
                output = {"plan": plan, "results": results}
        print(json.dumps(output, indent=2))
        if args.command == "run" and any(
            not test["passed"] for result in output["results"] for test in result["tests"]
        ):
            return 1
        if args.command == "benchmark" and any("error" in result for result in output):
            return 1
        return 0
    except (AssistantError, OSError, ProviderError, ValueError) as error:
        print(f"donatello: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
