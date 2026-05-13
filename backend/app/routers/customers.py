import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.customer import Customer
from app.models.customer_attachment import CustomerAttachment
from app.models.hydrometer import Hydrometer
from app.models.invoice import Invoice
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.schemas.customer import CustomerCreate, CustomerDetailResponse, CustomerListResponse, CustomerResponse, CustomerUpdate
from app.schemas.customer_attachment import CustomerAttachmentCreate, CustomerAttachmentResponse
from app.services.hydrometer_codes import get_next_hydrometer_code
from app.utils.security import get_current_user, require_admin
from app.utils.storage import build_public_upload_url, delete_photo, save_binary_from_base64

router = APIRouter(prefix="/customers", tags=["Clientes"])


def _resolve_month_date(base_day: int, reference: date) -> date:
    return date(reference.year, reference.month, base_day)


def _customer_in_route_window(customer: Customer, settings: SystemSetting, today: date) -> bool:
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


def _apply_billing_status(response: CustomerResponse, customer: Customer, today: date) -> None:
    due_date = _resolve_month_date(customer.due_day, today)
    days_until_due = (due_date - today).days
    response.days_until_due = days_until_due
    if days_until_due < 0:
        response.billing_status = "overdue"
        response.billing_status_label = f"Vencido ha {abs(days_until_due)} dia(s)"
    elif days_until_due == 0:
        response.billing_status = "due_today"
        response.billing_status_label = "Vence hoje"
    elif days_until_due <= 3:
        response.billing_status = "near_due"
        response.billing_status_label = f"Vence em {days_until_due} dia(s)"
    else:
        response.billing_status = "normal"
        response.billing_status_label = f"Vence dia {customer.due_day}"


async def _get_system_settings(db: AsyncSession) -> SystemSetting:
    result = await db.execute(select(SystemSetting).where(SystemSetting.id == 1))
    settings = result.scalar_one_or_none()
    if settings:
        return settings

    settings = SystemSetting(id=1)
    db.add(settings)
    await db.flush()
    return settings


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
    for customer in paged_items:
        response = CustomerResponse.model_validate(customer)
        _apply_billing_status(response, customer, today)
        response_items.append(response)

    return CustomerListResponse(items=response_items, total=total, page=page, per_page=per_page)


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
            func.coalesce(func.sum(case((Invoice.status == "pending", Invoice.amount), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.status == "overdue", Invoice.amount), else_=0)), 0),
        ).where(Invoice.customer_id == customer.id)
    )
    total_inv, pending, overdue = inv_result.one()

    response = CustomerDetailResponse.model_validate(customer)
    _apply_billing_status(response, customer, date.today())
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

        settings = await _get_system_settings(db)
        if settings.installation_fee_amount > 0:
            today = date.today()
            db.add(Invoice(
                customer_id=customer.id,
                amount=settings.installation_fee_amount,
                original_amount=settings.installation_fee_amount,
                reference_month=f"{today.year}-{today.month:02d}",
                due_date=date(today.year, today.month, min(customer.due_day, 28)),
                consumption_m3=0.0,
                tariff_rate=0.0,
                charge_type="installation",
                status="pending",
            ))

    await db.refresh(customer)
    return customer


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

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)

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
