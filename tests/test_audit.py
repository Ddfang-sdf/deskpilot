"""审计层（AuditLogger）单元测试。

覆盖：TC-N-AUD-01/02/03、TC-S-AUD-03 机制、TC-S-AUD-05、TC-E-CC-03 关联（seq 连续）。
断言值来源：record/record_event 返回或抛出的异常、审计目录 JSONL 持久化数据。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deskpilot.audit import AuditLogger
from deskpilot.errors import AuditFailure
from deskpilot.models import AuditEntry

from .conftest import read_audit


def _entry(**kw) -> AuditEntry:
    base = dict(seq=0, timestamp="2026-08-16T00:00:00+08:00", tool="type_text",
                params_digest="text=hello", params_full="hello", level="L2",
                decision="放行", reason_code="", result="ok", duration_ms=12,
                before_shot="shots/b.png", after_shot="shots/a.png",
                binding_token="tok-1")
    base.update(kw)
    return AuditEntry(**base)


class TestRecord:
    def test_record_full_fields(self, tmp_path):
        """TC-N-AUD-01：记录字段完整落盘，逐字段读回一致。"""
        log = AuditLogger(str(tmp_path / "audit"))
        log.record(_entry())
        records = read_audit(str(tmp_path / "audit"))
        assert len(records) == 1
        r = records[0]
        for field in ("seq", "timestamp", "tool", "params_digest", "params_full",
                      "level", "decision", "reason_code", "result", "duration_ms",
                      "before_shot", "after_shot", "binding_token"):
            assert field in r, field
        assert r["tool"] == "type_text"
        assert r["before_shot"] == "shots/b.png"
        assert r["after_shot"] == "shots/a.png"
        assert r["duration_ms"] == 12

    def test_light_record_without_shots(self, tmp_path):
        """TC-N-AUD-02：L0 轻量记录无截图字段值。"""
        log = AuditLogger(str(tmp_path / "audit"))
        log.record(_entry(tool="screenshot", level="L0", before_shot="",
                          after_shot="", binding_token=""))
        r = read_audit(str(tmp_path / "audit"))[0]
        assert r["before_shot"] == "" and r["after_shot"] == ""
        assert r["level"] == "L0"

    def test_digest_truncated_full_kept(self, tmp_path):
        """TC-N-AUD-03 + TC-S-AUD-05：摘要截断至 200，全文完整保留。"""
        log = AuditLogger(str(tmp_path / "audit"))
        long_text = "密" * 5000
        log.record(_entry(params_digest="x" * 5000, params_full=long_text))
        r = read_audit(str(tmp_path / "audit"))[0]
        assert len(r["params_digest"]) <= 200
        assert r["params_full"] == long_text

    def test_seq_continuous(self, tmp_path):
        """TC-E-CC-03 关联：seq 单调连续无空洞。"""
        log = AuditLogger(str(tmp_path / "audit"))
        for _ in range(3):
            log.record(_entry())
        seqs = [r["seq"] for r in read_audit(str(tmp_path / "audit"))]
        assert seqs == [1, 2, 3]

    def test_jsonl_one_line_per_record(self, tmp_path):
        """每条记录一行 JSONL，逐行可解析。"""
        log = AuditLogger(str(tmp_path / "audit"))
        log.record(_entry())
        log.record(_entry(tool="key"))
        log_dir = Path(str(tmp_path / "audit")) / "logs"
        lines = []
        for f in log_dir.glob("*.jsonl"):
            lines += [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2
        for line in lines:
            json.loads(line)                       # 不抛异常即合法 JSON

    def test_record_event(self, tmp_path):
        """特殊事件记录（服务启停、急停触发/复位、策略加载）。"""
        log = AuditLogger(str(tmp_path / "audit"))
        log.record_event("服务启动", "policy 加载成功")
        log.record_event("急停触发")
        events = [r for r in read_audit(str(tmp_path / "audit")) if r.get("event")]
        assert [e["event"] for e in events] == ["服务启动", "急停触发"]


class TestFailureSemantics:
    def test_write_failure_raises_audit_failure(self, tmp_path):
        """TC-S-AUD-03 机制：目录不可创建/不可写 → record 抛 AuditFailure。"""
        blocker = tmp_path / "blocker"
        blocker.write_text("i am a file", encoding="utf-8")
        log = AuditLogger(str(blocker / "audit"))   # 父路径是文件 → 不可建目录
        with pytest.raises(AuditFailure):
            log.record(_entry())

    def test_append_only_surface(self, tmp_path):
        """TC-S-AUD-04 关联：对外无修改/删除记录的入口。"""
        log = AuditLogger(str(tmp_path / "audit"))
        for forbidden in ("update", "delete", "remove", "rewrite", "truncate"):
            assert not hasattr(log, forbidden), forbidden
