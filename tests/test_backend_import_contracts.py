"""Detect broken internal Django module imports without needing Django at runtime.

Python compilation alone does not validate `from .module import symbol`.
This static contract check catches missing exported names before the
expensive disposable Docker/Django smoke-test stage.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "backend" / "dictionary"


def defined_names(source: Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0]
                         for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name
                         for alias in node.names)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


class BackendImportContracts(unittest.TestCase):
    def test_relative_imports_from_dictionary_modules_exist(self):
        for source in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8"),
                             filename=str(source))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level != 1:
                    continue
                if not node.module:
                    continue
                target = PACKAGE / (node.module + ".py")
                if not target.is_file():
                    # External or package submodule; not part of this checker.
                    continue
                exported = defined_names(target)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    with self.subTest(importer=source.name, module=node.module,
                                      name=alias.name):
                        self.assertIn(
                            alias.name, exported,
                            f"{source.name} imports {alias.name} from "
                            f"{node.module}.py, but the name is not defined there",
                        )


if __name__ == "__main__":
    unittest.main()
