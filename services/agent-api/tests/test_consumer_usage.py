"""Consumer usage ledger tests (upgrade plan task 13).

Idempotency, measured/estimated, pre-model quota rejection that never
blocks plain draft saving, settle/refund policies, and per-workspace
privacy.
"""

from __future__ import annotations

import pytest

from agent_api.api.security import Principal
from agent_api.application.usage import (
    QuotaExceeded,
    UsageLedgerService,
    ledgered_call,
)
from agent_api.domain.errors import NotFoundError
from agent_api.providers.base import ProviderExecutionError


def principal_for(workspace_id: str) -> Principal:
    return Principal(user_id="consumer-1", workspace_id=workspace_id, role="admin", experience="personal")


class MemoryUsageStore:
    """In-memory UsageLedgerStore: PK (workspace_id, request_id)."""

    def __init__(self, *, quota: int = 30000) -> None:
        self.quota = quota
        self.rows: dict[tuple[str, str], dict] = {}
        self.workspaces: set[str] = set()

    async def ensure_workspace(self, workspace_id: str, user_id: str) -> None:
        self.workspaces.add(workspace_id)

    async def find_entry(self, workspace_id: str, request_id: str) -> dict | None:
        entry = self.rows.get((workspace_id, request_id))
        return dict(entry) if entry else None

    async def insert_entry(self, entry: dict) -> dict:
        key = (entry["workspace_id"], entry["request_id"])
        if key in self.rows:
            raise KeyError("duplicate insert")
        self.rows[key] = dict(entry)
        return dict(entry)

    async def update_entry(self, workspace_id: str, request_id: str, updates: dict) -> dict:
        entry = self.rows[(workspace_id, request_id)]
        entry.update(updates)
        return dict(entry)

    async def settled_total(self, workspace_id: str) -> int:
        return sum(
            (entry.get("total_tokens") or 0)
            for (ws, _), entry in self.rows.items()
            if ws == workspace_id and entry["state"] == "settled"
        )

    async def committed_tokens(self, workspace_id: str) -> int:
        total = 0
        for (ws, _), entry in self.rows.items():
            if ws != workspace_id:
                continue
            if entry["state"] == "settled":
                total += entry.get("total_tokens") or 0
            elif entry["state"] == "reserved":
                total += entry.get("estimated_tokens") or 0
        return total

    async def usage_summary(self, workspace_id: str) -> dict | None:
        if workspace_id not in self.workspaces:
            return None
        return {
            "workspace_id": workspace_id,
            "used": await self.settled_total(workspace_id),
            "quota": self.quota,
        }


def make_service(*, quota: int = 30000) -> tuple[UsageLedgerService, MemoryUsageStore]:
    store = MemoryUsageStore(quota=quota)
    return UsageLedgerService(store=store, quota=quota), store


@pytest.mark.asyncio
async def test_reserve_then_settle_is_idempotent_per_request_id() -> None:
    service, store = make_service()
    principal = principal_for("ws-1")
    first = await service.reserve(principal, request_id="req-1", operation="suggestion", estimated_tokens=100)
    assert first["state"] == "reserved"
    # a second reserve with the same request id replays, never double-books
    replay = await service.reserve(principal, request_id="req-1", operation="suggestion", estimated_tokens=100)
    assert replay["replayed"] is True

    result = await service.settle(
        principal,
        request_id="req-1",
        operation="suggestion",
        input_tokens=40,
        output_tokens=35,
        model="glm-4.5-air",
    )
    assert result["state"] == "settled"
    assert result["total_tokens"] == 75
    # settling the SAME request again must not double-charge
    again = await service.settle(
        principal,
        request_id="req-1",
        operation="suggestion",
        input_tokens=40,
        output_tokens=35,
        model="glm-4.5-air",
    )
    assert again["replayed"] is True
    assert await store.settled_total("ws-1") == 75


@pytest.mark.asyncio
async def test_settle_records_measured_tokens_and_estimated_when_missing() -> None:
    service, _ = make_service()
    principal = principal_for("ws-1")
    await service.reserve(principal, request_id="req-2", operation="draft_generation", estimated_tokens=200)
    measured = await service.settle(
        principal, request_id="req-2", operation="draft_generation",
        input_tokens=120, output_tokens=130, model="glm-4.5-air",
    )
    assert measured["usage_source"] == "measured"

    await service.reserve(principal, request_id="req-3", operation="suggestion", estimated_tokens=90)
    estimated = await service.settle(
        principal, request_id="req-3", operation="suggestion",
        input_tokens=None, output_tokens=None, model=None,
    )
    assert estimated["usage_source"] == "estimated"
    assert estimated["total_tokens"] == 90


