# PPTX Converter Service

A containerized microservice that converts PowerPoint (PPTX) files to PDF using LibreOffice. Designed to run as an async job processor with S3 as the storage backend.

## Features

- **Async Job Processing**: Non-blocking API for submitting and tracking conversion jobs
- **Per-Page PDF Splitting**: Generates individual PDFs for each slide
- **S3 Integration**: Reads input from S3 and writes output to S3
- **Manifest-Based Completion**: Uses a manifest file as the atomic "commit marker" for job completion
- **Concurrency Control**: Configurable concurrent conversion limit per container
- **Container-Ready**: Runs as non-root with health checks

## Architecture

```
┌─────────────┐     POST /v1/jobs     ┌──────────────────┐
│  slides-api │ ───────────────────▶  │  pptx-converter  │
│             │ ◀─────────────────── │                  │
│             │    {status: queued}  │                  │
└─────────────┘                       └────────┬─────────┘
       │                                       │
       │  GET /v1/jobs/{id}                    │
       │  (poll until succeeded/failed)        │
       ▼                                       ▼
┌─────────────────────────────────────────────────────────┐
│                          S3                             │
│                                                         │
│  users/{userId}/jobs/{jobId}/input/deck.pptx           │
│  users/{userId}/jobs/{jobId}/output/pages/0001.pdf     │
│  users/{userId}/jobs/{jobId}/output/pages/0002.pdf     │
│  users/{userId}/jobs/{jobId}/output/manifest.json      │
└─────────────────────────────────────────────────────────┘
```

## API Endpoints

### Start Conversion Job

```http
POST /v1/jobs
Content-Type: application/json

{
  "tenantId": "t_abc",
  "jobId": "job_123",
  "input": {
    "bucket": "slides-prod",
    "key": "users/t_abc/jobs/job_123/input/deck.pptx"
  },
  "output": {
    "bucket": "slides-prod",
    "key": "users/t_abc/jobs/job_123/output/"
  }
}
```

**Response (immediate):**
```json
{
  "jobId": "job_123",
  "status": "queued"
}
```

### Get Job Status

```http
GET /v1/jobs/{jobId}?tenantId=t_abc
```

**Response:**
```json
{
  "jobId": "job_123",
  "userId": "t_abc",
  "status": "succeeded",
  "manifest": {
    "bucket": "slides-prod",
    "key": "users/t_abc/jobs/job_123/output/manifest.json"
  }
}
```

**Status Values:**
- `queued` - Job is waiting to start
- `running` - Conversion in progress
- `succeeded` - Conversion complete, manifest available
- `failed` - Conversion failed, failure manifest available

### Health Check

```http
GET /health
```

### Readiness Check

```http
GET /ready
```

## Manifest Schema

### Success Manifest

```json
{
  "jobId": "job_123",
  "userId": "t_abc",
  "status": "succeeded",
  "pageCount": 28,
  "pages": [
    { "page": 1, "key": "users/t_abc/jobs/job_123/output/pages/0001.pdf" },
    { "page": 2, "key": "users/t_abc/jobs/job_123/output/pages/0002.pdf" }
  ]
}
```

### Failure Manifest

```json
{
  "jobId": "job_123",
  "userId": "t_abc",
  "status": "failed",
  "error": {
    "code": "CONVERSION_FAILED",
    "message": "stderr excerpt..."
  }
}
```

## Local Development

### Prerequisites

- Docker and Docker Compose

### Quick Start

1. **Start the services:**
   ```bash
   docker compose up --build
   ```

   This starts:
   - Converter service on `http://localhost:8080`
   - MinIO (S3-compatible) on `http://localhost:9000`
   - MinIO Console on `http://localhost:9001`

2. **Upload a test PPTX to MinIO:**
   ```bash
   # Using MinIO client (mc)
   mc alias set local http://localhost:9000 minioadmin minioadmin
   mc cp test.pptx local/slides-dev/users/test/jobs/job1/input/deck.pptx
   ```

3. **Start a conversion job:**
   ```bash
   curl -X POST http://localhost:8080/v1/jobs \
     -H "Content-Type: application/json" \
     -d '{
       "tenantId": "test",
       "jobId": "job1",
       "input": {
         "bucket": "slides-dev",
         "key": "users/test/jobs/job1/input/deck.pptx"
       },
       "output": {
         "bucket": "slides-dev",
         "key": "users/test/jobs/job1/output/"
       }
     }'
   ```

4. **Poll for completion:**
   ```bash
   curl "http://localhost:8080/v1/jobs/job1?tenantId=test"
   ```

5. **Access output files in MinIO Console:**
   - URL: http://localhost:9001
   - Username: `minioadmin`
   - Password: `minioadmin`

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `CONCURRENCY` | `1` | Max concurrent conversions per container |
| `CONVERSION_TIMEOUT_SECONDS` | `180` | LibreOffice conversion timeout |
| `MAX_INPUT_SIZE_MB` | `100` | Maximum input PPTX file size |
| `TEMP_DIR` | `/tmp/converter` | Temp directory for processing |
| `AWS_REGION` | `us-east-1` | AWS region |
| `AWS_ACCESS_KEY_ID` | - | AWS access key (optional with IAM role) |
| `AWS_SECRET_ACCESS_KEY` | - | AWS secret key (optional with IAM role) |
| `S3_ENDPOINT_URL` | - | Custom S3 endpoint (for MinIO/LocalStack) |

## Deployment

### Docker Image

```bash
docker build -t pptx-converter .
```

### Kubernetes

Example deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pptx-converter
spec:
  replicas: 3  # Scale horizontally for throughput
  selector:
    matchLabels:
      app: pptx-converter
  template:
    metadata:
      labels:
        app: pptx-converter
    spec:
      serviceAccountName: pptx-converter  # With S3 IAM role
      containers:
        - name: converter
          image: pptx-converter:latest
          ports:
            - containerPort: 8080
          env:
            - name: CONCURRENCY
              value: "1"
            - name: LOG_LEVEL
              value: "INFO"
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
            limits:
              cpu: "2"
              memory: "4Gi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
```

## Scaling Strategy

- **Concurrency per container**: Keep at `1` for LibreOffice stability
- **Scale throughput**: Run multiple container replicas
- **Resource sizing**: ~2 CPU cores and 4GB RAM per container recommended

## Error Handling

The service handles errors gracefully:

1. **Conversion timeout**: If LibreOffice takes too long, the process is killed and a failure manifest is written
2. **Invalid input**: Large files or corrupt PPTX files result in failure manifests
3. **S3 errors**: Transient S3 failures are retried; persistent failures result in failure manifests

## Security

- Runs as non-root user in container
- No inbound internet access required
- S3 access via IAM role (no static credentials in production)
- Tenant ID validation on job status queries

## License

Private - All rights reserved
