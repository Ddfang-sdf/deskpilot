"""ISS-0051 PMV2 声明封送修复与查询制回报单元测试(TC-51-01/02,问题单 §2)。

层级:单元;TC-51-01 为子进程真 Win32 调用(封送 bug 的诚实回归,
同进程已被 deskpilot.main import 污染,必须另起进程)。
入口(设计):子进程 import deskpilot.main 读 _DPI_MODE / main._query_dpi_mode
+ _set_dpi_awareness(模块级公开函数)。
断言值来源:子进程 stdout / 函数返回值——直出。

测试设计(五要素):
- TC-51-01 场景=干净进程声明 DPI 感知;前提=子进程裸 import deskpilot.main;
  步骤=打印 _DPI_MODE;预期=pmv2(封送修复后 PMV2 必达;若回退 v1/unaware
  即回归);断言=stdout 直出。
- TC-51-02 场景=清单预设/调用被拒下回报如实;前提=替身两级声明调用全败,
  查询替身返"等于 PMV2 上下文";步骤=_set_dpi_awareness();预期=返回 pmv2
  (不按调用成败说谎);断言=返回值直出。
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# c_void_p.value 是无符号回绕整数(实证:c_void_p(-4).value=0xFFFF...FC),
# 替身比较必须与实现同形,禁止直比负数。
_PMV2_VAL = ctypes.c_void_p(-4).value


class TestPmv2RealCall:
    def test_tc51_01_fresh_process_reaches_pmv2(self):
        """干净子进程:import 即声明,回报必须是 pmv2(封送修复回归钉)。"""
        code = ("from deskpilot.main import _DPI_MODE;"
                "print('MODE=' + _DPI_MODE)")
        r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT),
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"子进程异常: {r.stderr[-400:]}"
        assert r.stdout.strip() == "MODE=pmv2"

    def test_tc51_02_reporting_follows_query_not_call(self, monkeypatch):
        """声明调用全败但上下文实为 PMV2(清单预设场景)→ 必须如实报 pmv2。"""
        from deskpilot import main as m
        monkeypatch.setattr(
            "ctypes.windll.user32.SetProcessDpiAwarenessContext",
            lambda *_a: 0)
        monkeypatch.setattr(
            "ctypes.windll.user32.SetProcessDPIAware", lambda: 0)
        monkeypatch.setattr(
            "ctypes.windll.user32.GetThreadDpiAwarenessContext",
            lambda: 999)                      # 原始句柄(含标志位)
        monkeypatch.setattr(
            "ctypes.windll.user32.AreDpiAwarenessContextsEqual",
            lambda a, b: getattr(b, "value", None) == _PMV2_VAL)
        assert m._set_dpi_awareness() == "pmv2"
