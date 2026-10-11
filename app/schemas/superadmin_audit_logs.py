from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class AuditLogResponse(BaseModel):
    """Schema for individual audit log entry details."""
    id: str
    user_id: Optional[str] = None
    user_name: str = "System"
    user_email: Optional[str] = None
    user_role: str = "system"
    action: str
    module: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    description: Optional[str] = None
    ip_address: Optional[str] = "127.0.0.1"
    user_agent: Optional[str] = None
    request_method: Optional[str] = None
    endpoint: Optional[str] = None
    status: str = "SUCCESS"
    metadata: Optional[Dict[str, Any]] = None
    created_at: str


class AuditLogListResponse(BaseModel):
    """Paginated list response for audit logs."""
    items: List[AuditLogResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    limit: int = 10


class BulkDeleteAuditLogsRequest(BaseModel):
    """Request schema for deleting multiple audit log entries."""
    log_ids: List[str] = Field(..., min_length=1, description="List of audit log UUIDs to delete")


class BulkDeleteAuditLogsResponse(BaseModel):
    """Response schema for bulk delete operation."""
    success: bool = True
    deleted_count: int = 0
    message: str = "Audit logs deleted successfully"
