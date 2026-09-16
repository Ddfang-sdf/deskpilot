"""ISS-0083:screenshot 按屏取图档 + region 显式意图(覆盖率)测试。

层级:**单元**(Executor 真本体;替身仅 `monitors.enum_monitors` 几何替身——
单元层允许 mock;落盘与取图全真,`screenshot()` 的 PNG 路径走真 mss,
与 ISS-0018 既有用例同规)。**断言出处**:返回体 `virtual_rect`/`coverage`/
`coord_space` 直出 + 落盘 PNG 的**像素尺寸**(= 实拍区域,数据层断言) +
 shots 目录快照(零取图证明)。

用例来源:ISS-0083 §5 验收口径(sdfang 2026-09-14 评审通过 ①按屏档+②region
显式意图/覆盖率)、§4.3 待钉形态(屏号=`enum_monitors()` 列表序号——与
fullscreen 返回的 monitors 同一清单,同一心智模型)。

**P1 红点位**:schema 的 scope 枚举无 `"screen"`(validate_call 直接拒)、
`_resolve_region` 无 `"screen"` 分支、返回体无 `coverage`。
"""

from __future__ import annotations

import pytest
from PIL import Image

from deskpilot.errors import INVALID_PARAMS, ExecutorError
from deskpilot.executor.core import Executor
from deskpilot.mcp_server import TOOL_SCHEMAS, validate_call

from .conftest import FIXTURE_HWND, FIXTURE_RECT, FakeProbe

# 双屏几何(与本机实测同形):副屏(1920,-1,3840,1079) 错位 + 主屏(0,0,1920,1080)。
# 外接矩形 = (0,-1)-(3840,1080),面积 3840×1081。
MONS = [
    {"rect": (1920, -1, 3840, 1079), "work_area": (1920, -1, 3840, 1079),
     "is_primary": False},
    {"rect": (0, 0, 1920, 1080), "work_area": (0, 0, 1920, 1032),
     "is_primary": True},
]
BOUNDING_AREA = 3840 * 1081


@pytest.fixture
def ex(estop, tmp_path, clock, monkeypatch):
    """真 Executor + 几何替身(enum_monitors)。"""
    import deskpilot.monitors as mon_mod
    monkeypatch.setattr(mon_mod, "enum_monitors", lambda: MONS)
    return Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                    wait_timeout_max=5.0, clock=clock, probe=FakeProbe())


def _shots(tmp_path) -> set:
    d = tmp_path / "audit" / "shots"
    return {str(p) for p in d.rglob("*") if p.is_file()} if d.exists() else set()


class TestScope01PerScreen:
    """TC-SCOPE-01:按屏取图——virtual_rect 逐分量等于 enum_monitors() 该屏 rect,
    落盘图像像素尺寸恰为该屏宽高(实拍区域证据,数据层)。"""

    def test_screen_zero_takes_first_monitor(self, ex, tmp_path):
        r = ex.screenshot("screen", window=None, rect=None, screen=0)
        assert r["virtual_rect"] == list(MONS[0]["rect"]), \
            "virtual_rect 须逐分量等于该屏 rect(含负坐标)"
        img = Image.open(r["path"])
        assert img.size == (1920, 1080), "落盘图尺寸 = 该屏宽高(实拍区域恰为该屏)"
        assert r["coord_space"] == "virtual_desktop", "坐标空间不新增"

    def test_screen_one_takes_second_monitor(self, ex):
        r = ex.screenshot("screen", window=None, rect=None, screen=1)
        assert r["virtual_rect"] == list(MONS[1]["rect"])
        assert Image.open(r["path"]).size == (1920, 1080)


class TestScope02OutOfRangeFailClosed:
    """TC-SCOPE-02:屏号越界 → 显式报错,零取图(不静默回退全屏/主屏)。"""

    def test_out_of_range_screen_refused(self, ex, tmp_path):
        before = _shots(tmp_path)
        with pytest.raises(ExecutorError) as ei:
            ex.screenshot("screen", window=None, rect=None, screen=9)
        assert ei.value.code == INVALID_PARAMS
        assert "9" in ei.value.message and "2" in ei.value.message, \
            "message 须含所给屏号与可用屏数"
        assert _shots(tmp_path) == before, "越界屏号零落盘(无静默回退)"

    def test_screen_param_must_be_int(self, policy):
        """R7:红/绿必须因「整数判定」——P1 期若借 scope 枚举缺失借道,
        message 不含「必须为整数」即红;P3 后由 _check_type 的 int 严格判定产出。"""
        with pytest.raises(Exception) as ei:
            validate_call("screenshot",
                          {"scope": "screen", "screen": "left"}, policy)
        assert getattr(ei.value, "code", None) == INVALID_PARAMS
        assert "必须为整数" in ei.value.message


