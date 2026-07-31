import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.customer import Customer
from app.models.customer_attachment import CustomerAttachment
from app.models.hydrometer import Hydrometer
from app.models.invoice import Invoice
from app.models.reading import Reading
from app.models.reading_cycle import ReadingCycle
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.schemas.customer import (
    CustomerCreate,
    CustomerDetailResponse,
    CustomerListResponse,
    CustomerOptionListResponse,
    CustomerOptionResponse,
    CustomerResponse,
    CustomerUpdate,
)
from app.schemas.customer_attachment import CustomerAttachmentCreate, CustomerAttachmentResponse
from app.services.hydrometer_codes import get_next_hydrometer_code
from app.services.reading_cycles import (
    ACTIONABLE_CYCLE_STATUSES,
    cycle_timing,
    ensure_actionable_cycle,
    reference_due_date,
)
from app.utils.security import get_current_user, require_admin
from app.utils.storage import build_public_upload_url, delete_photo, save_binary_from_base64

router = APIRouter(prefix="/customers", tags=["Clientes"])


class BulkDueDayUpdate(BaseModel):
    due_day: int

    @field_validator("due_day")
    @classmethod
    def validate_due_day(cls, value: int) -> int:
        if not 1 <= value <= 28:
            raise ValueError("Dia de vencimento deve ser entre 1 e 28")
        return value


def _active_route_cycles_query():
    return (
        select(ReadingCycle)
        .join(ReadingCycle.hydrometer)
        .join(ReadingCycle.customer)
        .options(
            selectinload(ReadingCycle.customer).selectinload(Customer.hydrometers),
            selectinload(ReadingCycle.hydrometer),
            selectinload(ReadingCycle.readings).selectinload(Reading.collaborator),
        )
        .where(
            ReadingCycle.status.in_(ACTIONABLE_CYCLE_STATUSES),
            Hydrometer.is_active.is_(True),
            Customer.status == "active",
        )
        .order_by(ReadingCycle.due_date, ReadingCycle.created_at)
    )


def _resolve_month_date(base_day: int, reference: date) -> date:
    return date(reference.year, reference.month, base_day)


def _customer_in_route_window(customer: Customer, settings: SystemSetting, today: date) -> bool:
    if any(hydrometer.last_reading_date is None for hydrometer in customer.hydrometers):
        return True

    if not settings.route_window_enabled:
        return True

    before = settings.route_window_days_before_due
    after = settings.route_window_days_after_due
    due_day = customer.due_day

    current_month_due = _resolve_month_date(due_day, today)
    first_of_month = today.replace(day=1)
    previous_month_anchor = first_of_month - timedelta(days=1)
    previous_month_due = _resolve_month_date(due_day, previous_month_anchor)
    next_month_anchor = (first_of_month + timedelta(days=32)).replace(day=1)
    next_month_due = _resolve_month_date(due_day, next_month_anchor)

    for due_date in (previous_month_due, current_month_due, next_month_due):
        if due_date - timedelta(days=before) <= today <= due_date + timedelta(days=after):
            return True
    return False


def _attachment_response(attachment: CustomerAttachment) -> CustomerAttachmentResponse:
    return CustomerAttachmentResponse(
        id=attachment.id,
        customer_id=attachment.customer_id,
        kind=attachment.kind,
        original_name=attachment.original_name,
        mime_type=attachment.mime_type,
        reference_month=attachment.reference_month,
        notes=attachment.notes,
        download_url=build_public_upload_url(attachment.stored_path),
        created_at=attachment.created_at,
    )


OPEN_INVOICE_STATUSES = ("pending", "sent", "overdue")
BILLING_CYCLE_CHARGE_TYPES = ("water", "installation")


def _next_due_date(customer: Customer, today: date) -> date:
    anchor = today
    created_on = customer.created_at.date() if customer.created_at else today
    if created_on.year == today.year and created_on.month == today.month:
        next_month_anchor = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        return _resolve_month_date(customer.due_day, next_month_anchor)

    due_date = _resolve_month_date(customer.due_day, anchor)
    if due_date >= today:
        return due_date

    first_of_month = today.replace(day=1)
    next_month_anchor = (first_of_month + timedelta(days=32)).replace(day=1)
    return _resolve_month_date(customer.due_day, next_month_anchor)


