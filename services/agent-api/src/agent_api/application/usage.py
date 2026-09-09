"""Consumer usage ledger (upgrade plan task 13).

The FastAPI usage ledger is the ONLY authority for C-end quota:

- reserve happens BEFORE the model call; quota exhaustion raises
  QuotaExceeded and the caller never invokes the provider;
- settle is idempotent per (workspace, request_id): replays never
  double-charge;
- tokens are 'measured' when the provider reported them, 'estimated'
  otherwise (reservation estimate);
- provider failures refund the reservation;
- drafts and manual editing never touch the ledger at all.

Legacy Supabase quota endpoints are deprecated, not double-written.
"""

from __future__ import annotations

from typing import Protocol

from agent_api.api.security import Principal
from agent_api.domain.errors import ConflictError, NotFoundError
from agent_api.providers.base import ProviderExecutionError


class QuotaExceeded(ConflictError):
    code = "QUOTA_EXCEEDED"

    def __init__(self, message: str = "本月额度已用完，AI 功能暂停；写作与保存不受影响。") -> None:
        super().__init__(message)


class UsageLedgerStore(Protocol):
    async def ensure_workspace(self, workspace_id: str, user_id: str) -> None: ...
    async def find_entry(self, workspace_id: str, request_id: str) -> dict | None: ...
    async def insert_entry(self, entry: dict) -> dict: ...
    async def update_entry(self, workspace_id: str, request_id: str, updates: dict) -> dict: ...
    async def committed_tokens(self, workspace_id: str) -> int: ...
    async def usage_summary(self, workspace_id: str) -> dict | None: ...