@pytest.mark.asyncio
async def test_quota_exhausted_rejects_model_calls_before_they_run() -> None:
    service, _ = make_service(quota=100)
    principal = principal_for("ws-1")
    await service.reserve(principal, request_id="req-4", operation="draft_generation", estimated_tokens=60)
    # second call exceeds the quota and must raise BEFORE the model runs
    with pytest.raises(QuotaExceeded):
        await service.reserve(principal, request_id="req-5", operation="suggestion", estimated_tokens=60)
    # the failed reservation must not be ledgered as settled usage
    entry = await _find(service, "ws-1", "req-5")
    assert entry is None


async def _find(service: UsageLedgerService, workspace_id: str, request_id: str) -> dict | None:
    return await service._store.find_entry(workspace_id, request_id)


@pytest.mark.asyncio
async def test_failed_model_calls_refund_the_reservation() -> None:
    service, store = make_service()
    principal = principal_for("ws-1")
    await service.reserve(principal, request_id="req-6", operation="draft_generation", estimated_tokens=500)
    refunded = await service.refund(principal, request_id="req-6", reason="PROVIDER_FAILED")
    assert refunded["state"] == "refunded"
    assert await store.settled_total("ws-1") == 0


@pytest.mark.asyncio
async def test_ambiguous_provider_execution_settles_the_estimate_instead_of_refunding() -> None:
    service, store = make_service()
    principal = principal_for("ws-1")

    with pytest.raises(ProviderExecutionError, match="response was lost"):
        async with ledgered_call(
            service,
            principal,
            request_id="req-unknown-execution",
            operation="suggestion",
            estimated_tokens=600,
        ):
            raise ProviderExecutionError(
                "MODEL_EXECUTION_UNKNOWN",
                "The provider may have executed the request but the response was lost.",
                retryable=False,
            )

    entry = await _find(service, "ws-1", "req-unknown-execution")
    assert entry is not None
    assert entry["state"] == "settled"
    assert entry["total_tokens"] == 600
    assert await store.settled_total("ws-1") == 600


@pytest.mark.asyncio
async def test_confirmed_provider_execution_settles_the_estimate_instead_of_refunding() -> None:
    service, _ = make_service()
    principal = principal_for("ws-1")

    with pytest.raises(ProviderExecutionError, match="invalid response"):
        async with ledgered_call(
            service,
            principal,
            request_id="req-confirmed-execution",
            operation="suggestion",
            estimated_tokens=600,
        ):
            raise ProviderExecutionError(
                "MODEL_INVALID_RESPONSE",
                "The provider returned an invalid response.",
                retryable=False,
                execution_confirmed=True,
            )

    entry = await _find(service, "ws-1", "req-confirmed-execution")
    assert entry is not None
    assert entry["state"] == "settled"
    assert entry["total_tokens"] == 600
    assert entry["usage_source"] == "estimated"


@pytest.mark.asyncio
async def test_second_model_response_loss_preserves_measured_usage_from_the_first_call() -> None:
    service, _ = make_service()
    principal = principal_for("ws-1")

    with pytest.raises(ProviderExecutionError, match="response was lost"):
        async with ledgered_call(
            service,
            principal,
            request_id="req-second-call-unknown",
            operation="suggestion",
            estimated_tokens=900,
        ) as outcome:
            outcome.update(
                {
                    "model_executed": True,
                    "input_tokens": 800,
                    "output_tokens": 700,
                    "model": "glm-test",
                }
            )
            raise ProviderExecutionError(
                "MODEL_EXECUTION_UNKNOWN",
                "The provider response was lost after the second call.",
                retryable=False,
            )

    entry = await _find(service, "ws-1", "req-second-call-unknown")
    assert entry is not None
    assert entry["state"] == "settled"
    assert entry["total_tokens"] == 1500
    assert entry["usage_source"] == "estimated"


@pytest.mark.asyncio
async def test_second_model_timeout_preserves_measured_usage_from_the_first_call() -> None:
    """A failed follow-up must not refund a classifier call that completed."""

    service, _ = make_service()
    principal = principal_for("ws-1")

    with pytest.raises(ProviderExecutionError, match="timed out"):
        async with ledgered_call(
            service,
            principal,
            request_id="req-second-call-timeout",
            operation="suggestion",
            estimated_tokens=900,
        ) as outcome:
            outcome.update(
                {
                    "model_executed": True,
                    "input_tokens": 80,
                    "output_tokens": 20,
                    "model": "glm-test",
                }
            )
            raise ProviderExecutionError("MODEL_TIMEOUT", "The second provider call timed out.", retryable=True)

    entry = await _find(service, "ws-1", "req-second-call-timeout")
    assert entry is not None
    assert entry["state"] == "settled"
    assert entry["total_tokens"] == 100
    assert entry["usage_source"] == "measured"


