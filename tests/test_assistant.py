import json
import tempfile
import unittest
from pathlib import Path

from donatello.assistant import (
    AssistantError,
    CodingAgent,
    ProjectManager,
    _apply_files,
    _validate_tests,
)
from donatello.providers import ModelResponse


class StubProvider:
    def __init__(self, responses):
        self.responses = iter(responses)

    def complete(self, messages, json_response=False):
        return ModelResponse(next(self.responses), "stub", 0.01)


class ProjectManagerTests(unittest.TestCase):
    def test_parses_ordered_tasks(self):
        provider = StubProvider(['{"tasks":[{"title":"Add test","description":"Cover input"}]}'])
        self.assertEqual(
            ProjectManager(provider).plan("Add validation"),
            {"tasks": [{"title": "Add test", "description": "Cover input"}]},
        )

    def test_rejects_empty_plan(self):
        with self.assertRaises(AssistantError):
            ProjectManager(StubProvider(['{"tasks":[]}'])).plan("Do work")


class CodingAgentTests(unittest.TestCase):
    def test_applies_changes_and_runs_unittest(self):
        response = json.dumps(
            {
                "summary": "Added a module",
                "files": [
                    {"path": "app.py", "content": "value = 1\n"},
                    {
                        "path": "test_app.py",
                        "content": (
                            "import unittest\n"
                            "from app import value\n"
                            "class AppTest(unittest.TestCase):\n"
                            "    def test_value(self):\n"
                            "        self.assertEqual(value, 1)\n"
                        ),
                    },
                ],
                "tests": [["python", "-m", "unittest"]],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = CodingAgent(StubProvider([response])).execute_plan(
                {"tasks": [{"title": "Add module", "description": "Create app.py"}]},
                root,
            )
            self.assertEqual((root / "app.py").read_text(), "value = 1\n")
            self.assertEqual(result[0]["files"], ["app.py", "test_app.py"])
            self.assertTrue(result[0]["tests"][0]["passed"])

    def test_rejects_path_outside_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(AssistantError):
                _apply_files(root, [{"path": "../outside.py", "content": "bad"}])

    def test_rejects_untrusted_test_commands(self):
        with self.assertRaises(AssistantError):
            _validate_tests([["python", "-c", "print('not a test')"]])

    def test_validates_test_commands_before_writing_files(self):
        response = json.dumps(
            {
                "files": [{"path": "app.py", "content": "value = 1\n"}],
                "tests": [["python", "-c", "not allowed"]],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(AssistantError):
                CodingAgent(StubProvider([response])).execute_plan(
                    {"tasks": [{"title": "Add module", "description": "Create app.py"}]},
                    root,
                )
            self.assertFalse((root / "app.py").exists())

    def test_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            (root / "linked").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(AssistantError):
                _apply_files(root, [{"path": "linked/file.py", "content": "bad"}])


if __name__ == "__main__":
    unittest.main()
