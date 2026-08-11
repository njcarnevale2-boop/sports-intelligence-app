"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2026-08-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)

    op.create_table(
        "games",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=True),
        sa.Column("away_team", sa.String(length=100), nullable=False),
        sa.Column("home_team", sa.String(length=100), nullable=False),
        sa.Column("commence_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_games_external_id"), "games", ["external_id"], unique=True)
    op.create_index(op.f("ix_games_id"), "games", ["id"], unique=False)

    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("market", sa.String(length=50), nullable=False),
        sa.Column("side", sa.String(length=50), nullable=False),
        sa.Column("point", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("book", sa.String(length=100), nullable=True),
        sa.Column("model_probability", sa.Float(), nullable=True),
        sa.Column("implied_probability", sa.Float(), nullable=True),
        sa.Column("edge", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_opportunities_game_id"), "opportunities", ["game_id"], unique=False)
    op.create_index(op.f("ix_opportunities_id"), "opportunities", ["id"], unique=False)

    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("opportunity_id", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("recommendation", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recommendations_game_id"), "recommendations", ["game_id"], unique=False)
    op.create_index(op.f("ix_recommendations_id"), "recommendations", ["id"], unique=False)
    op.create_index(op.f("ix_recommendations_opportunity_id"), "recommendations", ["opportunity_id"], unique=False)
    op.create_index(op.f("ix_recommendations_user_id"), "recommendations", ["user_id"], unique=False)

    op.create_table(
        "injuries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("team", sa.String(length=100), nullable=False),
        sa.Column("player_name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("estimated_point_impact", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_injuries_id"), "injuries", ["id"], unique=False)

    op.create_table(
        "weather",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("wind_speed", sa.Float(), nullable=True),
        sa.Column("precipitation", sa.Float(), nullable=True),
        sa.Column("humidity", sa.Float(), nullable=True),
        sa.Column("stadium_type", sa.String(length=100), nullable=True),
        sa.Column("surface", sa.String(length=100), nullable=True),
        sa.Column("weather_score", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_weather_id"), "weather", ["id"], unique=False)

    op.create_table(
        "odds_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=True),
        sa.Column("book", sa.String(length=100), nullable=False),
        sa.Column("market", sa.String(length=50), nullable=False),
        sa.Column("side", sa.String(length=50), nullable=False),
        sa.Column("point", sa.Float(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_odds_snapshots_id"), "odds_snapshots", ["id"], unique=False)

    op.create_table(
        "performance_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game", sa.String(length=255), nullable=True),
        sa.Column("sportsbook", sa.String(length=100), nullable=True),
        sa.Column("market", sa.String(length=100), nullable=True),
        sa.Column("recommendation", sa.String(length=100), nullable=True),
        sa.Column("sports_intelligence_score", sa.Float(), nullable=True),
        sa.Column("market_intelligence", sa.Text(), nullable=True),
        sa.Column("injury_context", sa.Text(), nullable=True),
        sa.Column("weather_context", sa.Text(), nullable=True),
        sa.Column("model_probability", sa.Float(), nullable=True),
        sa.Column("implied_probability", sa.Float(), nullable=True),
        sa.Column("edge", sa.Float(), nullable=True),
        sa.Column("expected_value", sa.Float(), nullable=True),
        sa.Column("line_at_recommendation", sa.Float(), nullable=True),
        sa.Column("closing_line", sa.Float(), nullable=True),
        sa.Column("final_score", sa.Float(), nullable=True),
        sa.Column("result", sa.String(length=50), nullable=True),
        sa.Column("units_won_lost", sa.Float(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_performance_records_id"), "performance_records", ["id"], unique=False)


def downgrade() -> None:
    op.drop_table("performance_records")
    op.drop_table("odds_snapshots")
    op.drop_table("weather")
    op.drop_table("injuries")
    op.drop_table("recommendations")
    op.drop_table("opportunities")
    op.drop_table("games")
    op.drop_table("users")
