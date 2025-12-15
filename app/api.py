"""HTTP API endpoints for the conversion service."""

import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
import structlog

from app.jobs import job_manager
from app.models import (
    CreateJobRequest,
    CreateJobResponse,
    GetJobResponse,
    JobStatus,
    S3Ref,
)
from app.pipeline import pipeline

logger = structlog.get_logger()

router = APIRouter(prefix="/v1", tags=["jobs"])


@router.post("/jobs", response_model=CreateJobResponse)
async def create_job(
    request: CreateJobRequest,
    background_tasks: BackgroundTasks,
) -> CreateJobResponse:
    """
    Start a new conversion job.

    The job runs asynchronously in the background. Poll GET /v1/jobs/{jobId}
    for status updates. The job is complete when status is 'succeeded' or 'failed'.
    """
    logger.info(
        "Received job creation request",
        job_id=request.jobId,
        user_id=request.userId,
        input_key=request.input.key,
    )

    # Check if job already exists
    existing_job = await job_manager.get_job(request.jobId)
    if existing_job:
        logger.info("Job already exists, returning current status",
                    job_id=request.jobId)
        return CreateJobResponse(
            jobId=existing_job.job_id,
            status=existing_job.status,
        )

    # Create new job
    job = await job_manager.create_job(
        job_id=request.jobId,
        user_id=request.userId,
        input_bucket=request.input.bucket,
        input_key=request.input.key,
        output_bucket=request.output.bucket,
        output_prefix=request.output.key,
    )

    # Schedule background conversion task
    async def run_conversion():
        """Wrapper to run conversion with concurrency control."""
        await job_manager.run_with_concurrency(
            job_id=job.job_id,
            task=lambda: pipeline.run(job),
        )

    background_tasks.add_task(run_conversion)

    logger.info("Job queued for conversion", job_id=job.job_id)

    return CreateJobResponse(
        jobId=job.job_id,
        status=JobStatus.QUEUED,
    )


@router.get("/jobs/{job_id}", response_model=GetJobResponse)
async def get_job(
    job_id: str,
    userId: str = Query(..., description="User identifier"),
) -> GetJobResponse:
    """
    Get the status of a conversion job.

    The 'manifest' field is populated when the job has completed (succeeded or failed).
    """
    job = await job_manager.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Verify user matches (basic authorization)
    if job.user_id != userId:
        raise HTTPException(status_code=404, detail="Job not found")

    # Build manifest location if job is complete
    manifest: S3Ref | None = None
    if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
        manifest = S3Ref(
            bucket=job.output_bucket,
            key=f"{job.output_prefix}manifest.json",
        )

    return GetJobResponse(
        jobId=job.job_id,
        userId=job.user_id,
        status=job.status,
        manifest=manifest,
    )
