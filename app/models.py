"""
Milestone Escrow Agent — data models.

State machine per milestone:
  PENDING_FUNDING -> FUNDED -> DELIVERED -> RELEASED
                                          -> DISPUTED -> RELEASED / REFUNDED

The AI never moves a milestone into RELEASED or REFUNDED — only a human
(the client) can trigger those transitions. The AI can only move a
milestone into a "flagged" review state or attach a recommendation.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Enum as SAEnum,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class MilestoneStatus(str, enum.Enum):
    PENDING_FUNDING = "pending_funding"
    FUNDED = "funded"
    DELIVERED = "delivered"       # freelancer submitted proof, awaiting client
    FLAGGED = "flagged"           # AI flagged something odd, still awaiting client
    RELEASED = "released"         # human-approved fund release
    DISPUTED = "disputed"         # client disputed the deliverable
    REFUNDED = "refunded"         # human-approved refund to client


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    client_name = Column(String(120), nullable=False)
    freelancer_name = Column(String(120), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    milestones = relationship(
        "Milestone", back_populates="project", cascade="all, delete-orphan"
    )


class Milestone(Base):
    __tablename__ = "milestones"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    title = Column(String(200), nullable=False)
    scope_description = Column(Text, nullable=False)
    amount_inr = Column(Float, nullable=False)

    status = Column(
        SAEnum(MilestoneStatus), default=MilestoneStatus.PENDING_FUNDING, nullable=False
    )

    razorpay_order_id = Column(String(120), nullable=True)
    razorpay_payment_id = Column(String(120), nullable=True)

    deliverable_link = Column(String(500), nullable=True)
    deliverable_note = Column(Text, nullable=True)

    ai_summary = Column(Text, nullable=True)
    ai_recommendation = Column(String(20), nullable=True)  # "release" | "review"
    ai_flags = Column(Text, nullable=True)  # comma-separated flag reasons

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="milestones")
    events = relationship(
        "AuditEvent", back_populates="milestone", cascade="all, delete-orphan"
    )


class AuditEvent(Base):
    """Immutable audit trail — every state transition gets a row here."""

    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    milestone_id = Column(Integer, ForeignKey("milestones.id"), nullable=False)
    actor = Column(String(50), nullable=False)  # "client" | "freelancer" | "ai" | "system"
    action = Column(String(100), nullable=False)
    detail = Column(Text, nullable=True)
    from_status = Column(String(30), nullable=True)
    to_status = Column(String(30), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    milestone = relationship("Milestone", back_populates="events")


# --- engine / session setup ---
engine = create_engine("sqlite:///./escrow.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db():
    Base.metadata.create_all(bind=engine)