class UsageLedgerService:
    def __init__(self, *, store: UsageLedgerStore, quota: int = 30000) -> None:
        self._store = store
        self._quota = quota

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _require_workspace(self, principal: Principal) -> None:
        await self._store.ensure_workspace(principal.workspace_id, principal.user_id)

    # ------------------------------------------------------------------
    # public interface
    # ------------------------------------------------------------------

    async def reserve(
        self,
        principal: Principal,
        *,
        request_id: str,
        operation: str,
        estimated_tokens: int,
    ) -> dict:
        """Reserve quota BEFORE the model call. Idempotent per request id."""

        await self._require_workspace(principal)
        existing = await self._store.find_entry(principal.workspace_id, request_id)
        if existing is not None:
            return {**existing, "replayed": True}

        # settled usage + open reservations both count against the quota
        used = await self._store.committed_tokens(principal.workspace_id)
        if used + estimated_tokens > self._quota:
            raise QuotaExceeded()

        entry = await self._store.insert_entry(
            {
                "workspace_id": principal.workspace_id,
                "request_id": request_id,
                "user_id": principal.user_id,
                "operation": operation,
                "estimated_tokens": estimated_tokens,
                "state": "reserved",
                "quota": self._quota,  # store serializes concurrent reserves (TOCTOU fix)
            }
        )
        if entry is None:
            # the atomic guard-INSERT rejected the reservation (quota oversubscribed
            # by concurrent requests); nothing partial was persisted
            raise QuotaExceeded()
        return {**entry, "replayed": False}

    async def settle(
        self,
        principal: Principal,
        *,
        request_id: str,
        operation: str,
        input_tokens: int | None,
        output_tokens: int | None,
        model: str | None,
        minimum_total_tokens: int | None = None,
    ) -> dict:
        """Settle a reservation with real (or estimated) usage. Idempotent.

        ``minimum_total_tokens`` is a conservative lower bound for a
        partially measured operation. It is used when a batch has known
        completed calls but a later non-idempotent call lost its response:
        charge no less than the reservation or those known calls.
        """

        await self._require_workspace(principal)
        entry = await self._store.find_entry(principal.workspace_id, request_id)
        if entry is None:
            # A settle without a prior reserve still books a row (defensive)
            entry = await self._store.insert_entry(
                {
                    "workspace_id": principal.workspace_id,
                    "request_id": request_id,
                    "user_id": principal.user_id,
                    "operation": operation,
                    "estimated_tokens": 0,
                    "state": "reserved",
                }
            )
        if entry.get("state") == "settled":
            return {**entry, "replayed": True}

        if input_tokens is not None and output_tokens is not None:
            total_tokens = int(input_tokens) + int(output_tokens)
            usage_source = "measured"
        else:
            total_tokens = int(entry.get("estimated_tokens") or 0)
            usage_source = "estimated"

        if minimum_total_tokens is not None:
            total_tokens = max(total_tokens, int(minimum_total_tokens))
            # The complete batch usage is not observable after a response
            # loss, even if earlier calls returned token counts.
            usage_source = "estimated"

        updated = await self._store.update_entry(
            principal.workspace_id,
            request_id,
            {
                "state": "settled",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "model": model,
                "total_tokens": total_tokens,
                "usage_source": usage_source,
                "estimated_cost": total_tokens * 0.000001,
            },
        )
        return {**updated, "replayed": False}

    async def refund(self, principal: Principal, *, request_id: str, reason: str) -> dict:
        """Release a reservation without charging (provider failure etc.).

        Settled entries are NEVER refunded: a settled row is a completed,
        billable charge (crash between a settle and the terminal status
        write must not erase it). Both refunds and settles are idempotent.
        """

        entry = await self._store.find_entry(principal.workspace_id, request_id)
        if entry is None:
            raise NotFoundError(f"usage entry {request_id} not found")
        if entry.get("state") == "settled":
            return {**entry, "replayed": True}
        if entry.get("state") == "refunded":
            return {**entry, "replayed": True}
        updated = await self._store.update_entry(
            principal.workspace_id,
            request_id,
            {"state": "refunded", "total_tokens": 0, "refund_reason": reason},
        )
        return {**updated, "replayed": False}

    async def usage_summary(self, principal: Principal) -> dict:
        """Per-workspace usage. Cross-workspace reads are impossible by scoping.

        P1-D: a workspace with NO creator_profiles row is simply a fresh
        workspace that never reserved anything — its usage is zero, not a
        404. The quota pill is an always-on UI surface; a brand-new user
        must see the full quota, not an error."""

        summary = await self._store.usage_summary(principal.workspace_id)
        if summary is None:
            return {"workspace_id": principal.workspace_id, "used": 0, "quota": self._quota}
        return summary


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def ledgered_call(
    ledger: UsageLedgerService,
    principal: Principal,
    *,
    request_id: str,
    operation: str,
    estimated_tokens: int,
):
    """Route-level quota guard: reserve BEFORE the model call.

    - QuotaExceeded propagates and the guarded call never runs;
    - a REPLAYED reserve (the ledger already holds this request_id) sets
      outcome["replayed"]=True and the body is SKIPPED: a network retry
      under the same Idempotency-Key must not re-invoke the provider,
      re-book ledger rows, or re-generate candidates/variants;
    - success settles with the reservation estimate unless the caller
      wrote real provider tokens into `outcome`;
    - ordinary failures refund the reservation;
    - a provider response-loss failure settles the estimate because the
      non-idempotent provider POST may already have been executed.
    """

    reserved = await ledger.reserve(
        principal,
        request_id=request_id,
        operation=operation,
        estimated_tokens=estimated_tokens,
    )
    outcome: dict = {"input_tokens": None, "output_tokens": None, "model": None, "replayed": bool(reserved.get("replayed"))}
    if outcome["replayed"]:
        # the first execution already settled (or refunded) this key: the
        # replay must be a no-op for tokens and for generated artifacts
        yield outcome
        return
    try:
        yield outcome
    except ProviderExecutionError as error:
        if error.code == "MODEL_EXECUTION_UNKNOWN" or error.execution_confirmed:
            await ledger.settle(
                principal,
                request_id=request_id,
                operation=operation,
                input_tokens=outcome.get("input_tokens"),
                output_tokens=outcome.get("output_tokens"),
                model=outcome.get("model"),
                # A prior model call in this same ledgered operation may
                # have returned real usage before this call became unknown
                # or confirmed-but-unparseable. Never replace that lower
                # bound with a smaller fixed reservation estimate.
                minimum_total_tokens=estimated_tokens,
            )
        elif outcome.get("model_executed"):
            # A multi-step operation (for example, free-intent classify then
            # rewrite) may fail on a later provider call. The first call has
            # already run and reported measured usage, so refunding the whole
            # operation would make that completed model call free.
            await ledger.settle(
                principal,
                request_id=request_id,
                operation=operation,
                input_tokens=outcome.get("input_tokens"),
                output_tokens=outcome.get("output_tokens"),
                model=outcome.get("model"),
            )
        else:
            await ledger.refund(principal, request_id=request_id, reason="CALL_FAILED")
        raise
    except Exception as error:
        # Application adapters can preserve this semantic without importing
        # the provider-layer exception type (for example, variant generation
        # returns a public VariantGenerationError). The provider POST may
        # already have run, so refunding would make a paid call free.
        if getattr(error, "execution_unknown", False):
            await ledger.settle(
                principal,
                request_id=request_id,
                operation=operation,
                input_tokens=None,
                output_tokens=None,
                model=None,
            )
        elif getattr(error, "execution_confirmed", False) or outcome.get("model_executed"):
            # The provider returned normally and a later local parser,
            # validator, or persistence operation rejected the result. The
            # invocation is already billable; keep its measured tokens (or
            # reservation estimate when the provider omitted usage fields).
            await ledger.settle(
                principal,
                request_id=request_id,
                operation=operation,
                input_tokens=outcome.get("input_tokens"),
                output_tokens=outcome.get("output_tokens"),
                model=outcome.get("model"),
            )
        else:
            await ledger.refund(principal, request_id=request_id, reason="CALL_FAILED")
        raise
    if outcome.get("execution_unknown"):
        await ledger.settle(
            principal,
            request_id=request_id,
            operation=operation,
            input_tokens=outcome.get("input_tokens"),
            output_tokens=outcome.get("output_tokens"),
            model=outcome.get("model"),
            minimum_total_tokens=estimated_tokens,
        )
        return
    await ledger.settle(
        principal,
        request_id=request_id,
        operation=operation,
        input_tokens=outcome.get("input_tokens"),
        output_tokens=outcome.get("output_tokens"),
        model=outcome.get("model"),
    )
