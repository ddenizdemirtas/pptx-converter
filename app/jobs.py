"""Job manager for tracking conversion job state."""

import asyncio
from datetime import datetime
from typing import Callable, Awaitable

import structlog

from app.config import settings
from app.models import Job, JobStatus

logger = structlog.get_logger()


class JobManager:
    """
    In-memory job state manager.

    Tracks job lifecycle and enforces concurrency limits.
    """

    def __init__(self, max_concurrency: int = 1) -> None:
        """
        Initialize job manager.

        Args:
            max_concurrency: Maximum number of concurrent conversions
        """
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_concurrency = max_concurrency

    async def create_job(
        self,
        job_id: str,
        tenant_id: str,
        user_id: str,
        input_key: str,
        output_prefix: str,
    ) -> Job:
        """
        Create a new job in QUEUED state.

        Args:
            job_id: Unique job identifier
            tenant_id: Tenant identifier
            user_id: User identifier
            input_key: S3 key for input PPTX
            output_prefix: S3 key prefix for output files

        Returns:
            Created Job instance
        """
        async with self._lock:
            if job_id in self._jobs:
                logger.warning("Job already exists", job_id=job_id)
                return self._jobs[job_id]

            job = Job(
                job_id=job_id,
                tenant_id=tenant_id,
                user_id=user_id,
                status=JobStatus.QUEUED,
                input_key=input_key,
                output_prefix=output_prefix,
            )
            self._jobs[job_id] = job

            logger.info(
                "Job created",
                job_id=job_id,
                tenant_id=tenant_id,
                user_id=user_id,
                status=job.status,
            )

            return job

    async def get_job(self, job_id: str) -> Job | None:
        """
        Get a job by ID.

        Args:
            job_id: Job identifier

        Returns:
            Job instance or None if not found
        """
        async with self._lock:
            return self._jobs.get(job_id)

    async def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error_code: str | None = None,
        error_message: str | None = None,
        page_count: int | None = None,
    ) -> Job | None:
        """
        Update job status and optional metadata.

        Args:
            job_id: Job identifier
            status: New job status
            error_code: Error code (for failures)
            error_message: Error message (for failures)
            page_count: Number of pages (for success)

        Returns:
            Updated Job instance or None if not found
        """
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None

            old_status = job.status
            job.status = status

            if status == JobStatus.RUNNING:
                job.started_at = datetime.utcnow()
            elif status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
                job.completed_at = datetime.utcnow()

            if error_code:
                job.error_code = error_code
            if error_message:
                job.error_message = error_message
            if page_count is not None:
                job.page_count = page_count

            logger.info(
                "Job status updated",
                job_id=job_id,
                old_status=old_status,
                new_status=status,
            )

            return job

    async def run_with_concurrency(
        self,
        job_id: str,
        task: Callable[[], Awaitable[None]],
    ) -> None:
        """
        Run a task with concurrency control.

        Acquires semaphore, updates job to RUNNING, executes task,
        and releases semaphore.

        Args:
            job_id: Job identifier
            task: Async callable to execute
        """
        async with self._semaphore:
            await self.update_job_status(job_id, JobStatus.RUNNING)
            try:
                await task()
            except Exception:
                # Task is responsible for updating job status on failure
                raise

    def get_active_job_count(self) -> int:
        """Get count of jobs currently running."""
        return self._max_concurrency - self._semaphore._value


# Global job manager instance
job_manager = JobManager(max_concurrency=settings.concurrency)
