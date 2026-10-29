"""Versioned singleton platform policy. Credentials are encrypted inside the document."""
from sqlalchemy import CheckConstraint, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column
from myink.models.base import Base


class PlatformConfiguration(Base):
    __tablename__ = 'platform_configuration'
    __table_args__ = (CheckConstraint('id = 1', name='singleton'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    document: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
