import tempfile
import unittest
from pathlib import Path

from donatello.cli import _parser, _resolve_request


def _parsed(args):
    return _parser().parse_args(args)


class ResolveRequestTests(unittest.TestCase):
    def test_uses_positional_request(self):
        args = _parsed(["plan", "Add validation"])
        self.assertEqual(_resolve_request(args), "Add validation")

    def test_reads_request_from_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.txt"
            path.write_text("Add input validation to the endpoint\n")
            args = _parsed(["plan", "--read", str(path)])
            self.assertIsNone(args.request)
            self.assertEqual(_resolve_request(args), "Add input validation to the endpoint")

    def test_strips_surrounding_whitespace_from_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.txt"
            path.write_text("\n\n  Do the thing  \n\n")
            args = _parsed(["run", "--read", str(path)])
            self.assertEqual(_resolve_request(args), "Do the thing")

    def test_rejects_both_positional_and_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.txt"
            path.write_text("content")
            args = _parsed(["plan", "Add validation", "--read", str(path)])
            with self.assertRaises(ValueError):
                _resolve_request(args)

    def test_rejects_neither_positional_nor_read(self):
        args = _parsed(["plan"])
        with self.assertRaises(ValueError):
            _resolve_request(args)

    def test_rejects_blank_positional_request(self):
        args = _parsed(["plan", "   "])
        with self.assertRaises(ValueError):
            _resolve_request(args)

    def test_rejects_empty_request_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.txt"
            path.write_text("   \n")
            args = _parsed(["plan", "--read", str(path)])
            with self.assertRaises(ValueError):
                _resolve_request(args)

    def test_rejects_missing_request_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "missing.txt"
            args = _parsed(["plan", "--read", str(path)])
            with self.assertRaises(ValueError):
                _resolve_request(args)


if __name__ == "__main__":
    unittest.main()
