"""审批管理程序（详细设计 §7）。

核心约束：令牌全程在服务内部流转（审批通道 → 强制层），不经 AI。
AI 获批后以完全相同参数原样重试，闸四按操作指纹查证并一次性消费。
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Callable, Mapping, Protocol

from .models import ApprovalToken


def _normalize_value(value: Any) -> str:
    """参数值规范化：字符串去首尾空白；数值统一格式；布尔小写；其余 JSON 定序。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def compute_fingerprint(tool: str, params: Mapping[str, Any]) -> str:
    """计算操作指纹（详细设计 §7.6）。

    参数规范化（键名排序、去首尾空白、数值统一格式）后拼接，取 SHA-256
    十六进制前 32 位。一个字符不同即指纹不同。
    """
    canonical = "\n".join(
        [f"tool={tool}"]
        + [f"{k}={_normalize_value(params[k])}" for k in sorted(params)]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


class ApprovalChannel(Protocol):
    """本地审批通道（M3 弹窗 / 测试模拟审批器），同步裁决语义（ISS-0003）。"""

    def request(self, description: str, fingerprint: str,
                image_path: str | None = None) -> str:
        """向人类请求批准并同步等待裁决；返回 "approve" / "deny" / "timeout"。

        image_path：目标窗口实拍图（可选），供弹窗展示"操作的是哪个窗口"。
        """
        ...


class DenyAllChannel:
    """M1 生产通道：无弹窗，一切 L3 恒拒绝（详细设计 §7.11）。"""

    def request(self, description: str, fingerprint: str,
                image_path: str | None = None) -> str:
        return "deny"


class ApprovalManager:
    """审批令牌的签发、按指纹校验、一次性消费、过期清理。"""

    def __init__(self, channel: ApprovalChannel, ttl_seconds: float, clock: Callable[[], float]):
        self._channel = channel
        self._ttl = ttl_seconds
        self._clock = clock
        self._tokens: dict[str, ApprovalToken] = {}

    def request_approval(self, description: str, fingerprint: str,
                         image_path: str | None = None) -> str:
        """经审批通道同步请求人类裁决；批准则在服务内部签发授权记录（不经 AI）。

        返回 "approve" / "deny" / "timeout"（ISS-0003 同步阻塞模型）。
        """
        decision = self._channel.request(description, fingerprint,
                                         image_path=image_path)
        if decision == "approve":
            self.issue_token(fingerprint)
        return decision

    def set_channel(self, channel: ApprovalChannel) -> None:
        """替换审批通道（main 装配 M3 弹窗通道用）。"""
        self._channel = channel

    def issue_token(self, fingerprint: str) -> ApprovalToken:
        """签发审批令牌（M3 异步弹窗通道的人类批准回调路径）。

        令牌不经 AI：签发权只经本地审批通道触达本方法。
        """
        now = self._clock()
        token = ApprovalToken(
            token_id=secrets.token_urlsafe(24),
            fingerprint=fingerprint,
            issued_at=now,
            expires_at=now + self._ttl,
        )
        self._tokens[token.token_id] = token
        return token

    def verify_and_consume(self, fingerprint: str) -> bool:
        """按指纹查证令牌：存在 ∧ 未消费 ∧ 未过期 → 通过并标记消费。

        先校验全部条件，最后才标记消费——指纹不匹配的请求不消耗令牌（§7.7）。
        """
        now = self._clock()
        for token in self._tokens.values():
            if token.fingerprint != fingerprint:
                continue
            if token.consumed or now > token.expires_at:
                continue
            token.consumed = True
            return True
        return False

    def count(self) -> int:
        """当前有效令牌数量（测试观测口；已消费/过期不计）。"""
        now = self._clock()
        return sum(1 for t in self._tokens.values()
                   if not t.consumed and now <= t.expires_at)
