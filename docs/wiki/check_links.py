#!/usr/bin/env python3
"""Wiki 自检：内部链接、锚点、表格列数、代码围栏，以及统计数字重算。

用法：
    python docs/wiki/check_links.py
    python docs/wiki/check_links.py --stats
    python docs/wiki/check_links.py --root .        # 指定仓库根

退出码：0 全部通过；1 存在问题。
零依赖，只用标准库。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

WIKI_DIR = Path(__file__).resolve().parent
REPO_ROOT = WIKI_DIR.parent.parent

SKIP_DIRS = {"_v1"}


# ---------------------------------------------------------------- 锚点计算


def slugify(heading: str) -> str:
    """按 GitHub 的规则把标题转成锚点。

    去反引号/加粗/链接语法，只保留字母数字、连字符、下划线与空白（含 CJK），
    空白转连字符。
    """
    text = heading.strip()
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    kept = []
    for ch in text.lower():
        if ch.isalnum() or ch in "-_" or ch.isspace():
            kept.append(ch)
    return re.sub(r"\s+", "-", "".join(kept)).strip("-")


def collect_anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    anchors: set[str] = set()
    seen: Counter[str] = Counter()
    for match in re.finditer(r"^(#{1,6})\s+(.*)$", text, re.M):
        base = slugify(match.group(2))
        if base in seen:
            seen[base] += 1
            anchors.add(f"{base}-{seen[base]}")
        else:
            seen[base] = 0
            anchors.add(base)
    return anchors


# ---------------------------------------------------------------- 各类检查


def _iter_link_targets(text: str):
    """只扫描反引号之外的行内链接，避免把文档里的语法示例当成真链接。"""
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            continue
        for segment in re.split(r"`[^`]*`", line):
            yield from re.finditer(r"\]\(([^)]+)\)", segment)


def check_links(files: list[Path], anchors: dict[str, set[str]]) -> list[str]:
    problems: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in _iter_link_targets(text):
            link = match.group(1).strip()
            if link.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target, _, anchor = link.partition("#")
            target = target.split("?")[0]
            if target:
                resolved = (path.parent / target).resolve()
                if not resolved.exists():
                    problems.append(f"{path.name}: 链接目标不存在 -> {link}")
                    continue
            else:
                resolved = path
            if anchor:
                name = Path(resolved).name
                if name in anchors and anchor not in anchors[name]:
                    problems.append(f"{path.name}: 锚点不存在 -> {link}")
    return problems


def check_tables(files: list[Path]) -> list[str]:
    problems: list[str] = []
    for path in files:
        lines = path.read_text(encoding="utf-8").split("\n")
        prev = None
        in_fence = False
        for idx, line in enumerate(lines, 1):
            if line.strip().startswith("```"):
                in_fence = not in_fence
                prev = None
                continue
            if in_fence:
                continue
            stripped = line.strip()
            if stripped.startswith("|"):
                count = len(re.findall(r"(?<!\\)\|", stripped))
                if prev is not None and count != prev:
                    problems.append(
                        f"{path.name}:{idx}: 表格列数 {count} != {prev} -> {stripped[:60]}"
                    )
                prev = count
            else:
                prev = None
    return problems


def check_fences(files: list[Path]) -> list[str]:
    problems: list[str] = []
    for path in files:
        count = sum(
            1
            for line in path.read_text(encoding="utf-8").split("\n")
            if line.strip().startswith("```")
        )
        if count % 2:
            problems.append(f"{path.name}: 代码围栏未闭合（``` 出现 {count} 次）")
    return problems


# ---------------------------------------------------------------- 统计重算


def _count_endpoints(paths: list[Path]) -> int:
    """用 ast 数路由装饰器，避免多行装饰器或字符串里的同名文本被误计。"""
    import ast

    total = 0
    for path in paths:
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if (
                    isinstance(deco, ast.Call)
                    and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr in {"get", "post", "put", "delete", "patch", "websocket"}
                ):
                    total += 1
    return total


def compute_stats(root: Path) -> dict[str, int]:
    src = root / "src" / "novelvideo"
    stats: dict[str, int] = {}
    py_files = [p for p in src.rglob("*.py")]
    stats["后端 .py 文件"] = len(py_files)
    # 与 `wc -l` 对齐：数换行符，而不是 split("\n") 的长度
    # （后者会给每个以换行结尾的文件多算一行，453 个文件就是 +453）
    stats["后端代码行"] = sum(
        p.read_text(encoding="utf-8", errors="ignore").count("\n") for p in py_files
    )
    stats["后端包目录"] = len({p.parent for p in py_files})
    stats["路由模块"] = len(list((src / "api" / "routes").glob("*.py")))
    stats["runner 模块"] = len(list((src / "task_backend" / "runners").glob("*.py")))

    stats["HTTP 端点"] = _count_endpoints(
        list((src / "api" / "routes").glob("*.py")) + [src / "verification" / "routes.py"]
    )

    task_types = set()
    for p in src.rglob("*.py"):
        task_types.update(
            re.findall(
                r'register_project_task_runner\(\s*"([a-z0-9_.-]+)"',
                p.read_text(encoding="utf-8", errors="ignore"),
            )
        )
    stats["任务类型"] = len(task_types)

    tables = set()
    for p in src.rglob("*.py"):
        tables.update(
            re.findall(
                r"CREATE TABLE IF NOT EXISTS ([A-Za-z0-9_]+)",
                p.read_text(encoding="utf-8", errors="ignore"),
            )
        )
    stats["SQLite 表"] = len(tables)

    fe = root / "frontend" / "src"
    if fe.exists():
        stats["前端 TS/TSX"] = len([p for p in fe.rglob("*") if p.suffix in {".ts", ".tsx"}])
    tests = root / "tests"
    if tests.exists():
        stats["测试 .py"] = len(list(tests.rglob("*.py")))
    return stats


def print_stats(root: Path) -> None:
    print(f"仓库根：{root}")
    for key, value in compute_stats(root).items():
        print(f"  {key:18s} {value}")
    print("\n提示：把这些数字与 README §5、00 §1 对照；不一致就更新文档。")


# ---------------------------------------------------------------- 入口


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wiki 自检")
    parser.add_argument("--stats", action="store_true", help="从源码重算统计数字")
    parser.add_argument("--root", default=str(REPO_ROOT), help="仓库根目录")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if args.stats:
        print_stats(root)
        return 0

    files = [
        p
        for p in sorted(WIKI_DIR.rglob("*.md"))
        if not any(part in SKIP_DIRS for part in p.relative_to(WIKI_DIR).parts)
    ]
    if not files:
        print("未找到 Markdown 文件", file=sys.stderr)
        return 1

    anchors = {p.name: collect_anchors(p) for p in files}
    problems = check_links(files, anchors) + check_tables(files) + check_fences(files)

    print(f"检查 {len(files)} 个 Markdown 文件")
    if problems:
        print(f"发现 {len(problems)} 个问题：")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("全部通过：链接、锚点、表格、代码围栏")
    return 0


if __name__ == "__main__":
    sys.exit(main())
