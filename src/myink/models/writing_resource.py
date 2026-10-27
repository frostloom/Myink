"""Platform publications, private resources and immutable project snapshots."""
import uuid
from sqlalchemy import String, Integer, JSON, Uuid, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from myink.models.base import Base

class ResourceColumns:
    id: Mapped[str] = mapped_column(String(160), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(2000))
    body: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='draft')
    generation: Mapped[int] = mapped_column(Integer, default=0)
    current_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

class WritingResource(ResourceColumns, Base):
    __tablename__ = 'writing_resources'
    publication: Mapped[dict] = mapped_column(JSON, default=dict)

class PersonalWritingResource(ResourceColumns, Base):
    __tablename__ = 'personal_writing_resources'
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    source_resource_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint("user_id", "source_resource_id", name="uq_personal_resource_source"),)

class WritingResourceRevision(Base):
    __tablename__ = 'writing_resource_revisions'
    resource_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    document: Mapped[dict] = mapped_column(JSON)

class ProjectWritingResources(Base):
    __tablename__ = 'project_writing_resources'
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey('projects.id', ondelete='CASCADE',
                         name='fk_project_writing_resources_project'), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    configured: Mapped[bool] = mapped_column(Boolean, default=True)
    automatic_initialized: Mapped[bool] = mapped_column(Boolean, default=False)
    defaults_initialized: Mapped[bool] = mapped_column(Boolean, default=False)
    selections: Mapped[list] = mapped_column(JSON, default=list)
    dismissed: Mapped[dict] = mapped_column(JSON, default=dict)

class WritingResourcePublication(Base):
    __tablename__ = 'writing_resource_publications'
    resource_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict] = mapped_column(JSON)
