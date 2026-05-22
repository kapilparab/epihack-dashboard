"""
Survey API for detailed field data ingestion.
Accepts structured survey data for Human, Livestock, Wildlife, and Environment reports.
"""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.jwt_validator import get_current_user
from app.utils.dynamo import client as db
from app.utils import s3 as s3_utils

_settings = get_settings()
router = APIRouter(prefix="/survey", tags=["Survey"])


# ────────────────────────────────────────────────────────────────
# ── Pydantic Models for Survey Data
# ────────────────────────────────────────────────────────────────


class HumanReportModel(BaseModel):
    """Detailed human health report."""

    sick_flag: bool = Field(..., description="Is the person sick?")
    symptoms: list[str] = Field(
        ..., description="List of reported symptoms"
    )
    num_affected: int = Field(
        ..., ge=1, description="Number of people affected in household"
    )
    goes_to_school_flag: bool = Field(default=False, description="Does person go to school?")
    absent_school_flag: bool = Field(default=False, description="Is person absent from school?")
    works_flag: bool = Field(default=False, description="Does person work?")
    absent_work_flag: bool = Field(default=False, description="Is person absent from work?")
    visited_doctor_flag: bool = Field(default=False, description="Visited a doctor?")
    received_diagnosis_flag: bool = Field(default=False, description="Received diagnosis?")
    diagnosis: str = Field(default="", description="Medical diagnosis if available")
    other_person_flag: bool = Field(
        default=False, description="Reporting for someone else?"
    )
    recent_mass_gathering_date: str | None = Field(
        default=None, description="ISO 8601 date of recent mass gathering"
    )
    recent_mass_gathering_location: str = Field(
        default="", description="Location of mass gathering (flexible format)"
    )
    insect_bite_flag: bool = Field(default=False, description="Had insect bite?")
    insect_bite_species: str = Field(default="", description="Insect species if known")
    animal_bite_flag: bool = Field(default=False, description="Had animal bite?")
    animal_bite_species: str = Field(default="", description="Animal species if known")
    recent_travel_date: str | None = Field(
        default=None, description="ISO 8601 date of recent travel"
    )
    recent_travel_location: str = Field(
        default="", description="Recent travel location (flexible format)"
    )
    live_animal_contact_flag: bool = Field(default=False, description="Contact with live animal?")
    live_animal_contact_date: str | None = Field(
        default=None, description="ISO 8601 date of animal contact"
    )
    dead_or_sick_animal_flag: bool = Field(
        default=False, description="Contact with dead/sick animal?"
    )
    dead_or_sick_animal_date: str | None = Field(
        default=None, description="ISO 8601 date of dead/sick animal contact"
    )
    sick_person_flag: bool = Field(default=False, description="Contact with sick person?")
    sick_person_date: str | None = Field(
        default=None, description="ISO 8601 date of sick person contact"
    )


class LivestockReportModel(BaseModel):
    """Livestock health incident report."""

    incident_date: str = Field(..., description="ISO 8601 date of incident")
    incident_location: str = Field(
        ..., description="Location of incident (flexible format - coordinates, address, description)"
    )
    num_animals_sick: int = Field(ge=0, description="Number of sick animals")
    num_animals_dead: int = Field(ge=0, description="Number of dead animals")
    species: str = Field(..., description="Animal species affected")


class WildlifeReportModel(BaseModel):
    """Wildlife health incident report."""

    incident_date: str = Field(..., description="ISO 8601 date of incident")
    incident_location: str = Field(
        ..., description="Location of incident (flexible format - coordinates, address, description)"
    )
    num_animals_dead: int = Field(ge=0, description="Number of dead animals")
    species: str = Field(..., description="Wildlife species affected")


class EnvironmentReportModel(BaseModel):
    """Environmental hazard report."""

    incident_date: str = Field(..., description="ISO 8601 date of incident")
    flooding_flag: bool = Field(default=False, description="Flooding observed?")
    water_contamination_flag: bool = Field(default=False, description="Water contamination?")
    unusual_vector: str = Field(default="", description="Unusual vector species observed")
    num_vectors: int = Field(default=0, ge=0, description="Number of vectors observed")
    vector_location: str = Field(default="", description="Location of vectors (flexible format)")


class SurveySubmissionResponse(BaseModel):
    """Response for successful survey submission."""

    status: str
    survey_id: str
    report_type: str
    submitted_at: str


# ────────────────────────────────────────────────────────────────
# ── Helper Functions
# ────────────────────────────────────────────────────────────────


