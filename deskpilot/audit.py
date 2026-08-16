"""审计层程序（详细设计 §10）。

JSONL append-only；同步落盘（flush + fsync），写失败抛 AuditFailure（操作视为失败）；
目录布局：audit/logs/（按日期滚动）+ audit/shots/（截图证据）。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .errors import AuditFailure  # noqa: F401  （供调用方捕获）
from .models import AuditEntry

_DIGEST_MAX = 200  # 参数摘要截断长度（展示用；全文留存于 params_full）


class AuditLogger:
    """审计记录组装与落盘。"""

    def __init__(self, audit_dir: str):
        self._dir = audit_dir
        self._seq = 0

    def record(self, entry: AuditEntry) -> None:
        """追加一条审计记录。

        params_digest 超 200 字符截断（仅影响展示字段）；params_full 全文保留。
        落盘失败抛 AuditFailure。
        """
        record = asdict(entry)
        record["params_digest"] = record["params_digest"][:_DIGEST_MAX]
        self._write_line(record)

    def record_event(self, event: str, detail: str = "") -> None:
        """记录特殊事件（服务启停、急停触发/复位、策略加载结果等）。"""
        self._write_line({"event": event, "detail": detail})

    def _write_line(self, record: dict) -> None:
        self._seq += 1
        record["seq"] = self._seq
        record["timestamp"] = datetime.now().astimezone().isoformat()
        line = json.dumps(record, ensure_ascii=False)
        try:
            log_dir = Path(self._dir) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            day = datetime.now().strftime("%Y%m%d")
            path = log_dir / f"audit-{day}.jsonl"
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())   # 同步落盘（§10.3）
        except OSError as e:
            raise AuditFailure(f"审计落盘失败: {e}") from e
