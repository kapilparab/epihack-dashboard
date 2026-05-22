from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, HTTPException, status, Depends, Query
from app.config import get_settings
from app.schemas.schemas import AlertCreate, AlertOut
from app.models.enums import AlertStatus, AlertSeverity, SurveyCategory, UserRole
from app.utils.auth import get_current_user, require_role
from app.utils.dynamo import client as db

settings = get_settings()
router = APIRouter(prefix="/alerts", tags=["Alerts"])
TABLE = settings.DYNAMO_ALERTS_TABLE


def _to_out(doc: dict) -> AlertOut:
    return AlertOut(**{**doc, "id": doc["alert_id"]})


# ── Community (citizen) endpoints ────────────────────────────────

@router.get("/", response_model=list[AlertOut])
async def list_alerts(
    alert_status: AlertStatus | None = Query(default=None),
    severity: AlertSeverity | None = Query(default=None),
    category: SurveyCategory | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Returns all alerts visible to the community.
    Filterable by status, severity, and category.
    No authentication required — citizens can view without logging in.
    """
    docs = db.scan(TABLE)

    if alert_status:
        docs = [d for d in docs if d.get("status") == alert_status]
    if severity:
        docs = [d for d in docs if d.get("severity") == severity]
    if category:
        docs = [d for d in docs if d.get("category") == category]

    docs.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    return [_to_out(d) for d in docs[skip : skip + limit]]


@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert(alert_id: str):
    """Return a single alert by ID. No authentication required."""
    doc = db.get_item(TABLE, {"alert_id": alert_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Alert not found")
    return _to_out(doc)


# ── Admin endpoints ───────────────────────────────────────────────

@router.post("/", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
async def create_alert(
    payload: AlertCreate,
    current_user: dict = Depends(require_role(UserRole.ADMIN)),
):
    """
    Broadcast a new alert to the community.
    Requires admin role.
    """
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        **payload.model_dump(),
        "alert_id": str(uuid4()),
        "status": AlertStatus.OPEN,
        "created_by": current_user.get("sub"),
        "created_at": now,
        "updated_at": now,
        "resolved_by": None,
    }
    db.put_item(TABLE, doc)
    return _to_out(doc)


@router.patch("/{alert_id}/status", response_model=AlertOut)
async def update_alert_status(
    alert_id: str,
    new_status: AlertStatus,
    current_user: dict = Depends(require_role(UserRole.ADMIN)),
):
    """
    Update the status of an alert (e.g. resolve it).
    Requires admin role.
    """
    doc = db.get_item(TABLE, {"alert_id": alert_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Alert not found")

    updates: dict = {
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if new_status == AlertStatus.RESOLVED:
        updates["resolved_by"] = current_user.get("sub")

    db.update_item(TABLE, {"alert_id": alert_id}, updates)
    return _to_out({**doc, **updates})


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: str,
    current_user: dict = Depends(require_role(UserRole.ADMIN)),
):
    """
    Delete an alert permanently.
    Requires admin role.
    """
    if not db.get_item(TABLE, {"alert_id": alert_id}):
        raise HTTPException(status_code=404, detail="Alert not found")
    db.delete_item(TABLE, {"alert_id": alert_id})
