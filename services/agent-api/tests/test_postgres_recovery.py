import os
import asyncio
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from langgraph.types import Command

from agent_api.api.models import BriefInput, CreateTaskRequest, DecisionRequest
from agent_api.api.security import Principal
from agent_api.application.tasks import TaskWorkflowService
from agent_api.domain.models import AgentState, Channel, ContentBrief
from agent_api.domain.errors import ConflictError, ForbiddenError, NotFoundError
from agent_api.providers.base import LLMProvider, ModelCallResult
from agent_api.repositories.postgres_tasks import PostgresTaskRepository
from agent_api.repositories.postgres_workflow import PostgresWorkflowRepository
from agent_api.repositories.leases import LeaseContext, bind_lease, reset_lease
from agent_api.workflow.checkpoint import FencedCheckpointer, checkpoint_config, checkpoint_serializer, postgres_checkpointer, verify_checkpoint_isolation
from agent_api.workflow.graph import build_master_content_graph
from agent_api.workflow.services import WorkflowDependencies


pytestmark = pytest.mark.skipif(os.getenv("RUN_AGENT_DB_TESTS") != "true", reason="requires disposable PostgreSQL")


class FakeProvider(LLMProvider):
    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        content = '{"strategy":"verified"}' if prompt_version == "strategy-v1" else f"content:{prompt_version}"
        return ModelCallResult(content, "fake", "fake-v1", prompt_version, 1, 1, 1, "estimated", 0)


class SlowProvider(FakeProvider):
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        self.calls += 1
        await asyncio.sleep(0.8)
        content = '{"strategy":"verified"}' if prompt_version == "strategy-v1" else f"content:{prompt_version}"
        return ModelCallResult(content, "fake", "fake-v1", prompt_version, 1, 1, 1, "estimated", 0)


class RecordingCheckpointer:
    def __init__(self) -> None:
        self.serde = checkpoint_serializer()
        self.called = False
        self.config_specs = []

    def get_next_version(self, current, channel):
        return 1 if current is None else current + 1

    async def aput(self, config, checkpoint, metadata, new_versions):
        self.called = True
        return config


@pytest.mark.asyncio
async def test_workspace_bootstrap_is_idempotent_and_requires_admin_for_creation() -> None:
    database_url = os.environ["AGENT_TEST_DATABASE_URL"]
    workspace_id = str(uuid4())
    repository = PostgresTaskRepository(database_url)
    await repository.open()
    member = Principal(user_id="member-1", workspace_id=workspace_id, role="content_operator")
    with pytest.raises(ForbiddenError, match="administrator"):
        await repository.bootstrap_workspace(member)
    admin = Principal(user_id="admin-1", workspace_id=workspace_id, role="admin")
    results = await asyncio.gather(
        repository.bootstrap_workspace(admin),
        repository.bootstrap_workspace(admin),
    )
    created = next(result for result in results if result["created"])
    replayed = next(result for result in results if not result["created"])
    joined = await repository.bootstrap_workspace(member)
    assert created == {"workspace_id": workspace_id, "role": "admin", "created": True}
    assert replayed == {"workspace_id": workspace_id, "role": "admin", "created": False}
    assert joined == {"workspace_id": workspace_id, "role": "content_operator", "created": False}
    assert await repository.list_tasks(member) == []
    await repository.close()


@pytest.mark.asyncio
async def test_business_role_is_scoped_by_workspace_rls() -> None:
    database_url = os.environ["AGENT_TEST_DATABASE_URL"]
    first_workspace = str(uuid4())
    second_workspace = str(uuid4())
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute(
            """INSERT INTO workspaces(workspace_id,name,slug,created_by)
            VALUES(%s,'First',%s,'test'),(%s,'Second',%s,'test')""",
            (first_workspace, f"first-{first_workspace}", second_workspace, f"second-{second_workspace}"),
        )
        await connection.commit()

    parsed = urlsplit(database_url)
    host = parsed.hostname or "127.0.0.1"
    port = f":{parsed.port}" if parsed.port else ""
    business_url = urlunsplit((parsed.scheme, f"brandflow_app@{host}{port}", parsed.path, "", ""))
    async with await psycopg.AsyncConnection.connect(business_url) as connection:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (first_workspace,))
        rows = await (await connection.execute("SELECT workspace_id FROM workspaces ORDER BY workspace_id")).fetchall()
        assert [str(row[0]) for row in rows] == [first_workspace]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await connection.execute(
                "INSERT INTO workspace_members(workspace_id,user_id,role,status) VALUES(%s,'intruder','admin','active')",
                (second_workspace,),
            )


