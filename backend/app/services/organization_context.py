"""Explicit per-request organization selection. Never trusts the header as authorization."""
from contextvars import ContextVar
from uuid import UUID

_active_org: ContextVar[UUID | None] = ContextVar('medwaste_organization', default=None)

def selected_org_id() -> UUID | None:
    return _active_org.get()

def select_organization(value: str | None):
    try:
        org = UUID(value) if value else None
    except (TypeError, ValueError):
        org = None  # invalid values NEVER grant an organization
        if value:
            raise ValueError('Invalid X-Organization-ID')
    return _active_org.set(org)

def reset_organization(token):
    _active_org.reset(token)
