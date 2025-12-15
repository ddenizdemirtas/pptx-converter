"""Conversion pipeline orchestrator."""

import asyncio
import shutil
from pathlib import Path
import structlog
from app.config import settings
from app.converter import converter, ConversionError
from app.jobs import job_manager
from app.models import (
    Job,
    JobStatus,
    SuccessManifest,
    FailureManifest,
    PageInfo,
    ErrorInfo,
)
from app.s3 import s3_client
from app.splitter import splitter, SplitterError

logger = structlog.get_logger()


class ConversionPipeline:
    """
    Orchestrates the full conversion pipeline:
    1. Download PPTX from S3
    2. Convert to PDF via LibreOffice
    3. Split into per-page PDFs
    4. Upload all outputs to S3
    5. Write manifest (success or failure)
    """

    async def run(self, job: Job) -> None:
        """
        Execute the full conversion pipeline for a job.

        Args:
            job: Job instance with all required metadata
        """
        job_id = job.job_id
        work_dir = Path(settings.temp_dir) / f"job-{job_id}"

        logger.info(
            "Starting conversion pipeline",
            job_id=job_id,
            tenant_id=job.tenant_id,
            input_key=job.input_key,
        )

        try:
            # Create working directory
            work_dir.mkdir(parents=True, exist_ok=True)
            input_dir = work_dir / "input"
            pdf_dir = work_dir / "pdf"
            pages_dir = work_dir / "pages"

            input_dir.mkdir(exist_ok=True)
            pdf_dir.mkdir(exist_ok=True)
            pages_dir.mkdir(exist_ok=True)

            # Step A: Download PPTX from S3
            input_path = input_dir / "deck.pptx"
            await asyncio.to_thread(
                s3_client.download_file,
                job.input_bucket,
                job.input_key,
                input_path,
            )

            # Validate file size
            file_size_mb = input_path.stat().st_size / (1024 * 1024)
            if file_size_mb > settings.max_input_size_mb:
                raise ConversionError(
                    code="FILE_TOO_LARGE",
                    message=f"Input file is {file_size_mb:.1f}MB, max is {settings.max_input_size_mb}MB",
                )

            # Step B: Convert PPTX to PDF via LibreOffice
            deck_pdf_path = await converter.convert(input_path, pdf_dir, job_id)

            # Step C: Split PDF into pages
            page_count, page_paths = await asyncio.to_thread(
                splitter.split, deck_pdf_path, pages_dir
            )

            # Step D: Upload outputs to S3
            page_infos: list[PageInfo] = []
            for i, page_path in enumerate(page_paths):
                page_num = i + 1
                page_key = f"{job.output_prefix}pages/{page_num:04d}.pdf"

                await asyncio.to_thread(
                    s3_client.upload_file,
                    page_path,
                    job.output_bucket,
                    page_key,
                )

                page_infos.append(PageInfo(page=page_num, key=page_key))

            # Write success manifest LAST
            manifest = SuccessManifest(
                jobId=job_id,
                userId=job.tenant_id,
                status="succeeded",
                pageCount=page_count,
                pages=page_infos,
            )
            manifest_key = f"{job.output_prefix}manifest.json"

            await asyncio.to_thread(
                s3_client.upload_json,
                manifest.model_dump_json(indent=2),
                job.output_bucket,
                manifest_key,
            )

            # Update job status to succeeded
            await job_manager.update_job_status(
                job_id=job_id,
                status=JobStatus.SUCCEEDED,
                page_count=page_count,
            )

            logger.info(
                "Conversion pipeline completed successfully",
                job_id=job_id,
                page_count=page_count,
            )

        except (ConversionError, SplitterError) as e:
            # Known conversion/splitting errors
            logger.error(
                "Conversion pipeline failed",
                job_id=job_id,
                error_code=e.code,
                error_message=e.message,
            )
            await self._write_failure_manifest(job, e.code, e.message)
            await job_manager.update_job_status(
                job_id=job_id,
                status=JobStatus.FAILED,
                error_code=e.code,
                error_message=e.message,
            )

        except Exception as e:
            # Unexpected errors
            logger.exception(
                "Conversion pipeline failed with unexpected error", job_id=job_id)
            error_message = str(e)[:500]  # Truncate for manifest
            await self._write_failure_manifest(job, "UNEXPECTED_ERROR", error_message)
            await job_manager.update_job_status(
                job_id=job_id,
                status=JobStatus.FAILED,
                error_code="UNEXPECTED_ERROR",
                error_message=error_message,
            )

        finally:
            # Clean up working directory
            if work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)
                logger.debug("Cleaned up work directory",
                             work_dir=str(work_dir))

    async def _write_failure_manifest(
        self, job: Job, error_code: str, error_message: str
    ) -> None:
        """
        Write a failure manifest to S3.

        Args:
            job: Job instance
            error_code: Error code
            error_message: Error message
        """
        try:
            manifest = FailureManifest(
                jobId=job.job_id,
                userId=job.tenant_id,
                status="failed",
                error=ErrorInfo(code=error_code, message=error_message),
            )
            manifest_key = f"{job.output_prefix}manifest.json"

            await asyncio.to_thread(
                s3_client.upload_json,
                manifest.model_dump_json(indent=2),
                job.output_bucket,
                manifest_key,
            )

            logger.info("Failure manifest written",
                        job_id=job.job_id, key=manifest_key)

        except Exception as e:
            # Log but don't fail - the job is already failed
            logger.error(
                "Failed to write failure manifest",
                job_id=job.job_id,
                error=str(e),
            )


# Global pipeline instance
pipeline = ConversionPipeline()
