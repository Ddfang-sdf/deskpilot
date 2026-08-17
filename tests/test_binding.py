"""绑定管理（BindingManager）单元测试。

覆盖：TC-N-BIND-01/03/04、TC-E-ST-01/02、TC-S-BIND-02/03（INV-1）。
断言值来源：create/validate/detach/reap 的返回值。
"""

from __future__ import annotations

from .conftest import FIXTURE_HWND, FIXTURE_RECT


class TestCreateValidate:
    def test_create_and_validate(self, bindings):
        """TC-N-BIND-01：创建后持令牌校验通过，返回记录字段与创建参数一致。"""
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        assert rec.token
        assert rec.hwnd == FIXTURE_HWND
        assert rec.process_name == "notepad.exe"
        assert rec.window_rect == FIXTURE_RECT
        assert bindings.count() == 1

        got = bindings.validate(rec.token)
        assert got is not None
        assert got.token == rec.token

    def test_create_stores_window_title(self, bindings):
        """绑定快照保存窗口标题，供审批描述的人话层兜底使用。"""
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT,
                              window_title="无标题 - 记事本")
        assert rec.window_title == "无标题 - 记事本"

    def test_create_default_title_empty(self, bindings):
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        assert rec.window_title == ""

    def test_forged_token_rejected(self, bindings):
        """TC-S-BIND-02：伪造令牌校验返回 None。"""
        bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        assert bindings.validate("forged-token-0000") is None

    def test_none_token_rejected(self, bindings):
        """TC-S-BIND-01 基础：无令牌即无绑定。"""
        assert bindings.validate(None) is None


class TestLifecycle:
    def test_detach_invalidates(self, bindings):
        """TC-N-BIND-03 + TC-S-BIND-03：detach 后原令牌立即失效。"""
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        assert bindings.detach(rec.token) is True
        assert bindings.validate(rec.token) is None
        assert bindings.count() == 0

    def test_activity_refresh(self, bindings, clock):
        """TC-N-BIND-04：校验通过即刷新活跃时间，不超时。"""
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        clock.advance(500)
        assert bindings.validate(rec.token) is not None
        first_seen = rec.last_active_at
        clock.advance(500)                        # 累计 1000s > ttl 600s
        assert bindings.validate(rec.token) is not None
        assert rec.last_active_at > first_seen    # 每次通过后已刷新

    def test_timeout_invalidates(self, bindings, clock):
        """TC-E-ST-01：超过 binding_ttl 无操作 → 失效并被回收。"""
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        clock.advance(601)
        assert bindings.validate(rec.token) is None
        assert bindings.count() == 0

    def test_window_closed_invalidates(self, bindings, probe):
        """INV-1：句柄不再存活 → 校验失败。"""
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        probe.alive[FIXTURE_HWND] = False
        assert bindings.validate(rec.token) is None

    def test_hwnd_reuse_process_changed(self, bindings, probe):
        """TC-E-ST-02：句柄被系统复用给另一进程 → 进程一致性校验拦截。"""
        rec = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        probe.processes[FIXTURE_HWND] = "evil.exe"   # 同值句柄归属变了
        assert bindings.validate(rec.token) is None
        assert bindings.count() == 0

    def test_reap_removes_dead_and_expired(self, bindings, probe, clock):
        """TC-E-CC-05 关联：回收只清失效绑定，有效绑定不受影响。"""
        dead = bindings.create(FIXTURE_HWND, "notepad.exe", FIXTURE_RECT)
        live = bindings.create(1002, "notepad.exe", (0, 0, 10, 10))
        probe.alive[FIXTURE_HWND] = False            # dead 的句柄失效
        removed = bindings.reap()
        assert removed == 1
        assert bindings.validate(live.token) is not None
        assert bindings.validate(dead.token) is None
