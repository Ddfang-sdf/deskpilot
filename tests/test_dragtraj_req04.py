"""REQ-004 drag 轨迹(via 途经点+duration_ms)测试(TC-TRAJ-01~07,需求单 v0.2 立项裁定)。

背景:AI 绘图实操证伪 REQ-001「任意序列可拼出」承诺——_drag 只有
start/end,24 段线性插值写死;组合路径 15 次调用画一条折线实际不可用。
立项裁定(方案①形态):drag 增 via(可选途经点,≤32 超限 fail-closed)+
duration_ms(可选总时长,按弧长分配到各段);缺省=现行为逐点不变;
折线够用贝塞尔不做;吸附/避障/占位感知不做。

层级分布:
- 单元:TC-TRAJ-01~05(真 Executor+替身 pyautogui/显示器枚举,
  照 test_drag_iss47 接缝;轨迹=moveTo 桩调用记录直出)
- 形态:TC-TRAJ-06/07(注册表直读+validate_call 调用)

步数契约(P3 实现依据,本文件钉死):via/duration_ms 给定才进自适应引擎
——总步数=min(48, max(2, round(总弧长/25))),各段步数=max(1,
round(总步数×段长/总弧长)),每段末点=该段锚点;缺省路径保持
steps=24/duration=0.02 逐点不变(回归钉)。duration_ms 给定时
每步时长=总时长/总步数(匀速)。

入口(设计):Executor.execute("drag")/TOOL_SCHEMAS["drag"]/validate_call。
断言出处:moveTo 桩调用记录(坐标+时长)直出/异常 code 属性直出/
注册表直读/validate_call 返回与异常直出——均直出。

P1 红态预期:TC-TRAJ-02/03/04/05/07 红(via 被忽略/无上限校验/coords
型未实现);TC-TRAJ-01/06 绿(缺省回归钉+声明面已落)。
"""

from __future__ import annotations

import pytest

from deskpilot.errors import (INVALID_PARAMS, OUT_OF_BOUNDS, ExecutorError,
                              InvalidParamsError)
from deskpilot.mcp_server import TOOL_SCHEMAS, validate_call

from .conftest import FIXTURE_HWND
from .test_drag_iss47 import _DUAL, _exec


def _interp_moves(rec):
    """插值 moveTo 调用(带 duration kwarg)=轨迹点序列(桩记录直出)。"""
    return [c for c in rec.named("moveTo") if "duration" in c[2]]


def _xy(call):
    return call[1]


