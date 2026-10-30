"""包边界测试。

功能：验证新系统不依赖缠论或运行三个上游工程。
"""
import ast
from pathlib import Path


def test_backend_import_boundary():
    """功能：检查依赖方向；输入：后端源码AST；输出：无旧系统硬耦合。"""
    root = Path(__file__).resolve().parents[1] / "backend" / "etf_monitor"
    forbidden = {"Strategies", "DataAPI", "DataBasis", "monitor", "Resonance"}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            assert not any(module.split(".")[0] in forbidden for module in modules), path


def test_runtime_and_environment_are_ignored():
    """功能：保护运行数据边界；输入：系统gitignore；输出：环境缓存不提交。"""
    root = Path(__file__).resolve().parents[1]
    rules = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".venv/" in rules
    assert "runtime/" in rules
    assert "frontend/node_modules/" in rules
