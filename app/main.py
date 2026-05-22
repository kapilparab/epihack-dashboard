from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from app.config import get_settings
from app.routers import analytics, reports, survey, alerts

settings = get_settings()

app = FastAPI(
    title="EpiHack Dashboard API",
    description="Field report ingestion service for the Epidemic Radar platform.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reports.router)
app.include_router(analytics.router)
app.include_router(survey.router)
app.include_router(alerts.router)


@app.on_event("startup")
async def validate_config():
    """Fail fast if essential AWS settings are missing."""
    required = {
        "DYNAMO_ACCESS_KEY_ID":     settings.DYNAMO_ACCESS_KEY_ID,
        "DYNAMO_SECRET_ACCESS_KEY": settings.DYNAMO_SECRET_ACCESS_KEY,
        "DYNAMO_REPORTS_TABLE":     settings.DYNAMO_REPORTS_TABLE,
        "DYNAMO_SURVEYS_TABLE":     settings.DYNAMO_SURVEYS_TABLE,
        "S3_IMAGES_BUCKET":         settings.S3_IMAGES_BUCKET,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(f"Missing required configuration: {', '.join(missing)}")


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "env": settings.ENVIRONMENT}


# Lambda entrypoint
handler = Mangum(app, lifespan="off")
