"""LibreOffice conversion logic for PPTX to PDF."""

import asyncio
import os
import shutil
from pathlib import Path

import structlog

from app.config import settings

logger = structlog.get_logger()


class ConversionError(Exception):
    """Exception raised when LibreOffice conversion fails."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class LibreOfficeConverter:
    """Converts PPTX files to PDF using LibreOffice headless mode."""

    def __init__(
        self,
        libreoffice_bin: str = settings.libreoffice_bin,
        timeout_seconds: int = settings.conversion_timeout_seconds,
    ) -> None:
        """
        Initialize converter.

        Args:
            libreoffice_bin: Path to soffice binary
            timeout_seconds: Maximum conversion time before timeout
        """
        self._bin = libreoffice_bin
        self._timeout = timeout_seconds

    async def convert(
        self,
        input_path: Path,
        output_dir: Path,
        job_id: str,
    ) -> Path:
        """
        Convert a PPTX file to PDF using LibreOffice.

        Args:
            input_path: Path to input PPTX file
            output_dir: Directory to write output PDF
            job_id: Job ID (used for unique LibreOffice profile)

        Returns:
            Path to the generated PDF file

        Raises:
            ConversionError: If conversion fails or times out
        """
        # Ensure output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create unique user profile directory for this job
        # This prevents LibreOffice lock file conflicts when running concurrently
        profile_dir = Path(settings.temp_dir) / f"lo-profile-{job_id}"
        profile_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Build LibreOffice command
            cmd = [
                self._bin,
                "--headless",
                "--nologo",
                "--nolockcheck",
                "--norestore",
                f"-env:UserInstallation=file://{profile_dir}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(input_path),
            ]

            logger.debug("Executing LibreOffice command", cmd=" ".join(cmd))

            # Run LibreOffice as subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                # Kill the process on timeout
                logger.error(
                    "LibreOffice conversion timed out",
                    job_id=job_id,
                    timeout=self._timeout,
                )
                process.kill()
                await process.wait()
                raise ConversionError(
                    code="CONVERSION_TIMEOUT",
                    message=f"Conversion timed out after {self._timeout} seconds",
                )

            # Check return code
            if process.returncode != 0:
                stderr_text = stderr.decode("utf-8", errors="replace")
                # Truncate stderr for manifest
                stderr_excerpt = stderr_text[:500] if len(
                    stderr_text) > 500 else stderr_text
                logger.error(
                    "LibreOffice conversion failed",
                    job_id=job_id,
                    return_code=process.returncode,
                    stderr=stderr_excerpt,
                )
                raise ConversionError(
                    code="CONVERSION_FAILED",
                    message=f"LibreOffice exited with code {process.returncode}: {stderr_excerpt}",
                )

            # Find the output PDF
            # LibreOffice names output as input_name.pdf
            expected_output = output_dir / f"{input_path.stem}.pdf"

            logger.info(
                "LibreOffice conversion complete",
                job_id=job_id,
                output_path=str(expected_output),
                output_size_bytes=expected_output.stat().st_size,
            )

            return expected_output

        finally:
            # Clean up profile directory
            if profile_dir.exists():
                shutil.rmtree(profile_dir, ignore_errors=True)


# Global converter instance
converter = LibreOfficeConverter()
