"""Enforce the maintainer's conventional runnable-example entry point."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

EXAMPLES_ROOT = Path(__file__).resolve().parents[1].joinpath('examples')
EXAMPLE_FILES = tuple(sorted(EXAMPLES_ROOT.glob('*.py')))


def _is_local_test_main_call(node: ast.stmt) -> bool:
    """Return whether a main-guard statement calls the conventional dispatcher."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    call = node.value
    if not isinstance(call.func, ast.Name) or call.func.id != 'run_local_test':
        return False
    return any(
        keyword.arg == 'local_test'
        and isinstance(keyword.value, ast.Attribute)
        and isinstance(keyword.value.value, ast.Name)
        and keyword.value.value.id == 'LocalTests'
        for keyword in call.keywords
    )


@pytest.mark.parametrize('example_path', EXAMPLE_FILES, ids=lambda path: path.name)
def test_example_uses_local_tests_dispatcher(example_path: Path) -> None:
    """Every tracked Python example uses LocalTests and run_local_test."""
    module = ast.parse(example_path.read_text(encoding='utf-8'), filename=str(example_path))
    class_names = {node.name for node in module.body if isinstance(node, ast.ClassDef)}
    function_names = {node.name for node in module.body if isinstance(node, ast.FunctionDef)}

    assert 'LocalTests' in class_names
    assert 'run_local_test' in function_names

    main_guards = [
        node
        for node in module.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == '__name__'
    ]
    assert len(main_guards) == 1
    assert len(main_guards[0].body) == 1
    assert _is_local_test_main_call(main_guards[0].body[0])
