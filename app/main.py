"""FastAPI application entry point."""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from app.api import router
from app.config import settings


def configure_logging() -> None:
    """Configure structured logging with structlog."""
    # Set up standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper()),
    )

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(
            ) if settings.log_level == "DEBUG" else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    logger = structlog.get_logger()

    # Startup
    logger.info(
        "Starting converter service",
        service=settings.service_name,
        concurrency=settings.concurrency,
        conversion_timeout=settings.conversion_timeout_seconds,
    )

    # Ensure temp directory exists
    temp_path = Path(settings.temp_dir)
    temp_path.mkdir(parents=True, exist_ok=True)
    logger.info("Temp directory ready", path=str(temp_path))

    yield

    # Shutdown
    logger.info("Shutting down converter service")


# Configure logging before creating app
configure_logging()

# Create FastAPI application
app = FastAPI(
    title="PPTX Converter Service",
    description="Converts PPTX files to PDF using LibreOffice",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware (permissive for internal service)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": settings.service_name}


# =============================================================================
# AWS Lambda Handler
# =============================================================================

# Wrap FastAPI app with Mangum for Lambda compatibility
_mangum_handler = Mangum(app, lifespan="auto")


def handler(event, context):
    """
    AWS Lambda entry point.

    Supports:
    - Regular API Gateway / ALB requests (routed to FastAPI)
    - Scheduled warming events (returns immediately to keep container warm)
    """
    logger = structlog.get_logger()

    # Check if this is a warming ping (CloudWatch scheduled event)
    if event.get("source") == "aws.events" or event.get("detail-type") == "Scheduled Event":
        logger.info("Received warming ping, keeping container warm")
        return {"statusCode": 200, "body": "warm"}

    # Check for custom warming event (alternative pattern)
    if event.get("warming") is True or event.get("source") == "warmup":
        logger.info("Received custom warming ping")
        return {"statusCode": 200, "body": "warm"}

    # Regular request - route to FastAPI via Mangum
    return _mangum_handler(event, context)