@pytest.mark.asyncio
async def test_unknown_execution_marker_on_a_wrapped_error_settles_the_estimate() -> None:
    class WrappedUnknownExecutionError(RuntimeError):
        execution_unknown = True

    service, store = make_service()
    principal = principal_for("ws-1")

    with pytest.raises(WrappedUnknownExecutionError):
        async with ledgered_call(
            service,
            principal,
            request_id="req-wrapped-unknown-execution",
            operation="variant_generation",
            estimated_tokens=900,
        ):
            raise WrappedUnknownExecutionError("a downstream adapter preserved an unknown execution")

    entry = await _find(service, "ws-1", "req-wrapped-unknown-execution")
    assert entry is not None
    assert entry["state"] == "settled"
    assert entry["total_tokens"] == 900


@pytest.mark.asyncio
async def test_partial_batch_response_loss_never_settles_below_known_measured_tokens() -> None:
    """The earlier variant calls in a batch may report real usage before a
    later non-idempotent request loses its response. Preserve that lower
    bound even when the final aggregate is not fully knowable."""

    service, _ = make_service()
    principal = principal_for("ws-1")

    async with ledgered_call(
        service,
        principal,
        request_id="req-partial-batch-unknown",
        operation="variants",
        estimated_tokens=3000,
    ) as outcome:
        outcome.update(
            {
                "input_tokens": 2200,
                "output_tokens": 3100,
                "model": "glm-test",
                "execution_unknown": True,
            }
        )

    entry = await _find(service, "ws-1", "req-partial-batch-unknown")
    assert entry is not None
    assert entry["state"] == "settled"
    assert entry["total_tokens"] == 5300
    assert entry["usage_source"] == "estimated"


@pytest.mark.asyncio
async def test_local_rejection_after_a_confirmed_model_result_keeps_measured_usage() -> None:
    service, _ = make_service()
    principal = principal_for("ws-1")

    with pytest.raises(ValueError, match="local validation"):
        async with ledgered_call(
            service,
            principal,
            request_id="req-confirmed-result-local-rejection",
            operation="variants",
            estimated_tokens=1200,
        ) as outcome:
            outcome.update(
                {
                    "model_executed": True,
                    "input_tokens": 700,
                    "output_tokens": 800,
                    "model": "glm-test",
                }
            )
            raise ValueError("local validation rejected the returned content")

    entry = await _find(service, "ws-1", "req-confirmed-result-local-rejection")
    assert entry is not None
    assert entry["state"] == "settled"
    assert entry["total_tokens"] == 1500
    assert entry["usage_source"] == "measured"


@pytest.mark.asyncio
async def test_usage_summary_is_private_per_workspace() -> None:
    service, store = make_service()
    principal = principal_for("ws-1")
    await service.reserve(principal, request_id="req-7", operation="suggestion", estimated_tokens=50)
    await service.settle(
        principal, request_id="req-7", operation="suggestion",
        input_tokens=20, output_tokens=25, model="glm-4.5-air",
    )
    summary = await service.usage_summary(principal_for("ws-1"))
    assert summary["used"] == 45
    # another workspace sees only its own usage (empty here)
    intruder = principal_for("ws-2")
    store.workspaces.add("ws-2")
    other = await service.usage_summary(intruder)
    assert other["used"] == 0
    assert other["workspace_id"] == "ws-2"


@pytest.mark.asyncio
async def test_summary_for_a_never_ledgered_workspace_is_zero_not_404() -> None:
    # P1-D contract update: a workspace with no creator_profiles row is a
    # FRESH workspace (nothing reserved yet), not a missing one. The quota
    # pill is an always-on surface — 404 hid the quota from every new user.
    service, _ = make_service()
    summary = await service.usage_summary(principal_for("never-seen"))
    assert summary["used"] == 0
    assert summary["quota"] == 30000


# ---------------------------------------------------------------------
# P1-D: fresh workspaces report ZERO usage, not 404 — the quota pill is
# an always-on surface; a brand-new user must see the full quota
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_usage_summary_returns_zero_for_a_never_ledgered_workspace():
    class NoProfileStore:
        async def usage_summary(self, workspace_id):
            return None  # no creator_profiles row for this workspace

    service = UsageLedgerService(store=NoProfileStore(), quota=30000)
    summary = await service.usage_summary(
        Principal(user_id="u-1", workspace_id="ws-fresh", role="admin", experience="personal")
    )
    assert summary == {"workspace_id": "ws-fresh", "used": 0, "quota": 30000}
