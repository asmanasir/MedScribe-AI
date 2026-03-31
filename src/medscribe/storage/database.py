from __future__ import annotations

"""
Database setup — SQLAlchemy 2.0 async engine.

We use SQLAlchemy's async support for non-blocking DB calls.
In dev: SQLite (zero config, file-based)
In prod: PostgreSQL (ACID, scalable, healthcare-grade)

The switch is just a connection string change in config.

Key concept: We use the Repository pattern. The database tables
(SQLAlchemy models) are SEPARATE from domain models (Pydantic).
This means:
- Domain logic never imports SQLAlchemy
- You can change the DB schema without touching business logic
- You can swap SQLAlchemy for another ORM without touching the domain
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from medscribe.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


# --- Table definitions ---
# These map directly to database tables. They are NOT the same as domain models.


class VisitRow(Base):
    __tablename__ = "visits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(255), index=True)
    clinician_id: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TranscriptRow(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    visit_id: Mapped[str] = mapped_column(String(36), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    segments_json: Mapped[str] = mapped_column(Text, default="[]")
    language: Mapped[str] = mapped_column(String(10))
    model_id: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ClinicalNoteRow(Base):
    __tablename__ = "clinical_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    visit_id: Mapped[str] = mapped_column(String(36), index=True)
    sections_json: Mapped[str] = mapped_column(Text)  # JSON of section -> content
    raw_llm_output: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50), default="")
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEntryRow(Base):
    """
    Audit log table — APPEND ONLY.

    In production, you'd also want:
    - Partitioning by timestamp (for performance)
    - Separate read replicas (auditors shouldn't slow down ops)
    - Archival to cold storage after N months
    """

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    visit_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    actor: Mapped[str] = mapped_column(String(255), index=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SafetyFlagRow(Base):
    __tablename__ = "safety_flags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    visit_id: Mapped[str] = mapped_column(String(36), index=True)
    severity: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(50), index=True)
    message: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --- Engine + Session setup ---

def _get_engine():
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
    )


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = _get_engine()
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables. Call once at startup."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
