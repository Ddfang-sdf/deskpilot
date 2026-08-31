"""M3 能力单元测试：OCR / 模板匹配 / SoM 标注与编号点击 / 审批异步通道。

入口：Executor 公开方法（ocr / template_match / get_clickable_map）与
execute()（som_id 点击路径）；ApprovalManager.issue_token 与
TkApprovalChannel.request（fire-and-forget 契约）。
断言值来源：返回结构 / 持久化文件 / 替身与回调的调用记录。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from deskpilot.approval import ApprovalManager, DenyAllChannel
from deskpilot.approval_ui import TkApprovalChannel
from deskpilot.errors import ELEMENT_NOT_FOUND, INTERNAL_ERROR, ExecutorError
from deskpilot.executor.core import Executor

from .conftest import (FIXTURE_HWND, FIXTURE_HWND_B, FIXTURE_RECT, FakeClock,
                       FakeProbe)
from .test_elements import FakeElement


# ---------- 公共夹具 ----------

@pytest.fixture
def fake_probe():
    p = FakeProbe()
    p.rects = {FIXTURE_HWND: FIXTURE_RECT,
               FIXTURE_HWND_B: (100, 100, 900, 700)}
    return p


@pytest.fixture
def m3_executor(estop, tmp_path, clock, fake_probe):
    return Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                    wait_timeout_max=5.0, clock=clock, probe=fake_probe)


# ---------- OCR ----------

class TestOCR:
    def test_ocr_path_source_passthrough(self, m3_executor, tmp_path):
        """图像路径来源：引擎结果原样返回（文字+位置）。"""
        img = Image.new("RGB", (60, 20), "white")
        p = tmp_path / "sample.png"
        img.save(p)
        seen = {}

        def fake_engine(image):
            seen["got_image"] = image
            return [{"text": "保存", "position": [10, 4, 34, 16]}]

        m3_executor._ocr_engine = fake_engine
        r = m3_executor.ocr(str(p))
        assert r["count"] == 1
        assert r["items"][0]["text"] == "保存"
        assert "position" in r["items"][0]
        assert seen["got_image"] is not None

    def test_ocr_engine_unavailable(self, m3_executor):
        """引擎未装配 → 显式错误（禁止静默成功，INV-7）。"""
        with pytest.raises(ExecutorError) as ei:
            m3_executor.ocr("nonexistent.png")
        assert ei.value.code == INTERNAL_ERROR
        assert "rapidocr" in ei.value.message


# ---------- 模板匹配 ----------

def _make_scene(tmp_path, size=(200, 150), square=(80, 60, 110, 90)):
    """生成黑底、内嵌非均匀图案方块（白底黑斜纹）的场景；
    返回场景图与模板文件路径。非均匀模板避免零方差导致的
    TM_CCOEFF_NORMED 数值退化。"""
    scene = Image.new("RGB", size, "black")
    d = ImageDraw.Draw(scene)
    d.rectangle(square, fill="white")
    d.line([square[0], square[1], square[2], square[3]], fill="black", width=4)
    d.line([square[0], square[3], square[2], square[1]], fill="black", width=4)
    tpl = scene.crop(square)
    tpl_path = tmp_path / "tpl.png"
    tpl.save(tpl_path)
    return scene, str(tpl_path)


def _make_other(tmp_path, size=(30, 30)):
    """场景中不存在的图案模板（白底黑圆）。"""
    other = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(other)
    d.ellipse([6, 6, 24, 24], fill="black")
    other_path = tmp_path / "other.png"
    other.save(other_path)
    return str(other_path)


class TestTemplateMatch:
    def test_hit(self, m3_executor, tmp_path):
        """命中：found=True，置信度达标，位置接近模板中心。"""
        scene, tpl_path = _make_scene(tmp_path)
        m3_executor._shot_fn = lambda region: scene
        r = m3_executor.template_match(tpl_path, (0, 0, 200, 150), 0.8)
        assert r["found"] is True
        assert r["best_confidence"] >= 0.8
        m = r["matches"][0]
        assert abs(m["x"] - 95) <= 3 and abs(m["y"] - 75) <= 3

    def test_miss(self, m3_executor, tmp_path):
        """未命中：如实返回最高置信度，不伪造命中（TC-S-VIS-04）。"""
        scene, tpl_path = _make_scene(tmp_path)
        other_path = _make_other(tmp_path)
        m3_executor._shot_fn = lambda region: scene
        r = m3_executor.template_match(other_path, (0, 0, 200, 150), 0.8)
        assert r["found"] is False
        assert r["best_confidence"] < 0.8


# ---------- SoM 标注与编号点击 ----------

def _map_tree():
    return FakeElement(children=[
        FakeElement(name="文件", rect=(110, 110, 160, 140)),
        FakeElement(name="编辑", rect=(170, 110, 220, 140)),
        FakeElement(name="保存", automation_id="save", rect=(110, 160, 160, 190)),
        FakeElement(name="灰按钮", enabled=False, rect=(200, 200, 240, 220)),
        FakeElement(name="零面积", rect=(0, 0, 0, 0)),
    ])


class TestClickableMap:
    def _map(self, m3_executor, tmp_path):
        shot = Image.new("RGB", (700, 500), "white")
        m3_executor._shot_fn = lambda region: shot
        m3_executor._element_source = lambda hwnd: _map_tree()
        return m3_executor.get_clickable_map(FIXTURE_HWND)

    def test_entries_filtered_and_numbered(self, m3_executor, tmp_path):
        """TC-N-L0-05：仅可交互非零面积元素入表，编号 1..N 连续唯一。"""
        r = self._map(m3_executor, tmp_path)
        assert r["count"] == 3
        ids = [e["id"] for e in r["entries"]]
        assert ids == [1, 2, 3]
        names = [e["name"] for e in r["entries"]]
        assert "文件" in names and "保存" in names
        assert "灰按钮" not in names and "零面积" not in names
        for e in r["entries"]:
            l, t, rr, b = e["rect"]
            assert FIXTURE_RECT[0] <= l and FIXTURE_RECT[1] <= t
            assert rr <= FIXTURE_RECT[2] and b <= FIXTURE_RECT[3]

    def test_annotated_image_exists(self, m3_executor, tmp_path):
        r = self._map(m3_executor, tmp_path)
        from pathlib import Path
        assert Path(r["path"]).exists()

    def test_som_id_click_invokes(self, m3_executor, tmp_path):
        """TC-N-L2-04：仅凭编号点击命中对应元素。"""
        self._map(m3_executor, tmp_path)
        r = m3_executor.execute(
            {"tool": "click_element", "params": {"som_id": 3},
             "binding_hwnd": FIXTURE_HWND})
        assert r["status"] == "ok"
        assert r["element"]["name"] == "保存"

    def test_som_id_expired(self, m3_executor, tmp_path, clock):
        """TC-E-ST-07：缓存过期（60 秒）→ 显式拒绝并引导重新取图。"""
        self._map(m3_executor, tmp_path)
        clock.advance(61)
        with pytest.raises(ExecutorError) as ei:
            m3_executor.execute(
                {"tool": "click_element", "params": {"som_id": 1},
                 "binding_hwnd": FIXTURE_HWND})
        assert ei.value.code == ELEMENT_NOT_FOUND
        assert "get_clickable_map" in ei.value.message

    def test_som_id_cross_window_refused(self, m3_executor, tmp_path):
        """TC-S-ATK-04：缓存句柄与绑定句柄不一致 → 拒绝（跨窗冒用防护）。"""
        self._map(m3_executor, tmp_path)
        with pytest.raises(ExecutorError) as ei:
            m3_executor.execute(
                {"tool": "click_element", "params": {"som_id": 1},
                 "binding_hwnd": FIXTURE_HWND_B})
        assert ei.value.code == ELEMENT_NOT_FOUND

    def test_empty_window_returns_empty(self, m3_executor, tmp_path):
        """无可交互元素 → 空图与空列表，不报错（F-L0-05 失败语义）。"""
        shot = Image.new("RGB", (700, 500), "white")
        m3_executor._shot_fn = lambda region: shot
        m3_executor._element_source = lambda hwnd: FakeElement(children=[])
        r = m3_executor.get_clickable_map(FIXTURE_HWND)
        assert r["count"] == 0
        assert r["entries"] == []


# ---------- 审批同步通道（ISS-0003：同步等待裁决，授权不经 AI） ----------

class TestSyncApproval:
    def _channel(self, tmp_path, timeout=2.0, fake_popen=None):
        return TkApprovalChannel(
            timeout=timeout,
            popen_factory=fake_popen or (lambda *a, **k: None),
            result_root=str(tmp_path))

    @staticmethod
    def _write_result_later(ch, content: str, delay: float = 0.1):
        """模拟弹窗进程：等 request 落出 result_path 后写入裁决结果。"""
        import threading

        def writer():
            for _ in range(200):
                lr = ch.last_request
                if lr:
                    open(lr["result_path"], "w",
                         encoding="utf-8").write(content)
                    return
                time.sleep(0.02)

        threading.Thread(target=writer, daemon=True).start()

    def test_approve_returns_approve(self, tmp_path):
        """人类批准 → request 同步返回 "approve"（单次调用闭环）。"""
        ch = self._channel(tmp_path)
        self._write_result_later(ch, "approve")
        t0 = time.monotonic()
        r = ch.request("危险键 alt+f4", "fp-a")
        assert r == "approve"
        assert time.monotonic() - t0 < 2.0         # 裁决即返回，不拖到超时
        assert ch.last_request["fingerprint"] == "fp-a"
        assert "alt+f4" in ch.last_request["description"]

    def test_deny_returns_deny(self, tmp_path):
        ch = self._channel(tmp_path)
        self._write_result_later(ch, "deny")
        assert ch.request("危险键", "fp-d") == "deny"

    def test_timeout_returns_timeout(self, tmp_path):
        """倒计时结束无人操作 = 默认拒绝（fail-closed），返回 "timeout"。"""
        ch = self._channel(tmp_path, timeout=0.3)
        t0 = time.monotonic()
        assert ch.request("危险键", "fp-t") == "timeout"
        assert time.monotonic() - t0 >= 0.3

    def test_dialog_written_timeout_honored(self, tmp_path):
        """弹窗进程自己倒计时结束写入 "timeout" 时，通道按超时返回。"""
        ch = self._channel(tmp_path)
        self._write_result_later(ch, "timeout")
        assert ch.request("危险键", "fp-dt") == "timeout"

    def test_issue_token_consumed_once(self, policy, clock):
        """issue_token 签发 → 按指纹一次性消费（INV-4，manager 层语义不变）。"""
        mgr = ApprovalManager(DenyAllChannel(), policy.approval_ttl, clock)
        fp = "fp-123"
        mgr.issue_token(fp)
        assert mgr.count() == 1
        assert mgr.verify_and_consume(fp) is True
        assert mgr.verify_and_consume(fp) is False
        assert mgr.count() == 0


# ---------- 打包形态弹窗拉起（onefile 回归） ----------

class TestSpawnDialogFrozen:
    def test_frozen_uses_exe_dispatch_and_strips_meipass(self, monkeypatch, tmp_path):
        """onefile 下须以 deskpilot.exe --approval-dialog 拉起弹窗（-m 无效），
        且剥离 _MEIPASS2（避免子进程共享解压目录、父退即崩）。"""
        import deskpilot.approval_ui as aui
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setenv("_MEIPASS2", r"C:\mei_shared")
        captured = {}
        ch = TkApprovalChannel(
            popen_factory=lambda cmd, env=None: captured.update(cmd=cmd, env=env),
            result_root=str(tmp_path))
        ch._spawn_dialog(tmp_path / "a.desc", tmp_path / "a.result")
        assert captured["cmd"][0] == sys.executable
        assert captured["cmd"][1] == "--approval-dialog"
        assert captured["env"] is not None
        assert "_MEIPASS2" not in captured["env"]
        assert captured["env"].get("PATH")          # 其余环境变量保留

    def test_nonfrozen_uses_dash_m(self, monkeypatch, tmp_path):
        """源码形态保持 python -m deskpilot.approval_dialog。"""
        monkeypatch.delattr(sys, "frozen", raising=False)
        captured = {}
        ch = TkApprovalChannel(
            popen_factory=lambda cmd, env=None: captured.update(cmd=cmd, env=env),
            result_root=str(tmp_path))
        ch._spawn_dialog(tmp_path / "a.desc", tmp_path / "a.result")
        assert captured["cmd"][1:3] == ["-m", "deskpilot.approval_dialog"]
        assert captured["env"] is None

    def test_entry_dispatches_approval_dialog(self, tmp_path):
        """打包入口脚本识别 --approval-dialog（黑盒：1s 倒计时结束写 timeout）。"""
        import subprocess
        desc = tmp_path / "d.desc"
        desc.write_text("测试描述", encoding="utf-8")
        result = tmp_path / "d.result"
        root = Path(__file__).resolve().parent.parent
        subprocess.run(
            [sys.executable, str(root / "run_deskpilot.py"),
             "--approval-dialog", str(desc), str(result), "1"],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
            cwd=str(root))
        assert result.read_text(encoding="utf-8") == "timeout"

    def test_entry_dialog_with_image(self, tmp_path):
        """弹窗携带目标窗口截图参数正常渲染（黑盒：含图像不崩溃）。"""
        import subprocess
        img = tmp_path / "target.png"
        Image.new("RGB", (800, 400), "#336699").save(img)
        desc = tmp_path / "d.desc"
        desc.write_text("关闭窗口「无标题 - 画图」\n---\n"
                        "按键 alt+f4 · 进程 mspaint.exe · 句柄 1",
                        encoding="utf-8")
        result = tmp_path / "d.result"
        root = Path(__file__).resolve().parent.parent
        subprocess.run(
            [sys.executable, str(root / "run_deskpilot.py"),
             "--approval-dialog", str(desc), str(result), "1", str(img)],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
            cwd=str(root))
        assert result.read_text(encoding="utf-8") == "timeout"

    def test_spawn_forwards_image_path(self, tmp_path):
        """审批通道把目标窗口截图路径传给弹窗进程（ISS-0012：enroll 参数居末位）。"""
        captured = {}
        ch = TkApprovalChannel(
            popen_factory=lambda cmd, env=None: captured.update(cmd=cmd),
            result_root=str(tmp_path))
        ch._spawn_dialog(tmp_path / "a.desc", tmp_path / "a.result",
                         "C:/shots/x.png")
        assert captured["cmd"][-2] == "C:/shots/x.png"
        assert captured["cmd"][-1] == ""          # enroll 缺省空串

    def test_spawn_without_image_passes_empty(self, tmp_path):
        """无截图时末位参数为空串（弹窗端据此跳过图像区）。"""
        captured = {}
        ch = TkApprovalChannel(
            popen_factory=lambda cmd, env=None: captured.update(cmd=cmd),
            result_root=str(tmp_path))
        ch._spawn_dialog(tmp_path / "a.desc", tmp_path / "a.result")
        assert captured["cmd"][-1] == ""


# ---------- 审批弹窗落位（右下角 toast，滑入起点屏外） ----------

class TestToastPlacement:
    def test_bottom_right_with_margins(self):
        from deskpilot.approval_dialog import _toast_placement
        screen = {"rect": (0, 0, 2560, 1440), "work_area": (0, 0, 2560, 1392)}
        x, y_start, y_final = _toast_placement(screen, 440, 210)
        assert x == 2560 - 440 - 16
        assert y_final == 1392 - 210 - 48 - 16            # 任务栏 + 边距
        assert y_start == 1440                             # 滑入起点：屏外底部

    def test_default_size_bottom_right(self):
        """默认 480×216 尺寸的落位（Fluent toast 规格）。"""
        from deskpilot.approval_dialog import _toast_placement
        screen = {"rect": (0, 0, 2560, 1440), "work_area": (0, 0, 2560, 1392)}
        x, y_start, y_final = _toast_placement(screen, 480, 216)
        assert x == 2560 - 480 - 16
        assert y_final == 1392 - 216 - 48 - 16
        assert y_start == 1440

    def test_small_screen_negative_coords_allowed(self):
        """小屏退化为屏外坐标（虚拟桌面坐标系允许负值，不再钳零，ISS-0007）。"""
        from deskpilot.approval_dialog import _toast_placement
        screen = {"rect": (0, 0, 300, 200), "work_area": (0, 0, 300, 200)}
        x, _, y_final = _toast_placement(screen, 440, 210)
        assert x == 300 - 440 - 16
        assert y_final == 200 - 210 - 48 - 16


# ---------- OCR 引擎装配（RapidOCR 1.2 适配） ----------

class TestOcrEngineAdapter:
    def test_pil_to_bgr_ndarray_and_flat_bbox(self):
        """PIL Image 须转 BGR ndarray；四点框须转平铺包围盒 [x1,y1,x2,y2]。"""
        import numpy as np
        from deskpilot.main import _build_ocr_engine
        captured = {}

        class FakeRapid:
            def __call__(self, img):
                captured["img"] = img
                return ([[[[10, 4], [34, 4], [34, 16], [10, 16]],
                          "保存", 0.99]], 0.05)

        engine = _build_ocr_engine(FakeRapid())
        items = engine(Image.new("RGB", (2, 2), (10, 20, 30)))
        assert items == [{"text": "保存", "position": [10, 4, 34, 16]}]
        arr = captured["img"]
        assert isinstance(arr, np.ndarray)
        assert arr[0, 0].tolist() == [30, 20, 10]    # RGB → BGR 通道翻转

    def test_empty_result_gives_empty_items(self):
        from deskpilot.main import _build_ocr_engine

        class FakeRapid:
            def __call__(self, img):
                return (None, 0.01)

        engine = _build_ocr_engine(FakeRapid())
        assert engine(Image.new("RGB", (2, 2))) == []
