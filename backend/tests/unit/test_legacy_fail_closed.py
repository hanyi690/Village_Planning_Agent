"""Wave A.1: mapping-style EXECUTE chain is fail-closed without legacy switch."""

from __future__ import annotations

import pytest


def test_mip_allocator_blocked_without_legacy(monkeypatch):
    monkeypatch.delenv("GIS_LEGACY_MAPPING", raising=False)
    from app.modules.schema.advisory_crosswalks.legacy import require_legacy, LegacyBlocked
    with pytest.raises(LegacyBlocked):
        require_legacy("test")


def test_legacy_enabled_with_switch(monkeypatch):
    monkeypatch.setenv("GIS_LEGACY_MAPPING", "1")
    from app.modules.schema.advisory_crosswalks.legacy import legacy_enabled
    assert legacy_enabled() is True


def test_legacy_exports_from_advisory_crosswalks():
    from app.modules.schema.advisory_crosswalks import (
        legacy_enabled,
        require_legacy,
        LegacyBlocked,
    )
    assert callable(legacy_enabled)
    assert callable(require_legacy)
    assert issubclass(LegacyBlocked, Exception)


def test_legacy_modules_removed_in_wave_i():
    """Wave I deleted the legacy mapping modules; they must not be importable."""
    with pytest.raises(ModuleNotFoundError):
        from app.tools.gis._generation.zone_type_deriver import derive_zone_types  # noqa: F401
    with pytest.raises(ModuleNotFoundError):
        from app.tools.gis._generation.optimizer.mip_allocator import MIPZoneAllocator  # noqa: F401
