from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI

from app.redaction.policies import list_policies
from app.state import model_state


def register(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/v1/policies")
    def policies() -> dict[str, Any]:
        settings = model_state.settings
        policies_dir = getattr(settings, "policies_dir", "./policies")
        loaded = list_policies(policies_dir)
        return {
            "policies": [
                {
                    "name": p.name,
                    "version": p.version,
                    "description": p.description,
                    "fields": list(p.fields.keys()),
                }
                for p in loaded
            ]
        }

    app.include_router(router)
