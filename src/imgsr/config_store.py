"""Admin-editable settings layered over environment defaults."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from imgsr.config import OVERRIDABLE, Settings
from imgsr.db.models import SettingRow, utcnow

_INT_RANGES: dict[str, tuple[int, int]] = {
    "pixel_cap": (100_000, 20_000_000),
    "upstream_concurrency": (1, 10),
    "max_upload_mb": (1, 100),
    "max_pixels": (1_000_000, 100_000_000),
}
_DEFAULT_RANGE = (0, 1_000_000)


class SettingsError(ValueError):
    """User-facing validation error."""


def _validate(key: str, value: Any) -> Any:
    kind = OVERRIDABLE.get(key)
    if kind is None:
        raise SettingsError(f"不支持修改的设置项：{key}")
    if kind is int:
        if isinstance(value, bool):
            raise SettingsError(f"{key} 必须是整数")
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise SettingsError(f"{key} 必须是整数") from None
        lo, hi = _INT_RANGES.get(key, _DEFAULT_RANGE)
        if not lo <= number <= hi:
            raise SettingsError(f"{key} 必须在 {lo} 到 {hi} 之间")
        return number
    text = str(value).strip()
    if not text or len(text) > 100:
        raise SettingsError(f"{key} 不能为空且不超过 100 字符")
    return text


class SettingsProvider:
    def __init__(self, base: Settings, session_factory: sessionmaker[Session]) -> None:
        self._base = base
        self._sf = session_factory

    def overrides(self) -> dict[str, Any]:
        with self._sf() as db:
            return {row.key: row.value for row in db.scalars(select(SettingRow))}

    def __call__(self) -> Settings:
        return self._base.with_overrides(self.overrides())

    def update(self, changes: dict[str, Any]) -> Settings:
        clean = {key: _validate(key, value) for key, value in changes.items()}
        with self._sf() as db:
            for key, value in clean.items():
                row = db.get(SettingRow, key)
                if row is None:
                    db.add(SettingRow(key=key, value=value))
                else:
                    row.value, row.updated_at = value, utcnow()
            db.commit()
        return self()
