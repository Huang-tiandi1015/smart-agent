"""「打开应用」工具测试：按名称解析、计划明细、启动调用、规则回退。"""
from __future__ import annotations

import pytest

from server.app.agents import planner
from server.app.agents.tools import launch_app
from server.app.agents.tools.base import RiskLevel
from server.app.agents.tools.launch_app import LaunchAppTool


@pytest.fixture(autouse=True)
def _clear_resolve_cache():
    """每个用例前后清空解析缓存，避免跨用例的路径污染。"""
    launch_app._RESOLVE_CACHE.clear()
    yield
    launch_app._RESOLVE_CACHE.clear()


def _make_root(tmp_path, files: dict[str, str]) -> object:
    """在 tmp 下构造假软件目录，files 为 {相对路径: 内容}。"""
    root = tmp_path / "Programs"
    for rel, content in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    return root


def test_resolve_exact_exe(tmp_path):
    root = _make_root(tmp_path, {"Steam/steam.exe": ""})
    assert launch_app.resolve_app("steam", roots=[root]) == str(root / "Steam" / "steam.exe")


def test_resolve_case_insensitive(tmp_path):
    root = _make_root(tmp_path, {"Steam/steam.exe": ""})
    assert launch_app.resolve_app("Steam", roots=[root]) == str(root / "Steam" / "steam.exe")


def test_resolve_lnk_preferred_over_substring(tmp_path):
    root = _make_root(tmp_path, {"Steam/steam.exe": "", "Google Chrome.lnk": ""})
    # 词级精确匹配快捷方式，优于子串匹配的 steam.exe
    assert launch_app.resolve_app("google chrome", roots=[root]).endswith("Google Chrome.lnk")


def test_resolve_partial_name(tmp_path):
    root = _make_root(tmp_path, {"Steam/Steam Client.lnk": ""})
    # 无精确匹配时退化为子串匹配
    assert launch_app.resolve_app("steam", roots=[root]).endswith("Steam Client.lnk")


def test_resolve_not_found_raises(tmp_path):
    root = _make_root(tmp_path, {"Steam/steam.exe": ""})
    with pytest.raises(ValueError, match="未找到软件"):
        launch_app.resolve_app("不存在的软件xyz", roots=[root])


def test_resolve_empty_name_raises(tmp_path):
    root = _make_root(tmp_path, {})
    with pytest.raises(ValueError, match="未指定"):
        launch_app.resolve_app("  ", roots=[root])


def test_plan_sensitive_and_shows_target(tmp_path, monkeypatch):
    root = _make_root(tmp_path, {"Steam/steam.exe": ""})
    monkeypatch.setattr(launch_app, "_default_search_roots", lambda: [root])
    action = LaunchAppTool().plan({"app": "steam"})
    assert action.risk == RiskLevel.SENSITIVE
    assert not action.noop
    assert "steam" in action.summary
    assert "steam.exe" in action.details[0]


def test_plan_not_found_raises(tmp_path, monkeypatch):
    root = _make_root(tmp_path, {"Steam/steam.exe": ""})
    monkeypatch.setattr(launch_app, "_default_search_roots", lambda: [root])
    with pytest.raises(ValueError, match="未找到软件"):
        LaunchAppTool().plan({"app": "nothere"})


def test_run_launches_resolved_target(tmp_path, monkeypatch):
    root = _make_root(tmp_path, {"Steam/steam.exe": ""})
    monkeypatch.setattr(launch_app, "_default_search_roots", lambda: [root])
    launched: list[str] = []
    monkeypatch.setattr(launch_app, "_launch", lambda t: launched.append(t))
    res = LaunchAppTool().run({"app": "steam"})
    assert res.ok
    assert launched == [str(root / "Steam" / "steam.exe")]
    assert res.data["target"] == launched[0]


def test_run_not_found_fails(tmp_path, monkeypatch):
    root = _make_root(tmp_path, {"Steam/steam.exe": ""})
    monkeypatch.setattr(launch_app, "_default_search_roots", lambda: [root])
    res = LaunchAppTool().run({"app": "nothere"})
    assert not res.ok
    assert "未找到软件" in res.message


def test_run_missing_arg_fails():
    res = LaunchAppTool().run({})
    assert not res.ok
    assert "未指定" in res.message


def test_run_launch_error_reported(tmp_path, monkeypatch):
    root = _make_root(tmp_path, {"Steam/steam.exe": ""})
    monkeypatch.setattr(launch_app, "_default_search_roots", lambda: [root])

    def boom(_target: str) -> None:
        raise OSError("启动失败")

    monkeypatch.setattr(launch_app, "_launch", boom)
    res = LaunchAppTool().run({"app": "steam"})
    assert not res.ok
    assert "启动失败" in res.message


def test_rules_open_prefix():
    plan = planner.rules_plan("打开steam")
    assert plan.tool_name == "launch_app"
    assert plan.args == {"app": "steam"}


def test_rules_open_suffix():
    plan = planner.rules_plan("steam打开")
    assert plan.tool_name == "launch_app"
    assert plan.args == {"app": "steam"}


def test_rules_launch():
    plan = planner.rules_plan("启动 微信")
    assert plan.tool_name == "launch_app"
    assert plan.args == {"app": "微信"}


def test_rules_open_ambiguous_long_sentence_ignored():
    # 长句中的「打开」不匹配规则（交给 LLM），避免截取到无关文字
    plan = planner.rules_plan("帮我打开一下steam")
    assert plan.tool_name is None


def test_rules_help_lists_open():
    plan = planner.rules_plan("帮助")
    assert "打开 <软件名>" in plan.reply
