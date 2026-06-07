"""The single ``User`` / ``UserRole`` mapping (SQLAlchemy 2.0 typed declarative).

This is the ONLY mapped class for the ``users`` table. ``app/models/user.py`` is
a pure re-export of these symbols. Columns, Enum, indexes, uniqueness,
nullability, defaults (``now_china``) and relationships are kept byte-for-byte
equivalent to the previous Flask ``db.Model`` definition so the ORM reorg
produces ZERO Alembic schema diff.

The related classes (``Classroom``, ``Enrollment``, ``Submission``, ``Quiz``,
``ClassroomQuiz``, ``QuizAttempt``) remain Flask ``db.Model`` classes in
``app/models/``. Because they live on the SAME ``DomainBase`` registry/metadata,
the string-based ``relationship()`` targets below still resolve.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, Enum as SAEnum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.timezone import now_china
from domain.base import DomainBase


class UserRole(Enum):
    """User role enumeration"""
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"


class User(DomainBase):
    """User model"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(
        String(80), unique=True, nullable=False, index=True
    )
    password: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(
        String(120), unique=True, nullable=True
    )
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole), default=UserRole.STUDENT, nullable=False
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=now_china
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=now_china, onupdate=now_china
    )

    # Relationships - using back_populates instead of backref.
    # Targets remain Flask db.Model classes resolved via the shared registry.
    # Classrooms taught by teacher
    taught_classrooms = relationship(
        "Classroom",
        back_populates="teacher",
        foreign_keys="Classroom.teacher_id",
        lazy=True,
    )

    # Student's enrollment records
    enrollments = relationship(
        "Enrollment",
        back_populates="student",
        lazy=True,
        cascade="all, delete-orphan",
    )

    # Student's submission records
    submissions = relationship(
        "Submission",
        back_populates="student",
        lazy=True,
    )

    # Quizzes created by teacher
    created_quizzes = relationship(
        "Quiz",
        back_populates="creator",
        lazy=True,
    )

    # Quizzes assigned by teacher (as assigner)
    assigned_classroom_quizzes = relationship(
        "ClassroomQuiz",
        back_populates="assigner",
        lazy=True,
    )

    # Student's quiz attempt records
    quiz_attempts = relationship(
        "QuizAttempt",
        back_populates="student",
        lazy=True,
    )

    def __repr__(self) -> str:
        return f"<User {self.username}>"

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        def format_datetime(dt):
            """Safely format datetime object"""
            if dt is None:
                return None
            # If it's a datetime object, convert to ISO format
            if isinstance(dt, datetime):
                return dt.isoformat()
            # If it's already a string, return as is
            return str(dt)

        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role.value if isinstance(self.role, UserRole) else self.role,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