def _next_reference_month(due_date: date) -> str:
    return f"{due_date.year}-{due_date.month:02d}"


def _current_reference_month(today: date) -> str:
    return f"{today.year}-{today.month:02d}"


def _format_reference_month(reference_month: str) -> str:
    try:
        year, month = reference_month.split("-", 1)
        return f"{month}/{year}"
    except ValueError:
        return reference_month


def _apply_billing_status(
    response: CustomerResponse,
    customer: Customer,
    today: date,
    oldest_open_overdue_due_date: date | None = None,
    last_paid_date: date | None = None,
    active_cycle: ReadingCycle | None = None,
) -> None:
    if oldest_open_overdue_due_date:
        days_overdue = (today - oldest_open_overdue_due_date).days
        response.days_until_due = -days_overdue
        response.billing_status = "overdue"
        response.billing_status_label = (
            f"Vencido desde {oldest_open_overdue_due_date.strftime('%d/%m/%Y')} "
            f"ha {days_overdue} dia(s)"
        )
        return

    if active_cycle is not None:
        due_date = active_cycle.due_date
        reference_month = active_cycle.reference_month
        response.next_invoice_reference_month = reference_month
        response.next_invoice_due_date = datetime.combine(due_date, datetime.min.time())
        days_until_due = (due_date - today).days
        response.days_until_due = days_until_due
        formatted_reference = _format_reference_month(reference_month)
        if active_cycle.status == "pending_review":
            response.billing_status = "reading_pending"
            response.billing_status_label = (
                f"Leitura de {formatted_reference} aguardando aprovacao"
            )
        elif active_cycle.status == "recapture_required":
            response.billing_status = "reading_rejected"
            response.billing_status_label = (
                f"Nova captura obrigatoria para {formatted_reference}"
            )
        elif today > due_date:
            response.billing_status = "reading_overdue"
            response.billing_status_label = (
                f"Leitura de {formatted_reference} atrasada ha {(today - due_date).days} dia(s); "
                "fatura ainda nao gerada"
            )
        elif days_until_due == 0:
            response.billing_status = "reading_due"
            response.billing_status_label = f"Leitura de {formatted_reference} vence hoje"
        elif days_until_due <= 3:
            response.billing_status = "reading_due"
            response.billing_status_label = (
                f"Leitura de {formatted_reference} vence em {days_until_due} dia(s)"
            )
        else:
            response.billing_status = "normal"
            response.billing_status_label = (
                f"Proxima leitura {formatted_reference} em {due_date.strftime('%d/%m/%Y')}"
            )
        return

    due_date = _next_due_date(customer, today)
    reference_month = _next_reference_month(due_date)
    response.next_invoice_reference_month = reference_month
    response.next_invoice_due_date = datetime.combine(due_date, datetime.min.time())
    if last_paid_date:
        response.last_paid_date = datetime.combine(last_paid_date, datetime.min.time())
        response.billing_status = "paid"
        response.billing_status_label = (
            f"Pago em {last_paid_date.strftime('%d/%m/%Y')} - proxima fatura {due_date.strftime('%d/%m/%Y')}"
        )
        response.days_until_due = (due_date - today).days
        return

    days_until_due = (due_date - today).days
    response.days_until_due = days_until_due
    if days_until_due == 0:
        response.billing_status = "due_today"
        response.billing_status_label = f"Vence hoje ({due_date.strftime('%d/%m/%Y')})"
    elif days_until_due <= 3:
        response.billing_status = "near_due"
        response.billing_status_label = f"Vence em {days_until_due} dia(s) - {due_date.strftime('%d/%m/%Y')}"
    else:
        response.billing_status = "normal"
        response.billing_status_label = (
            f"Vence em {due_date.strftime('%d/%m/%Y')} "
            f"(ref. {_format_reference_month(reference_month)})"
        )


