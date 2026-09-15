from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class CanonicalSportsbook:
    canonical_key: str
    canonical_display: str
    approved_for_actionable: bool
    mapping_verified: bool
    aliases: frozenset[str]


def _normalize_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "".join(character for character in text if character.isalnum())


CANONICAL_SPORTSBOOKS: tuple[CanonicalSportsbook, ...] = (
    CanonicalSportsbook(
        canonical_key="draftkings",
        canonical_display="DraftKings",
        approved_for_actionable=True,
        mapping_verified=True,
        aliases=frozenset({"draftkings", "dk"}),
    ),
    CanonicalSportsbook(
        canonical_key="fanduel",
        canonical_display="FanDuel",
        approved_for_actionable=True,
        mapping_verified=True,
        aliases=frozenset({"fanduel", "fd"}),
    ),
    CanonicalSportsbook(
        canonical_key="betmgm",
        canonical_display="BetMGM",
        approved_for_actionable=True,
        mapping_verified=True,
        aliases=frozenset({"betmgm", "mgm"}),
    ),
    CanonicalSportsbook(
        canonical_key="fanatics",
        canonical_display="Fanatics Sportsbook",
        approved_for_actionable=True,
        mapping_verified=True,
        aliases=frozenset({"fanatics", "fanaticssportsbook"}),
    ),
    CanonicalSportsbook(
        canonical_key="betrivers",
        canonical_display="BetRivers",
        approved_for_actionable=True,
        mapping_verified=True,
        aliases=frozenset({"betrivers"}),
    ),
    CanonicalSportsbook(
        canonical_key="caesars",
        canonical_display="Caesars Sportsbook",
        approved_for_actionable=True,
        mapping_verified=True,
        aliases=frozenset({"caesars", "caesarssportsbook", "williamhillus", "czr"}),
    ),
    CanonicalSportsbook(
        canonical_key="bet365",
        canonical_display="bet365",
        approved_for_actionable=True,
        mapping_verified=False,
        aliases=frozenset({"bet365"}),
    ),
    CanonicalSportsbook(
        canonical_key="hardrockbet",
        canonical_display="Hard Rock Bet",
        approved_for_actionable=True,
        mapping_verified=False,
        aliases=frozenset({"hardrockbet"}),
    ),
    CanonicalSportsbook(
        canonical_key="thescorebet",
        canonical_display="theScore Bet",
        approved_for_actionable=True,
        mapping_verified=False,
        aliases=frozenset({"thescorebet"}),
    ),
)


_ALIAS_TO_CANONICAL: dict[str, CanonicalSportsbook] = {}
for sportsbook in CANONICAL_SPORTSBOOKS:
    for alias in sportsbook.aliases:
        _ALIAS_TO_CANONICAL[_normalize_token(alias)] = sportsbook


def resolve_canonical_sportsbook(value: Any) -> dict[str, Any]:
    provider_title = str(value or "").strip()
    normalized = _normalize_token(provider_title)
    canonical = _ALIAS_TO_CANONICAL.get(normalized)

    if canonical is None:
        return {
            "providerTitle": provider_title or None,
            "normalizedToken": normalized,
            "canonicalKey": None,
            "canonicalDisplay": None,
            "approvedForActionable": False,
            "mappingVerified": False,
            "actionableAllowed": False,
            "knownSportsbook": False,
            "status": "UNKNOWN",
        }

    approved = bool(canonical.approved_for_actionable)
    verified = bool(canonical.mapping_verified)
    actionable_allowed = approved and verified

    if not verified:
        status = "PENDING_VERIFICATION"
    elif not approved:
        status = "KNOWN_UNAPPROVED"
    else:
        status = "APPROVED"

    return {
        "providerTitle": provider_title or None,
        "normalizedToken": normalized,
        "canonicalKey": canonical.canonical_key,
        "canonicalDisplay": canonical.canonical_display,
        "approvedForActionable": approved,
        "mappingVerified": verified,
        "actionableAllowed": actionable_allowed,
        "knownSportsbook": True,
        "status": status,
    }


def normalize_current_market_sportsbook(value: Any) -> str:
    return _normalize_token(value)


def is_current_market_sportsbook_allowed(value: Any) -> bool:
    resolved = resolve_canonical_sportsbook(value)
    return bool(resolved["actionableAllowed"])


def filter_current_market_sportsbook_rows(df: pd.DataFrame, column: str = "sportsbook") -> pd.DataFrame:
    if df.empty or column not in df.columns:
        return df.copy()

    allowed = df[column].map(is_current_market_sportsbook_allowed)
    return df.loc[allowed].copy()


def annotate_current_market_sportsbooks(df: pd.DataFrame, column: str = "sportsbook") -> pd.DataFrame:
    if df.empty or column not in df.columns:
        return df.copy()

    out = df.copy()
    resolved = out[column].map(resolve_canonical_sportsbook)
    out["sportsbookCanonicalKey"] = resolved.map(lambda item: item.get("canonicalKey"))
    out["sportsbookCanonicalDisplay"] = resolved.map(lambda item: item.get("canonicalDisplay"))
    out["sportsbookApprovedForActionable"] = resolved.map(lambda item: bool(item.get("approvedForActionable")))
    out["sportsbookMappingVerified"] = resolved.map(lambda item: bool(item.get("mappingVerified")))
    out["sportsbookActionableAllowed"] = resolved.map(lambda item: bool(item.get("actionableAllowed")))
    out["sportsbookPolicyStatus"] = resolved.map(lambda item: item.get("status"))
    out["sportsbookProviderTitle"] = resolved.map(lambda item: item.get("providerTitle"))
    return out