@pytest.mark.asyncio
async def test_task_idempotency_and_checkpoint_restart_recovery() -> None:
    database_url = os.environ["AGENT_TEST_DATABASE_URL"]
    workspace_id = str(uuid4())
    brand_id = str(uuid4())
    product_id = str(uuid4())
    document_id = str(uuid4())
    reviewer_id = "reviewer-1"
    suspended_id = "suspended-1"
    principal = Principal(user_id="operator-1", workspace_id=workspace_id, role="content_operator")

    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute("INSERT INTO workspaces(workspace_id,name,slug,created_by) VALUES(%s,'Test','test-'||%s,'test')", (workspace_id, workspace_id))
        await connection.execute("INSERT INTO workspace_members(workspace_id,user_id,role,status) VALUES(%s,%s,'content_operator','active'),(%s,%s,'brand_reviewer','active'),(%s,%s,'brand_reviewer','suspended')", (workspace_id, principal.user_id, workspace_id, reviewer_id, workspace_id, suspended_id))
        await connection.execute("INSERT INTO source_documents(document_id,workspace_id,document_name,document_type,version,authority_level,public_usage_allowed,status,checksum,created_by) VALUES(%s,%s,'Facts','product_fact','v1','primary',TRUE,'active','checksum','test')", (document_id, workspace_id))
        await connection.execute("INSERT INTO verified_facts(workspace_id,product_id,fact_content,source_document_id,version,authority_level,public_usage_allowed,status) VALUES(%s,%s,'Verified capability',%s,'v1','primary',TRUE,'active')", (workspace_id, product_id, document_id))
        await connection.execute("INSERT INTO brand_guideline_versions(workspace_id,brand_id,version,active) VALUES(%s,%s,'brand-v1',TRUE)", (workspace_id, brand_id))
        await connection.execute("INSERT INTO channel_spec_versions(workspace_id,channel,version,active) VALUES(%s,'wechat_website','channel-v1',TRUE)", (workspace_id,))
        await connection.commit()

    tasks = PostgresTaskRepository(database_url)
    workflow = PostgresWorkflowRepository(database_url)
    await tasks.open()
    await workflow.open()
    request = CreateTaskRequest(
        title="Nova launch",
        selected_channels=[Channel.WECHAT_WEBSITE],
        brief=BriefInput(topic="Nova", brand_id=brand_id, product_id=product_id, target_audience="IT", publishing_objective="Explain", primary_channel=Channel.WECHAT_WEBSITE, desired_audience_action="Demo"),
    )
    fenced_request = request.model_copy(update={"title": "Fenced stale worker"})
    fenced_first = await tasks.create_task(principal, fenced_request, "fenced-create-123")
    stale_lease = fenced_first["_dispatch_lease"]
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute(
            """UPDATE idempotency_records SET lease_expires_at=NOW()-INTERVAL '1 second'
            WHERE workspace_id=%s AND actor_id=%s AND action='create_task' AND idempotency_key=%s""",
            (workspace_id, principal.user_id, "fenced-create-123"),
        )
        await connection.commit()
    fenced_second = await tasks.create_task(principal, fenced_request, "fenced-create-123")
    current_lease = fenced_second["_dispatch_lease"]
    assert current_lease.version > stale_lease.version
    stale_context = LeaseContext(workspace_id, principal.user_id, "create_task", "fenced-create-123", stale_lease)
    context_token = bind_lease(stale_context)
    try:
        stale_state = AgentState(task_id=fenced_first["task_id"], workspace_id=workspace_id, user_id=principal.user_id)
        with pytest.raises(ConflictError, match="no longer active"):
            await workflow.save(state=stale_state, content_type="master_outline", content="stale write")
        checkpoint_delegate = RecordingCheckpointer()
        fenced_checkpointer = FencedCheckpointer(checkpoint_delegate, workflow)
        with pytest.raises(ConflictError, match="Checkpoint lease"):
            await fenced_checkpointer.aput({}, {}, {}, {})
        assert checkpoint_delegate.called is False
    finally:
        reset_lease(context_token)
    with pytest.raises(ConflictError, match="lease was lost"):
        await tasks.complete_idempotency(
            principal,
            "create_task",
            "fenced-create-123",
            {"task_id": fenced_first["task_id"]},
            stale_lease,
        )
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        fenced_versions = await connection.execute(
            "SELECT COUNT(*) FROM content_versions WHERE task_id=%s",
            (fenced_first["task_id"],),
        )
        assert (await fenced_versions.fetchone())[0] == 0
    short_tasks = PostgresTaskRepository(database_url, lease_seconds=0.6)
    short_workflow = PostgresWorkflowRepository(database_url, lease_seconds=0.6)
    await short_tasks.open()
    await short_workflow.open()
    slow_provider = SlowProvider()
    slow_request = request.model_copy(update={"title": "Slow lease heartbeat"})
    async with postgres_checkpointer(database_url) as saver:
        slow_service = TaskWorkflowService(tasks=short_tasks, workflow=short_workflow, provider=slow_provider, checkpointer=saver)
        first_worker = asyncio.create_task(slow_service.create_task(principal, slow_request, "slow-create-lease1"))
        await asyncio.sleep(0.9)
        with pytest.raises(ConflictError, match="already in progress"):
            await slow_service.create_task(principal, slow_request, "slow-create-lease1")
        slow_result = await first_worker
    assert slow_result["status"] == "waiting_for_outline_approval"
    assert slow_provider.calls == 2
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        slow_versions = await connection.execute(
            "SELECT COUNT(*) FROM content_versions WHERE task_id=%s AND content_type='master_outline'",
            (slow_result["task_id"],),
        )
        assert (await slow_versions.fetchone())[0] == 1
    await short_workflow.close()
    await short_tasks.close()
    created = await tasks.create_task(principal, request, "create-key-123456")
    created_lease = created["_dispatch_lease"]
    await tasks.complete_idempotency(
        principal,
        "create_task",
        "create-key-123456",
        {key: value for key, value in created.items() if not key.startswith("_")},
        created_lease,
    )
    repeated = await tasks.create_task(principal, request, "create-key-123456")
    assert repeated["task_id"] == created["task_id"]
    with pytest.raises(NotFoundError):
        await tasks.get_task(Principal(user_id=suspended_id, workspace_id=workspace_id, role="brand_reviewer"), created["task_id"])
    with pytest.raises(NotFoundError):
        await tasks.get_events(Principal(user_id=reviewer_id, workspace_id=workspace_id, role="final_approver"), created["task_id"], 0)

    crash_request = request.model_copy(update={"title": "Crash-window recovery"})
    crashed = await tasks.create_task(principal, crash_request, "create-crash-window1")
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute(
            """UPDATE idempotency_records SET lease_expires_at=NOW()-INTERVAL '1 second'
            WHERE workspace_id=%s AND actor_id=%s AND action='create_task' AND idempotency_key=%s""",
            (workspace_id, principal.user_id, "create-crash-window1"),
        )
        await connection.commit()
    async with postgres_checkpointer(database_url) as saver:
        recovery_service = TaskWorkflowService(tasks=tasks, workflow=workflow, provider=FakeProvider(), checkpointer=saver)
        recovered_create = await recovery_service.create_task(principal, crash_request, "create-crash-window1")
        repeated_recovered_create = await recovery_service.create_task(principal, crash_request, "create-crash-window1")
    assert recovered_create["task_id"] == crashed["task_id"]
    assert recovered_create["status"] == "waiting_for_outline_approval"
    assert repeated_recovered_create["status"] == "waiting_for_outline_approval"
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        version_count_cursor = await connection.execute(
            "SELECT COUNT(*) FROM content_versions WHERE task_id=%s AND content_type='master_outline'",
            (crashed["task_id"],),
        )
        assert (await version_count_cursor.fetchone())[0] == 1

    incomplete_request = CreateTaskRequest(
        title="Needs clarification",
        selected_channels=[Channel.WECHAT_WEBSITE],
        brief=BriefInput(topic="Nova", target_audience="IT", publishing_objective="Explain", desired_audience_action="Demo"),
    )
    incomplete = await tasks.create_task(principal, incomplete_request, "create-clarify-123")
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute(
            "UPDATE content_tasks SET status='waiting_for_clarification' WHERE workspace_id=%s AND task_id=%s",
            (workspace_id, incomplete["task_id"]),
        )
        await connection.commit()
    clarification_answers = {"brand_id": brand_id, "product_id": product_id, "primary_channel": "wechat_website"}
    clarification_lease = await tasks.persist_clarification(principal, incomplete["task_id"], clarification_answers, "clarify-answer-123")
    assert clarification_lease is not None
    await tasks.complete_idempotency(
        principal, "answer_clarification", "clarify-answer-123", {"task_id": incomplete["task_id"]}, clarification_lease,
    )
    assert await tasks.persist_clarification(principal, incomplete["task_id"], clarification_answers, "clarify-answer-123") is None
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        brief_cursor = await connection.execute(
            "SELECT brand_id,product_id,primary_channel,clarification_history FROM content_briefs WHERE task_id=%s",
            (incomplete["task_id"],),
        )
        persisted_brief = await brief_cursor.fetchone()
    assert str(persisted_brief[0]) == brand_id
    assert str(persisted_brief[1]) == product_id
    assert persisted_brief[2] == "wechat_website"
    assert len(persisted_brief[3]) == 3

    state = AgentState(
        task_id=created["task_id"], workspace_id=workspace_id, user_id=principal.user_id,
        brief=ContentBrief(task_id=created["task_id"], workspace_id=workspace_id, **request.brief.model_dump()),
        selected_channels=[Channel.WECHAT_WEBSITE],
    )
    config = checkpoint_config(workspace_id=workspace_id, task_id=created["task_id"])
    dependencies = WorkflowDependencies(provider=FakeProvider(), context=workflow, versions=workflow, decisions=workflow, runtime=workflow)
    async with postgres_checkpointer(database_url) as saver:
        graph = build_master_content_graph(dependencies, checkpointer=saver)
        paused = await graph.ainvoke(state, config)
    outline_version_id = paused["master_outline_version_id"]

    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        hash_cursor = await connection.execute("SELECT immutable_hash FROM content_versions WHERE content_version_id=%s", (outline_version_id,))
        content_hash = (await hash_cursor.fetchone())[0]
    with pytest.raises(ForbiddenError):
        await workflow.record_decision(
            workspace_id=workspace_id, task_id=created["task_id"], user_id=reviewer_id,
            user_role="brand_reviewer", scope="outline", content_version_id=outline_version_id,
            target_snapshot_hash="0" * 64, decision="approve", comment="Wrong hash",
            idempotency_key="outline-wrong-hash-1",
        )
    with pytest.raises(ForbiddenError):
        await workflow.record_decision(
            workspace_id=workspace_id, task_id=created["task_id"], user_id=reviewer_id,
            user_role="brand_reviewer", scope="master_brand", content_version_id=outline_version_id,
            target_snapshot_hash=content_hash, decision="approve", comment="Wrong scope",
            idempotency_key="outline-wrong-scope1",
        )
    with pytest.raises(ForbiddenError):
        await workflow.record_decision(
            workspace_id=workspace_id, task_id=created["task_id"], user_id=reviewer_id,
            user_role="brand_reviewer", scope="outline", content_version_id=str(uuid4()),
            target_snapshot_hash=content_hash, decision="approve", comment="Wrong version",
            idempotency_key="outline-wrong-version1",
        )
    with pytest.raises(ForbiddenError):
        await workflow.record_decision(
            workspace_id=workspace_id, task_id=created["task_id"], user_id=suspended_id,
            user_role="brand_reviewer", scope="outline", content_version_id=outline_version_id,
            target_snapshot_hash=content_hash, decision="approve", comment="Suspended reviewer",
            idempotency_key="outline-suspended-1",
        )
    decision_id, decision_lease = await workflow.record_decision(
        workspace_id=workspace_id, task_id=created["task_id"], user_id=reviewer_id,
        user_role="brand_reviewer", scope="outline", content_version_id=outline_version_id,
        target_snapshot_hash=content_hash, decision="approve", comment="Approved evidence",
        idempotency_key="outline-decision-1234",
    )
    assert decision_lease is not None
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute(
            """UPDATE idempotency_records SET lease_expires_at=NOW()-INTERVAL '1 second'
            WHERE workspace_id=%s AND actor_id=%s AND action='decision:outline' AND idempotency_key=%s""",
            (workspace_id, reviewer_id, "outline-decision-1234"),
        )
        await connection.commit()
    with pytest.raises(ConflictError):
        await workflow.record_decision(
            workspace_id=workspace_id, task_id=created["task_id"], user_id=reviewer_id,
            user_role="brand_reviewer", scope="outline", content_version_id=outline_version_id,
            target_snapshot_hash=content_hash, decision="approve", comment="Changed request",
            idempotency_key="outline-decision-1234",
        )

    reviewer_principal = Principal(user_id=reviewer_id, workspace_id=workspace_id, role="brand_reviewer")
    decision_request = DecisionRequest(
        content_version_id=outline_version_id,
        target_snapshot_hash=content_hash,
        decision="approve",
        comment="Approved evidence",
    )
    async with postgres_checkpointer(database_url) as saver:
        recovery_service = TaskWorkflowService(tasks=tasks, workflow=workflow, provider=FakeProvider(), checkpointer=saver)
        task_after_resume = await recovery_service.decide(
            reviewer_principal, created["task_id"], "outline", decision_request, "outline-decision-1234",
        )
        replay_after_completion = await recovery_service.decide(
            reviewer_principal, created["task_id"], "outline", decision_request, "outline-decision-1234",
        )
    assert task_after_resume["status"] == "waiting_for_master_approval"
    assert replay_after_completion["status"] == "waiting_for_master_approval"
    events = await tasks.get_events(principal, created["task_id"], 0)
    event_types = [event["event_type"] for event in events]
    for required_event in (
        "task_started", "brief_parsed", "sources_retrieved", "outline_ready",
        "human_approval_required", "master_generation_started", "master_review_completed",
    ):
        assert required_event in event_types

    await tasks.cancel_task(principal, created["task_id"], "cancel-running-1234")
    async with postgres_checkpointer(database_url) as saver:
        cancelled_graph = build_master_content_graph(dependencies, checkpointer=saver)
        cancelled = await cancelled_graph.ainvoke(Command(resume={"decision_id": "must-not-run"}), config)
    assert cancelled["status"] == "cancelled"

    cancelled_request = request.model_copy(update={"title": "Cancel me"})
    cancellable = await tasks.create_task(principal, cancelled_request, "create-key-cancel1")
    first_cancel = await tasks.cancel_task(principal, cancellable["task_id"], "cancel-key-12345")
    second_cancel = await tasks.cancel_task(principal, cancellable["task_id"], "cancel-key-12345")
    assert first_cancel == second_cancel
    await workflow.close()
    await tasks.close()


