import json
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.config import get_settings
from app.jwt_validator import get_current_user
from app.utils.dynamo import client as db
from app.utils import s3 as s3_utils

_settings = get_settings()

router = APIRouter(tags=["Reporting"])


@router.post("/report", status_code=201)
async def receive_report(
    report: str = Form(..., description="Report JSON (see sample_report.json)"),
    animal_images: list[UploadFile] | None = File(default=None),
    human_images: list[UploadFile] | None = File(default=None),
    environment_images: list[UploadFile] | None = File(default=None),
    current_user: dict = Depends(get_current_user),
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
        try:
            data = json.loads(report)
        except json.JSONDecodeError as je:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON in report field: {je}",
            )

        report_id = str(uuid4())
        data["report_id"]         = report_id
        data["submitted_by"]      = current_user["sub"]
        data["submitted_by_email"] = current_user.get("email", "")
        data["lat"]  = Decimal(str(data["lat"]))
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

        db.put_item(_settings.DYNAMO_REPORTS_TABLE, data)
        return {"status": "success", "report_id": report_id}

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error receiving report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to receive report",
        )


@router.get("/reports")
async def list_reports(current_user: dict = Depends(get_current_user)):
    """Return all reports from DynamoDB."""
    try:
        items = db.scan(_settings.DYNAMO_REPORTS_TABLE)
        return {"status": "success", "reports": items}
    except Exception as e:
        print(f"Error listing reports: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list reports",
        )


@router.get("/reports/me")
async def list_my_reports(current_user: dict = Depends(get_current_user)):
    """Return all reports submitted by the authenticated user."""
    try:
        items = db.scan(
            _settings.DYNAMO_REPORTS_TABLE,
            filters={"submitted_by": current_user["sub"]},
        )
        return {"status": "success", "reports": items}
    except Exception as e:
        print(f"Error listing reports for current user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list reports",
        )


@router.get("/reports/user/{user_id}")
async def list_reports_by_user(
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return all reports submitted by a specific user (identified by their Cognito sub)."""
    try:
        items = db.scan(
            _settings.DYNAMO_REPORTS_TABLE,
            filters={"submitted_by": user_id},
        )
        return {"status": "success", "user_id": user_id, "reports": items}
    except Exception as e:
        print(f"Error listing reports for user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list reports",
        )
