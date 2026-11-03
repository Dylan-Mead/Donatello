import io
import json
import tempfile
import unittest
from pathlib import Path

from donatello.approval import ApprovalCancelled, Approver
from donatello.assistant import CodingAgent, ProjectManager
from donatello.providers import ModelResponse


class StubProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.messages = []

    def complete(self, messages, json_response=False):
        self.messages.append(list(messages))
        return ModelResponse(next(self.responses), "stub", 0.01)


def approver(*answers, auto=False):
    lines = iter(answer + "\n" for answer in answers)
    output = io.StringIO()
    return Approver(auto=auto, input_fn=lambda: next(lines, ""), output=output), output


def change(path, content, reason="because"):
    return json.dumps({"summary": "s", "files": [{"path": path, "content": content, "reason": reason}]})


TASKS = {"tasks": [{"title": "Add module", "description": "Create app.py"}]}


class ApproverTests(unittest.TestCase):
    def test_yes_approves(self):
        review, _ = approver("y")
        self.assertIsNone(review.review("h", "b"))

    def test_text_is_feedback(self):
        review, _ = approver("use a different name")
        self.assertEqual(review.review("h", "b"), "use a different name")

    def test_auto_response_approves_later_reviews_without_prompting(self):
        review, _ = approver("--auto")
        self.assertIsNone(review.review("h", "b"))
        self.assertIsNone(review.review("h", "b"))

    def test_auto_option_never_prompts(self):
        review, output = approver(auto=True)
        self.assertIsNone(review.review("h", "b"))
        self.assertEqual(output.getvalue(), "")

    def test_no_then_blank_cancels(self):
        review, _ = approver("n", "")
        with self.assertRaises(ApprovalCancelled):
            review.review("h", "b")

    def test_no_then_feedback(self):
        review, _ = approver("no", "rename it")
        self.assertEqual(review.review("h", "b"), "rename it")

    def test_end_of_input_cancels(self):
        review, _ = approver()
        with self.assertRaises(ApprovalCancelled):
            review.review("h", "b")


class ApprovalFlowTests(unittest.TestCase):
    def test_plan_is_revised_from_feedback(self):
        provider = StubProvider(
            [
                json.dumps({"tasks": [{"title": "One", "description": "first"}]}),
                json.dumps({"tasks": [{"title": "Two", "description": "second"}]}),
            ]
        )
        review, _ = approver("make it two", "y")
        plan = ProjectManager(provider).plan("request", review)
        self.assertEqual(plan["tasks"][0]["title"], "Two")
        self.assertIn("make it two", provider.messages[1][-1]["content"])

    def test_nothing_written_until_approved_and_revision_is_written(self):
        provider = StubProvider([change("old.py", "a = 1\n"), change("new.py", "b = 2\n")])
        review, output = approver("name it new.py", "y")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            result = CodingAgent(provider, approver=review).execute_plan(TASKS, root)
            self.assertFalse((root / "old.py").exists())
            self.assertEqual((root / "new.py").read_text(), "b = 2\n")
            self.assertEqual(result[0]["files"], ["new.py"])
            shown = output.getvalue()
            self.assertIn(f"CREATE new file: {root / 'old.py'}", shown)
            self.assertIn("a = 1", shown)
            self.assertIn("Why: because", shown)

    def test_cancel_writes_nothing(self):
        provider = StubProvider([change("app.py", "x = 1\n")])
        review, _ = approver("n", "")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ApprovalCancelled):
                CodingAgent(provider, approver=review).execute_plan(TASKS, root)
            self.assertFalse((root / "app.py").exists())


if __name__ == "__main__":
    unittest.main()
