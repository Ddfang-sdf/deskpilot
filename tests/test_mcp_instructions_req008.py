"""REQ-008 钉测试族(TC-R8-01~09,测试设计 v0.1;验证通过才提交)。

层级:形态/单元(直读真源:i18n.yml/policy.yml/TOOL_SCHEMAS/build_server
直出,不经生产代码转发)。红态:访问器与注册键尚不存在。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from deskpilot import i18n, mcp_server

_KEY = "mcp.instructions"
_I18N_YML = Path(i18n.__file__).resolve().parent / "i18n.yml"
_POLICY_YML = Path(__file__).resolve().parent.parent / "policy.yml"


def _text() -> str:
    raw = yaml.safe_load(_I18N_YML.read_text(encoding="utf-8"))
    return str((raw.get("en") or {}).get(_KEY) or "")


def _ttl() -> int:
    raw = yaml.safe_load(_POLICY_YML.read_text(encoding="utf-8"))
    return int(raw["timeouts"]["approval_ttl"])


def _check_ttl(text: str, ttl: int) -> None:
    """TC-R8-04 核对函数(独立出来供变异守护轮复用)。"""
    m = re.search(r"about (\d+) seconds", text)
    assert m, "审批 TTL 声明缺席"
    assert int(m.group(1)) == ttl, \
        f"说明书 TTL={m.group(1)} 与 policy 真值 {ttl} 不符"
    m2 = re.search(r"exceed (\d+) seconds", text)
    assert m2 and int(m2.group(1)) >= ttl + 5, \
        "缺「外层预算须 >TTL+5」指引或数字失真"


class TestRegistration:
    def test_r8_01_registered(self):
        """TC-R8-01:i18n.yml en 位注册 mcp.instructions 且非空。"""
        assert _text().strip(), "mcp.instructions 未注册/为空"

    def test_r8_02_word_budget(self):
        """TC-R8-02:词数口径(ASCII 空白分词)≤500。"""
        n = len(_text().split())
        assert n <= 500, f"词数超预算(直出): {n}"


class TestTruthfulness:
    def test_r8_03_tool_names_real(self):
        """TC-R8-03:文本提及的 snake_case 工具名 ⊆ TOOL_SCHEMAS。"""
        names = set(re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b",
                               _text()))
        known = set(mcp_server.TOOL_SCHEMAS.keys())
        dangling = names - known
        assert not dangling, f"悬空工具名(直出): {dangling}"

    def test_r8_04_ttl_truth(self):
        """TC-R8-04:审批 TTL 数字 == policy.yml 真值;含 >TTL+5 预算指引。"""
        _check_ttl(_text(), _ttl())

    def test_r8_04_mutation_guard(self):
        """TC-R8-04 变异守护:TTL 改成 60,核对函数必须转红。"""
        with pytest.raises(AssertionError):
            _check_ttl(_text(), 60)

    def test_r8_05_client_neutral(self):
        """TC-R8-05:客户端名零出现(大小写不敏感)。"""
        low = _text().lower()
        for name in ("claude", "codex", "cursor", "gpt", "copilot",
                     "gemini"):
            assert name not in low, f"客户端名出现(直出): {name}"

    def test_r8_06_stale_sentence_gone(self):
        """TC-R8-06:旧「勿用本服务」零残留;新路由锚点在场;
        mcp_server 源码无内联长串。"""
        text = _text()
        assert "勿用本服务" not in text
        assert "browser_snapshot" in text
        src = Path(mcp_server.__file__).read_text(encoding="utf-8")
        assert "本服务操作" not in src, "mcp_server.py 内联旧文案残留"

    def test_r8_09_five_topics(self):
        """TC-R8-09:五主题节锚点全部在场。"""
        text = _text()
        for anchor in ("Scope and routing", "Approvals",
                       "Emergency stop", "Whitelist and levels",
                       "Forms and errors"):
            assert anchor in text, f"主题缺席(直出): {anchor}"


class TestWiring:
    def test_r8_07_build_server_wired(self):
        """TC-R8-07:生产默认装配 build_server().instructions ==
        访问器输出(R1/R3:装配真实接通,非空壳)。"""
        ctx = type("C", (), {"policy": None})()
        server = mcp_server.build_server(ctx)
        ins = getattr(server, "instructions", "") or ""
        assert ins, "instructions 为空(装配断裂)"
        assert ins == i18n.mcp_instructions(), \
            "装配未走访问器(直出不等)"

    def test_r8_08_missing_key_degrades(self, monkeypatch):
        """TC-R8-08:目录缺键 → 访问器返回空串+缺键审计,不抛异常。"""
        seen: list[tuple] = []
        monkeypatch.setattr(i18n, "_load_catalog", lambda: {})
        i18n._missing_reported.discard(_KEY)
        i18n.set_audit_sink(lambda ev, detail="": seen.append((ev, detail)))
        try:
            out = i18n.mcp_instructions()
        finally:
            i18n.set_audit_sink(None)
        assert out == "", f"缺键应回退空串(直出): {out!r}"
        assert any(ev == "i18n 缺键" and detail == _KEY
                   for ev, detail in seen), \
            f"缺键审计缺席(直出): {seen}"
