from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Float, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    recommendations: Mapped[List["Recommendation"]] = relationship(back_populates="user")


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True, index=True)
    away_team: Mapped[str] = mapped_column(String(100), nullable=False)
    home_team: Mapped[str] = mapped_column(String(100), nullable=False)
    commence_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="scheduled", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    opportunities: Mapped[List["Opportunity"]] = relationship(back_populates="game")
    recommendations: Mapped[List["Recommendation"]] = relationship(back_populates="game")
    injuries: Mapped[List["Injury"]] = relationship(back_populates="game")
    weather: Mapped[List["Weather"]] = relationship(back_populates="game")


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id"), nullable=True, index=True)
    market: Mapped[str] = mapped_column(String(50), nullable=False)
    side: Mapped[str] = mapped_column(String(50), nullable=False)
    point: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    book: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    implied_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    game: Mapped[Game | None] = relationship(back_populates="opportunities")
    recommendations: Mapped[List["Recommendation"]] = relationship(back_populates="opportunity")
    odds_snapshots: Mapped[List["OddsSnapshot"]] = relationship(back_populates="opportunity")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id"), nullable=True, index=True)
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"), nullable=True, index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user: Mapped[User | None] = relationship(back_populates="recommendations")
    game: Mapped[Game | None] = relationship(back_populates="recommendations")
    opportunity: Mapped[Opportunity | None] = relationship(back_populates="recommendations")


class PerformanceRecord(Base):
    __tablename__ = "performance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    game: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sportsbook: Mapped[str | None] = mapped_column(String(100), nullable=True)
    market: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sports_intelligence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_intelligence: Mapped[str | None] = mapped_column(Text, nullable=True)
    injury_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    weather_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    implied_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    line_at_recommendation: Mapped[float | None] = mapped_column(Float, nullable=True)
    closing_line: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[str | None] = mapped_column(String(50), nullable=True)
    units_won_lost: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class Injury(Base):
    __tablename__ = "injuries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id"), nullable=True, index=True)
    team: Mapped[str] = mapped_column(String(100), nullable=False)
    player_name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    estimated_point_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    game: Mapped[Game | None] = relationship(back_populates="injuries")


class Weather(Base):
    __tablename__ = "weather"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id"), nullable=True, index=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    stadium_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    surface: Mapped[str | None] = mapped_column(String(100), nullable=True)
    weather_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    game: Mapped[Game | None] = relationship(back_populates="weather")


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"), nullable=True, index=True)
    book: Mapped[str] = mapped_column(String(100), nullable=False)
    market: Mapped[str] = mapped_column(String(50), nullable=False)
    side: Mapped[str] = mapped_column(String(50), nullable=False)
    point: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    opportunity: Mapped[Opportunity | None] = relationship(back_populates="odds_snapshots")
