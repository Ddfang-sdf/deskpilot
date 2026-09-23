"""ISS-0102 screenshot 落盘路径参数测试(TC-102-01~07,问题单 §4 表)。

背景:素材生产需要「精确 region+落指定路径」截图;现 screenshot 只落
受管审计目录+内联,AI 被迫裸 PIL ImageGrab 绕行 MCP 面(2026-09-21
sdfang 怒批事件缺口之二)。设计=path 参数+允许根护栏(fail-closed)+
覆盖写留痕+冻结期 path 拒写;L0 级别保留。

层级分布(§4 表逐行落码):
- 单元:TC-102-01~06(真 Executor 真落盘真 mss——iss83 同规;替身仅
  FakeProbe/几何,允许根经构造入参 allowed_roots 传入,P1 空壳签名)
- 形态:TC-102-07(TOOL_SCHEMAS 注册表直读)

入口(设计):Executor.screenshot(scope,…,path=)/TOOL_SCHEMAS。
断言出处:盘上文件存在/像素尺寸/文件内容直读;返回值 path 直出;
异常 code 属性直出;真 AuditLogger JSONL 记录对象 event/detail 直读;
注册表 optional/描述直读——均直出,无中间转换。

空壳签名拟定(上报裁决点,P2 确认):Executor.__init__ 尾部增
`allowed_roots=None`(允许根集合=仓库根∪审计根,装配期 main.py 传入);
Executor.screenshot 尾部增 `path=None`;schema optional 增 "path": ("str",)。

P1 红态预期:TC-102-01~06 红(path 形参被忽略,落盘/护栏/留痕/冻结闸
均未实现——红精确落在未实现行为);TC-102-07 schema 半绿(path 声明已加)、
描述 path 语义半红(描述改写属 P3,拆分两函数各承其半)。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from deskpilot.errors import EMERGENCY_STOP, INVALID_PARAMS, ExecutorError
from deskpilot.executor.core import Executor
from deskpilot.mcp_server import TOOL_SCHEMAS

from deskpilot.audit_events import (
    EV_SCREENSHOT_OVERWRITE)
from .conftest import FakeProbe, read_audit


@pytest.fixture
def repo_root(tmp_path) -> Path:
    """允许根①:仓库根(policy.yml 所在目录语义,tmp 替身)。"""
    root = tmp_path / "repo"
    (root / "assets").mkdir(parents=True)
    return root


@pytest.fixture
def audit_root(tmp_path) -> Path:
    """允许根②:审计根(resolve_audit_dir 绝对值语义,tmp 替身)。"""
    root = tmp_path / "audit_root"
    (root / "custom").mkdir(parents=True)
    return root


@pytest.fixture
def ex(estop, tmp_path, clock, audit_log, repo_root, audit_root):
    """真 Executor+允许根两集合(构造入参,设计 §3.2 装配语义)。"""
    return Executor(estop, str(tmp_path / "audit"), poll_interval=0.02,
                    wait_timeout_max=5.0, clock=clock, probe=FakeProbe(),
                    audit=audit_log,
                    allowed_roots=(str(repo_root), str(audit_root)))


class TestPathLanding:
    """TC-102-01/02/04(单元,§3.3):path 落指定路径/相对锚仓库根/审计根放行。"""

    def test_tc102_01_absolute_path_lands_at_target(self, ex, repo_root):
        """TC-102-01(单元):screenshot(scope=region,rect=…,path=<root>/
        assets/x.png) → 文件落该路径;返回 path=该绝对路径。
        断言:盘上文件存在+像素尺寸直读;返回值直出。
        红态:path 形参被忽略,落受管 shots 目录,目标不存在。"""
        target = repo_root / "assets" / "x.png"
        r = ex.screenshot("region", rect=[0, 0, 10, 10], path=str(target))
        assert target.is_file(), "指定路径未落盘(盘上直读)"
        assert Image.open(target).size == (10, 10)     # 像素尺寸直读
        assert r["path"] == str(target)                # 返回值直出(绝对语义)

    def test_tc102_02_relative_path_anchors_repo_root(self, ex, repo_root):
        """TC-102-02(单元,§3.2):path="assets/x.png"(相对) → 锚仓库根
        落 <仓库根>/assets/x.png;返回该绝对路径。
        断言:盘上路径直读;返回值直出。
        红态:同上(path 被忽略)。"""
        target = repo_root / "assets" / "x.png"
        r = ex.screenshot("region", rect=[0, 0, 10, 10], path="assets/x.png")
        assert target.is_file(), "相对路径未锚仓库根落盘(盘上直读)"
        assert r["path"] == str(target)

    def test_tc102_04_audit_root_allowed(self, ex, audit_root):
        """TC-102-04(单元,§3.2):允许根=仓库根+审计根(两集合);
        path=<审计根>/custom/x.png → 放行落盘。
        断言:盘上文件存在直读。
        红态:同上(path 被忽略)。"""
        target = audit_root / "custom" / "x.png"
        ex.screenshot("region", rect=[0, 0, 10, 10], path=str(target))
        assert target.is_file(), "审计根下指定路径未放行(盘上直读)"


class TestGuardRails:
    """TC-102-03/05/06(单元,§3.2):越界 fail-closed/覆盖写留痕/冻结闸。"""

    def test_tc102_03_outside_and_traversal_fail_closed(self, ex, tmp_path,
                                                        repo_root):
        """TC-102-03(单元,§3.2 护栏):①path=允许根外绝对路径;
        ②path="../outside.png"(.. 穿越) → 均 ExecutorError INVALID_PARAMS;
        目标零创建。
        断言:异常 code 直出;盘上不存在直读。
        红态:无护栏,path 被忽略按受管落盘返回 ok(DID NOT RAISE)。"""
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        t1 = outside_dir / "x.png"
        with pytest.raises(ExecutorError) as e1:
            ex.screenshot("region", rect=[0, 0, 10, 10], path=str(t1))
        assert e1.value.code == INVALID_PARAMS    # 异常 code 直出
        assert not t1.exists(), "越界目标零创建(盘上直读)"

        t2 = tmp_path / "outside.png"             # <repo>/../outside.png
        with pytest.raises(ExecutorError) as e2:
            ex.screenshot("region", rect=[0, 0, 10, 10], path="../outside.png")
        assert e2.value.code == INVALID_PARAMS
        assert not t2.exists(), "穿越目标零创建(盘上直读)"

    def test_tc102_05_overwrite_audited(self, ex, repo_root, tmp_path):
        """TC-102-05(单元,§3.2 留痕):目标已存在(预置内容 OLD) →
        screenshot(path=同路径) 覆盖写前 record_event 留痕;内容被覆盖。
        断言:真 AuditLogger JSONL 记录对象 event/detail 直读;
        文件内容直读≠OLD。
        红态:path 被忽略,目标仍 OLD 且零「覆盖写」审计。"""
        target = repo_root / "assets" / "x.png"
        target.write_bytes(b"OLD")
        ex.screenshot("region", rect=[0, 0, 10, 10], path=str(target))
        events = read_audit(str(tmp_path / "audit"))
        overwrites = [e for e in events if e.get("event") == EV_SCREENSHOT_OVERWRITE]
        assert len(overwrites) == 1, \
            "覆盖写须审计留痕 record_event(记录对象直读)"
        assert str(target) in overwrites[0]["detail"]   # detail 直读
        assert target.read_bytes() != b"OLD", "内容须被覆盖(文件直读)"

    def test_tc102_06_frozen_rejects_path_allows_managed(self, ex, estop,
                                                         tmp_path, repo_root):
        """TC-102-06(单元,§3.2 裁决①):estop 已冻结 → ①path 给定拒
        EMERGENCY_STOP(「冻结期写操作全拒」补破口);②不给 path 放行
        落受管目录(现状零变化)。
        断言:①异常 code 直出;②返回值 path 直出。
        红态:①path 被忽略照常返回(DID NOT RAISE);②现绿。"""
        estop.on_trigger_hotkey()                # 前提:冻结态
        target = repo_root / "assets" / "frozen.png"
        with pytest.raises(ExecutorError) as ei:
            ex.screenshot("region", rect=[0, 0, 10, 10], path=str(target))
        assert ei.value.code == EMERGENCY_STOP    # 异常 code 直出
        assert not target.exists(), "冻结期 path 写零落盘(盘上直读)"
        r = ex.screenshot("region", rect=[0, 0, 10, 10])   # ②不给 path
        assert Path(r["path"]).is_file(), \
            "不给 path 现状零变化(受管落盘放行,返回值直出)"


class TestSchemaAndDescription:
    """TC-102-07(形态,§3.1):schema 注册表+描述钉(直读)。"""

    def test_tc102_07_schema_optional_has_path(self):
        """TC-102-07(形态,前半):TOOL_SCHEMAS["screenshot"]["optional"]
        含 path。断言:注册表直读。绿态:P1 空壳声明已加。"""
        assert "path" in TOOL_SCHEMAS["screenshot"]["optional"]

    def test_tc102_07_description_rewrite_keeps_pins(self):
        """TC-102-07(形态,后半):描述 ≤200;含 path 参数语义("path=");
        全部既有钉子串保留(「图像不可见」/「0=主屏」/screen+屏/
        region+精读/coverage 比例/首句领域+查看)。
        断言:注册表描述直读。红态:描述未改写(P3 范围),无「path=」。"""
        d = TOOL_SCHEMAS["screenshot"]["description"]
        assert len(d) <= 200
        assert "path=" in d, "描述须补 path 落盘参数语义(现 195/200 未改写)"
        assert "图像不可见" in d
        assert "0=主屏" in d
        assert "screen" in d and "屏" in d
        assert "region" in d and ("精读" in d or "局部" in d)
        assert "coverage" in d or "比例" in d
        assert "查看" in d                          # 首句领域+查看(bound04)
