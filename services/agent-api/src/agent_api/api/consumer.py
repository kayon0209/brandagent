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
    assist: ConsumerAssist
    variants: ConsumerVariants


class ConsumerAssist(Protocol):
    async def propose(self, principal: Principal, task_id: str, *, action: str, selected_text: str, block_id: str, base_revision: int) -> dict | None: ...
    async def accept(self, principal: Principal, task_id: str, suggestion_id: str, *, base_revision: int) -> dict: ...


class ConsumerVariants(Protocol):
    async def preview(self, principal: Principal, task_id: str) -> dict: ...
    async def generate_variants(self, principal: Principal, task_id: str) -> dict: ...
    async def regenerate(self, principal: Principal, task_id: str, channel: str) -> dict: ...
    async def prepare_export(self, principal: Principal, task_id: str) -> dict: ...


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

    @router.post("/{task_id}/suggestions")
    async def propose_suggestion(task_id: str, body: dict, actor: Principal = Depends(principal)):
        from agent_api.application.editorial_assist import ActionNotSupported, SelectionStale
        from agent_api.domain.errors import ApplicationError, NotFoundError

        action = str(body.get("action", ""))
        selected_text = body.get("selectedText")
        block_id = str(body.get("blockId", ""))
        base_revision = body.get("baseRevision")
        if not isinstance(selected_text, str) or not block_id or not isinstance(base_revision, int):
            raise HTTPException(status_code=422, detail="selectedText, blockId and baseRevision (int) are required")
        try:
            suggestion = await apps.assist.propose(
                actor,
                task_id,
                action=action,
                selected_text=selected_text,
                block_id=block_id,
                base_revision=base_revision,
            )
        except ActionNotSupported:
            return JSONResponse(
                status_code=422,
                content={"success": False, "error": {"code": "VALIDATION_ERROR", "message": f"不支持的改写动作：{action}"}},
            )
        except SelectionStale:
            return JSONResponse(
                status_code=409,
                content={"success": False, "error": {"code": "SELECTION_STALE", "message": "选区已过期，请重新选择"}},
            )
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Draft not found") from None
        except RuntimeError as error:
            return JSONResponse(
                status_code=502,
                content={"success": False, "error": {"code": "ASSIST_UNAVAILABLE", "message": "AI 助手暂时不可用，稿件未做任何改动"}},
            )
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error
        if suggestion is None:
            return JSONResponse(
                status_code=422,
                content={"success": False, "error": {"code": "SUGGESTION_REFUSED", "message": "建议包含无法溯源的新事实，已拒绝生成"}},
            )
        payload = {
            "suggestion_id": suggestion["suggestion_id"],
            "action": suggestion["action"],
            "suggested_text": suggestion.get("suggested_text", suggestion.get("proposal_text", "")),
            "block_id": suggestion["block_id"],
            "base_revision": suggestion["base_revision"],
            "selected_text_hash": suggestion["selected_text_hash"],
            "status": suggestion["status"],
        }
        return {"success": True, "data": payload}

    @router.post("/{task_id}/suggestions/{suggestion_id}/accept")
    async def accept_suggestion(task_id: str, suggestion_id: str, body: dict, actor: Principal = Depends(principal)):
        from agent_api.application.editorial_assist import SelectionStale
        from agent_api.domain.errors import ApplicationError, NotFoundError

        base_revision = body.get("baseRevision")
        if not isinstance(base_revision, int):
            raise HTTPException(status_code=422, detail="baseRevision (int) is required")
        try:
            result = await apps.assist.accept(actor, task_id, suggestion_id, base_revision=base_revision)
        except SelectionStale:
            return JSONResponse(
                status_code=409,
                content={"success": False, "error": {"code": "SELECTION_STALE", "message": "选区已过期，稿件未修改"}},
            )
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Suggestion or draft not found") from None
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error
        return {"success": True, "data": result}

    # ------------------------------------------------------------------
    # platform variants + pre-publish review (plan task 11)
    # ------------------------------------------------------------------

    @router.get("/{task_id}/variants/preview")
    async def variants_preview(task_id: str, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError, NotFoundError

        try:
            return {"success": True, "data": await apps.variants.preview(actor, task_id)}
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Project not found") from None
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error

    @router.post("/{task_id}/variants/generate")
    async def variants_generate(task_id: str, actor: Principal = Depends(principal)):
        from agent_api.application.platform_variants import VariantGenerationError
        from agent_api.domain.errors import ApplicationError, NotFoundError

        try:
            return {"success": True, "data": await apps.variants.generate_variants(actor, task_id)}
        except NotFoundError:
            raise HTTPException(status_code=404, detail="先采用当前稿，再生成平台版本") from None
        except VariantGenerationError as error:
            return JSONResponse(
                status_code=502,
                content={"success": False, "error": {"code": error.code, "message": str(error), "retryable": error.retryable}},
            )
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error

    @router.post("/{task_id}/variants/{channel}/regenerate")
    async def variants_regenerate(task_id: str, channel: str, actor: Principal = Depends(principal)):
        from agent_api.application.platform_variants import VariantGenerationError
        from agent_api.domain.errors import ApplicationError, NotFoundError

        try:
            return {"success": True, "data": await apps.variants.regenerate(actor, task_id, channel)}
        except NotFoundError:
            raise HTTPException(status_code=404, detail="先采用当前稿，再生成平台版本") from None
        except VariantGenerationError as error:
            return JSONResponse(
                status_code=502,
                content={"success": False, "error": {"code": error.code, "message": str(error), "retryable": error.retryable}},
            )
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error

    @router.post("/{task_id}/export/prepare")
    async def variants_prepare_export(task_id: str, actor: Principal = Depends(principal)):
        from agent_api.domain.errors import ApplicationError, NotFoundError

        try:
            return {"success": True, "data": await apps.variants.prepare_export(actor, task_id)}
        except NotFoundError:
            raise HTTPException(status_code=404, detail="先采用当前稿，再导出") from None
        except ApplicationError as error:
            raise HTTPException(status_code=_error_status(error), detail=str(error)) from error

    return router
