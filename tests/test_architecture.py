import tempfile
import unittest
from pathlib import Path

from donatello import architecture


class ArchitectureDocumentTests(unittest.TestCase):
    def test_find_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(architecture.find(Path(temporary)))

    def test_find_locates_canonical_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / architecture.FILENAME).write_text("# Architecture\n")
            self.assertEqual(architecture.find(root), root / architecture.FILENAME)

    def test_find_locates_alternate_location(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            (root / "docs" / "ARCHITECTURE.md").write_text("# Architecture\n")
            self.assertEqual(architecture.find(root), root / "docs" / "ARCHITECTURE.md")

    def test_load_returns_canonical_path_and_none_when_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, content = architecture.load(root)
            self.assertEqual(path, root / architecture.FILENAME)
            self.assertIsNone(content)

    def test_load_returns_existing_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / architecture.FILENAME).write_text("# Architecture\n\nExisting.\n")
            path, content = architecture.load(root)
            self.assertEqual(path, root / architecture.FILENAME)
            self.assertEqual(content, "# Architecture\n\nExisting.\n")

    def test_context_block_offers_template_when_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            block = architecture.context_block(Path(temporary))
            self.assertIn("No system architecture", block)
            self.assertIn(architecture.FILENAME, block)
            self.assertIn("## Components", block)

    def test_context_block_includes_existing_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / architecture.FILENAME).write_text("# Architecture\n\nExisting.\n")
            block = architecture.context_block(root)
            self.assertIn("Existing.", block)
            self.assertIn("Update only the sections this task affects", block)


if __name__ == "__main__":
    unittest.main()