class TestScope03Coverage:
    """TC-SCOPE-03:coverage = 本图面积 ÷ 虚拟桌面外接矩形面积(实数断言)。"""

    def test_region_coverage_exact(self, ex):
        r = ex.screenshot("region", rect=[0, 0, 960, 540])
        expected = (960 * 540) / BOUNDING_AREA
        assert abs(r["coverage"] - expected) < 1e-9, \
            f"coverage 须为实数比值:期望 {expected},得 {r.get('coverage')}"

    def test_screen_coverage_is_screen_share(self, ex):
        r = ex.screenshot("screen", window=None, rect=None, screen=1)
        expected = (1920 * 1080) / BOUNDING_AREA
        assert abs(r["coverage"] - expected) < 1e-9

    def test_fullscreen_vs_screen_difference_visible(self, ex):
        """ISS-0083 §5.3:错位双屏下 fullscreen 外接面积 > 任一单屏——证「外接
        矩形含虚空」是既有事实而非本单引入。

        环境不变量(icons09 先例):fullscreen 的 virtual_rect 全真取自 mss
        `monitors[0]`(虚拟桌面外接矩形),其跨环境恒真性质是**覆盖
        enum_monitors 每一屏**;替身错位双屏下退化为「外接面积 > 任一单屏
        面积」。不钉本机绝对几何(CI runner 为单屏)。"""
        r_full = ex.screenshot("fullscreen")
        l, t, r, b = r_full["virtual_rect"]
        for m in MONS:
            ml, mt, mr, mb = m["rect"]
            assert l <= ml and t <= mt and r >= mr and b >= mb, \
                f"fullscreen 外接矩形须覆盖屏 {m['rect']},实得 {[l, t, r, b]}"
        full_area = (r - l) * (b - t)
        single_area = (MONS[1]["rect"][2] - MONS[1]["rect"][0]) * \
                      (MONS[1]["rect"][3] - MONS[1]["rect"][1])
        assert full_area > single_area  # 外接矩形 > 单屏(虚空存在)


class TestScope04SchemaShape:
    """TC-SCOPE-04:schema 形态——scope 枚举含 screen,conditional 挂 screen 参数,
    描述 ≤200 字且含 region 的用途定位。"""

    def test_schema_screen_enum_and_conditional(self, policy):
        schema = TOOL_SCHEMAS["screenshot"]
        scopes = schema["required"]["scope"][1]
        assert "screen" in scopes, "scope 枚举须含 screen"
        assert schema["conditional"]["screen"] == ["screen"]
        # scope=screen 缺 screen 参数 → 条件必填拦截
        with pytest.raises(Exception) as ei:
            validate_call("screenshot", {"scope": "screen"}, policy)
        assert getattr(ei.value, "code", None) == INVALID_PARAMS

    def test_description_bounds(self):
        d = TOOL_SCHEMAS["screenshot"]["description"]
        assert len(d) <= 200
        assert any(w in d for w in ("Windows", "桌面", "窗口", "浏览器"))
        assert "screen" in d and "屏" in d, "须含按屏档语义"
        assert "region" in d and ("精读" in d or "局部" in d), \
            "region 须标用途定位(精读/局部核对)"
        assert "coverage" in d or "比例" in d, "须含覆盖率语义"


class TestScope05Regression:
    """TC-SCOPE-05:fullscreen/window/region 原行为不变(既有键集与坐标)。"""

    def test_fullscreen_unchanged(self, ex):
        """fullscreen 回归:virtual_rect 全真(mss `monitors[0]`),环境不变量=
        覆盖 enum_monitors 每一屏;coord_space/monitors/vision_note 为
        环境无关键。不钉本机绝对坐标(CI runner 为单屏)。"""
        r = ex.screenshot("fullscreen")
        l, t, rr, b = r["virtual_rect"]
        for m in MONS:
            ml, mt, mr, mb = m["rect"]
            assert l <= ml and t <= mt and rr >= mr and b >= mb
        assert r["coord_space"] == "virtual_desktop"
        assert len(r["monitors"]) == 2
        assert "vision_note" in r

    def test_region_path_unchanged(self, ex):
        """region 的 rect 既有约定 = [left, top, width, height](M2/M3 起,
        `_region_dict`/`ocr`/`template_match` 同一约定;a58b0dc)。ISS-0083 §5.4
        「保持原行为」以代码为准。"""
        r = ex.screenshot("region", rect=[10, 20, 300, 200])
        assert r["virtual_rect"] == [10, 20, 310, 220]
        assert Image.open(r["path"]).size == (300, 200)
