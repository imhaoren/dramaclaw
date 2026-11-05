"""Build a machine-readable index of the repository (AST scan, no imports).

Writes ``project_index.json`` at the repository root: backend modules, public
classes/functions, API endpoints, task runners, frontend routes/features,
tests, docs and scripts. Companion human-readable map: ``INDEX.md``.

Usage: ``python scripts/build_project_index.py``
"""

from __future__ import annotations

import ast
import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "project_index.json"
SKIP_DIRS = {
    "__pycache__",
    "node_modules",
    "dist",
    ".venv",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
}


def parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        return None


def doc_line(node: ast.AST | None) -> str:
    doc = (ast.get_docstring(node) if node is not None else "") or ""
    for line in doc.splitlines():
        if line.strip():
            return line.strip()
    return ""


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def internal_imports(tree: ast.AST) -> list[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("novelvideo"):
                    names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("novelvideo"):
                names.add(node.module)
    return sorted(names)


def module_info(path: Path) -> dict[str, Any]:
    tree = parse(path)
    if tree is None:
        return {"path": rel(path), "doc": "", "error": "parse failed"}
    module = ".".join(path.relative_to(ROOT / "src").with_suffix("").parts)
    classes = []
    functions = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "bases": [ast.unparse(b) for b in node.bases],
                    "doc": doc_line(node),
                }
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                    "doc": doc_line(node),
                }
            )
    return {
        "path": rel(path),
        "module": module,
        "doc": doc_line(tree),
        "lines": len(path.read_text(encoding="utf-8").splitlines()),
        "classes": classes,
        "functions": functions,
        "imports": internal_imports(tree),
    }


def api_routes(path: Path) -> list[dict[str, Any]]:
    tree = parse(path)
    if tree is None:
        return []
    methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            if dec.func.attr not in methods:
                continue
            route = None
            if (
                dec.args
                and isinstance(dec.args[0], ast.Constant)
                and isinstance(dec.args[0].value, str)
            ):
                route = dec.args[0].value
            found.append(
                {
                    "method": dec.func.attr.upper(),
                    "path": route,
                    "handler": node.name,
                    "line": node.lineno,
                    "doc": doc_line(node),
                }
            )
    return sorted(found, key=lambda r: (r["path"] or "", r["method"]))


def registered_task_types(path: Path) -> list[str]:
    tree = parse(path)
    if tree is None:
        return []
    names = {"register_project_task_runner", "register_task_runner"}
    types: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if fname not in names:
            continue
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            types.add(node.args[0].value)
    return sorted(types)


def walk_files(base: Path, pattern: str | tuple[str, ...] | None = None) -> list[Path]:
    suffixes = (pattern,) if isinstance(pattern, str) else pattern
    files = []
    for p in base.rglob("*"):
        if p.is_dir() or any(part in SKIP_DIRS for part in p.parts):
            continue
        if suffixes and p.suffix not in suffixes:
            continue
        files.append(p)
    return sorted(files)