async def _save_survey(
    report_type: str, data: dict, current_user: dict, image: UploadFile | None = None
) -> str:
    """
    Save survey data to DynamoDB with optional image upload to S3.

    Args:
        report_type: Type of report (human, livestock, wildlife, environment)
        data: Survey data as dictionary
        current_user: Authenticated user info
        image: Optional image file to upload

    Returns:
        survey_id: Unique identifier for the saved survey

    Raises:
        HTTPException: On database or S3 errors
    """
    try:
        survey_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Build survey document
        survey_doc = {
            "survey_id": survey_id,
            "report_type": report_type,
            "submitted_by": current_user["sub"],
            "submitted_by_email": current_user.get("email", ""),
            "submitted_at": now,
            **data.model_dump(),
        }

        # Handle image upload if provided
        if image:
            try:
                image_url = await s3_utils.upload_report_image(
                    survey_id, report_type, image
                )
                survey_doc["image_url"] = image_url
            except Exception as e:
                print(f"Warning: Image upload failed: {e}")
                # Continue without image rather than failing the entire request

        # Save to DynamoDB
        db.put_item(_settings.DYNAMO_SURVEYS_TABLE, survey_doc)
        return survey_id

    except Exception as e:
        print(f"Error saving survey: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save survey: {str(e)}",
        )


# ────────────────────────────────────────────────────────────────
# ── Survey Submission Endpoints
# ────────────────────────────────────────────────────────────────


@router.post("/human", response_model=SurveySubmissionResponse, status_code=201)
async def submit_human_report(
    sick_flag: bool = ...,
    symptoms: list[str] = ...,
    num_affected: int = ...,
    goes_to_school_flag: bool = False,
    absent_school_flag: bool = False,
    works_flag: bool = False,
    absent_work_flag: bool = False,
    visited_doctor_flag: bool = False,
    received_diagnosis_flag: bool = False,
    diagnosis: str = "",
    other_person_flag: bool = False,
    recent_mass_gathering_date: str | None = None,
    recent_mass_gathering_location: str = "",
    insect_bite_flag: bool = False,
    insect_bite_species: str = "",
    animal_bite_flag: bool = False,
    animal_bite_species: str = "",
    recent_travel_date: str | None = None,
    recent_travel_location: str = "",
    live_animal_contact_flag: bool = False,
    live_animal_contact_date: str | None = None,
    dead_or_sick_animal_flag: bool = False,
    dead_or_sick_animal_date: str | None = None,
    sick_person_flag: bool = False,
    sick_person_date: str | None = None,
    image: UploadFile | None = None,
    current_user: dict = Depends(get_current_user),
):
    """
    Submit a detailed human health report.

    All required fields must be provided. Optional fields can be omitted or null.
    Image file is optional and will be uploaded to S3 if provided.
    """
    try:
        human_report = HumanReportModel(
            sick_flag=sick_flag,
            symptoms=symptoms,
            num_affected=num_affected,
            goes_to_school_flag=goes_to_school_flag,
            absent_school_flag=absent_school_flag,
            works_flag=works_flag,
            absent_work_flag=absent_work_flag,
            visited_doctor_flag=visited_doctor_flag,
            received_diagnosis_flag=received_diagnosis_flag,
            diagnosis=diagnosis,
            other_person_flag=other_person_flag,
            recent_mass_gathering_date=recent_mass_gathering_date,
            recent_mass_gathering_location=recent_mass_gathering_location,
            insect_bite_flag=insect_bite_flag,
            insect_bite_species=insect_bite_species,
            animal_bite_flag=animal_bite_flag,
            animal_bite_species=animal_bite_species,
            recent_travel_date=recent_travel_date,
            recent_travel_location=recent_travel_location,
            live_animal_contact_flag=live_animal_contact_flag,
            live_animal_contact_date=live_animal_contact_date,
            dead_or_sick_animal_flag=dead_or_sick_animal_flag,
            dead_or_sick_animal_date=dead_or_sick_animal_date,
            sick_person_flag=sick_person_flag,
            sick_person_date=sick_person_date,
        )

        survey_id = await _save_survey(
            "human", human_report, current_user, image
        )

        return SurveySubmissionResponse(
            status="success",
            survey_id=survey_id,
            report_type="human",
            submitted_at=datetime.now(timezone.utc).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error submitting human report: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid human report data: {str(e)}",
        )


