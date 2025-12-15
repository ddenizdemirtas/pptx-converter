"""Pydantic models for request/response schemas and internal data structures."""

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Possible states of a conversion job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# ============================================================================
# API Request/Response Models
# ============================================================================


class S3Ref(BaseModel):
    """S3 bucket and path reference."""

    bucket: str
    key: str = Field(..., description="S3 key or prefix path")


class CreateJobRequest(BaseModel):
    """Request body for POST /v1/jobs."""

    tenantId: str = Field(..., description="Tenant identifier")
    jobId: str = Field(..., description="Unique job identifier")
    input: S3Ref = Field(..., description="S3 location of input PPTX")
    output: S3Ref = Field(..., description="S3 output prefix for results")

    model_config = {"populate_by_name": True}


class CreateJobResponse(BaseModel):
    """Response for POST /v1/jobs."""

    jobId: str
    status: JobStatus


class GetJobResponse(BaseModel):
    """Response for GET /v1/jobs/{jobId}."""

    jobId: str
    userId: str
    status: JobStatus
    manifest: S3Ref | None = None


# ============================================================================
# Manifest Models
# ============================================================================


class PageInfo(BaseModel):
    """Information about a single page PDF."""

    page: int
    key: str


class SuccessManifest(BaseModel):
    """Manifest written on successful conversion."""

    jobId: str
    userId: str
    status: str = "succeeded"
    pageCount: int
    pages: list[PageInfo]


class ErrorInfo(BaseModel):
    """Error information in failure manifest."""

    code: str
    message: str


class FailureManifest(BaseModel):
    """Manifest written on failed conversion."""

    jobId: str
    userId: str
    status: str = "failed"
    error: ErrorInfo


# ============================================================================
# Internal Job State
# ============================================================================


class Job(BaseModel):
    """Internal representation of a conversion job."""

    job_id: str
    tenant_id: str
    status: JobStatus
    input_bucket: str
    input_key: str
    output_bucket: str
    output_prefix: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    page_count: int | None = None