async def _get_system_settings(db: AsyncSession) -> SystemSetting:
    result = await db.execute(select(SystemSetting).where(SystemSetting.id == 1))
    settings = result.scalar_one_or_none()
    if settings:
        return settings

    settings = SystemSetting(id=1)
    db.add(settings)
    await db.flush()
    return settings


async def _build_customer_response(db: AsyncSession, customer_id: uuid.UUID) -> CustomerResponse:
    result = await db.execute(
        select(Customer)
        .options(selectinload(Customer.hydrometers))
        .where(Customer.id == customer_id)
    )
    customer = result.scalar_one()

    today = date.today()
    overdue_result = await db.execute(
        select(func.min(Invoice.due_date)).where(
            Invoice.customer_id == customer.id,
            Invoice.status.in_(OPEN_INVOICE_STATUSES),
            Invoice.charge_type.in_(BILLING_CYCLE_CHARGE_TYPES),
            Invoice.due_date < today,
        )
    )
    oldest_overdue_due_date = overdue_result.scalar_one_or_none()

    paid_result = await db.execute(
        select(func.max(Invoice.paid_date)).where(
            Invoice.customer_id == customer.id,
            Invoice.status == "paid",
            Invoice.charge_type.in_(BILLING_CYCLE_CHARGE_TYPES),
            Invoice.paid_date.is_not(None),
        )
    )
    last_paid_date = paid_result.scalar_one_or_none()
    active_cycle = (
        await db.execute(
            select(ReadingCycle)
            .where(
                ReadingCycle.customer_id == customer.id,
                ReadingCycle.status.in_(ACTIONABLE_CYCLE_STATUSES),
            )
            .order_by(ReadingCycle.due_date)
            .limit(1)
        )
    ).scalar_one_or_none()

    response = CustomerResponse.model_validate(customer)
    _apply_billing_status(
        response,
        customer,
        today,
        oldest_overdue_due_date,
        last_paid_date,
        active_cycle,
    )
    return response


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=2000),
    search: str | None = None,
    status: str | None = None,
    has_hydrometer: bool | None = None,
    route_scope: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Customer).options(selectinload(Customer.hydrometers))

    if search:
        query = query.where(
            or_(
                Customer.name.ilike(f"%{search}%"),
                Customer.cpf_cnpj.ilike(f"%{search}%"),
                Customer.phone.ilike(f"%{search}%"),
            )
        )
    if status:
        query = query.where(Customer.status == status)
    if has_hydrometer is not None:
        query = query.where(Customer.has_hydrometer == has_hydrometer)

    query = query.order_by(Customer.name)

    if route_scope:
        result = await db.execute(query)
        items = list(result.scalars().all())
        system_settings = await _get_system_settings(db)
        today = date.today()
        items = [customer for customer in items if _customer_in_route_window(customer, system_settings, today)]

        customer_ids = [customer.id for customer in items]
        if customer_ids:
            billed_result = await db.execute(
                select(Invoice.customer_id)
                .where(
                    Invoice.customer_id.in_(customer_ids),
                    Invoice.reference_month == _current_reference_month(today),
                    Invoice.charge_type.in_(BILLING_CYCLE_CHARGE_TYPES),
                    Invoice.status.in_(OPEN_INVOICE_STATUSES + ("paid",)),
                )
                .group_by(Invoice.customer_id)
            )
            billed_customer_ids = {row[0] for row in billed_result.all()}
            items = [customer for customer in items if customer.id not in billed_customer_ids]

        total = len(items)
        offset = (page - 1) * per_page
        paged_items = items[offset:offset + per_page]
    else:
        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0
        offset = (page - 1) * per_page
        result = await db.execute(query.offset(offset).limit(per_page))
        paged_items = list(result.scalars().all())

    today = date.today()
    response_items = []
    overdue_by_customer: dict[uuid.UUID, date] = {}
    paid_by_customer: dict[uuid.UUID, date] = {}
    cycle_by_customer: dict[uuid.UUID, ReadingCycle] = {}
    customer_ids = [customer.id for customer in paged_items]
    if customer_ids:
        overdue_result = await db.execute(
            select(Invoice.customer_id, func.min(Invoice.due_date))
            .where(
                Invoice.customer_id.in_(customer_ids),
                Invoice.status.in_(OPEN_INVOICE_STATUSES),
                Invoice.charge_type.in_(BILLING_CYCLE_CHARGE_TYPES),
                Invoice.due_date < today,
            )
            .group_by(Invoice.customer_id)
        )
        overdue_by_customer = {row[0]: row[1] for row in overdue_result.all()}
        paid_result = await db.execute(
            select(Invoice.customer_id, func.max(Invoice.paid_date))
            .where(
                Invoice.customer_id.in_(customer_ids),
                Invoice.status == "paid",
                Invoice.charge_type.in_(BILLING_CYCLE_CHARGE_TYPES),
                Invoice.paid_date.is_not(None),
            )
            .group_by(Invoice.customer_id)
        )
        paid_by_customer = {row[0]: row[1] for row in paid_result.all()}
        cycle_result = await db.execute(
            select(ReadingCycle)
            .where(
                ReadingCycle.customer_id.in_(customer_ids),
                ReadingCycle.status.in_(ACTIONABLE_CYCLE_STATUSES),
            )
            .order_by(ReadingCycle.due_date)
        )
        for cycle in cycle_result.scalars().all():
            cycle_by_customer.setdefault(cycle.customer_id, cycle)

    for customer in paged_items:
        response = CustomerResponse.model_validate(customer)
        _apply_billing_status(
            response,
            customer,
            today,
            overdue_by_customer.get(customer.id),
            paid_by_customer.get(customer.id),
            cycle_by_customer.get(customer.id),
        )
        response_items.append(response)

    return CustomerListResponse(items=response_items, total=total, page=page, per_page=per_page)


