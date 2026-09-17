from __future__ import annotations

from dataclasses import dataclass


HFA = 1.5
K = 0.07
ERROR_CAP = 21.0
GAME_SHRINK = 0.985
UPDATER_VERSION = "sia_power_engine_2e4a_v1"


@dataclass(frozen=True)
class FrozenMethodology:
    hfa: float = HFA
    k: float = K
    error_cap: float = ERROR_CAP
    game_shrink: float = GAME_SHRINK

    def to_identity_payload(self) -> dict[str, float]:
        return {
            "hfa": float(self.hfa),
            "k": float(self.k),
            "errorCap": float(self.error_cap),
            "gameShrink": float(self.game_shrink),
        }


FROZEN_METHODOLOGY = FrozenMethodology()
