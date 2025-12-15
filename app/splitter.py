"""PDF splitting logic to extract individual pages."""

from pathlib import Path

import structlog
from pypdf import PdfReader, PdfWriter

logger = structlog.get_logger()


class SplitterError(Exception):
    """Exception raised when PDF splitting fails."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class PdfSplitter:
    """Splits a multi-page PDF into individual page PDFs."""

    def split(self, input_pdf: Path, output_dir: Path) -> tuple[int, list[Path]]:
        """
        Split a PDF into individual page files.

        Args:
            input_pdf: Path to input PDF file
            output_dir: Directory to write page PDFs

        Returns:
            Tuple of (page_count, list of page PDF paths)

        Raises:
            SplitterError: If splitting fails
        """
        try:
            # Ensure output directory exists
            output_dir.mkdir(parents=True, exist_ok=True)

            # Read input PDF
            reader = PdfReader(input_pdf)
            page_count = len(reader.pages)

            if page_count == 0:
                raise SplitterError(
                    code="EMPTY_PDF",
                    message="PDF has no pages",
                )

            page_paths: list[Path] = []

            for i, page in enumerate(reader.pages):
                # Create zero-padded filename: 0001.pdf, 0002.pdf, etc.
                page_num = i + 1
                page_filename = f"{page_num:04d}.pdf"
                page_path = output_dir / page_filename

                # Write single page PDF
                writer = PdfWriter()
                writer.add_page(page)

                with open(page_path, "wb") as f:
                    writer.write(f)

                page_paths.append(page_path)

                logger.debug(
                    "Page extracted",
                    page_num=page_num,
                    path=str(page_path),
                    size_bytes=page_path.stat().st_size,
                )

            logger.info(
                "PDF split complete",
                page_count=page_count,
                output_dir=str(output_dir),
            )

            return page_count, page_paths

        except SplitterError:
            raise
        except Exception as e:
            logger.exception("PDF split failed", error=str(e))
            raise SplitterError(
                code="SPLIT_FAILED",
                message=f"Failed to split PDF: {str(e)}",
            )


# Global splitter instance
splitter = PdfSplitter()
