"""Manual fallback: supply kill timestamps yourself (seconds)."""

from __future__ import annotations

from .template import KillEvent


def kills_from_timestamps(timestamps: list[float]) -> list[KillEvent]:
    return [KillEvent(time=round(float(t), 3), score=1.0, count=1)
            for t in sorted(timestamps)]
