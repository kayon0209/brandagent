"""Consumer material API routes (upgrade plan task 6, step 4).

These routes are mounted under /api/v1/consumer/materials and reuse the
shared success/error envelope. All handlers resolve the Principal from the
Bearer token; no anonymous access.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile

from agent_api.api.security import Principal
from agent_api.api.main import create_principal_dependency


class MaterialApplication(Protocol):
    async def import_text(self, principal: Principal, request, request_id: str | None) -> dict: ...
    async def import_url(self, principal: Principal, url: str, request_id: str | None) -> dict: ...
    async def upload_file(self, principal: Principal, filename: str, payload: bytes, *, content_type: str, request_id: str | None) -> dict: ...
    async def get_document_view(self, principal: Principal, document_id: str) -> dict: ...
    async def list_documents(self, principal: Principal) -> list[dict]: ...


def create_materials_router(materials: MaterialApplication, *, principal) -> APIRouter:
    router = APIRouter(prefix="/api/v1/consumer/materials", tags=["consumer-materials"])

    @router.get("")
    async def list_materials(actor: Principal = Depends(principal)):
        return {"success": True, "data": {"items": await materials.list_documents(actor)}}

    @router.post("/text")
    async def import_text(
        body: dict,
        actor: Principal = Depends(principal),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ):
        from agent_api.domain.consumer import MaterialImportRequest
        from agent_api.domain.errors import ApplicationError

        try:
            request = MaterialImportRequest(text=str(body.get("text", "")), name=str(body.get("name", "")))
        except Exception as error:
            raise HTTPException(status_code=422, detail="text is required") from error
        try:
            result = await materials.import_text(actor, request, request_id=idempotency_key)
        except ApplicationError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"success": True, "data": result}

    @router.post("/url")
    async def import_url(
        body: dict,
        actor: Principal = Depends(principal),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ):
        from agent_api.domain.errors import ApplicationError

        url = str(body.get("url", "")).strip()
        if not url:
            raise HTTPException(status_code=422, detail="url is required")
        try:
            result = await materials.import_url(actor, url, request_id=idempotency_key)
        except ApplicationError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="URL import arrives with the fetch adapter") from None
        return {"success": True, "data": result}

    @router.post("/upload")
    async def upload_material(
        file: UploadFile,
        actor: Principal = Depends(principal),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ):
        from agent_api.domain.consumer import UploadLimits
        from agent_api.domain.errors import ApplicationError

        limits = UploadLimits()
        payload = await file.read(limits.max_bytes + 1)
        try:
            result = await materials.upload_file(
                actor,
                file.filename or "untitled",
                payload,
                content_type=file.content_type or "",
                request_id=idempotency_key,
            )
        except ApplicationError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"success": True, "data": result}

    @router.get("/{document_id}")
    async def material_detail(document_id: str, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError, NotFoundError

        try:
            view = await materials.get_document_view(actor, document_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Material not found") from None
        except ApplicationError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        return {"success": True, "data": view}

    @router.get("/{document_id}/excerpts")
    async def material_excerpts(document_id: str, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError, NotFoundError

        try:
            view = await materials.get_document_view(actor, document_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Material not found") from None
        except ApplicationError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        return {"success": True, "data": {"items": view["excerpts"]}}

    return router
