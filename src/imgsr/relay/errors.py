"""Relay error type and HTTP status classification."""

from __future__ import annotations

import json


class RelayError(Exception):
    def __init__(self, message: str, *, kind: str, retryable: bool, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.retryable = retryable
        self.status = status


def _upstream_message(body: str) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:300]
        if isinstance(err, str):
            return err[:300]
    return body.strip()[:200] or "empty body"


def classify(status: int, body: str) -> RelayError:
    if status in (429, 503):
        return RelayError(f"上游繁忙：{_upstream_message(body)}", kind="busy", retryable=True, status=status)
    if status in (401, 403):
        return RelayError(f"上游拒绝鉴权：{_upstream_message(body)}", kind="auth", retryable=False, status=status)
    if 400 <= status < 500:
        return RelayError(f"上游拒绝请求：{_upstream_message(body)}", kind="rejected", retryable=False, status=status)
    return RelayError(f"上游错误 {status}", kind="upstream", retryable=True, status=status)
