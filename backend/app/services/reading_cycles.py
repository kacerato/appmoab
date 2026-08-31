"""Regras centrais da fila mensal de leituras."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hydrometer import Hydrometer
from app.models.reading import Reading
from app.models.reading_cycle import ReadingCycle

ACTIONABLE_CYCLE_STATUSES = ("open", "pending_review", "recapture_required")


def hydrometer_available_for_field(hydrometer: Hydrometer) -> bool:
    """A field capture is valid only while both meter and customer are active."""
    return bool(
        hydrometer.is_active
        and hydrometer.customer
        and hydrometer.customer.status == "active"
    )


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


async def get_latest_approved_reading(
    db: AsyncSession,
    hydrometer_id,
    *,
    exclude_reading_id=None,
) -> Reading | None:
    query = select(Reading).where(
        Reading.hydrometer_id == hydrometer_id,
        Reading.status == "approved",
    )
    if exclude_reading_id is not None:
        query = query.where(Reading.id != exclude_reading_id)
    return (
        await db.execute(
            query.order_by(Reading.captured_at.desc(), Reading.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()


async def is_first_official_reading(
    db: AsyncSession,
    hydrometer_id,
    *,
    exclude_reading_id=None,
) -> bool:
    return (
        await get_latest_approved_reading(
            db,
            hydrometer_id,
            exclude_reading_id=exclude_reading_id,
        )
    ) is None


async def promote_cycle_to_installation(
    db: AsyncSession,
    cycle: ReadingCycle,
) -> ReadingCycle:
    """Corrige ciclos legados: a primeira leitura oficial sempre e instalacao."""
    if cycle.cycle_type == "installation":
        return cycle

    existing_installation = (
        await db.execute(
            select(ReadingCycle).where(
                ReadingCycle.hydrometer_id == cycle.hydrometer_id,
                ReadingCycle.reference_month == cycle.reference_month,
                ReadingCycle.cycle_type == "installation",
            )
        )
    ).scalar_one_or_none()
    if existing_installation:
        cycle.status = "superseded"
        cycle.completed_at = datetime.now(timezone.utc)
        return existing_installation

    cycle.cycle_type = "installation"
    await db.flush()
    return cycle


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


async def register_administrative_baseline(
    db: AsyncSession,
    hydrometer: Hydrometer,
    *,
    value: float,
    captured_at: datetime,
    admin_id,
) -> Reading:
    """Registra uma leitura-base oficial informada pelo gestor, sem gerar cobranca.

    O registro aprovado preserva o historico e evita que a fila de campo trate o
    medidor como uma instalacao pendente. A cobranca de consumo comeca no ciclo
    seguinte ao da leitura-base.
    """
    reference = reference_month(captured_at.date())
    installation_cycle = await create_cycle(
        db,
        hydrometer,
        reference=reference,
        cycle_type="installation",
        status="completed",
    )
    installation_cycle.status = "completed"
    installation_cycle.completed_at = datetime.now(timezone.utc)

    reading = Reading(
        hydrometer_id=hydrometer.id,
        collaborator_id=admin_id,
        cycle_id=installation_cycle.id,
        current_value=float(value),
        previous_value=float(value),
        consumption=0.0,
        photo_url="",
        reference_month=reference,
        reading_kind="installation",
        location_status="manual_dashboard",
        captured_at=captured_at,
        validation_flags=[{
            "code": "administrative_baseline",
            "label": "Leitura-base administrativa",
            "message": "Valor informado pelo gestor no dashboard, sem foto de campo.",
            "severity": "info",
        }],
        status="approved",
        approved_by=admin_id,
        approved_at=datetime.now(timezone.utc),
        review_adjustment_reason="Leitura-base informada na associacao pelo dashboard",
    )
    db.add(reading)
    hydrometer.last_reading_value = float(value)
    hydrometer.last_reading_date = captured_at
    await db.flush()

    await create_cycle(
        db,
        hydrometer,
        reference=next_reference_month(reference),
        cycle_type="water",
    )
    return reading


async def ensure_actionable_cycle(
    db: AsyncSession,
    hydrometer: Hydrometer,
    *,
    today: date | None = None,
    lock: bool = False,
) -> ReadingCycle:
    existing = await get_actionable_cycle(db, hydrometer.id, lock=lock)
    current_day = today or date.today()
    latest = await get_latest_approved_reading(db, hydrometer.id)
    if latest is None:
        if existing:
            return await promote_cycle_to_installation(db, existing)
        return await create_cycle(
            db,
            hydrometer,
            reference=reference_month(current_day),
            cycle_type="installation",
        )

    if existing:
        return existing

    base_reference = (
        latest.reference_month
        if latest and latest.reference_month
        else reference_month(
            hydrometer.last_reading_date.date()
            if hydrometer.last_reading_date
            else latest.captured_at.date()
        )
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
