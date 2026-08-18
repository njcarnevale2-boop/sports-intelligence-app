import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class Settings:
    PROJECT_NAME: str = "Sports Intelligence API"
    API_V1_STR: str = "/api"
    SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", os.getenv("SECRET_KEY", "dev-secret-key"))
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./sports_intelligence.db")
    DB_ECHO: bool = os.getenv("DB_ECHO", "0").lower() in {"1", "true", "yes"}

    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "postgres")
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: str = os.getenv("POSTGRES_PORT", "5432")
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "sports_intelligence")
    MIN_PLAYABLE_EV: float = float(os.getenv("MIN_PLAYABLE_EV", "0.0"))
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "dev-admin-token")
    DEFAULT_MODEL_VERSION: str = os.getenv("MODEL_VERSION", "sia_model_v2026_preseason")
    DEFAULT_PROBABILITY_ENGINE_VERSION: str = os.getenv("PROBABILITY_ENGINE_VERSION", "empirical_residual_engine_v2026_preseason")
    DEFAULT_CALIBRATION_VERSION: str = os.getenv("CALIBRATION_VERSION", "guarded_isotonic_v2026_preseason")
    DEFAULT_SI_SCORE_VERSION: str = os.getenv("SI_SCORE_VERSION", "si_score_v2026_semantic_alignment")
    DEFAULT_RANKING_VERSION: str = os.getenv("RANKING_VERSION", "ranking_calibrated_edge_v2026")
    DEFAULT_QUALIFICATION_POLICY_VERSION: str = os.getenv("QUALIFICATION_POLICY_VERSION", "qualification_explicit_policy_v2026")
    DEFAULT_GIT_COMMIT_HASH: str = os.getenv("GIT_COMMIT_HASH", "")
    OFFICIAL_SIA3_CADENCE: str = os.getenv("OFFICIAL_SIA3_CADENCE", "UNSET")
    OFFICIAL_PUBLICATION_MAX_ODDS_AGE_MINUTES: int = int(os.getenv("OFFICIAL_PUBLICATION_MAX_ODDS_AGE_MINUTES", "60"))

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL

        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()


def _resolve_git_commit_hash() -> str:
    if settings.DEFAULT_GIT_COMMIT_HASH:
        return settings.DEFAULT_GIT_COMMIT_HASH
    try:
        root = Path(__file__).resolve().parents[2]
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        commit = out.stdout.strip()
        if out.returncode == 0 and commit:
            return commit
    except Exception:
        pass
    return "git-unavailable"


settings.DEFAULT_GIT_COMMIT_HASH = _resolve_git_commit_hash()
