"""黑名单分类器测试：系统目录/盘符根目录拦截，普通路径放行。"""
from __future__ import annotations

from server.app.safety import classifier


class _DummyTool:
    name = "dummy"
    risk = "safe"


def test_blacklist_prefix():
    assert classifier.check_directory("C:\\Windows\\System32") is not None
    assert classifier.check_directory("c:\\program files\\app") is not None
    assert classifier.check_directory("C:\\ProgramData\\x") is not None


def test_drive_root_blocked():
    assert classifier.check_directory("D:\\") is not None
    assert classifier.check_directory("c:") is not None
    assert classifier.check_directory("E:/") is not None


def test_normal_path_allowed():
    assert classifier.check_directory("C:\\Users\\96066\\Desktop") is None
    assert classifier.check_directory("D:\\work\\files") is None


def test_empty_path_allowed():
    assert classifier.check_directory("") is None
    assert classifier.check_directory("   ") is None


def test_check_tool_blocks_path_arg():
    decision = classifier.check_tool(_DummyTool(), {"directory": "C:\\Windows"})
    assert not decision.allowed
    assert "目录命中黑名单前缀" in decision.reason
    assert "directory" in decision.reason


def test_check_tool_allows_safe_path():
    decision = classifier.check_tool(_DummyTool(), {"directory": "C:\\Users\\me\\Desktop"})
    assert decision.allowed
    assert decision.reason is None


def test_check_tool_ignores_non_path_args():
    decision = classifier.check_tool(_DummyTool(), {"mode": "type", "count": 3})
    assert decision.allowed
