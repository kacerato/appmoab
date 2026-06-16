"""
Tasks de verificação de pagamentos e geração de faturas fixas.
"""

import asyncio
import logging
from datetime import date, datetime, timezone

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Helper para executar coroutines no Celery (sync worker)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.tasks.check_payments.check_payment_status")
def check_payment_status():
    """Consulta Efí por cobranças pagas e atualiza status."""
    _run_async(_check_payments_async())


async def _check_payments_async():
    from app.database import async_session_factory
    from app.models.invoice import Invoice
    from app.services.efi_api import efi_service
    from app.services.payment_receipts import store_efi_payment_receipt
    from sqlalchemy import select

    logger.info("Verificando pagamentos recebidos...")

    try:
        cobrancas = await efi_service.listar_cobrancas(statuses=["paid", "settled"])

        async with async_session_factory() as db:
            for cob in cobrancas:
                codigo = str(cob.get("id") or cob.get("charge_id") or "")
                if not codigo:
                    continue

                result = await db.execute(
                    select(Invoice).where(
                        Invoice.efi_charge_id == codigo,
                        Invoice.status.in_(["sent", "overdue"]),
                    )
                )
                invoice = result.scalar_one_or_none()
                if invoice:
                    invoice.status = "paid"
                    invoice.efi_status = cob.get("status") or invoice.efi_status
                    invoice.efi_raw_response = cob
                    paid_at = ((cob.get("payment") or {}).get("paid_at") or cob.get("paid_at") or "")[:10]
                    invoice.paid_date = date.fromisoformat(paid_at) if paid_at else date.today()
                    invoice.efi_payment_receipt_url = store_efi_payment_receipt(invoice, cob)
                    logger.info(f"Fatura {invoice.id} marcada como PAGA")

            await db.commit()

    except Exception as e:
        logger.error(f"Erro ao verificar pagamentos: {e}")


@celery_app.task(name="app.tasks.check_payments.mark_overdue_invoices")
def mark_overdue_invoices():
    """Marca faturas vencidas como 'overdue'."""
    _run_async(_mark_overdue_async())


async def _mark_overdue_async():
    from app.database import async_session_factory
    from app.models.invoice import Invoice
    from sqlalchemy import select, update

    logger.info("Marcando faturas vencidas...")

    async with async_session_factory() as db:
        today = date.today()
        result = await db.execute(
            update(Invoice)
            .where(
                Invoice.due_date < today,
                Invoice.status.in_(["pending", "sent"]),
            )
            .values(status="overdue")
            .returning(Invoice.id)
        )
        updated = result.all()
        await db.commit()
        logger.info(f"{len(updated)} faturas marcadas como vencidas")


@celery_app.task(name="app.tasks.check_payments.generate_fixed_invoices")
def generate_fixed_invoices():
    """Gera faturas fixas (R$100) para clientes sem hidrômetro."""
    _run_async(_generate_fixed_async())


async def _generate_fixed_async():
    from app.database import async_session_factory
    from app.models.customer import Customer
    from app.models.invoice import Invoice
    from app.services.billing import get_fixed_rate
    from app.models.system_setting import SystemSetting
    from sqlalchemy import select
    from app.services.billing_policy import payment_due_date_for_provider
    from app.services.efi_api import efi_service

    logger.info("Gerando faturas fixas para clientes sem hidrômetro...")

    async with async_session_factory() as db:
        now = datetime.now(timezone.utc)
        ref_month = f"{now.year}-{now.month:02d}"

        # Busca clientes sem hidrômetro e ativos
        result = await db.execute(
            select(Customer).where(
                Customer.has_hydrometer == False,  # noqa: E712
                Customer.status == "active",
            )
        )
        customers = result.scalars().all()
        fixed_rate = await get_fixed_rate(db)
        settings_result = await db.execute(select(SystemSetting).where(SystemSetting.id == 1))
        settings = settings_result.scalar_one_or_none() or SystemSetting(id=1)

        for customer in customers:
            # Verifica se já existe fatura do mês
            existing = await db.execute(
                select(Invoice).where(
                    Invoice.customer_id == customer.id,
                    Invoice.reference_month == ref_month,
                )
            )
            if existing.scalar_one_or_none():
                continue

            due_date = date(now.year, now.month, customer.due_day)

            invoice = Invoice(
                customer_id=customer.id,
                reading_id=None,
                consumption_m3=0.0,
                tariff_rate=0.0,
                amount=fixed_rate,
                original_amount=fixed_rate,
                reference_month=ref_month,
                due_date=due_date,
                status="pending",
            )
            db.add(invoice)
            await db.flush()
            await db.refresh(invoice)

            # Gera cobranca Efí
            try:
                payment_due_date = payment_due_date_for_provider(invoice.due_date, date.today())
                boleto = await efi_service.emitir_cobranca(
                    valor=fixed_rate,
                    cpf_cnpj=customer.cpf_cnpj,
                    nome=customer.name,
                    email=customer.email or "",
                    telefone=customer.phone,
                    endereco=customer.address,
                    numero=customer.number,
                    bairro=customer.neighborhood,
                    cidade=customer.city,
                    uf=customer.state,
                    cep=customer.zip_code,
                    data_vencimento=payment_due_date,
                    seu_numero=f"AQ-FX-{str(invoice.id)[:8].upper()}",
                    mensagem=f"Taxa fixa mensal - Ref: {ref_month}",
                    multa_percentual=settings.late_fee_percent,
                    juros_diario_percentual=settings.daily_interest_percent,
                )

                invoice.payment_provider = "efi"
                invoice.payment_due_date = payment_due_date
                invoice.efi_charge_id = boleto.get("charge_id")
                invoice.efi_status = boleto.get("status")
                invoice.efi_barcode = boleto.get("barcode")
                invoice.efi_payment_url = boleto.get("payment_url")
                invoice.efi_pdf_url = boleto.get("pdf_url")
                invoice.efi_pix_qrcode = boleto.get("pix_qrcode")
                invoice.efi_raw_response = boleto.get("raw")
                invoice.status = "sent"

                if invoice.efi_pdf_url:
                    pdf = await efi_service.baixar_pdf(invoice.efi_pdf_url)
                    if pdf:
                        invoice.pdf_data = pdf

            except Exception as e:
                logger.error(f"Erro ao gerar cobranca Efí para {customer.name}: {e}")

        await db.commit()
        logger.info(f"Processados {len(customers)} clientes sem hidrômetro")
