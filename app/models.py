from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    mirrors: Mapped[list["Mirror"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Mirror(Base):
    __tablename__ = "mirrors"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    self_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    report_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    owner: Mapped[User] = relationship(back_populates="mirrors")
    answers: Mapped[list["Answer"]] = relationship(back_populates="mirror", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="mirror", cascade="all, delete-orphan")


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("mirror_id", "respondent_telegram_id", "trait_key", name="uq_response_trait"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    mirror_id: Mapped[int] = mapped_column(ForeignKey("mirrors.id"), index=True)
    respondent_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    is_self: Mapped[bool] = mapped_column(Boolean, default=False)
    relation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trait_key: Mapped[str] = mapped_column(String(32))
    score: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    mirror: Mapped[Mirror] = relationship(back_populates="answers")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    mirror_id: Mapped[int] = mapped_column(ForeignKey("mirrors.id"), index=True)
    payer_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    receipt_file_id: Mapped[str] = mapped_column(String(512))
    receipt_kind: Mapped[str] = mapped_column(String(20), default="photo")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    mirror: Mapped[Mirror] = relationship(back_populates="payments")