@router.post("/bulk-due-day")
async def update_all_customers_due_day(
    data: BulkDueDayUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        update(Customer)
        .where(Customer.status == "active")
        .values(due_day=data.due_day, updated_at=datetime.now(timezone.utc))
        .returning(Customer.id)
    )
    updated_ids = result.scalars().all()
    cycle_result = await db.execute(
        select(ReadingCycle).where(
            ReadingCycle.customer_id.in_(updated_ids),
            ReadingCycle.status.in_(ACTIONABLE_CYCLE_STATUSES),
        )
    )
    for cycle in cycle_result.scalars().all():
        cycle.due_date = reference_due_date(cycle.reference_month, data.due_day)
    await db.flush()
    return {"updated": len(updated_ids), "due_day": data.due_day}


@router.get("/options", response_model=CustomerOptionListResponse)
async def list_customer_options(
    limit: int = Query(500, ge=1, le=2000),
    search: str | None = None,
    has_phone: bool | None = None,
    has_hydrometer: bool | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Customer)
    if search:
        query = query.where(
            or_(
                Customer.name.ilike(f"%{search}%"),
                Customer.cpf_cnpj.ilike(f"%{search}%"),
                Customer.phone.ilike(f"%{search}%"),
            )
        )
    if has_phone is True:
        query = query.where(Customer.phone.is_not(None), Customer.phone != "")
    if has_hydrometer is not None:
        query = query.where(Customer.has_hydrometer == has_hydrometer)
    if status:
        query = query.where(Customer.status == status)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(query.order_by(Customer.name).limit(limit))
    return CustomerOptionListResponse(
        items=[CustomerOptionResponse.model_validate(customer) for customer in result.scalars().all()],
        total=total,
    )


