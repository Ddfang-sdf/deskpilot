"""REQ-003 TC-CVDET:CV 检测器本体(D-12 终裁:CV 单线出货,标识 `cv-contour`)。

层级:**单元**(检测器本体是纯函数面,**零替身**——样本图是 `tests/fixtures/req003/`
下的真实 PNG,侦察穿刺实测样本的归档副本)。

**断言出处**:预期区域框位取自侦察穿刺实测记录(侦察方案 v0.5 §5.1/§5.2,
`docs/需求/REQ-003-侦察/samples/spike-*.png` 证据图)——容差 ±10px(管线产品化
参数可能微移边界),覆盖判据 IoU≥0.3(测试设计 §5A)。

**P1 红点位**:`DetectorRegistry().build("cv-contour")` 当前抛
`DETECTOR_UNAVAILABLE`(未知标识)——P3 回填注册表后转绿。
用例来源:测试设计 v0.6 §5A(TC-CVDET-01~08)。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from deskpilot.errors import DETECTOR_UNAVAILABLE, ExecutorError
from deskpilot.executor.core import Executor
from deskpilot.executor.detector import DetectorRegistry

from .conftest import FIXTURE_HWND, FIXTURE_RECT, FakeProbe
from .test_elements import FakeElement

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "req003"

# 预期涂鸦区域框位(穿刺实测记录,±10px 容差;IoU≥0.3 判覆盖)
PAINT_V1_DOODLES = [
    (411, 358, 463, 415),     # 三角
    (686, 354, 754, 427),     # 方块
    (1118, 349, 1214, 442),   # 大团
    (1404, 377, 1468, 441),   # 小团
    (355, 566, 460, 648),     # 爱心
    (548, 529, 897, 636),     # 带翅爱心(连笔合一)
    (1125, 525, 1189, 854),   # 长条
]
PAINT_V2_REGIONS = PAINT_V1_DOODLES + [
    (1402, 564, 1462, 623),   # 播放键(嵌套 glyph)
]
# 西柚电源大圆钮(800×500 窗口图内坐标,穿刺实测)
SEEYOU_POWER = (370, 160, 530, 320)


def _iou(a, b) -> float:
    l, t = max(a[0], b[0]), max(a[1], b[1])
    r, bt = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, r - l) * max(0, bt - t)
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def _load(name):
    return Image.open(FIXTURES / name)


class TestCVDET01ContractShape:
    """TC-CVDET-01:契约形态——恰两键、rect 四整数且非退化、confidence 值域。"""

    def test_output_is_two_key_dicts_with_value_ranges(self):
        detector = DetectorRegistry().build("cv-contour")
        out = detector(_load("paint-canvas-v1-线条.png"))
        assert isinstance(out, list) and len(out) > 0
        for d in out:
            assert set(d) == {"rect", "confidence"}, "恰两键,不得多产字段(§2)"
            rect = d["rect"]
            assert len(rect) == 4 and all(isinstance(v, int) for v in rect)
            assert rect[0] < rect[2] and rect[1] < rect[3], "矩形非退化"
            assert isinstance(d["confidence"], float)
            # D-12 口径:几何显著度派生,[0.5, 0.99],不冒充语义置信度
            assert 0.5 <= d["confidence"] <= 0.99


class TestCVDET02CanvasCoverage:
    """TC-CVDET-02/02b:画布检出(H1 回归)——预期区域全覆盖(IoU≥0.3)。"""

    def _assert_covered(self, sample, regions):
        detector = DetectorRegistry().build("cv-contour")
        out = detector(_load(sample))
        boxes = [tuple(d["rect"]) for d in out]
        missing = [r for r in regions
                   if not any(_iou(r, b) >= 0.3 for b in boxes)]
        assert missing == [], f"涂鸦区域漏检: {missing}"

    def test_paint_v1_all_seven_doodles_covered(self):
        self._assert_covered("paint-canvas-v1-线条.png", PAINT_V1_DOODLES)

    def test_paint_v2_all_eight_regions_covered(self):
        self._assert_covered("paint-canvas-v2-填充彩色.png", PAINT_V2_REGIONS)


class TestCVDET03TextureSuppression:
    """TC-CVDET-03:纹理抑制——电源钮入框,点阵地图大团被丢弃。"""

    def test_seeyou_power_button_boxed_and_no_mega_blob(self):
        detector = DetectorRegistry().build("cv-contour")
        img = _load("seeyou-accelerator-全盲.png")
        w, h = img.size
        out = detector(img)
        # ①电源钮被框:存在返回框的中心点落入电源钮预期区域
        centers = [((d["rect"][0] + d["rect"][2]) / 2,
                    (d["rect"][1] + d["rect"][3]) / 2) for d in out]
        assert any(SEEYOU_POWER[0] <= cx <= SEEYOU_POWER[2]
                   and SEEYOU_POWER[1] <= cy <= SEEYOU_POWER[3]
                   for cx, cy in centers), "电源大圆钮未被检出"
        # ②无占图 >50% 的大框(点阵纹理被填充率过滤丢弃)
        for d in out:
            l, t, r, b = d["rect"]
            assert (r - l) * (b - t) <= 0.5 * w * h, \
                f"出现超大框(纹理未抑制): {d['rect']}"


class TestCVDET04RealUIIconSeparation:
    """TC-CVDET-04:真实自绘 UI 图标逐枚分离(企微左侧图标栏)。"""

    def test_wxwork_icon_bar_individually_boxed(self):
        detector = DetectorRegistry().build("cv-contour")
        out = detector(_load("wxwork-main-全盲.png"))
        icons = [d for d in out
                 if d["rect"][2] < 60 and d["rect"][3] - d["rect"][1] < 60]
        assert len(icons) >= 5, \
            f"图标栏逐枚分离不足(期望≥5,实得 {len(icons)}):面板合并未消解"


class TestCVDET05Determinism:
    """TC-CVDET-05:确定性——同图连调两次,返回逐位一致。"""

    def test_same_image_same_output(self):
        detector = DetectorRegistry().build("cv-contour")
        img = _load("paint-canvas-v1-线条.png")
        a = detector(img)
        b = detector(img)
        assert a == b, "同一输入两次调用返回须逐位一致(纯函数面)"


class TestCVDET06BlankNegative:
    """TC-CVDET-06:空白负例——纯白图零检出,不误报。"""

    def test_blank_image_returns_empty(self):
        detector = DetectorRegistry().build("cv-contour")
        out = detector(Image.new("RGB", (800, 500), "white"))
        assert out == [], "纯白图须零检出"


class TestCVDET07RegistryShape:
    """TC-CVDET-07:注册表形态——出厂标识注册、可 build、未知标识不误放。"""

    def test_names_contains_cv_contour(self):
        assert DetectorRegistry().names() == ("cv-contour",)

    def test_build_known_returns_callable(self):
        assert callable(DetectorRegistry().build("cv-contour"))

    def test_build_unknown_still_refused(self):
        """既有 TC-DET-06b 语义不回退:未知标识仍抛 DETECTOR_UNAVAILABLE。"""
        with pytest.raises(ExecutorError) as ei:
            DetectorRegistry().build("no_such_detector_xyz")
        assert ei.value.code == DETECTOR_UNAVAILABLE
        assert "no_such_detector_xyz" in ei.value.message


class TestCVDET08ZeroWeightOrchestration:
    """TC-CVDET-08:零权重链路编排——空清单 + 不配置权重目录 + 注册表真工厂,
    `detect=True` 必须成功(锁死「CV 线不需要权重目录」的形态,详设 §13
    空清单语义;防实现把权重目录当成 CV 的前置条件)。

    全真件:Executor 本体、注册表、检测器全真;`_shot_fn`/`element_source`/
    `probe` 为既有构造接缝(单元层同族形态,同 TC-SOM-09 归层口径)。
    """

    def test_detect_true_works_without_weights_dir(
            self, estop, tmp_path, clock):
        probe = FakeProbe()
        probe.rects = {FIXTURE_HWND: FIXTURE_RECT}
        img = _load("paint-canvas-v1-线条.png")
        ex = Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                      wait_timeout_max=5.0, clock=clock, probe=probe)
        # 注意:①不传 detector_weights_dir(缺省 None);②weight_manifest 保持
        # 缺省空清单;③工厂经注册表真 build(不替身)
        ex._shot_fn = lambda region: img
        ex._element_source = lambda hwnd: FakeElement(children=[])
        ex.detector_factory = lambda: DetectorRegistry().build("cv-contour")

        got = ex.get_clickable_map(FIXTURE_HWND, detect=True)

        assert got["coord_space"] == "virtual_desktop"
        detect = [e for e in got["entries"] if e["source"] == "detect"]
        # 涂鸦至少 7 区入编号空间(UIA 树空,无去重对象)
        assert len(detect) >= 7, \
            f"涂鸦检出不足(期望≥7,实得 {len(detect)}):零权重链路须真实可达"
