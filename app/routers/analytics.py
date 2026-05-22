from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import get_settings
from app.jwt_validator import get_current_user
from app.utils.dynamo import client as db

_settings = get_settings()

router = APIRouter(tags=["Analytics"])


# ── Schemas ──────────────────────────────────────────────────────

class ReportTypeStats(BaseModel):
    """Statistics for a single report type."""
    type: str  # human | animal | environment
    count: int
    sick_cases: int
    death_cases: int
    percentage: float


class PastStatsResponse(BaseModel):
    """Historical report statistics."""
    total_reports: int
    reporting_period: str  # e.g. "last 30 days"
    by_type: list[ReportTypeStats]
    timestamp: datetime


class DailyTrendPoint(BaseModel):
    """Single data point for trend graph."""
    date: str  # ISO format: YYYY-MM-DD
    human: int
    animal: int
    environment: int
    total: int


class TimeSeriesTrendResponse(BaseModel):
    """Time series data for reports trend over past 7 days."""
    period: str  # e.g. "7 days"
    start_date: str
    end_date: str
    data: list[DailyTrendPoint]
    summary: dict[str, int]  # total counts for each type over the period


# ── Helpers ──────────────────────────────────────────────────────

def _parse_timestamp(timestamp_str: str) -> datetime | None:
    """Parse ISO format timestamp strings from DynamoDB."""
    if not timestamp_str:
        return None
    try:
        return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        try:
            return datetime.strptime(timestamp_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            return None


def _extract_report_type_data(report_item: dict) -> list[dict]:
    """
    Extract individual report entries from a report document.
    Each document has a 'report' array with items containing 'type', 'sick_flag', 'death_flag'.
    """
    entries = []
    for entry in report_item.get("report", []):
        if isinstance(entry, dict):
            entries.append({
                "type":       entry.get("type", "unknown"),
                "sick_flag":  entry.get("sick_flag", False),
                "death_flag": entry.get("death_flag", False),
            })
    return entries


def _aggregate_by_date(reports: list[dict], days_back: int = 7) -> dict[str, dict[str, int]]:
    """
    Aggregate report sub-entries by date and type.
    Returns {date_str: {type: count}} with every date in the window pre-populated.
    """
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days_back - 1)

    aggregation: dict[str, dict[str, int]] = {}
    current = start_date
    while current <= end_date:
        aggregation[current.isoformat()] = {"human": 0, "animal": 0, "environment": 0}
        current += timedelta(days=1)

    for report in reports:
        ts = _parse_timestamp(report.get("submitted_at", ""))
        if not ts:
            continue
        date_str = ts.date().isoformat()
        for entry in _extract_report_type_data(report):
            rtype = entry.get("type", "")
            if rtype in aggregation.get(date_str, {}):
                aggregation[date_str][rtype] += 1

    return aggregation


def _stats_by_type(reports: list[dict], days_back: int = 30) -> dict[str, Any]:
    """Aggregate counts, sick cases, and deaths per report type within a date window."""
    stats: dict[str, Any] = {
        "human":       {"count": 0, "sick": 0, "deaths": 0},
        "animal":      {"count": 0, "sick": 0, "deaths": 0},
        "environment": {"count": 0, "sick": 0, "deaths": 0},
    }
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    for report in reports:
        ts = _parse_timestamp(report.get("submitted_at", ""))
        if not ts or ts < cutoff:
            continue
        for entry in _extract_report_type_data(report):
            rtype = entry.get("type", "").lower()
            if rtype in stats:
                stats[rtype]["count"] += 1
                if entry.get("sick_flag"):
                    stats[rtype]["sick"] += 1
                if entry.get("death_flag"):
                    stats[rtype]["deaths"] += 1

    return stats


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/stats/past", response_model=PastStatsResponse)
async def get_past_stats(
    days: int = 30,
    current_user: dict = Depends(get_current_user),
):
    """
    Aggregated report statistics over the past N days (default 30, max 365).
    Returns counts, sick cases, and deaths broken down by report type.
    """
    if days < 1 or days > 365:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="days must be between 1 and 365",
        )
    try:
        all_reports = db.scan(_settings.DYNAMO_REPORTS_TABLE)
        stats = _stats_by_type(all_reports, days_back=days)
        total = sum(s["count"] for s in stats.values())

        by_type = [
            ReportTypeStats(
                type=rtype,
                count=stats[rtype]["count"],
                sick_cases=stats[rtype]["sick"],
                death_cases=stats[rtype]["deaths"],
                percentage=round(stats[rtype]["count"] / total * 100, 2) if total else 0.0,
            )
            for rtype in ("human", "animal", "environment")
        ]

        return PastStatsResponse(
            total_reports=total,
            reporting_period=f"last {days} days",
            by_type=by_type,
            timestamp=datetime.now(timezone.utc),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch past stats: {e}",
        )


@router.get("/trends/7days", response_model=TimeSeriesTrendResponse)
async def get_7day_trend(current_user: dict = Depends(get_current_user)):
    """
    Daily report counts per type for the last 7 days.
    Useful for visualising submission trends and patterns.
    """
    try:
        all_reports = db.scan(_settings.DYNAMO_REPORTS_TABLE)
        daily = _aggregate_by_date(all_reports, days_back=7)

        trend_data = []
        summary: dict[str, int] = {"human": 0, "animal": 0, "environment": 0}

        for date_str in sorted(daily):
            counts = daily[date_str]
            trend_data.append(DailyTrendPoint(
                date=date_str,
                human=counts["human"],
                animal=counts["animal"],
                environment=counts["environment"],
                total=sum(counts.values()),
            ))
            for rtype in summary:
                summary[rtype] += counts[rtype]

        today = datetime.now(timezone.utc).date()
        return TimeSeriesTrendResponse(
            period="7 days",
            start_date=(today - timedelta(days=6)).isoformat(),
            end_date=today.isoformat(),
            data=trend_data,
            summary=summary,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch trends: {e}",
        )


@router.get("/summary")
async def get_dashboard_summary(current_user: dict = Depends(get_current_user)):
    """
    Comprehensive dashboard summary: total reports, breakdown by type,
    today's activity, and aggregate sick/death counts.
    """
    try:
        all_reports = db.scan(_settings.DYNAMO_REPORTS_TABLE)

        today_cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_reports = [
            r for r in all_reports
            if (ts := _parse_timestamp(r.get("submitted_at", ""))) and ts >= today_cutoff
        ]

        all_time = _stats_by_type(all_reports, days_back=365 * 10)
        today    = _stats_by_type(today_reports, days_back=1)

        return {
            "total_reports_all_time": len(all_reports),
            "total_reports_today":    len(today_reports),
            "reports_by_type": {
                rtype: all_time[rtype]["count"]
                for rtype in ("human", "animal", "environment")
            },
            "today_reports_by_type": {
                rtype: today[rtype]["count"]
                for rtype in ("human", "animal", "environment")
            },
            "total_sick_cases": sum(s["sick"]   for s in all_time.values()),
            "total_deaths":     sum(s["deaths"] for s in all_time.values()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch dashboard summary: {e}",
        )
