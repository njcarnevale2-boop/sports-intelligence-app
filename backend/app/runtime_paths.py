from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from app.config import settings


DEFAULT_NFL_ANALYTICS_OS_ROOT = Path.home() / "Downloads" / "NFL_Analytics_OS_v1_9"


class RuntimePathRef(os.PathLike[str]):
    def __init__(self, resolver: Callable[[], Path]) -> None:
        self._resolver = resolver

    def resolve(self) -> Path:
        return self._resolver()

    def __fspath__(self) -> str:
        return os.fspath(self.resolve())

    def __str__(self) -> str:
        return str(self.resolve())

    def __repr__(self) -> str:
        return f"RuntimePathRef({self.resolve()!s})"

    def __truediv__(self, key: object) -> RuntimePathRef:
        return RuntimePathRef(lambda: self.resolve() / Path(str(key)))

    def __getattr__(self, name: str) -> Any:
        return getattr(self.resolve(), name)


@dataclass(frozen=True)
class RuntimeReadinessCheck:
    name: str
    path: str
    required: bool
    exists: bool
    kind: str


class RuntimePaths:
    @property
    def configured_root_raw(self) -> Optional[str]:
        raw = os.getenv("NFL_ANALYTICS_OS_ROOT")
        if raw is None:
            return None
        value = str(raw).strip()
        return value or None

    @property
    def root_source(self) -> str:
        return "ENV" if self.configured_root_raw else "LOCAL_FALLBACK"

    def _resolve_root(self) -> Path:
        raw = self.configured_root_raw
        if raw:
            return Path(raw).expanduser().resolve()
        return DEFAULT_NFL_ANALYTICS_OS_ROOT.expanduser().resolve()

    @property
    def root(self) -> RuntimePathRef:
        return RuntimePathRef(self._resolve_root)

    @property
    def database_dir(self) -> RuntimePathRef:
        return RuntimePathRef(lambda: self._resolve_root() / "database")

    @property
    def outputs_dir(self) -> RuntimePathRef:
        return RuntimePathRef(lambda: self._resolve_root() / "outputs")

    @property
    def logs_dir(self) -> RuntimePathRef:
        return RuntimePathRef(lambda: self._resolve_root() / "logs")

    @property
    def scripts_dir(self) -> RuntimePathRef:
        return RuntimePathRef(lambda: self._resolve_root() / "scripts")

    @property
    def nfl_python(self) -> RuntimePathRef:
        return RuntimePathRef(lambda: self._resolve_root() / ".venv" / "bin" / "python3")

    @property
    def nfl_model_duckdb(self) -> RuntimePathRef:
        return RuntimePathRef(lambda: self._resolve_root() / "database" / "nfl_model.duckdb")

    @property
    def current_game_projections_csv(self) -> RuntimePathRef:
        return RuntimePathRef(lambda: self._resolve_root() / "outputs" / "current_game_projections.csv")

    @property
    def line_movement_board_csv(self) -> RuntimePathRef:
        return RuntimePathRef(lambda: self._resolve_root() / "outputs" / "line_movement_board.csv")

    @property
    def schedule_context_latest_csv(self) -> RuntimePathRef:
        return RuntimePathRef(lambda: self._resolve_root() / "outputs" / "schedule_context_latest.csv")

    @property
    def ranked_bet_board_csv(self) -> RuntimePathRef:
        return RuntimePathRef(lambda: self._resolve_root() / "outputs" / "ranked_bet_board.csv")

    @property
    def portfolio_recommendations_csv(self) -> RuntimePathRef:
        return RuntimePathRef(lambda: self._resolve_root() / "outputs" / "portfolio_recommendations.csv")

    @property
    def walkforward_multiseason_predictions_csv(self) -> RuntimePathRef:
        return RuntimePathRef(lambda: self._resolve_root() / "outputs" / "walkforward_multiseason_predictions.csv")

    @property
    def refresh_state_json(self) -> RuntimePathRef:
        return RuntimePathRef(lambda: self._resolve_root() / "logs" / "refresh_state.json")


