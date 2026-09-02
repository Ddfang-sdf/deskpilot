"""ISS-0008 性能基准脚本测试（TC-BM-01~05,2026-09-01 评审通过）。

层级：TC-BM-01/02 单元（返回结构直出）；TC-BM-03~05 集成（真实 daemon/
真实窗口/真实进程，断言在系统外表面：/health、FindWindowW、数值）。
入口（设计）：scripts/benchmark_iss8.py measure_all / main。
"""

from __future__ import annotations

import importlib.util
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BM = ROOT / "scripts" / "benchmark_iss8.py"

EXPECTED_KEYS = {
    "cold_start_s", "l0_latency_ms", "health_during_approval_ms",
    "dialog_thread_ms", "dialog_subprocess_ms", "jpeg_encode_speedup_pct",
    "png_vs_jpeg_size", "exe_size_mb", "daemon_rss_mb",
}


def _load():
    spec = importlib.util.spec_from_file_location("benchmark_iss8", BM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def result():
    """module 级一次实测（约 1~2 分钟；行为含 daemon 恢复与弹窗清理）。"""
    return _load().measure_all()


class TestStructure:
    """TC-BM-01/02:输出结构与采样规格(直出)。"""

    def test_bm01_keys_and_fields(self, result):
        assert set(result.keys()) == EXPECTED_KEYS
        for k, v in result.items():
            assert set(v.keys()) >= {"value", "unit", "method"}, k

    def test_bm02_sample_counts(self, result):
        assert result["l0_latency_ms"]["samples"] == 10
        assert result["health_during_approval_ms"]["samples"] == 5


@pytest.mark.integration
class TestSmokeIntegration:
    """TC-BM-03~05:冒烟合理/daemon 恢复/弹窗清理(集成,系统外表面直出)。"""

    def test_bm03_reasonable_values(self, result):
        assert 0 < result["l0_latency_ms"]["value"] < 500
        # 弹窗可见延迟受整机负载影响有波动(实测 100~800ms);
        # 断言只挡"子进程路径级"回退(≥2.5s),报告值为准
        assert result["dialog_thread_ms"]["value"] < 2000

    def test_bm04_daemon_restored(self, result):
        with urllib.request.urlopen("http://127.0.0.1:9420/health",
                                    timeout=3) as resp:
            assert resp.status == 200                     # 测完 daemon 在线

    def test_bm05_no_leftover_dialog(self, result):
        import ctypes
        u32 = ctypes.windll.user32
        assert u32.FindWindowW(None, "DeskPilot 入白审批") == 0
        assert u32.FindWindowW(None, "DeskPilot 审批") == 0
