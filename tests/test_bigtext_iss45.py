"""ISS-0045 大文本读回窗口与写锁级联单元测试(TC-45-01~04,问题单 §2 方向①+③)。

层级:单元(Executor.__new__ 取方法+替身读回/剪贴板/睡眠;httpd 写锁真锁)。
入口(设计):Executor._type_text 剪贴板桥 / HttpDaemon._call_with_budget。
断言值来源:替身计数(粘贴/读回次数)、ToolResult 字段、异常 code——直出。

语义钉:
- ① 读回轮询窗口按文本规模缩放:300ms × ceil(len/8k),3 拍起步,20 拍封顶;
- ③ 参数校验前置到写锁之外:超限输入秒拒 INVALID_PARAMS,
  不排在在途写锁后把预算耗成 TOOL_TIMEOUT;合法写仍入锁串行(语义不变)。

测试设计(五要素):
- TC-45-01 场景=65536 字符窗口缩放;前提=替身读回前 4 空第 5 中;
  步骤=_type_text;预期=恰 1 次粘贴、5 次读回、note 一致;
  断言=计数直出(旧窗口 3 拍必重贴,可区分)。
- TC-45-02 场景=窗口封顶 20 拍;前提=200k 字符+读回恒不命中;
  步骤=_type_text;预期=INTERNAL_ERROR、粘贴 2、读回 40;断言=计数直出。
- TC-45-03 场景=超限校验锁外前置;前提=写锁被测试线程占住不放;
  步骤=_call_with_budget(type_text, 65537 字符);预期=立即 ToolResult
  INVALID_PARAMS(非 _BUDGET_EXCEEDED),耗时 < 1s;断言=返回值+耗时直出。
- TC-45-04 场景=合法写仍入锁串行;前提=写锁被占+合法参数+预算替身 0.3s;
  预期=_BUDGET_EXCEEDED(等锁语义不变);断言=返回值是哨兵直出。
"""

from __future__ import annotations

import time

import pytest

from deskpilot.errors import INTERNAL_ERROR, INVALID_PARAMS, ExecutorError

from .conftest import FIXTURE_HWND  # noqa: F401


def _typed_executor(monkeypatch, readback):
    from deskpilot.executor import Executor
    import deskpilot.executor.core as core
    ex = Executor.__new__(Executor)              # 不经 __init__,仅取方法
    monkeypatch.setattr(ex, "_activate_if_needed", lambda hwnd: True)
    reads = []

    def _read(hwnd):
        v = readback.pop(0) if readback else "stale"
        reads.append(v)
        return v
    monkeypatch.setattr(ex, "_read_edit_value", _read)
    pastes = []
    monkeypatch.setattr(core.pyautogui, "hotkey",
                        lambda *a, **k: pastes.append(a))
    monkeypatch.setattr(core.pyperclip, "copy", lambda t: None)
    monkeypatch.setattr(core.pyperclip, "paste", lambda: "old")
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    return ex, pastes, reads


class TestReadbackWindowScaling:
    def test_tc45_01_window_scales_with_text_size(self, monkeypatch):
        """65536 字符:窗口 8 拍,第 5 拍命中 → 恰一次粘贴。"""
        text = "中" * 65536
        ex, pastes, reads = _typed_executor(
            monkeypatch, ["", "", "", "", "xx" + text])
        r = ex._type_text(text, 42)
        assert len(pastes) == 1                  # 不重贴(直出)
        assert len(reads) == 5                   # 第 5 拍命中(>旧窗口 3,直出)
        assert r["note"] == "读回校验一致"

    def test_tc45_02_window_capped_at_20(self, monkeypatch):
        """200k 字符:ceil(25) 封顶 20 拍×2 轮=40 读,重贴 2 次后报。"""
        ex, pastes, reads = _typed_executor(monkeypatch, [])
        with pytest.raises(ExecutorError) as ei:
            ex._type_text("中" * 200000, 42)
        assert ei.value.code == INTERNAL_ERROR
        assert len(pastes) == 2
        assert len(reads) == 40                  # 20 拍 × 2 轮(直出)


class TestValidationBeforeWriteLock:
    def test_tc45_03_oversize_rejected_outside_lock(self, ctx, monkeypatch):
        """写锁被占时,超限输入立即 INVALID_PARAMS(不排队等锁)。"""
        from deskpilot.httpd import HttpDaemon
        d = HttpDaemon(ctx, host="127.0.0.1", port=0)
        d.start()
        d._write_lock.acquire()                  # 模拟在途大写占锁 60s+
        try:
            t0 = time.monotonic()
            r = d._call_with_budget(
                "type_text", {"token": "x", "text": "中" * 65537})
            elapsed = time.monotonic() - t0
        finally:
            d._write_lock.release()
            d.stop()
        assert r is not HttpDaemon._BUDGET_EXCEEDED
        assert r.ok is False
        assert r.error_code == INVALID_PARAMS    # 秒拒,校验真的执行了
        assert elapsed < 1.0                     # 没等锁(直出)

    def test_tc45_04_valid_write_still_serializes(self, ctx, monkeypatch):
        """合法参数在锁被占时仍排队等锁(写串行语义不变)。"""
        import deskpilot.httpd as httpd_mod
        monkeypatch.setattr(httpd_mod, "resolve_budget",
                            lambda *a, **k: 0.3)   # 短预算替身
        d = httpd_mod.HttpDaemon(ctx, host="127.0.0.1", port=0)
        d.start()
        d._write_lock.acquire()
        try:
            r = d._call_with_budget(
                "type_text", {"token": "x", "text": "中"})
        finally:
            d._write_lock.release()
            d.stop()
        assert r is httpd_mod.HttpDaemon._BUDGET_EXCEEDED  # 等锁到预算耗尽
