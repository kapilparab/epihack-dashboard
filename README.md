# EpiHack Dashboard API

FastAPI service for ingesting and querying crowd-sourced field reports for the Epidemic Radar platform. Stores reports in AWS DynamoDB and images in S3. Authentication is handled via AWS Cognito JWT tokens. Deployed as a container on AWS Lambda.

## Endpoints

All endpoints except `/health` require a valid Cognito `id_token` in the `Authorization: Bearer <token>` header.

### Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Liveness check |

### Reporting

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/report` | Yes | Submit a field report with optional images |
| `GET` | `/reports` | Yes | List all reports |
| `GET` | `/reports/me` | Yes | List reports submitted by the authenticated user |
| `GET` | `/reports/user/{user_id}` | Yes | List reports submitted by a specific user (Cognito `sub`) |

### Analytics

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/stats/past` | Yes | Aggregated stats by report type over the past N days |
| `GET` | `/trends/7days` | Yes | Daily report counts per type for the last 7 days |
| `GET` | `/summary` | Yes | Dashboard summary: totals, today's activity, sick/death counts |

---

## Endpoint Details

### `POST /report`

Accepts `multipart/form-data`. The authenticated user's Cognito `sub` and email are automatically stamped onto the document.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `report` | string | Yes | Full report JSON serialised as a string |
| `animal_images` | file(s) | No | Images for the animal sub-report |
| `human_images` | file(s) | No | Images for the human sub-report |
| `environment_images` | file(s) | No | Images for the environment sub-report |

Images are uploaded to S3 at `report_images/{report_id}/{subtype}/{filename}` and their public URLs are saved in the document.

**Stored document fields:**

| Field | Source | Description |
|-------|--------|-------------|
| `report_id` | Generated | UUID for the report |
| `submitted_by` | JWT `sub` claim | Cognito user identifier (used for user filtering) |
| `submitted_by_email` | JWT `email` claim | User's email address |
| `lat` / `long` | Request body | Location coordinates (stored as Decimal) |
| `report` | Request body | Array of sub-reports (`type`, `sick_flag`, `death_flag`, `images`) |

**Response:**
```json
{ "status": "success", "report_id": "<uuid>" }
```

---

### `GET /reports/user/{user_id}`

`user_id` is the Cognito `sub` (UUID), not the email address. Use `GET /reports/me` to fetch your own reports without knowing your `sub`.

---

### `GET /stats/past`

| Query param | Type | Default | Description |
|-------------|------|---------|-------------|
| `days` | int | `30` | Look-back window (1–365) |

**Response:**
```json
{
  "total_reports": 42,
  "reporting_period": "last 30 days",
  "by_type": [
    { "type": "human", "count": 20, "sick_cases": 5, "death_cases": 1, "percentage": 47.62 },
    { "type": "animal", "count": 15, "sick_cases": 3, "death_cases": 0, "percentage": 35.71 },
    { "type": "environment", "count": 7, "sick_cases": 0, "death_cases": 0, "percentage": 16.67 }
  ],
  "timestamp": "2026-05-21T12:00:00Z"
}
```

---

### `GET /trends/7days`

**Response:**
```json
{
  "period": "7 days",
  "start_date": "2026-05-15",
  "end_date": "2026-05-21",
  "data": [
    { "date": "2026-05-15", "human": 3, "animal": 1, "environment": 0, "total": 4 }
  ],
  "summary": { "human": 18, "animal": 9, "environment": 2 }
}
```

---

### `GET /summary`

**Response:**
```json
{
  "total_reports_all_time": 120,
  "total_reports_today": 5,
  "reports_by_type": { "human": 60, "animal": 40, "environment": 20 },
  "today_reports_by_type": { "human": 3, "animal": 2, "environment": 0 },
  "total_sick_cases": 22,
  "total_deaths": 3,
  "timestamp": "2026-05-21T12:00:00Z"
}
```

---

## Project Structure

```
epihack-dashboard/
├── app/
│   ├── __init__.py
│   ├── main.py              # App setup, middleware, router includes, health, Lambda handler
│   ├── config.py            # Settings via pydantic-settings (.env / env vars)
│   ├── jwt_validator.py     # Cognito JWT verification (RS256 via JWKS)
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── reports.py       # POST /report  GET /reports  GET /reports/me  GET /reports/user/{id}
│   │   └── analytics.py     # GET /stats/past  GET /trends/7days  GET /summary
│   └── utils/
│       ├── __init__.py
│       ├── dynamo.py        # DynamoDB client wrapper (boto3)
│       └── s3.py            # S3 image upload helper
├── Dockerfile
├── .dockerignore
├── .env.example
├── requirements.txt
└── README.md
```

---

## Authentication

All data endpoints require a Cognito `id_token` issued by the configured user pool:

```
Authorization: Bearer <id_token>
```

