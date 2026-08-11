from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from database.base import Base


engine = create_engine(
    settings.sqlalchemy_database_url,
    echo=settings.DB_ECHO,
    future=True,
    connect_args={"check_same_thread": False} if settings.sqlalchemy_database_url.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
