"""
Pydantic schemas for audit log endpoints.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: str
    environment_id: Optional[str] = None
    actor_id: Optional[str] = None
    action: str
    actor_type: str
    metadata: Optional[Dict[str, Any]] = None
    created_at: str


class PaginatedAuditResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[AuditLogResponse]