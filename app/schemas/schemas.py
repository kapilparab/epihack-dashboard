from datetime import datetime
from typing import Any
from pydantic import BaseModel, EmailStr, Field
from app.models.enums import (
    UserRole, SurveyCategory, SurveyStatus,
    AlertSeverity, AlertStatus, QuestionType,
)


# ── Shared ───────────────────────────────────────────────────────

class GeoPoint(BaseModel):
    type: str = "Point"
    coordinates: list[float]  # [longitude, latitude]


# ── User ─────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: UserRole = UserRole.CITIZEN
    location: GeoPoint | None = None


class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: UserRole
    created_at: datetime

    class Config:
        populate_by_name = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── Survey ────────────────────────────────────────────────────────

class QuestionOption(BaseModel):
    value: str
    label: str


class SurveyQuestion(BaseModel):
    id: str
    text: str
    type: QuestionType
    required: bool = True
    options: list[QuestionOption] | None = None
    min_value: float | None = None
    max_value: float | None = None


class SurveyCreate(BaseModel):
    title: str = Field(..., min_length=5, max_length=200)
    description: str
    category: SurveyCategory
    questions: list[SurveyQuestion] = Field(..., min_length=1)
    tags: list[str] = []
    target_region: str | None = None


class SurveyOut(SurveyCreate):
    id: str
    status: SurveyStatus
    response_count: int = 0
    created_by: str
    created_at: datetime
    updated_at: datetime


# ── Survey Response ───────────────────────────────────────────────

class ResponseAnswer(BaseModel):
    question_id: str
    value: Any   # str | list[str] | float | bool


class SurveyResponseCreate(BaseModel):
    survey_id: str
    answers: list[ResponseAnswer]
    location: GeoPoint | None = None
    notes: str | None = None


class SurveyResponseOut(SurveyResponseCreate):
    id: str
    user_id: str
    submitted_at: datetime


# ── Alert ─────────────────────────────────────────────────────────

class AlertCreate(BaseModel):
    title: str
    description: str
    category: SurveyCategory
    severity: AlertSeverity
    location: GeoPoint | None = None
    affected_survey_ids: list[str] = []
    anomaly_score: float | None = None


class AlertOut(AlertCreate):
    id: str
    status: AlertStatus
    created_at: datetime
    updated_at: datetime
    resolved_by: str | None = None


# ── Dashboard Stats ───────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_surveys: int
    active_surveys: int
    total_responses_today: int
    total_responses_all_time: int
    open_alerts: int
    critical_alerts: int
    responses_by_category: dict[str, int]
    recent_alerts: list[AlertOut]
