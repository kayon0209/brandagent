"""Consumer material API routes (upgrade plan task 6, step 4).

These routes are mounted under /api/v1/consumer/materials and reuse the
shared success/error envelope. All handlers resolve the Principal from the
Bearer token; no anonymous access.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

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


class ConsumerProjectsApp(Protocol):
    """Protocol bundling the consumer project/draft applications."""

    projects: ConsumerProjects
    drafts: ConsumerDrafts
    generation: ConsumerGeneration


class ConsumerProjects(Protocol):
    async def create_project(self, principal: Principal, *, title: str, core_idea: str, intent: str) -> dict: ...
    async def get_project(self, principal: Principal, task_id: str) -> dict: ...
    async def list_projects(self, principal: Principal) -> list[dict]: ...
    async def update_project(self, principal: Principal, task_id: str, *, title: str | None, core_idea: str | None, intent: str | None) -> dict: ...
    async def link_excerpt(self, principal: Principal, task_id: str, excerpt_id: str) -> dict: ...
    async def unlink_excerpt(self, principal: Principal, task_id: str, excerpt_id: str) -> dict: ...


class ConsumerDrafts(Protocol):
    async def get_or_create_draft(self, principal: Principal, task_id: str) -> dict: ...
    async def autosave(self, principal: Principal, task_id: str, document: dict, plain_text: str, *, expected_revision: int) -> dict | None: ...
    async def adopt(self, principal: Principal, task_id: str, *, base_revision: int) -> dict: ...


class ConsumerGeneration(Protocol):
    async def generate(self, principal: Principal, task_id: str) -> dict: ...
    async def apply_candidate(self, principal: Principal, task_id: str, content_version_id: str, *, base_revision: int) -> dict | None: ...


def _error_status(error) -> int:
    from agent_api.domain.errors import ApplicationError

    return error.status_code if isinstance(error, ApplicationError) else 500


def create_projects_router(apps: ConsumerProjectsApp, *, principal) -> APIRouter:
    """Project, draft, and generation routes (plan task 8)."""

    router = APIRouter(prefix="/api/v1/consumer/projects", tags=["consumer-projects"])

    @router.post("", status_code=201)
    async def create_project(body: dict, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError

        try:
            project = await apps.projects.create_project(
                actor,
                title=str(body.get("title", "")),
                core_idea=str(body.get("core_idea", "")),
                intent=str(body.get("writing_intent", "")),
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error
        return {"success": True, "data": project}

    @router.get("")
    async def list_projects(actor: Principal = Depends(principal)):
        return {"success": True, "data": {"items": await apps.projects.list_projects(actor)}}

    @router.get("/{task_id}")
    async def get_project(task_id: str, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError, NotFoundError

        try:
            project = await apps.projects.get_project(actor, task_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Project not found") from None
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error
        return {"success": True, "data": project}

    @router.patch("/{task_id}")
    async def update_project(task_id: str, body: dict, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError, NotFoundError

        title = body.get("title")
        core_idea = body.get("core_idea")
        intent = body.get("writing_intent")
        try:
            project = await apps.projects.update_project(
                actor, task_id, title=title, core_idea=core_idea, intent=intent
            )
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Project not found") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error
        return {"success": True, "data": project}

    @router.put("/{task_id}/materials/{excerpt_id}")
    async def link_material(task_id: str, excerpt_id: str, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError, NotFoundError

        try:
            project = await apps.projects.link_excerpt(actor, task_id, excerpt_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Excerpt or project not found") from None
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error
        return {"success": True, "data": project}

    @router.delete("/{task_id}/materials/{excerpt_id}")
    async def unlink_material(task_id: str, excerpt_id: str, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError, NotFoundError

        try:
            project = await apps.projects.unlink_excerpt(actor, task_id, excerpt_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Project not found") from None
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error
        return {"success": True, "data": project}

    @router.get("/{task_id}/draft")
    async def get_draft(task_id: str, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError, NotFoundError

        try:
            draft = await apps.drafts.get_or_create_draft(actor, task_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Draft not found") from None
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error
        return {"success": True, "data": draft}

    @router.put("/{task_id}/draft")
    async def save_draft(task_id: str, body: dict, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError, NotFoundError

        base_revision = body.get("baseRevision")
        document = body.get("document")
        if not isinstance(base_revision, int) or not isinstance(document, dict):
            raise HTTPException(status_code=422, detail="baseRevision (int) and document (object) are required")
        try:
            await apps.drafts.get_or_create_draft(actor, task_id)  # ensure the draft exists (404 if project is foreign)
            draft = await apps.drafts.autosave(
                actor,
                task_id,
                document,
                str(body.get("plainText", "")),
                expected_revision=base_revision,
            )
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Draft not found") from None
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error
        if draft is None:
            return JSONResponse(
                status_code=409,
                content={"success": False, "error": {"code": "REVISION_CONFLICT", "message": "稿件在别处有更新，请先刷新"}},
            )
        return {"success": True, "data": {"revision": draft["revision"], "task_id": draft["task_id"]}}

    @router.post("/{task_id}/draft/adopt")
    async def adopt_draft(task_id: str, body: dict, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError, ConflictError, NotFoundError

        base_revision = body.get("baseRevision")
        if not isinstance(base_revision, int):
            raise HTTPException(status_code=422, detail="baseRevision (int) is required")
        try:
            result = await apps.drafts.adopt(actor, task_id, base_revision=base_revision)
        except ConflictError:
            return JSONResponse(
                status_code=409,
                content={"success": False, "error": {"code": "REVISION_CONFLICT", "message": "稿件在别处有更新，请先刷新"}},
            )
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Draft not found") from None
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error
        return {"success": True, "data": result}

    @router.post("/{task_id}/draft/generate")
    async def generate_draft(task_id: str, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError, NotFoundError

        try:
            await apps.drafts.get_or_create_draft(actor, task_id)  # ensure the draft exists
            result = await apps.generation.generate(actor, task_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Project or draft not found") from None
        except RuntimeError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error
        return {"success": True, "data": result}

    @router.post("/{task_id}/draft/apply-candidate")
    async def apply_candidate(task_id: str, body: dict, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError, NotFoundError

        content_version_id = str(body.get("contentVersionId", ""))
        base_revision = body.get("baseRevision")
        if not content_version_id or not isinstance(base_revision, int):
            raise HTTPException(status_code=422, detail="contentVersionId and baseRevision (int) are required")
        try:
            draft = await apps.generation.apply_candidate(
                actor, task_id, content_version_id, base_revision=base_revision
            )
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Candidate not found") from None
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error
        if draft is None:
            return JSONResponse(
                status_code=409,
                content={"success": False, "error": {"code": "REVISION_CONFLICT", "message": "稿件在别处有更新，候选稿未应用"}},
            )
        return {"success": True, "data": {"revision": draft["revision"], "task_id": draft["task_id"]}}

    return router
