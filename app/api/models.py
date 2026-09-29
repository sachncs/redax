"""Shared bounded request-field types for the HTTP API."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.limits import MAX_ENTITY_TYPE_CHARS, MAX_ENTITY_TYPES

EntityType = Annotated[str, Field(min_length=1, max_length=MAX_ENTITY_TYPE_CHARS)]
EntityTypes = Annotated[list[EntityType], Field(max_length=MAX_ENTITY_TYPES)]

__all__ = ["MAX_ENTITY_TYPES", "MAX_ENTITY_TYPE_CHARS", "EntityType", "EntityTypes"]
