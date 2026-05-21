import json
from uuid import uuid4
from decimal import Decimal
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from app.config import get_settings
from app.utils.dynamo import client as db
from app.utils import s3 as s3_utils

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


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "env": settings.ENVIRONMENT}


@app.post("/report", tags=["Reporting"])
async def receive_report(
    report: str = Form(..., description="Report JSON (see sample_report.json)"),
    animal_images: list[UploadFile] | None = File(default=None),
    human_images: list[UploadFile] | None = File(default=None),
    environment_images: list[UploadFile] | None = File(default=None),
):
    """
    Accept a crowd-sourced field report with optional images.

    Send as multipart/form-data:
    - `report`: the full report JSON serialised as a string
    - `animal_images`: zero or more image files for the animal sub-report
    - `human_images`:  zero or more image files for the human sub-report
    - `environment_images`: zero or more image files for the environment sub-report

    Uploaded images are stored in S3 and their URLs are written into the
    matching sub-report's `images` list before the document is saved to DynamoDB.
    """
    try:
        data = json.loads(report)
        report_id = str(uuid4())
        data["report_id"] = report_id
        data["lat"] = Decimal(str(data["lat"]))
        data["long"] = Decimal(str(data["long"]))

        image_map: dict[str, list[UploadFile]] = {
            "animal":      animal_images      or [],
            "human":       human_images       or [],
            "environment": environment_images or [],
        }

        for sub in data.get("report", []):
            files = image_map.get(sub.get("type"), [])
            if files:
                sub["images"] = [
                    await s3_utils.upload_report_image(report_id, sub["type"], f)
                    for f in files
                ]

        db.put_item(settings.DYNAMO_REPORTS_TABLE, data)
        return {"status": "success", "report_id": report_id}

    except Exception as e:
        print(f"Error receiving report: {e}")
        return {"status": "error", "message": "Failed to receive report"}


@app.get("/reports", tags=["Reporting"])
async def list_reports():
    """Return all reports from DynamoDB."""
    try:
        items = db.scan(settings.DYNAMO_REPORTS_TABLE)
        return {"status": "success", "reports": items}
    except Exception as e:
        print(f"Error listing reports: {e}")
        return {"status": "error", "message": "Failed to list reports"}


# Lambda entrypoint — used by the container CMD
handler = Mangum(app, lifespan="off")
