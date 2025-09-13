"""
Base repository pattern with generic type support
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

from sqlalchemy import Engine, and_, select
from sqlalchemy.orm import Session

from ..db.models import Base

T = TypeVar("T", bound=Base)


@runtime_checkable
class Repository(Protocol[T]):
    """Repository protocol for data access"""

    def get(self, id: Any) -> T | None: ...
    def get_many(self, filters: dict[str, Any]) -> list[T]: ...
    def create(self, entity: T) -> T: ...
    def create_many(self, entities: Sequence[T]) -> list[T]: ...
    def update(self, entity: T) -> T: ...
    def delete(self, id: Any) -> bool: ...
    def exists(self, filters: dict[str, Any]) -> bool: ...
    def count(self, filters: dict[str, Any] | None = None) -> int: ...


class BaseRepository(ABC, Generic[T]):
    """Base repository with common CRUD operations"""

    def __init__(self, engine: Engine, model_class: type[T]) -> None:
        self._engine = engine
        self._model_class = model_class

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        """Provide a transactional scope for database operations"""
        with Session(self._engine, autoflush=False) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def get(self, id: Any) -> T | None:
        """Get entity by ID"""
        with self._session_scope() as session:
            return session.get(self._model_class, id)

    def get_many(self, filters: dict[str, Any] | None = None) -> list[T]:
        """Get multiple entities matching filters"""
        with self._session_scope() as session:
            query = select(self._model_class)

            if filters:
                conditions = []
                for key, value in filters.items():
                    if hasattr(self._model_class, key):
                        column = getattr(self._model_class, key)
                        if isinstance(value, list | tuple):
                            conditions.append(column.in_(value))
                        else:
                            conditions.append(column == value)

                if conditions:
                    query = query.where(and_(*conditions))

            return list(session.scalars(query).all())

    def create(self, entity: T) -> T:
        """Create a new entity"""
        with self._session_scope() as session:
            session.add(entity)
            session.flush()
            session.refresh(entity)
            return entity

    def create_many(self, entities: Sequence[T]) -> list[T]:
        """Create multiple entities"""
        with self._session_scope() as session:
            session.add_all(entities)
            session.flush()
            return list(entities)

    def update(self, entity: T) -> T:
        """Update an existing entity"""
        with self._session_scope() as session:
            merged = session.merge(entity)
            session.flush()
            session.refresh(merged)
            return merged

    def delete(self, id: Any) -> bool:
        """Delete entity by ID"""
        with self._session_scope() as session:
            entity = session.get(self._model_class, id)
            if entity:
                session.delete(entity)
                session.flush()
                return True
            return False

    def exists(self, filters: dict[str, Any]) -> bool:
        """Check if entity exists matching filters"""
        with self._session_scope() as session:
            query = select(self._model_class)

            conditions = []
            for key, value in filters.items():
                if hasattr(self._model_class, key):
                    column = getattr(self._model_class, key)
                    conditions.append(column == value)

            if conditions:
                query = query.where(and_(*conditions)).limit(1)
                return session.scalar(query) is not None

            return False

    def count(self, filters: dict[str, Any] | None = None) -> int:
        """Count entities matching filters"""
        from sqlalchemy import func

        with self._session_scope() as session:
            query = select(func.count()).select_from(self._model_class)

            if filters:
                conditions = []
                for key, value in filters.items():
                    if hasattr(self._model_class, key):
                        column = getattr(self._model_class, key)
                        if isinstance(value, list | tuple):
                            conditions.append(column.in_(value))
                        else:
                            conditions.append(column == value)

                if conditions:
                    query = query.where(and_(*conditions))

            return session.scalar(query) or 0
