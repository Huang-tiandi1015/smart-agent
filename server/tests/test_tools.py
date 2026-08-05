"""整理工具行为测试：分类归档、重名加序号、空目录 noop。"""
from __future__ import annotations

from server.app.agents.tools.base import RiskLevel
from server.app.agents.tools.organize_desktop import OrganizeDesktopTool


def test_organize_moves_by_category(tmp_path):
    tool = OrganizeDesktopTool()
    d = tmp_path / "desk"
    d.mkdir()
    (d / "a.txt").write_text("hi")
    (d / "b.png").write_bytes(b"\x89PNG\r\n")

    action = tool.plan({"directory": str(d)})
    assert not action.noop
    assert action.risk == RiskLevel.SENSITIVE

    res = tool.run({"directory": str(d)})
    assert res.ok
    assert res.data["count"] == 2
    assert (d / "文档" / "a.txt").exists()
    assert (d / "图片" / "b.png").exists()


def test_duplicate_name_gets_suffix(tmp_path):
    tool = OrganizeDesktopTool()
    d = tmp_path / "desk"
    d.mkdir()
    (d / "a.txt").write_text("to-move")
    (d / "文档").mkdir()
    (d / "文档" / "a.txt").write_text("occupied")  # 目标已存在同名文件

    res = tool.run({"directory": str(d)})
    assert res.ok
    assert (d / "文档" / "a.txt").read_text() == "occupied"  # 原文件不动
    assert (d / "文档" / "a (1).txt").exists()  # 新文件加序号


def test_empty_dir_noop(tmp_path):
    tool = OrganizeDesktopTool()
    d = tmp_path / "empty"
    d.mkdir()

    action = tool.plan({"directory": str(d)})
    assert action.noop

    res = tool.run({"directory": str(d)})
    assert res.ok
    assert res.data["count"] == 0


def test_nonexistent_dir_fails(tmp_path):
    tool = OrganizeDesktopTool()
    res = tool.run({"directory": str(tmp_path / "nope")})
    assert not res.ok
    assert "目录不存在" in res.message