runtime_paths = RuntimePaths()


def resolve_sqlite_database_path(database_url: Optional[str] = None) -> Optional[Path]:
    raw = str(database_url or settings.DATABASE_URL or "").strip()
    if not raw.startswith("sqlite:///"):
        return None

    suffix = raw.removeprefix("sqlite:///")
    if suffix.startswith("/"):
        return Path(suffix).expanduser().resolve()
    return (Path.cwd() / suffix).resolve()


def backend_instance_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def runtime_readiness() -> dict[str, Any]:
    sqlite_path = resolve_sqlite_database_path()
    checks = [
        RuntimeReadinessCheck("runtimeRoot", str(runtime_paths.root), True, runtime_paths.root.exists(), "dir"),
        RuntimeReadinessCheck("databaseDir", str(runtime_paths.database_dir), True, runtime_paths.database_dir.exists(), "dir"),
        RuntimeReadinessCheck("outputsDir", str(runtime_paths.outputs_dir), True, runtime_paths.outputs_dir.exists(), "dir"),
        RuntimeReadinessCheck("logsDir", str(runtime_paths.logs_dir), True, runtime_paths.logs_dir.exists(), "dir"),
        RuntimeReadinessCheck("nflModelDuckDB", str(runtime_paths.nfl_model_duckdb), True, runtime_paths.nfl_model_duckdb.exists(), "file"),
        RuntimeReadinessCheck("currentGameProjections", str(runtime_paths.current_game_projections_csv), True, runtime_paths.current_game_projections_csv.exists(), "file"),
        RuntimeReadinessCheck("lineMovementBoard", str(runtime_paths.line_movement_board_csv), True, runtime_paths.line_movement_board_csv.exists(), "file"),
        RuntimeReadinessCheck("scheduleContextLatest", str(runtime_paths.schedule_context_latest_csv), False, runtime_paths.schedule_context_latest_csv.exists(), "file"),
        RuntimeReadinessCheck("rankedBetBoard", str(runtime_paths.ranked_bet_board_csv), False, runtime_paths.ranked_bet_board_csv.exists(), "file"),
    ]

    sqlite_parent_ready = sqlite_path is None or sqlite_path.parent.exists()
    required_missing = [check.name for check in checks if check.required and not check.exists]
    optional_missing = [check.name for check in checks if (not check.required) and not check.exists]
    if not sqlite_parent_ready:
        required_missing.append("sqliteDatabaseParent")

    if required_missing:
        status = "NOT_READY"
    elif optional_missing:
        status = "DEGRADED"
    else:
        status = "READY"

    return {
        "runtimeRootConfigured": runtime_paths.configured_root_raw is not None,
        "runtimeRootSource": runtime_paths.root_source,
        "runtimeRoot": str(runtime_paths.root),
        "databaseDir": str(runtime_paths.database_dir),
        "outputsDir": str(runtime_paths.outputs_dir),
        "logsDir": str(runtime_paths.logs_dir),
        "scriptsDir": str(runtime_paths.scripts_dir),
        "sqliteDatabasePath": None if sqlite_path is None else str(sqlite_path),
        "persistentStorageReady": not required_missing and sqlite_parent_ready,
        "requiredArtifactsReady": len(required_missing) == 0,
        "missingArtifacts": required_missing + optional_missing,
        "deploymentReadiness": status,
        "backendReplicaRequirement": 1,
        "backendInstanceId": backend_instance_id(),
        "checks": [
            {
                "name": check.name,
                "path": check.path,
                "required": check.required,
                "exists": check.exists,
                "kind": check.kind,
            }
            for check in checks
        ] + [
            {
                "name": "sqliteDatabaseParent",
                "path": "" if sqlite_path is None else str(sqlite_path.parent),
                "required": sqlite_path is not None,
                "exists": sqlite_parent_ready,
                "kind": "dir",
            }
        ],
    }