The JWT validator (`jwt_validator.py`):
1. Fetches the user pool's public JWKS keys lazily on first request; refreshes automatically on key rotation.
2. Verifies the RS256 signature.
3. Checks the `aud` claim matches a registered `COGNITO_CLIENT_IDS` entry — tokens from unknown app clients are rejected with `401`.

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `development` | Runtime environment label |
| `DYNAMO_ACCESS_KEY_ID` | | AWS access key |
| `DYNAMO_SECRET_ACCESS_KEY` | | AWS secret key |
| `DYNAMO_REGION` | `us-east-2` | AWS region for DynamoDB and S3 |
| `DYNAMO_REPORTS_TABLE` | `epihack_reports` | DynamoDB table name |
| `S3_IMAGES_BUCKET` | `epihack` | S3 bucket for report images |
| `COGNITO_REGION` | `us-east-2` | Cognito user pool region |
| `COGNITO_USER_POOL_ID` | | User pool ID (e.g. `us-east-2_xxxxxxxx`) |
| `COGNITO_CLIENT_IDS` | | Comma-separated allowed app client IDs |
| `COGNITO_CLIENT_SECRETS` | | Comma-separated secrets in the same order as IDs; blank if no secret |
| `COGNITO_AUTHORITY` | *(derived)* | Override the JWKS issuer URL; auto-built from region + pool ID if blank |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins |

> In Lambda, set these directly as function environment variables. The `.env` file is skipped automatically when `LAMBDA_TASK_ROOT` is present.

---

## Local Development

```bash
# Install dependencies (conda env assumed to already exist)
pip install -r requirements.txt

# Run with uvicorn
uvicorn app.main:app --reload
```

API docs available at `http://localhost:8000/docs`.

---

## Docker & AWS Lambda Deployment

The container uses the official AWS Lambda Python 3.12 base image. [Mangum](https://mangum.fastapiexpert.com/) adapts the FastAPI ASGI app to the Lambda event format.

### ECR Repository

```
206896361792.dkr.ecr.us-east-2.amazonaws.com/epihack-dashboard
```

### Build & Push

> **Note:** Use `--provenance=false` to produce a Docker V2 manifest. Lambda does not support the OCI image index format that newer BuildKit versions generate by default. Use `--platform linux/amd64` to avoid architecture mismatches when building on Apple Silicon.

```bash
# Authenticate
aws ecr get-login-password --region us-east-2 | \
  docker login --username AWS --password-stdin \
  206896361792.dkr.ecr.us-east-2.amazonaws.com

# Build
docker build --platform linux/amd64 --provenance=false -t epihack-dashboard .

# Tag
docker tag epihack-dashboard:latest \
  206896361792.dkr.ecr.us-east-2.amazonaws.com/epihack-dashboard:latest

# Push
docker push \
  206896361792.dkr.ecr.us-east-2.amazonaws.com/epihack-dashboard:latest
```

### Create Lambda Function

```bash
aws lambda create-function \
  --function-name epihack-dashboard \
  --package-type Image \
  --code ImageUri=206896361792.dkr.ecr.us-east-2.amazonaws.com/epihack-dashboard:latest \
  --role arn:aws:iam::206896361792:role/<your-lambda-execution-role> \
  --region us-east-2
```

### Update an Existing Function

```bash
aws lambda update-function-code \
  --function-name epihack-dashboard \
  --image-uri 206896361792.dkr.ecr.us-east-2.amazonaws.com/epihack-dashboard:latest \
  --region us-east-2
```

### Lambda Environment Variables

Set these in the Lambda function configuration (in addition to any already configured):

```
COGNITO_USER_POOL_ID=us-east-2_xxxxxxxxx
COGNITO_CLIENT_IDS=your-client-id
COGNITO_CLIENT_SECRETS=          # only if your app client has a secret
DYNAMO_ACCESS_KEY_ID=...
DYNAMO_SECRET_ACCESS_KEY=...
DYNAMO_REPORTS_TABLE=epihack_reports
S3_IMAGES_BUCKET=epihack
CORS_ORIGINS=https://your-frontend.com
```

### Required IAM Permissions

The Lambda execution role needs:

```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:PutItem",
    "dynamodb:GetItem",
    "dynamodb:Scan"
  ],
  "Resource": "arn:aws:dynamodb:us-east-2:206896361792:table/epihack_reports"
},
{
  "Effect": "Allow",
  "Action": [
    "s3:PutObject"
  ],
  "Resource": "arn:aws:s3:::epihack/*"
}
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `fastapi` | Web framework |
| `mangum` | ASGI → Lambda adapter |
| `boto3` | AWS SDK (DynamoDB + S3) |
| `httpx` | HTTP client for JWKS key fetch |
| `python-jose[cryptography]` | RS256 JWT decoding and verification |
| `pydantic` | Request/response schema validation |
| `pydantic-settings` | Settings management from env vars |
| `python-multipart` | Multipart form / file upload parsing |
| `python-dotenv` | `.env` file loading for local development |
| `starlette` | ASGI toolkit (bundled with FastAPI) |
| `uvicorn` | Local development server |
