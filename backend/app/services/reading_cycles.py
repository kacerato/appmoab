"""Regras centrais da fila mensal de leituras."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hydrometer import Hydrometer
from app.models.reading import Reading
from app.models.reading_cycle import ReadingCycle

ACTIONABLE_CYCLE_STATUSES = ("open", "pending_review", "recapture_required")


def reference_month(value: date) -> str:
    return f"{value.year}-{value.month:02d}"


def reference_due_date(reference: str, due_day: int) -> date:
    year, month = (int(part) for part in reference.split("-", 1))
    return date(year, month, due_day)


def next_reference_month(reference: str) -> str:
    year, month = (int(part) for part in reference.split("-", 1))
    if month == 12:
        return f"{year + 1}-01"
    return f"{year}-{month + 1:02d}"


def cycle_timing(cycle: ReadingCycle, today: date, days_before: int, grace_days: int) -> tuple[str, int]:
    days = (cycle.due_date - today).days
    if cycle.cycle_type == "installation":
        return ("installation", days)
    if cycle.status == "pending_review":
        return ("pending_review", days)
    if cycle.status == "recapture_required":
        return ("recapture_required", days)
    if today > cycle.due_date:
        overdue_days = -days
        if overdue_days <= max(grace_days, 0):
            return ("due", days)
        return ("late", overdue_days)
    if today == cycle.due_date:
        return ("due", days)
    if days <= days_before:
        return ("open", days)
    return ("scheduled", days)


async def get_actionable_cycle(
    db: AsyncSession,
    hydrometer_id,
    *,
    lock: bool = False,
) -> ReadingCycle | None:
    query = (
        select(ReadingCycle)
        .where(
            ReadingCycle.hydrometer_id == hydrometer_id,
            ReadingCycle.status.in_(ACTIONABLE_CYCLE_STATUSES),
        )
        .order_by(ReadingCycle.due_date, ReadingCycle.created_at)
        .limit(1)
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def create_cycle(
    db: AsyncSession,
    hydrometer: Hydrometer,
    *,
    reference: str,
    cycle_type: str,
    status: str = "open",
) -> ReadingCycle:
    existing = (
        await db.execute(
            select(ReadingCycle).where(
                ReadingCycle.hydrometer_id == hydrometer.id,
                ReadingCycle.reference_month == reference,
                ReadingCycle.cycle_type == cycle_type,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    cycle = ReadingCycle(
        customer_id=hydrometer.customer_id,
        hydrometer_id=hydrometer.id,
        reference_month=reference,
        due_date=reference_due_date(reference, hydrometer.customer.due_day),
        cycle_type=cycle_type,
        status=status,
    )
    db.add(cycle)
    await db.flush()
    return cycle


async def ensure_actionable_cycle(
    db: AsyncSession,
    hydrometer: Hydrometer,
    *,
    today: date | None = None,
    lock: bool = False,
) -> ReadingCycle:
    existing = await get_actionable_cycle(db, hydrometer.id, lock=lock)
    if existing:
        return existing

    current_day = today or date.today()
    if hydrometer.last_reading_date is None:
        return await create_cycle(
            db,
            hydrometer,
            reference=reference_month(current_day),
            cycle_type="installation",
        )

    latest = (
        await db.execute(
            select(Reading)
            .where(
                Reading.hydrometer_id == hydrometer.id,
                Reading.status == "approved",
                Reading.reference_month.is_not(None),
            )
            .order_by(Reading.captured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    base_reference = (
        latest.reference_month
        if latest and latest.reference_month
        else reference_month(hydrometer.last_reading_date.date())
    )
    return await create_cycle(
        db,
        hydrometer,
        reference=next_reference_month(base_reference),
        cycle_type="water",
    )


async def advance_after_approval(
    db: AsyncSession,
    hydrometer: Hydrometer,
    cycle: ReadingCycle,
) -> ReadingCycle:
    cycle.status = "invoiced"
    cycle.completed_at = datetime.now(timezone.utc)
    return await create_cycle(
        db,
        hydrometer,
        reference=next_reference_month(cycle.reference_month),
        cycle_type="water",
    )
