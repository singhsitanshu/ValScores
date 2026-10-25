"""Enforce the layer boundaries documented in docs/ARCHITECTURE.md."""

import ast
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPOSITORY_ROOT / "valoreal"
APP = REPOSITORY_ROOT / "ValScores"

# layer -> layers it may import (besides itself). Anything not listed is forbidden.
ALLOWED_LAYER_IMPORTS = {
    "domain": set(),
    "scraper": {"domain"},
    "database": {"domain"},
    "services": {"domain", "scraper", "database"},
    "api": {"domain", "database", "services"},
}


def module_name(path):
    relative = path.relative_to(REPOSITORY_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def resolve_import(module, node, is_package):
    """Absolute valoreal module names imported by an Import/ImportFrom node."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level == 0:
        base = node.module or ""
    else:
        package_parts = module.split(".") if is_package else module.split(".")[:-1]
        package_parts = package_parts[: len(package_parts) - (node.level - 1)]
        base = ".".join(package_parts + ([node.module] if node.module else []))
    # "from . import connection" names a submodule; "from .x import y" names x,
    # or x.y when y is itself a submodule (callers drop names that are not modules).
    submodules = [f"{base}.{alias.name}" for alias in node.names]
    return submodules if node.module is None else [base, *submodules]


def backend_imports(top_level_only=False):
    """{module: set of imported valoreal modules} for every backend module."""
    graph = {}
    for path in PACKAGE.rglob("*.py"):
        module = module_name(path)
        tree = ast.parse(path.read_text())
        nodes = tree.body if top_level_only else ast.walk(tree)
        imports = set()
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for name in resolve_import(module, node, path.name == "__init__.py"):
                    if name == "valoreal" or name.startswith("valoreal."):
                        imports.add(name)
        graph[module] = imports
    return graph


def layer(module):
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else None


class BackendStructureTests(unittest.TestCase):
    def test_every_module_belongs_to_a_layer(self):
        for module in backend_imports():
            if module == "valoreal":
                continue
            with self.subTest(module=module):
                self.assertIn(layer(module), ALLOWED_LAYER_IMPORTS)

    def test_imports_follow_the_layer_direction(self):
        violations = []
        for module, imports in backend_imports().items():
            source_layer = layer(module)
            for imported in imports:
                target_layer = layer(imported)
                if target_layer in (None, source_layer):
                    continue
                if target_layer not in ALLOWED_LAYER_IMPORTS[source_layer]:
                    violations.append(f"{module} -> {imported}")
        self.assertEqual(violations, [])

    def test_module_level_imports_have_no_cycles(self):
        graph = backend_imports(top_level_only=True)
        modules = set(graph)

        def resolve(name):
            # "from valoreal.database import connection" may name a module or a package.
            while name and name not in modules:
                name = name.rpartition(".")[0]
            return name

        edges = {
            module: {resolve(name) for name in imports} - {module, "valoreal", ""}
            for module, imports in graph.items()
        }

        visiting, visited, cycles = set(), set(), []

        def visit(module, stack):
            visiting.add(module)
            for target in sorted(edges.get(module, ())):
                if target in visiting:
                    cycles.append(" -> ".join(stack[stack.index(target):] + [target]))
                elif target not in visited:
                    visit(target, stack + [target])
            visiting.discard(module)
            visited.add(module)

        for module in sorted(edges):
            if module not in visited:
                visit(module, [module])
        self.assertEqual(cycles, [])

    def test_every_module_imports_cleanly_in_a_fresh_interpreter(self):
        modules = sorted(m for m in backend_imports() if not m.endswith("__main__"))
        script = "import importlib\n" + "".join(
            f"importlib.import_module({module!r})\n" for module in modules
        )
        environment = {**os.environ, "DATABASE_URL": "sqlite://", "PYTHONDONTWRITEBYTECODE": "1"}
        environment.pop("TEST_DATABASE_URL", None)
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_parsers_run_without_database_configuration(self):
        script = """
import sys
from pathlib import Path
from valoreal.scraper import VlrScraper

fixtures = Path("tests/fixtures")
scraper = VlrScraper()
assert scraper.parse_match_list((fixtures / "vlr_list_upcoming.html").read_text())
assert scraper.parse_match_details((fixtures / "vlr_completed_multi_map.html").read_text())["games"]
loaded = sorted(name for name in sys.modules if name.startswith(("valoreal.database", "sqlalchemy")))
assert not loaded, loaded
"""
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"DATABASE_URL", "TEST_DATABASE_URL"}
        }
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPOSITORY_ROOT,
            env={**environment, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class AppStructureTests(unittest.TestCase):
    HTTP_CONSTRUCTION = re.compile(r"\b(URLRequest|URLSession|URLComponents|URLQueryItem|dataTask)\b")
    TYPE_DECLARATION = re.compile(
        r"^\s*(?:@\w+\s+)*(?:(?:private|fileprivate|internal|public|final)\s+)*"
        r"(?:struct|class|enum|actor|protocol)\s+(\w+)",
        re.MULTILINE,
    )

    def swift_files(self):
        return sorted(APP.rglob("*.swift"))

    def test_app_folder_contains_no_backend_files(self):
        stray = sorted(
            str(path.relative_to(REPOSITORY_ROOT))
            for path in APP.rglob("*")
            if path.suffix in {".py", ".pyc", ".db"}
        )
        self.assertEqual(stray, [])

    def test_only_shared_networking_constructs_http_requests(self):
        networking = APP / "Shared" / "Networking"
        offenders = [
            str(path.relative_to(REPOSITORY_ROOT))
            for path in self.swift_files()
            if networking not in path.parents and self.HTTP_CONSTRUCTION.search(path.read_text())
        ]
        self.assertEqual(offenders, [])

    def test_swift_types_are_declared_once(self):
        declarations = {}
        for path in self.swift_files():
            for name in self.TYPE_DECLARATION.findall(path.read_text()):
                declarations.setdefault(name, []).append(str(path.relative_to(REPOSITORY_ROOT)))
        duplicates = {name: paths for name, paths in declarations.items() if len(paths) > 1}
        self.assertEqual(duplicates, {})


if __name__ == "__main__":
    unittest.main()
