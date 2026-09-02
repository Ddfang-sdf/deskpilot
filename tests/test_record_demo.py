"""record_demo 录制工具测试(2026-09-02,演示 GIF 重录配套)。

层级:单元(合成帧注入,不触真实屏幕)。
入口(设计):scripts/record_demo.py capture_frames / downscale / save_gif。
断言:返回值与产物文件(PIL 直读)——直出。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REC = ROOT / "scripts" / "record_demo.py"


def _load():
    spec = importlib.util.spec_from_file_location("record_demo", REC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _synthetic(color):
    """合成帧源:每次调用返回一帧指定色的 800x600 图。"""
    return lambda: Image.new("RGB", (800, 600), color)


class TestCaptureFrames:
    """场景:注入帧源截帧。断言:帧数/尺寸(返回值直出)。"""

    def test_frame_count_matches_seconds_fps(self):
        rec = _load()
        frames = rec.capture_frames(1.0, 8, source=_synthetic((255, 0, 0)))
        assert len(frames) == 8
        assert frames[0].size == (800, 600)

    def test_minimum_one_frame(self):
        rec = _load()
        frames = rec.capture_frames(0.01, 1, source=_synthetic((0, 0, 0)))
        assert len(frames) == 1


class TestDownscale:
    """场景:等比缩放。断言:返回图尺寸(直出)。"""

    def test_scales_proportionally(self):
        rec = _load()
        out = rec.downscale(Image.new("RGB", (1920, 1080)), 960)
        assert out.size == (960, 540)

    def test_noop_when_narrower(self):
        rec = _load()
        img = Image.new("RGB", (640, 480))
        assert rec.downscale(img, 960) is img

    def test_noop_when_width_nonpositive(self):
        rec = _load()
        img = Image.new("RGB", (640, 480))
        assert rec.downscale(img, 0) is img


class TestSaveGif:
    """场景:合成帧写 gif。断言:产物文件 PIL 直读(帧数/尺寸/时长)与返回信息。"""

    def test_gif_frames_size_duration(self, tmp_path):
        rec = _load()
        frames = [Image.new("RGB", (800, 600), (i * 40, 0, 0))
                  for i in range(6)]
        out = tmp_path / "t.gif"
        info = rec.save_gif(frames, out, fps=5, width=400)
        assert info["frames"] == 6
        assert info["size_bytes"] == out.stat().st_size   # 返回=实测(直出)
        with Image.open(out) as gif:
            assert gif.n_frames == 6                       # 帧数(产物直读)
            assert gif.size == (400, 300)                  # 已按宽等比(产物直读)
            assert gif.info["duration"] == 200             # 1000/5(产物直读)
            assert gif.info["loop"] == 0                   # 循环播放(产物直读)

    def test_empty_frames_rejected(self, tmp_path):
        rec = _load()
        try:
            rec.save_gif([], tmp_path / "x.gif", fps=5)
        except ValueError:
            return
        raise AssertionError("空帧列必须报错(fail-closed)")

    def test_colors_knob_shrinks_file(self, tmp_path):
        """colors=128 的文件不得大于 colors=256(体积控制旋钮有效)。"""
        rec = _load()
        frames = [Image.new("RGB", (800, 600), (i * 30, i * 20, i * 10))
                  for i in range(6)]
        big = rec.save_gif(frames, tmp_path / "b.gif", fps=5, colors=256)
        small = rec.save_gif(frames, tmp_path / "s.gif", fps=5, colors=128)
        assert small["size_bytes"] <= big["size_bytes"]

    def test_parent_dir_created(self, tmp_path):
        rec = _load()
        out = tmp_path / "a" / "b" / "t.gif"
        rec.save_gif([Image.new("RGB", (64, 64))], out, fps=5)
        assert out.exists()
