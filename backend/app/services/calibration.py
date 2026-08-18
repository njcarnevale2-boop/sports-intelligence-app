from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List


_CALIBRATION_ARTIFACT = Path(__file__).resolve().parents[1] / "data" / "calibration" / "guarded_isotonic_v2026_preseason.json"


@dataclass(frozen=True)
class CalibrationInfo:
    status: str
    method: str
    version: str


@lru_cache(maxsize=1)
def _load_artifact() -> Dict[str, Any]:
    with _CALIBRATION_ARTIFACT.open("r", encoding="utf-8") as f:
        return json.load(f)


def calibration_info() -> CalibrationInfo:
    artifact = _load_artifact()
    return CalibrationInfo(
        status=str(artifact.get("calibrationStatus") or "INACTIVE"),
        method=str(artifact.get("calibrationMethod") or "UNKNOWN"),
        version=str(artifact.get("calibrationVersion") or "unknown-calibration-version"),
    )


def _clamp_probability(value: float) -> float:
    if value < 1e-6:
        return 1e-6
    if value > 1 - 1e-6:
        return 1 - 1e-6
    return value


def _to_unit_probability(value: float | None) -> float | None:
    if value is None:
        return None
    p = float(value)
    if p > 1.0:
        p = p / 100.0
    return _clamp_probability(p)


def _interpolate_isotonic(raw_probability: float, bins: List[Dict[str, Any]]) -> tuple[float, float]:
    # Use linear interpolation over frozen avgPredicted -> isotonicProbability control points.
    points = sorted(
        [
            (float(b["avgPredicted"]), float(b["isotonicProbability"]), float(b["n"]))
            for b in bins
        ],
        key=lambda x: x[0],
    )

    if raw_probability <= points[0][0]:
        return points[0][1], points[0][2]
    if raw_probability >= points[-1][0]:
        return points[-1][1], points[-1][2]

    for i in range(len(points) - 1):
        x0, y0, n0 = points[i]
        x1, y1, n1 = points[i + 1]
        if x0 <= raw_probability <= x1:
            width = x1 - x0
            t = 0.0 if width <= 0 else (raw_probability - x0) / width
            y = (1.0 - t) * y0 + t * y1
            n = (1.0 - t) * n0 + t * n1
            return y, n

    return points[-1][1], points[-1][2]


def apply_guarded_isotonic(raw_probability: float | None) -> float | None:
    unit = _to_unit_probability(raw_probability)
    if unit is None:
        return None

    artifact = _load_artifact()
    bins = artifact.get("bins") or []
    if not bins:
        return unit

    guard_k = float(artifact.get("guardK") or 60.0)
    iso, n_bin = _interpolate_isotonic(unit, bins)

    # Guard toward raw probability for sparse bins, mirroring guarded-isotonic intent.
    weight = n_bin / (n_bin + guard_k)
    calibrated = (weight * iso) + ((1.0 - weight) * unit)
    return _clamp_probability(calibrated)
