"""Interactive command-line approval of planned actions."""

from __future__ import annotations

import sys
from typing import Callable, TextIO

AUTO_FLAG = "--auto"
_YES = {"y", "yes", "approve", "approved", "ok"}
_NO = {"n", "no"}


class ApprovalCancelled(RuntimeError):
    """Raised when the user cancels instead of approving or suggesting changes."""


class Approver:
    """Asks the user to approve an action or to suggest changes to it.

    Prompts and proposals go to stderr so stdout stays reserved for the final
    JSON result. Once auto mode is on (``--auto`` on the command line or as an
    approval response), every later review is approved without prompting.
    """

    def __init__(
        self,
        auto: bool = False,
        input_fn: Callable[[], str] | None = None,
        output: TextIO | None = None,
    ) -> None:
        self.auto = auto
        self._input = input_fn or sys.stdin.readline
        self._output = output or sys.stderr

    def review(self, heading: str, body: str) -> str | None:
        """Return None if approved, or the user's suggested changes."""
        if self.auto:
            return None
        self._say(f"\n=== {heading} ===\n{body}\n")
        while True:
            answer = self._ask(
                "Approve? [y]es / [n]o / type suggested changes / "
                f"{AUTO_FLAG} to approve everything from now on: "
            )
            lowered = answer.lower()
            if lowered == AUTO_FLAG:
                self.auto = True
                return None
            if lowered in _YES:
                return None
            if lowered in _NO:
                feedback = self._ask("What should change? (leave blank to cancel): ")
                if not feedback:
                    raise ApprovalCancelled("Cancelled by user")
                if feedback.lower() == AUTO_FLAG:
                    self.auto = True
                    return None
                return feedback
            if answer:
                return answer

    def _say(self, text: str) -> None:
        print(text, file=self._output, flush=True)

    def _ask(self, prompt: str) -> str:
        self._output.write(prompt)
        self._output.flush()
        line = self._input()
        if line == "":
            raise ApprovalCancelled(
                f"No approval input available (end of input); run with {AUTO_FLAG} to skip approvals"
            )
        return line.strip()