@router.post("/livestock", response_model=SurveySubmissionResponse, status_code=201)
async def submit_livestock_report(
    incident_date: str = ...,
    incident_location: str = ...,
    num_animals_sick: int = 0,
    num_animals_dead: int = 0,
    species: str = ...,
    image: UploadFile | None = None,
    current_user: dict = Depends(get_current_user),
):
    """
    Submit a livestock health incident report.

    All required fields must be provided. Image file is optional.
    """
    try:
        livestock_report = LivestockReportModel(
            incident_date=incident_date,
            incident_location=incident_location,
            num_animals_sick=num_animals_sick,
            num_animals_dead=num_animals_dead,
            species=species,
        )

        survey_id = await _save_survey(
            "livestock", livestock_report, current_user, image
        )

        return SurveySubmissionResponse(
            status="success",
            survey_id=survey_id,
            report_type="livestock",
            submitted_at=datetime.now(timezone.utc).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error submitting livestock report: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid livestock report data: {str(e)}",
        )


@router.post("/wildlife", response_model=SurveySubmissionResponse, status_code=201)
async def submit_wildlife_report(
    incident_date: str = ...,
    incident_location: str = ...,
    num_animals_dead: int = 0,
    species: str = ...,
    image: UploadFile | None = None,
    current_user: dict = Depends(get_current_user),
):
    """
    Submit a wildlife health incident report.

    All required fields must be provided. Image file is optional.
    """
    try:
        wildlife_report = WildlifeReportModel(
            incident_date=incident_date,
            incident_location=incident_location,
            num_animals_dead=num_animals_dead,
            species=species,
        )

        survey_id = await _save_survey(
            "wildlife", wildlife_report, current_user, image
        )

        return SurveySubmissionResponse(
            status="success",
            survey_id=survey_id,
            report_type="wildlife",
            submitted_at=datetime.now(timezone.utc).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error submitting wildlife report: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid wildlife report data: {str(e)}",
        )


@router.post("/environment", response_model=SurveySubmissionResponse, status_code=201)
async def submit_environment_report(
    incident_date: str = ...,
    flooding_flag: bool = False,
    water_contamination_flag: bool = False,
    unusual_vector: str = "",
    num_vectors: int = 0,
    vector_location: str = "",
    image: UploadFile | None = None,
    current_user: dict = Depends(get_current_user),
):
    """
    Submit an environmental hazard report.

    incident_date is required. Image file is optional.
    """
    try:
        environment_report = EnvironmentReportModel(
            incident_date=incident_date,
            flooding_flag=flooding_flag,
            water_contamination_flag=water_contamination_flag,
            unusual_vector=unusual_vector,
            num_vectors=num_vectors,
            vector_location=vector_location,
        )

        survey_id = await _save_survey(
            "environment", environment_report, current_user, image
        )

        return SurveySubmissionResponse(
            status="success",
            survey_id=survey_id,
            report_type="environment",
            submitted_at=datetime.now(timezone.utc).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error submitting environment report: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid environment report data: {str(e)}",
        )


@router.get("/")
async def list_all_surveys(current_user: dict = Depends(get_current_user)):
    """Retrieve all surveys from DynamoDB."""
    try:
        items = db.scan(_settings.DYNAMO_SURVEYS_TABLE)
        return {"status": "success", "surveys": items}
    except Exception as e:
        print(f"Error listing surveys: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list surveys",
        )


@router.get("/me")
async def list_my_surveys(current_user: dict = Depends(get_current_user)):
    """Retrieve all surveys submitted by the authenticated user."""
    try:
        items = db.scan(
            _settings.DYNAMO_SURVEYS_TABLE,
            filters={"submitted_by": current_user["sub"]},
        )
        return {"status": "success", "surveys": items}
    except Exception as e:
        print(f"Error listing user surveys: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list user surveys",
        )


@router.get("/{report_type}")
async def list_surveys_by_type(
    report_type: str, current_user: dict = Depends(get_current_user)
):
    """
    Retrieve surveys filtered by report type.

    Valid report types: human, livestock, wildlife, environment
    """
    valid_types = ["human", "livestock", "wildlife", "environment"]
    if report_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid report type. Must be one of: {', '.join(valid_types)}",
        )

    try:
        items = db.scan(
            _settings.DYNAMO_SURVEYS_TABLE,
            filters={"report_type": report_type},
        )
        return {"status": "success", "surveys": items}
    except Exception as e:
        print(f"Error listing surveys by type: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list surveys by type",
        )
