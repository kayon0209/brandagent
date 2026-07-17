from dataclasses import dataclass
from contextvars import ContextVar, Token


@dataclass(frozen=True, slots=True)
class WorkflowLease:
    owner: str
    version: int
    heartbeat_seconds: float


@dataclass(frozen=True, slots=True)
class LeaseContext:
    workspace_id: str
    actor_id: str
    action: str
    idempotency_key: str
    lease: WorkflowLease


CURRENT_LEASE: ContextVar[LeaseContext | None] = ContextVar("brandflow_workflow_lease", default=None)


def bind_lease(context: LeaseContext) -> Token:
    return CURRENT_LEASE.set(context)


def reset_lease(token: Token) -> None:
    CURRENT_LEASE.reset(token)


def current_lease() -> LeaseContext | None:
    return CURRENT_LEASE.get()