@pytest.mark.asyncio
async def test_checkpoint_role_and_schema_are_isolated_in_postgres() -> None:
    database_url = os.environ["AGENT_TEST_DATABASE_URL"]
    suffix = uuid4().hex[:12]
    business_role = f"business_{suffix}"
    checkpoint_role = f"checkpoint_{suffix}"
    checkpoint_schema = f"checkpoint_{suffix}"
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(business_role)))
        await connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(checkpoint_role)))
        await connection.execute(
            sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(sql.Identifier(checkpoint_schema), sql.Identifier(checkpoint_role))
        )
        await connection.commit()

    parsed = urlsplit(database_url)
    host = parsed.hostname or "127.0.0.1"
    port = f":{parsed.port}" if parsed.port else ""
    business_url = urlunsplit((parsed.scheme, f"{business_role}@{host}{port}", parsed.path, "", ""))
    checkpoint_url = urlunsplit((
        parsed.scheme,
        f"{checkpoint_role}@{host}{port}",
        parsed.path,
        urlencode({"options": f"-csearch_path={checkpoint_schema}"}),
        "",
    ))
    await verify_checkpoint_isolation(business_url, checkpoint_url)
    async with await psycopg.AsyncConnection.connect(checkpoint_url) as connection:
        await connection.execute("CREATE TABLE checkpoint_probe(id INTEGER)")
        await connection.commit()
    async with await psycopg.AsyncConnection.connect(business_url) as connection:
        with pytest.raises(psycopg.Error):
            await connection.execute(
                sql.SQL("SELECT * FROM {}.checkpoint_probe").format(sql.Identifier(checkpoint_schema))
            )