@router.get("/route-tasks")
async def list_route_tasks(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Fila duravel de campo: atrasos nunca somem depois da janela de vencimento."""
    hydrometers_result = await db.execute(
        select(Hydrometer)
        .options(selectinload(Hydrometer.customer))
        .join(Hydrometer.customer)
        .where(
            Hydrometer.is_active.is_(True),
            Customer.status == "active",
        )
    )
    for hydrometer in hydrometers_result.scalars().all():
        await ensure_actionable_cycle(db, hydrometer)

    settings = await _get_system_settings(db)
    today = date.today()
    result = await db.execute(_active_route_cycles_query())

    items = []
    for cycle in result.scalars().unique().all():
        state, day_count = cycle_timing(
            cycle,
            today,
            settings.route_window_days_before_due if settings.route_window_enabled else 10000,
            settings.route_window_days_after_due,
        )
        if state == "scheduled" and settings.route_window_enabled:
            continue
        latest_reading = max(cycle.readings, key=lambda item: item.created_at, default=None)
        items.append({
            "id": str(cycle.id),
            "cycle_id": str(cycle.id),
            "reference_month": cycle.reference_month,
            "due_date": cycle.due_date.isoformat(),
            "cycle_type": cycle.cycle_type,
            "cycle_status": cycle.status,
            "state": state,
            "day_count": day_count,
            "rejection_reason": (
                latest_reading.rejection_reason
                if latest_reading and latest_reading.status == "rejected"
                else None
            ),
            "pending_collaborator_name": (
                latest_reading.collaborator.name
                if latest_reading
                and latest_reading.status == "pending"
                and latest_reading.collaborator
                else None
            ),
            "customer": CustomerResponse.model_validate(cycle.customer).model_dump(mode="json"),
            "hydrometer": {
                "id": str(cycle.hydrometer.id),
                "code": cycle.hydrometer.code,
                "qr_code_token": cycle.hydrometer.qr_code_token,
                "last_reading_value": cycle.hydrometer.last_reading_value,
                "last_reading_date": (
                    cycle.hydrometer.last_reading_date.isoformat()
                    if cycle.hydrometer.last_reading_date
                    else None
                ),
                "red_digits": cycle.hydrometer.red_digits,
                "black_digits": cycle.hydrometer.black_digits,
                "brand": cycle.hydrometer.brand,
                "model": cycle.hydrometer.model,
                "latitude": cycle.hydrometer.latitude,
                "longitude": cycle.hydrometer.longitude,
                "location_description": cycle.hydrometer.location_description,
            },
        })
    return {"items": items, "total": len(items), "generated_at": datetime.now(timezone.utc)}


@router.get("/{customer_id}", response_model=CustomerDetailResponse)
async def get_customer(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Customer)
        .options(
            selectinload(Customer.hydrometers),
            selectinload(Customer.attachments),
        )
        .where(Customer.id == uuid.UUID(customer_id))
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    inv_result = await db.execute(
        select(
            func.count(Invoice.id),
            func.coalesce(func.sum(case((
                (Invoice.status == "pending") & (Invoice.due_date <= date.today()),
                Invoice.amount,
            ), else_=0)), 0),
            func.coalesce(func.sum(case((
                (Invoice.status.in_(OPEN_INVOICE_STATUSES))
                & (Invoice.charge_type.in_(BILLING_CYCLE_CHARGE_TYPES))
                & (Invoice.due_date < date.today()),
                Invoice.amount,
            ), else_=0)), 0),
            func.min(case((
                (Invoice.status.in_(OPEN_INVOICE_STATUSES))
                & (Invoice.charge_type.in_(BILLING_CYCLE_CHARGE_TYPES))
                & (Invoice.due_date < date.today()),
                Invoice.due_date,
            ), else_=None)),
            func.max(case((
                (Invoice.status == "paid") & (Invoice.charge_type.in_(BILLING_CYCLE_CHARGE_TYPES)),
                Invoice.paid_date,
            ), else_=None)),
        ).where(Invoice.customer_id == customer.id)
    )
    total_inv, pending, overdue, oldest_overdue_due_date, last_paid_date = inv_result.one()

    response = CustomerDetailResponse.model_validate(customer)
    active_cycle = (
        await db.execute(
            select(ReadingCycle)
            .where(
                ReadingCycle.customer_id == customer.id,
                ReadingCycle.status.in_(ACTIONABLE_CYCLE_STATUSES),
            )
            .order_by(ReadingCycle.due_date)
            .limit(1)
        )
    ).scalar_one_or_none()
    _apply_billing_status(
        response,
        customer,
        date.today(),
        oldest_overdue_due_date,
        last_paid_date,
        active_cycle,
    )
    response.attachments = [_attachment_response(attachment) for attachment in customer.attachments]
    response.total_invoices = total_inv
    response.total_pending = float(pending)
    response.total_overdue = float(overdue)
    return response


@router.post("", response_model=CustomerResponse, status_code=201)
async def create_customer(
    data: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    existing = await db.execute(select(Customer).where(Customer.cpf_cnpj == data.cpf_cnpj))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="CPF/CNPJ ja cadastrado")

    payload = data.model_dump()
    for optional_field in ("phone", "email", "complement", "notes"):
        if payload.get(optional_field) == "":
            payload[optional_field] = None
    hydrometer_initial_reading = payload.pop("hydrometer_initial_reading", 0.0)
    hydrometer_red_digits = payload.pop("hydrometer_red_digits", 3)
    hydrometer_black_digits = payload.pop("hydrometer_black_digits", None)
    hydrometer_brand = payload.pop("hydrometer_brand", None)
    hydrometer_model = payload.pop("hydrometer_model", None)
    hydrometer_location_description = payload.pop("hydrometer_location_description", None)

    customer = Customer(**payload)
    db.add(customer)
    await db.flush()

    if customer.has_hydrometer:
        target_code = await get_next_hydrometer_code(db)
        hydrometer = Hydrometer(
            customer_id=customer.id,
            code=target_code,
            brand=hydrometer_brand,
            model=hydrometer_model,
            red_digits=hydrometer_red_digits,
            black_digits=hydrometer_black_digits,
            location_description=hydrometer_location_description or "Instalacao padrao",
            last_reading_value=hydrometer_initial_reading,
        )
        db.add(hydrometer)
        await db.flush()
        hydrometer.customer = customer
        await ensure_actionable_cycle(db, hydrometer)

    await db.flush()
    return await _build_customer_response(db, customer.id)


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: str,
    data: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(Customer).where(Customer.id == uuid.UUID(customer_id)))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(customer, field, value)
    if update_data.get("due_day") is not None:
        cycle_result = await db.execute(
            select(ReadingCycle).where(
                ReadingCycle.customer_id == customer.id,
                ReadingCycle.status.in_(ACTIONABLE_CYCLE_STATUSES),
            )
        )
        for cycle in cycle_result.scalars().all():
            cycle.due_date = reference_due_date(cycle.reference_month, customer.due_day)

    await db.flush()
    await db.refresh(customer)
    return customer


@router.post("/{customer_id}/attachments", response_model=CustomerAttachmentResponse, status_code=201)
async def create_customer_attachment(
    customer_id: str,
    data: CustomerAttachmentCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(Customer).where(Customer.id == uuid.UUID(customer_id)))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    stored_path = save_binary_from_base64(data.file_base64, prefix="legacy_invoice", fallback_ext="pdf")
    attachment = CustomerAttachment(
        customer_id=customer.id,
        kind="legacy_invoice",
        original_name=data.original_name,
        stored_path=stored_path,
        mime_type=data.mime_type,
        reference_month=data.reference_month,
        notes=data.notes,
    )
    db.add(attachment)
    await db.flush()
    await db.refresh(attachment)
    return _attachment_response(attachment)


@router.delete("/{customer_id}/attachments/{attachment_id}", status_code=204)
async def delete_customer_attachment(
    customer_id: str,
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(CustomerAttachment).where(
            CustomerAttachment.id == uuid.UUID(attachment_id),
            CustomerAttachment.customer_id == uuid.UUID(customer_id),
        )
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Anexo nao encontrado")

    delete_photo(attachment.stored_path)
    await db.delete(attachment)
    await db.flush()


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(Customer).where(Customer.id == uuid.UUID(customer_id)))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    await db.delete(customer)
    await db.flush()
