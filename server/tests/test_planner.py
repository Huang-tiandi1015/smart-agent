"""规则规划器测试：帮助/显式路径/桌面/未知 路由。"""
from __future__ import annotations

from server.app.agents import planner


def test_help():
    r = planner.rules_plan("帮助")
    assert r.is_help
    assert "支持的指令" in r.reply


def test_explicit_path():
    r = planner.rules_plan("整理 D:\\work\\files")
    assert r.tool_name == "organize_desktop"
    assert r.args["directory"] == "D:\\work\\files"


def test_desktop_keyword():
    r = planner.rules_plan("整理桌面文件")
    assert r.tool_name == "organize_desktop"
    assert r.args["directory"] == planner.config.DESKTOP_DIR


def test_organize_keyword_without_path():
    r = planner.rules_plan("整理一下")
    assert r.tool_name is None  # 无路径、无桌面关键词 → 无法路由


def test_unknown():
    r = planner.rules_plan("随便说点什么")
    assert r.tool_name is None
    assert r.reply
