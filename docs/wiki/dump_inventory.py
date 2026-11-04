#!/usr/bin/env python3
"""为 wiki 的逐文件参考生成两份原始数据（零依赖，仅 stdlib）。

用法：
    python docs/wiki/dump_inventory.py            # 默认扫描仓库 src/novelvideo
    python docs/wiki/dump_inventory.py --root .   # 指定仓库根

产出（都写在 docs/wiki/ 下，均可随时删掉重建）：
    .inventory.txt   按目录分组的逐文件清单：行数、docstring、
                     公开类/函数、包内 import、被谁 import
    .endpoints.txt   按路由模块分组的 HTTP 端点：方法、路径、handler、docstring

这两份文件是写 files/0x-*.md 与 06-HTTP-API参考.md 时的底稿。
写文档时用它们定位，不要把它们当成文档的一部分提交给读者。
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
from collections import defaultdict
from pathlib import Path

INVENTORY = ".inventory.txt"
ENDPOINTS = ".endpoints.txt"

SKIP_DIRS = {"__pycache__", ".venv", "node_modules", ".git", "dist", "build"}


# ---------------------------------------------------------------- 文件发现


def iter_py_files(base: Path):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(dirpath) / name


def loc_of(path: Path) -> int:
    """物理行数，与 `wc -l` 一致（数换行符）。

    不要用 len(text.split("\n"))：那会给每个以换行结尾的文件多算一行。
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return text.count("\n")


# ---------------------------------------------------------------- AST 提取


def parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return None


def public_defs(tree: ast.Module):
    """公开类与顶层函数名（单下划线开头视为私有）。"""
    classes, funcs = [], []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                funcs.append(node.name)
    return classes, funcs


def internal_imports(tree: ast.Module, package_root: str):
    """只保留包内 import，用来还原依赖边。"""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:  # 相对导入
                out.add("." * node.level + mod)
            elif mod.startswith(package_root):
                out.add(mod)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(package_root):
                    out.add(alias.name)
    return sorted(out)


def docstring_of(tree: ast.Module) -> str:
    raw = ast.get_docstring(tree) or ""
    return " ".join(raw.split())


# ---------------------------------------------------------------- 端点提取


def endpoints_of(path: Path, tree: ast.Module):
    """从装饰器里抽 HTTP 端点。支持 router.get("/x") 与 @app.post("/y", ...)。

    路径可能写成空字符串（路由用 APIRouter(prefix=...) 声明前缀），
    这种情况按空串输出，由读者结合同文件的 prefix 补全。
    """
    rows = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            method = dec.func.attr.upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "WEBSOCKET"}:
                continue
            route = ""
            if dec.args:
                first = dec.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    route = first.value
            status = ""
            for kw in dec.keywords:
                if kw.arg == "status_code" and isinstance(kw.value, ast.Constant):
                    status = str(kw.value.value)
            rows.append(
                {
                    "method": method,
                    "path": route,
                    "handler": node.name,
                    "status": status,
                    "doc": " ".join((ast.get_docstring(node) or "").split())[:100],
                }
            )
    return rows


def router_prefix(tree: ast.Module) -> str:
    """抓 APIRouter(prefix=...) / FastAPI(...)，用于给空路径补前缀。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"APIRouter", "FastAPI"}:
                for kw in node.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        return str(kw.value.value)
    return ""


# ---------------------------------------------------------------- 写出


def write_inventory(root: Path, pkg: Path, out: Path) -> tuple[int, int]:
    by_dir: dict[Path, list[Path]] = defaultdict(list)
    for f in iter_py_files(pkg):
        by_dir[f.parent].append(f)

    total_files = total_lines = 0
    lines: list[str] = [f"# inventory of {pkg}  (generated by dump_inventory.py)", ""]

    for directory in sorted(by_dir):
        rel = directory.relative_to(root)
        files = sorted(by_dir[directory])
        dir_loc = sum(loc_of(f) for f in files)
        total_files += len(files)
        total_lines += dir_loc
        lines.append(f"## {rel}  ({len(files)} files, {dir_loc} lines)")
        lines.append("")
        for f in files:
            n = loc_of(f)
            tree = parse(f)
            doc = docstring_of(tree) if tree else "<parse error>"
            classes, funcs = public_defs(tree) if tree else ([], [])
            imports = internal_imports(tree, "novelvideo") if tree else []
            lines.append(f"### {f.name}  {n} lines")
            if doc:
                lines.append(f"    doc: {doc[:300]}")
            if classes:
                lines.append(f"    classes: {', '.join(classes)}")
            if funcs:
                shown = funcs[:20]
                more = "" if len(funcs) <= 20 else f" ... +{len(funcs) - 20}"
                lines.append(f"    funcs: {', '.join(shown)}{more}")
            if imports:
                lines.append(f"    imports: {', '.join(imports[:12])}")
            lines.append("")
        lines.append("")

    lines.append(f"# TOTAL: {total_files} files, {total_lines} lines")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return total_files, total_lines


def write_endpoints(root: Path, pkg: Path, out: Path) -> int:
    lines = ["# HTTP endpoints (generated by dump_inventory.py)", ""]
    total = 0
    # 范围与 check_links.py --stats 及 06-HTTP-API参考.md 对齐：
    #   api/routes/*.py + verification/routes.py
    # 不含 api/app.py 的 3 条基础设施路由（/healthz 与两条 /static 挂载），
    # 它们不是业务 API，06 文档也不单列。
    scope = sorted((pkg / "api" / "routes").glob("*.py"))
    verif = pkg / "verification" / "routes.py"
    if verif.exists():
        scope.append(verif)
    for f in scope:
        tree = parse(f)
        if tree is None:
            continue
        rows = endpoints_of(f, tree)
        if not rows:
            continue
        prefix = router_prefix(tree)
        lines.append(f"## {f.relative_to(root)}  ({len(rows)} endpoints"
                     + (f", APIRouter prefix={prefix!r}" if prefix else "") + ")")
        lines.append("")
        for r in sorted(rows, key=lambda r: (r["path"], r["method"])):
            path = r["path"] or "<empty>"
            extra = f" [{r['status']}]" if r["status"] else ""
            doc = f"  -- {r['doc']}" if r["doc"] else ""
            lines.append(f"  {r['method']:7s} {path:60s} {r['handler']}{extra}{doc}")
        lines.append("")
        total += len(rows)
    lines.append(f"# TOTAL: {total} endpoints")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return total


# ---------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=None, help="仓库根，默认按脚本位置向上两级")
    args = ap.parse_args(argv)

    here = Path(__file__).resolve().parent
    root = Path(args.root).resolve() if args.root else here.parent.parent
    pkg = root / "src" / "novelvideo"
    if not pkg.is_dir():
        print(f"找不到 {pkg}；用 --root 指定仓库根", file=sys.stderr)
        return 2

    n_files, n_lines = write_inventory(root, pkg, here / INVENTORY)
    n_eps = write_endpoints(root, pkg, here / ENDPOINTS)

    print(f"仓库根：{root}")
    print(f"  {INVENTORY:16s} {n_files} 个 .py，{n_lines} 行")
    print(f"  {ENDPOINTS:16s} {n_eps} 个端点")
    print("写文档时用这两份底稿定位；数字仍以 check_links.py --stats 为准。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
