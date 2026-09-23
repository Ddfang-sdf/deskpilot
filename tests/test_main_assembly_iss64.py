"""ISS-0064 main() 装配拆分形态钉(S0 基线钉,S1~S6 随步收紧阈值)。

层级:形态(ast 结构直读,无执行)。
入口(出处):deskpilot/main.py main() 函数体与模块级接缝符号。
断言出处:ast 节点行号/符号存在性直出。

用途:①main() 行数只减不增(S0 阈值=现状 300,S6 收紧至 ≤60,批准②);
②既有 monkeypatch 接缝符号存在性钉——段函数留在 main.py 内、符号
不得改名(方案 §0 接缝清单:拆出模块或改名即钉碎,防拆分事故)。
"""

from __future__ import annotations

import ast
from pathlib import Path

MAIN_PY = Path(__file__).resolve().parent.parent / "deskpilot" / "main.py"

# 行数阈值(随步收紧;S0=现状,S6 终值 ≤60,批准②)
MAIN_MAX_LINES = 300

# 既有钉依赖的模块级接缝(方案 §0 实证清单;存在即钉,防移出/改名)
SEAM_SYMBOLS = (
    "_find_policy_path", "probe_daemon", "_start_estop_listeners",
    "serve", "Executor", "_corner_loop", "_hotkey_loop", "_DPI_MODE",
    "policy_sha256_audit", "local_policy_sha256_audit",
    "_start_policy_watch", "_run_migrate_policy", "_open_manager_for",
    "_warm_caches_with_audit", "_build_ocr_engine", "_start_janitor",
    "os",                                   # test_tray_iss12e 守门
)


def _tree() -> ast.Module:
    return ast.parse(MAIN_PY.read_text(encoding="utf-8"))


def _main_fn(tree: ast.Module) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("main() 函数不存在")


class TestMainAssemblyShape:
    """S0 形态钉:行数只减不增 + 接缝符号存在性。"""

    def test_s0_main_lines_ceiling(self):
        """S0(形态):main() 行数 ≤ 阈值(只减不增;S6 收紧至 ≤60)。
        断言:ast end_lineno-lineno 直出。"""
        fn = _main_fn(_tree())
        lines = fn.end_lineno - fn.lineno + 1
        assert lines <= MAIN_MAX_LINES, \
            f"main() {lines} 行超阈值 {MAIN_MAX_LINES}(只减不增,ast 直出)"

    def test_s0_seam_symbols_present(self):
        """S0(形态):既有 monkeypatch 接缝符号在 main.py 模块级存在
        (段函数不出 main.py、符号不改名——拆出即钉碎)。
        断言:模块级赋值/函数定义/导入符号集合直出。"""
        tree = _tree()
        names: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(
                    node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, ast.ImportFrom):
                names.update(a.asname or a.name for a in node.names)
            elif isinstance(node, ast.Import):
                names.update(a.asname or a.name.split(".")[0]
                             for a in node.names)
        missing = [s for s in SEAM_SYMBOLS if s not in names]
        assert missing == [], \
            f"接缝符号缺失(拆分移出 main.py 或改名?钉碎风险): {missing}"