class TestDragTrajectory:
    """TC-TRAJ-01~05(单元):缺省回归/via 分段/时长分配/上限/越界。"""

    def test_traj01_default_straight_line_unchanged(self, estop, tmp_path,
                                                    monkeypatch):
        """TC-TRAJ-01(单元,缺省回归钉):不给 via/duration_ms → 行为与
        现版逐点一致:初始 moveTo(start)+24 步线性插值,每步
        duration=0.02,末点=end。
        断言:桩调用记录直出。P1 即绿(守卫钉:防实现改动缺省行为)。"""
        ex, rec = _exec(estop, tmp_path, monkeypatch, _DUAL)
        out = ex.execute({"tool": "drag",
                          "params": {"start": [200, 200], "end": [800, 500]},
                          "binding_hwnd": FIXTURE_HWND})
        assert out["status"] == "ok"
        moves = rec.named("moveTo")
        assert len(moves) == 25                  # 1 初始 + 24 插值(直出)
        interp = _interp_moves(rec)
        assert len(interp) == 24
        assert all(c[2] == {"duration": 0.02} for c in interp), \
            "缺省每步时长 0.02 不变(桩记录直出)"
        assert _xy(interp[-1]) == pytest.approx((800, 500))

    def test_traj02_via_segmented_by_arc_length(self, estop, tmp_path,
                                                monkeypatch):
        """TC-TRAJ-02(单元,via 分段):start(200,200)→via(500,200)→
        via(500,500)→end(800,500),三段各 300px(总 900px → 36 步,
        段均分 12/12/12)→轨迹经全部途经点,段末=锚点。
        断言:轨迹点桩记录直出(步数/锚点坐标/默认时长 0.02 保持)。
        红态:via 被忽略,线性 24 步无途经点。"""
        ex, rec = _exec(estop, tmp_path, monkeypatch, _DUAL)
        ex.execute({"tool": "drag",
                    "params": {"start": [200, 200], "end": [800, 500],
                               "via": [[500, 200], [500, 500]]},
                    "binding_hwnd": FIXTURE_HWND})
        interp = _interp_moves(rec)
        assert len(interp) == 36, \
            f"总步数=min(48,round(900/25))=36(桩记录直出): {len(interp)}"
        assert _xy(interp[11]) == pytest.approx((500, 200))   # 段1 末=via0
        assert _xy(interp[23]) == pytest.approx((500, 500))   # 段2 末=via1
        assert _xy(interp[35]) == pytest.approx((800, 500))   # 段3 末=end
        assert all(c[2] == {"duration": 0.02} for c in interp), \
            "未给 duration_ms 时每步时长保持 0.02(桩记录直出)"

    def test_traj03_duration_allocated_by_arc_length(self, estop, tmp_path,
                                                     monkeypatch):
        """TC-TRAJ-03(单元,duration_ms 弧长分配):start(200,200)→
        via(500,200)(300px)→end(500,300)(100px),总 400px → 16 步
        (12/4);duration_ms=1200 → 每步 1200/16=75ms(匀速)。
        断言:桩记录直出(步数/段末锚点/每步时长)。
        红态:duration_ms 被忽略,24 步×0.02。"""
        ex, rec = _exec(estop, tmp_path, monkeypatch, _DUAL)
        ex.execute({"tool": "drag",
                    "params": {"start": [200, 200], "end": [500, 300],
                               "via": [[500, 200]], "duration_ms": 1200},
                    "binding_hwnd": FIXTURE_HWND})
        interp = _interp_moves(rec)
        assert len(interp) == 16, \
            f"总步数=round(400/25)=16(桩记录直出): {len(interp)}"
        assert _xy(interp[11]) == pytest.approx((500, 200))   # 段1 末=via0
        assert _xy(interp[15]) == pytest.approx((500, 300))   # 段2 末=end
        durs = [c[2]["duration"] for c in interp]
        assert durs == pytest.approx([0.075] * 16), \
            f"每步时长=1200ms/16 步=0.075s(匀速,桩记录直出): {durs[:4]}…"

    def test_traj04_via_over_limit_fail_closed(self, estop, tmp_path,
                                               monkeypatch):
        """TC-TRAJ-04(单元,via 上限):33 个途经点(>32)→ ExecutorError
        INVALID_PARAMS,零派发。
        断言:异常 code 直出;桩零调用记录。
        红态:无上限校验,via 被忽略照常执行(DID NOT RAISE)。"""
        ex, rec = _exec(estop, tmp_path, monkeypatch, _DUAL)
        via = [[200 + i, 200] for i in range(33)]
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "drag",
                        "params": {"start": [200, 200], "end": [800, 500],
                                   "via": via},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == INVALID_PARAMS
        assert rec.calls == [], "超限拒绝零派发(桩记录直出)"

    def test_traj05_via_point_offscreen_rejected(self, estop, tmp_path,
                                                 monkeypatch):
        """TC-TRAJ-05(单元,途经点越界):via 含 (5000,300)(任何屏外)→
        OUT_OF_BOUNDS 零派发(途经点沿用逐屏判定,与终点同闸)。
        断言:异常 code 直出;桩零调用记录。
        红态:via 被忽略照常执行(DID NOT RAISE)。"""
        ex, rec = _exec(estop, tmp_path, monkeypatch, _DUAL)
        with pytest.raises(ExecutorError) as ei:
            ex.execute({"tool": "drag",
                        "params": {"start": [200, 200], "end": [800, 500],
                                   "via": [[5000, 300]]},
                        "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == OUT_OF_BOUNDS
        assert rec.calls == []


class TestDragTrajSchema:
    """TC-TRAJ-06/07(形态):schema 声明+coords 型校验。"""

    def test_traj06_schema_via_duration_declared(self):
        """TC-TRAJ-06(形态):drag optional 含 via(coords 型)+duration_ms
        (int 型);描述 ≤200 且含「途经」语义(可发现性,目标 C)。
        断言:注册表直读。绿态:P1 声明面已落。"""
        schema = TOOL_SCHEMAS["drag"]
        assert schema["optional"]["via"] == ("coords",)
        assert schema["optional"]["duration_ms"] == ("int",)
        d = schema["description"]
        assert len(d) <= 200
        assert "途经" in d, "描述须写明可拐弯/途经语义(AI 可发现性)"

    def test_traj07_coords_type_validated(self, policy):
        """TC-TRAJ-07(形态,coords 型):validate_call 接受合法 via 坐标
        数组;非数组/非坐标元素(三元点/字符串)一律 InvalidParamsError。
        断言:validate_call 返回与异常直出。
        红态:coords 型未实现(合法 via 报「模式声明非法」)。"""
        base = {"token": "t", "start": [1, 2], "end": [3, 4]}
        ok = validate_call("drag", {**base, "via": [[500, 200], [500, 500]],
                                    "duration_ms": 1200}, policy)
        assert ok["via"] == [[500, 200], [500, 500]]   # 返回值直出
        with pytest.raises(InvalidParamsError):
            validate_call("drag", {**base, "via": [[1, 2, 3]]}, policy)
        with pytest.raises(InvalidParamsError):
            validate_call("drag", {**base, "via": "x"}, policy)
        with pytest.raises(InvalidParamsError):
            validate_call("drag", {**base, "via": [["a", 2]]}, policy)
