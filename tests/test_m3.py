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


# ---------- 审批异步通道（令牌不经 AI） ----------

class TestAsyncApproval:
    def _channel(self, tmp_path, cb, timeout=0.5, fake_popen=None):
        return TkApprovalChannel(
            on_approved=cb, timeout=timeout,
            popen_factory=fake_popen or (lambda *a, **k: None),
            result_root=str(tmp_path))

    def test_issue_token_consumed_once(self, policy, clock):
        """issue_token 签发 → 按指纹一次性消费（INV-4）。"""
        mgr = ApprovalManager(DenyAllChannel(), policy.approval_ttl, clock)
        fp = "fp-123"
        mgr.issue_token(fp)
        assert mgr.count() == 1
        assert mgr.verify_and_consume(fp) is True
        assert mgr.verify_and_consume(fp) is False
        assert mgr.count() == 0

    def test_request_returns_immediately(self, tmp_path):
        """fire-and-forget：request() 立即返回 False，不阻塞调用方。"""
        calls = []
        ch = self._channel(tmp_path, lambda fp: calls.append(fp))
        t0 = time.monotonic()
        r = ch.request("删除文件？", "fp-x")
        assert r is False
        assert time.monotonic() - t0 < 0.3
        assert ch.last_request["fingerprint"] == "fp-x"
        assert "删除文件" in ch.last_request["description"]

    def test_approve_issues_token_via_callback(self, tmp_path):
        """人类批准 → 回调签发令牌；AI 通道全程只见 False。"""
        approved = []
        ch = self._channel(tmp_path, lambda fp: approved.append(fp))
        ch.request("危险键 alt+f4", "fp-a")
        rp = ch.last_request["result_path"]
        open(rp, "w", encoding="utf-8").write("approve")
        for _ in range(60):
            if approved:
                break
            time.sleep(0.05)
        assert approved == ["fp-a"]

    def test_deny_no_token(self, tmp_path):
        approved = []
        ch = self._channel(tmp_path, lambda fp: approved.append(fp))
        ch.request("危险键", "fp-d")
        open(ch.last_request["result_path"], "w", encoding="utf-8").write("deny")
        time.sleep(0.4)
        assert approved == []

    def test_timeout_no_token(self, tmp_path):
        """倒计时结束无人操作 = 默认拒绝（fail-closed）。"""
        approved = []
        ch = self._channel(tmp_path, lambda fp: approved.append(fp), timeout=0.3)
        ch.request("危险键", "fp-t")
        time.sleep(0.8)
        assert approved == []


# ---------- 弹窗去重（同指纹在途不重复弹） ----------

class TestApprovalDedup:
    def _channel(self, tmp_path, spawns, timeout=5.0):
        return TkApprovalChannel(
            on_approved=lambda fp: None, timeout=timeout,
            popen_factory=lambda *a, **k: spawns.append(a[0] if a else None),
            result_root=str(tmp_path))

    def test_same_fingerprint_pending_spawns_once(self, tmp_path):
        """同一操作指纹已有弹窗在途时，AI 重试不得再弹新窗。"""
        spawns = []
        ch = self._channel(tmp_path, spawns)
        for _ in range(3):
            ch.request("危险键 alt+f4", "fp-same")
        assert len(spawns) == 1

    def test_different_fingerprints_spawn_each(self, tmp_path):
        spawns = []
        ch = self._channel(tmp_path, spawns)
        ch.request("操作 A", "fp-1")
        ch.request("操作 B", "fp-2")
        assert len(spawns) == 2

    def test_respawn_after_result_consumed(self, tmp_path):
        """在途弹窗被批复后，同指纹再次请求应重新弹窗（新的一轮审批）。"""
        spawns = []
        ch = self._channel(tmp_path, spawns, timeout=5.0)
        ch.request("危险键", "fp-r")
        open(ch.last_request["result_path"], "w", encoding="utf-8").write("deny")
        for _ in range(40):
            if len(spawns) or True:
                time.sleep(0.05)
                break
        time.sleep(0.4)                      # 等轮询线程消费结果
        ch.request("危险键", "fp-r")
        assert len(spawns) == 2

    def test_respawn_after_timeout(self, tmp_path):
        """在途弹窗超时后，同指纹再次请求应重新弹窗。"""
        spawns = []
        ch = self._channel(tmp_path, spawns, timeout=0.3)
        ch.request("危险键", "fp-to")
        time.sleep(0.6)
        ch.request("危险键", "fp-to")
        assert len(spawns) == 2


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
            on_approved=lambda fp: None,
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
            on_approved=lambda fp: None,
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


# ---------- 审批弹窗落位（右下角 toast，滑入起点屏外） ----------

class TestToastPlacement:
    def test_bottom_right_with_margins(self):
        from deskpilot.approval_dialog import _toast_placement
        x, y_start, y_final = _toast_placement(2560, 1440, 440, 210)
        assert x == 2560 - 440 - 16
        assert y_final == 1440 - 210 - 48 - 16      # 任务栏 + 边距
        assert y_start == 1440                       # 滑入起点：屏外底部

    def test_default_size_bottom_right(self):
        """默认 480×216 尺寸的落位（Fluent toast 规格）。"""
        from deskpilot.approval_dialog import _toast_placement
        x, y_start, y_final = _toast_placement(2560, 1440)
        assert x == 2560 - 480 - 16
        assert y_final == 1440 - 216 - 48 - 16
        assert y_start == 1440

    def test_small_screen_clamps_nonnegative(self):
        from deskpilot.approval_dialog import _toast_placement
        x, _, y_final = _toast_placement(300, 200, 440, 210)
        assert x == 0
        assert y_final == 0


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
