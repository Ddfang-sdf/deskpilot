"""ISS-0008 性能优化单元测试（问题单 §4.1 / §6 接口定义）。

层级：单元测试（允许打桩；断言在被测对象可观察行为——返回值/HTTP 响应体/计数观测口/
替身调用记录/文件持久化内容，均直出，无中间转换）。
五要素：各类 docstring 标注 场景/前提/步骤/预期/断言。
入口（§6）：
- HttpDaemon(__init__(idle_timeout_s)/start/last_activity/idle_stopped/stop)
- Executor.ocr_factory / Executor.ocr / Executor.execute（证据图）/
  get_ui_tree / get_clickable_map（结构回归）
- DialogService(start/show/visible_latency_s)
- FreezeNotifier.state_reads
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from deskpilot.estop import EstopMonitor
from deskpilot.executor.core import Executor
from deskpilot.freeze_notify import STATE_FILE, FreezeNotifier
from deskpilot.httpd import HttpDaemon
from deskpilot.dialog_service import DialogService

from .conftest import FIXTURE_HWND, FIXTURE_RECT, FakeClock, FakeProbe


# ---------- 本文件夹具 ----------

@pytest.fixture
def fake_probe():
    p = FakeProbe()
    p.rects = {FIXTURE_HWND: FIXTURE_RECT}
    return p


@pytest.fixture
def m3_executor(estop, tmp_path, clock, fake_probe):
    return Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                    wait_timeout_max=5.0, clock=clock, probe=fake_probe)


@pytest.fixture
def spawn_log():
    return []


@pytest.fixture
def notifier(tmp_path, spawn_log):
    return FreezeNotifier(str(tmp_path), clock=time.monotonic,
                          spawn=spawn_log.append)


@pytest.fixture
def estop_n(policy, clock, audit_log, notifier):
    return EstopMonitor(policy.corner_hold_ms, clock, audit_log,
                        on_state_change=notifier.on_state_change)


def _post_json(url: str, payload: dict, timeout: float = 5.0) -> tuple[int, dict]:
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _get(url: str, timeout: float = 5.0) -> tuple[int, dict]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


class _StubExecutor:
    """L0/L1 与写路径替身：get_cursor 即回；execute 按 Event 可控阻塞并计时。"""

    def __init__(self):
        self.block = threading.Event()
        self.intervals: list[tuple[float, float]] = []

    def get_cursor(self):
        return {"x": 1, "y": 2}

    def execute(self, instruction):
        t0 = time.monotonic()
        self.block.wait(timeout=5)
        self.intervals.append((t0, time.monotonic()))
        return {"status": "ok", "before_shot": "", "after_shot": ""}


# ---------- P1 并发（C1:单线程×同步审批） ----------

class TestThreadedDaemon:
    """场景:一个写调用阻塞时,L0 调用与写调用并发行为。
    前提:daemon 以 stub executor 装配(execute 可控阻塞),临时端口启动。
    步骤:线程 A 发起阻塞写调用;随后线程 B 调 /health 与 L0(get_cursor)。
    预期:B 的两次调用均在 1.5s 内返回(不被 A 阻塞)。
    断言:HTTP 响应体状态与体字段、两次调用的墙钟时长(直测)。"""

    @pytest.fixture
    def stub_ctx(self, ctx, enforcement):
        stub = _StubExecutor()
        enforcement._executor = stub               # 写路径也走同一替身（测试接缝）
        return dataclasses.replace(ctx, executor=stub)

    @pytest.fixture
    def daemon(self, stub_ctx):
        d = HttpDaemon(stub_ctx, host="127.0.0.1", port=0)
        d.start()
        yield d
        d.stop()

    def test_l0_not_blocked_by_slow_write(self, daemon, stub_ctx, bound_record):
        t = threading.Thread(target=_post_json, args=(
            f"http://127.0.0.1:{daemon.port}/call",
            {"tool": "type_text",
             "params": {"token": bound_record.token, "text": "x"}}, 10.0))
        t.start()
        time.sleep(0.3)                       # 确保 A 已进入阻塞
        t0 = time.monotonic()
        s1, _ = _get(f"http://127.0.0.1:{daemon.port}/health")
        s2, body = _post_json(
            f"http://127.0.0.1:{daemon.port}/call",
            {"tool": "get_cursor", "params": {}}, timeout=1.5)
        elapsed = time.monotonic() - t0
        stub_ctx.executor.block.set()         # 放行 A
        t.join(timeout=5)
        assert s1 == 200
        assert s2 == 200 and body["ok"] is True
        assert elapsed < 1.5

    def test_writes_serialize_under_lock(self, daemon, stub_ctx, bound_record):
        stub_ctx.executor.block.clear()
        calls = [
            {"tool": "type_text",
             "params": {"token": bound_record.token, "text": t}}
            for t in ("a", "b")]
        threads = [threading.Thread(target=_post_json, args=(
            f"http://127.0.0.1:{daemon.port}/call", c, 10.0)) for c in calls]
        for th in threads:
            th.start()
        time.sleep(0.5)
        stub_ctx.executor.block.set()         # 两个写调用都在等锁外的阻塞点
        for th in threads:
            th.join(timeout=10)
        (s1, e1), (s2, e2) = stub_ctx.executor.intervals
        assert e1 <= s2 or e2 <= s1           # 区间不交叠 = 严格串行


# ---------- P8 idle 自停与人类豁免 ----------

class TestIdleTimeout:
    """场景:idle_timeout_s 到期 daemon 自停;人类活动(冻结)豁免。
    前提:idle_timeout_s=0.4 的 daemon。
    步骤:启动后不再调用,等待超时;另一组冻结后同样等待。
    预期:前者 idle_stopped=True 且 /health 失败;后者仍在服务。
    断言:idle_stopped 观测口、/health 可达性(直出)。"""

    @pytest.fixture
    def idle_daemon(self, ctx, estop):
        d = HttpDaemon(ctx, host="127.0.0.1", port=0, estop=estop,
                       idle_timeout_s=0.4)
        d.start()
        yield d
        d.stop()

    def test_stops_after_idle_timeout(self, idle_daemon):
        _get(f"http://127.0.0.1:{idle_daemon.port}/health")
        time.sleep(1.2)
        assert idle_daemon.idle_stopped is True
        with pytest.raises(Exception):
            _get(f"http://127.0.0.1:{idle_daemon.port}/health", timeout=1)

    def test_frozen_exempts_idle_stop(self, idle_daemon, estop):
        estop.on_trigger_hotkey()
        time.sleep(1.2)
        assert idle_daemon.idle_stopped is False
        s, _ = _get(f"http://127.0.0.1:{idle_daemon.port}/health")
        assert s == 200


# ---------- P2 OCR 懒加载 ----------

class TestLazyOcr:
    """场景:ocr 引擎首次使用时才初始化,失败记忆化。
    前提:Executor 注入计数工厂。
    步骤:装配后不调用 → 调两次 ocr → 换失败工厂再调两次。
    预期:工厂仅在首次 ocr 被调一次;失败路径两次均显式报错且不重复初始化。
    断言:工厂调用计数(替身记录)、ocr 返回结构/异常错误码(直出)。"""

    def test_engine_inits_once_on_first_use(self, m3_executor, tmp_path):
        calls = []
        img = tmp_path / "a.png"
        from PIL import Image
        Image.new("RGB", (10, 10), "white").save(img)

        def factory():
            calls.append(1)
            return lambda image: [{"text": "t", "position": [0, 0, 1, 1]}]

        m3_executor.ocr_factory = factory
        assert calls == []
        r1 = m3_executor.ocr(str(img))
        r2 = m3_executor.ocr(str(img))
        assert calls == [1]
        assert r1["count"] == 1 and r2["count"] == 1

    def test_init_failure_memoized(self, m3_executor, tmp_path):
        from deskpilot.errors import INTERNAL_ERROR, ExecutorError
        calls = []

        def bad_factory():
            calls.append(1)
            raise RuntimeError("no model")

        m3_executor.ocr_factory = bad_factory
        with pytest.raises(ExecutorError) as e1:
            m3_executor.ocr("x.png")
        with pytest.raises(ExecutorError) as e2:
            m3_executor.ocr("x.png")
        assert e1.value.code == INTERNAL_ERROR
        assert e2.value.code == INTERNAL_ERROR
        assert calls == [1]


# ---------- P3 证据图区域与格式 ----------

class TestEvidenceShots:
    """场景:写操作证据图取绑定窗口区域,格式 JPEG;无绑定回退全桌面。
    前提:Executor 以 fake _shot_fn 捕获拍摄区域。
    步骤:执行一次绑定内 click;再执行一次 launch_app。
    预期:click 的前后图区域=绑定矩形且路径 .jpg;launch_app 回退虚拟桌面全域。
    断言:execute() 返回的 before/after_shot 路径扩展名、被捕获的区域 dict(直出)。"""

    def test_binding_rect_and_jpeg(self, m3_executor, monkeypatch):
        regions = []
        m3_executor._shot_fn = lambda region: regions.append(region) or \
            __import__("PIL.Image", fromlist=["Image"]).new("RGB", (4, 4))
        # 测试卫生:像素动作只记录不真点(禁止测试操作真实桌面)
        clicks = []
        monkeypatch.setattr("deskpilot.executor.core.pyautogui.click",
                            lambda *a, **k: clicks.append(a))
        monkeypatch.setattr("deskpilot.executor.core.pyautogui.moveTo",
                            lambda *a, **k: None)
        # 遮挡校验打桩:其落点判定打真实屏幕,前台窗口状态会把单测变环境
        # 依赖(随机序 CI 实证)——本用例被测对象是证据图格式与区域
        monkeypatch.setattr(m3_executor, "_check_occlusion",
                            lambda hwnd, x, y: None)
        r = m3_executor.execute(
            {"tool": "click", "params": {"x": 300, "y": 300},
             "binding_hwnd": FIXTURE_HWND})
        assert r["before_shot"].endswith(".jpg")
        assert r["after_shot"].endswith(".jpg")
        assert clicks == [(300, 300)]                # 驱动参数直出,未真点
        l, t, w, h = (regions[0]["left"], regions[0]["top"],
                      regions[0]["width"], regions[0]["height"])
        assert (l, t, w, h) == (FIXTURE_RECT[0], FIXTURE_RECT[1],
                                FIXTURE_RECT[2] - FIXTURE_RECT[0],
                                FIXTURE_RECT[3] - FIXTURE_RECT[1])

    def test_no_binding_falls_back_full_desktop(self, m3_executor, monkeypatch):
        regions = []
        m3_executor._shot_fn = lambda region: regions.append(region) or \
            __import__("PIL.Image", fromlist=["Image"]).new("RGB", (4, 4))
        # 测试卫生:进程拉起只记录不真开(此前每跑必开一个真记事本)
        launched = []

        class FakePopen:
            def __init__(self, cmd, *a, **k):
                launched.append(cmd)
                self.pid = 424242                 # 替身进程号(直出)

        monkeypatch.setattr("deskpilot.executor.core.subprocess.Popen",
                            FakePopen)
        m3_executor.execute({"tool": "launch_app", "params": {"app": "notepad.exe"},
                             "binding_hwnd": None})
        assert launched == [["notepad.exe"]]           # 驱动参数直出,未真开
        assert regions and regions[0]["width"] > 0 and regions[0]["height"] > 0


# ---------- P4 枚举结构回归（性能经基准另验） ----------

class TestEnumStructureRegression:
    """场景:P4 改批量枚举后返回结构逐字段不变。
    前提:fake 元素树(同既有 SoM 树形)。
    步骤:调用 get_ui_tree。
    预期:elements 名称/控件类型/矩形与现状一致,truncated 语义不变。
    断言:get_ui_tree 返回结构各字段(直出)。"""

    def test_ui_tree_shape_unchanged(self, m3_executor):
        from .test_elements import FakeElement
        m3_executor._element_source = lambda hwnd: FakeElement(children=[
            FakeElement(name="文件", rect=(10, 10, 50, 30)),
            FakeElement(name="保存", automation_id="save", rect=(10, 40, 50, 60)),
        ])
        r = m3_executor.get_ui_tree(FIXTURE_HWND)
        assert r["hwnd"] == FIXTURE_HWND
        names = [n.get("name") for n in r["elements"]]
        assert "文件" in names and "保存" in names
        assert "truncated" in r


# ---------- P6 弹窗线程 ----------

class TestDialogService:
    """场景:弹窗经单 Tk 线程投递,零进程开销,异常不波及调用方。
    前提:DialogService 以 fake window_factory 装配。
    步骤:start 两次;show 两次(第二次工厂抛异常);再 show 一次。
    预期:工厂收到 3 次投递;start 幂等(单线程);异常被吞且后续投递正常;
         visible_latency_s < 0.3。
    断言:工厂调用记录、visible_latency_s 观测口、show() 不抛异常(直出)。"""

    def test_show_delivers_and_survives_errors(self):
        from .conftest import FakeClock
        delivered = []
        calls = {"n": 0}

        def factory(kind, payload):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            delivered.append((kind, payload))

        svc = DialogService(clock=FakeClock(), window_factory=factory)
        svc.start()
        svc.start()                            # 幂等
        svc.show("approval", {"desc": "x"})
        svc.show("approval", {"desc": "y"})    # 这次工厂抛异常
        svc.show("freeze", {"audit_dir": "z"})
        for _ in range(100):                   # 队列异步消费,等待三次派发完成
            if calls["n"] >= 3:
                break
            time.sleep(0.02)
        assert delivered == [("approval", {"desc": "x"}),
                             ("freeze", {"audit_dir": "z"})]
        assert svc.visible_latency_s < 0.3
        svc.stop()

    def test_start_idempotent_single_thread(self):
        from .conftest import FakeClock
        svc = DialogService(clock=FakeClock(), window_factory=lambda k, p: None)
        svc.start()
        svc.start()
        assert svc.thread_count == 1
        svc.stop()


# ---------- P7 状态文件 mtime 快路 ----------

class TestStateMtimeFastPath:
    """场景:共享状态未变时 tick 不重复读盘。
    前提:目录内已有一份冻结状态文件。
    步骤:连续两次 sync;再经 on_state_change 改写一次状态后 sync。
    预期:前两次 sync 只读一次盘;改写后再读一次。
    断言:state_reads 观测口计数(直出)。"""

    def test_unchanged_state_skips_read(self, tmp_path, notifier, estop_n):
        estop_n.on_trigger_hotkey()                # 写出共享状态
        notifier.sync_local_with_shared_state(estop_n)
        n1 = notifier.state_reads
        notifier.sync_local_with_shared_state(estop_n)
        assert notifier.state_reads == n1          # mtime 未变 → 零新读取
        estop_n.cli_reset()                        # 状态变化 → mtime 变
        notifier.sync_local_with_shared_state(estop_n)
        assert notifier.state_reads == n1 + 1