def dir_summary(base: Path, *, deep: bool = False, suffix: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        if child.is_dir():
            if child.name in SKIP_DIRS:
                continue
            files = walk_files(child, suffix) if deep else [p for p in child.iterdir() if p.is_file()]
            rows.append(
                {
                    "name": child.name,
                    "type": "dir",
                    "files": len(files),
                    "python": sum(1 for f in files if f.suffix == ".py"),
                    "doc": doc_line(parse(child / "__init__.py")) if (child / "__init__.py").exists() else "",
                }
            )
        elif suffix is None or child.suffix == suffix:
            tree = parse(child)
            rows.append(
                {
                    "name": child.name,
                    "type": "file",
                    "doc": doc_line(tree),
                    "lines": len(child.read_text(encoding="utf-8").splitlines()),
                }
            )
    return rows


def test_info(path: Path) -> dict[str, Any]:
    tree = parse(path)
    names: list[str] = []
    if tree is not None:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                names.append(node.name)
    return {"path": rel(path), "tests": names}


def build() -> dict[str, Any]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project", {})

    backend_root = ROOT / "src" / "novelvideo"
    modules = [module_info(p) for p in walk_files(backend_root, ".py")]

    packages = []
    for pkg in sorted(backend_root.iterdir()):
        if not pkg.is_dir() or pkg.name in SKIP_DIRS:
            continue
        init = pkg / "__init__.py"
        pkg_modules = [m for m in modules if m["path"].startswith(f"src/novelvideo/{pkg.name}/")]
        packages.append(
            {
                "name": pkg.name,
                "doc": doc_line(parse(init)) if init.exists() else "",
                "modules": len(pkg_modules),
                "lines": sum(m.get("lines", 0) for m in pkg_modules),
            }
        )

    routes_dir = backend_root / "api" / "routes"
    routes = {
        p.name: api_routes(p)
        for p in sorted(routes_dir.glob("*.py"))
        if p.name != "__init__.py"
    }

    runners_dir = backend_root / "task_backend" / "runners"
    runners = {}
    for p in sorted(runners_dir.glob("*.py")):
        if p.name == "__init__.py":
            continue
        runners[p.name] = {
            "doc": doc_line(parse(p)),
            "task_types": registered_task_types(p),
        }

    tests = [test_info(p) for p in sorted((ROOT / "tests").rglob("test_*.py"))]

    frontend_root = ROOT / "frontend" / "src"
    package_json = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    frontend = {
        "top_level": dir_summary(frontend_root, deep=True, suffix=(".ts", ".tsx", ".css")),
        "routes": [
            p.relative_to(frontend_root).as_posix()
            for p in sorted((frontend_root / "routes").rglob("*"))
            if p.is_file()
        ],
        "features": [
            {
                "name": d.name,
                "files": len(walk_files(d, (".ts", ".tsx", ".css", ".json"))),
                "tests": len([f for f in walk_files(d, (".ts", ".tsx")) if ".test." in f.name]),
            }
            for d in sorted((frontend_root / "features").iterdir())
            if d.is_dir()
        ],
    }

    docs = [rel(p) for p in sorted((ROOT / "docs").rglob("*.md"))]
    scripts = []
    for p in sorted((ROOT / "scripts").rglob("*")):
        if p.is_file() and p.suffix in {".py", ".sh", ".json"}:
            scripts.append({"path": rel(p), "doc": doc_line(parse(p)) if p.suffix == ".py" else ""})

    return {
        "schema": "dramaclaw-project-index@1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/build_project_index.py (AST scan, no runtime imports)",
        "project": {
            "name": project.get("name"),
            "version": project.get("version"),
            "description": project.get("description"),
            "python": project.get("requires-python"),
            "license": project.get("license"),
            "entrypoint": project.get("scripts", {}),
        },
        "layout": {
            "top_level": dir_summary(ROOT, suffix=".md"),
            "docs": docs,
            "scripts": scripts,
            "deploy": [rel(p) for p in walk_files(ROOT / "deploy")],
            "schemas": [rel(p) for p in walk_files(ROOT / "schemas")],
            "agent_kit": [rel(p) for p in walk_files(ROOT / "agent-kit")],
        },
        "backend": {"packages": packages, "modules": modules},
        "api": {
            "base_path": "/api/v1",
            "routes": routes,
            "endpoint_count": sum(len(v) for v in routes.values()),
        },
        "task_backend": {"runners": runners},
        "frontend": {
            "framework": {
                "react": package_json.get("dependencies", {}).get("react"),
                "router": package_json.get("dependencies", {}).get("@tanstack/react-router"),
                "vite": package_json.get("devDependencies", {}).get("vite"),
            },
            **frontend,
        },
        "tests": {"count": len(tests), "files": tests},
    }


def main() -> None:
    index = build()
    OUT.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")
    print(
        f"modules={len(index['backend']['modules'])} "
        f"endpoints={index['api']['endpoint_count']} "
        f"tests={index['tests']['count']}"
    )


if __name__ == "__main__":
    main()
