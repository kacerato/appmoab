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
    """Consulta Inter por boletos RECEBIDO e atualiza status."""
    _run_async(_check_payments_async())


async def _check_payments_async():
    from app.database import async_session_factory
    from app.models.invoice import Invoice
    from app.services.inter_api import inter_service
    from sqlalchemy import select

    logger.info("Verificando pagamentos recebidos...")

    try:
        cobrancas = await inter_service.consultar_situacao(["RECEBIDO"])

        async with async_session_factory() as db:
            for cob in cobrancas:
                codigo = cob.get("codigoSolicitacao")
                if not codigo:
                    continue

                result = await db.execute(
                    select(Invoice).where(
                        Invoice.inter_codigo_solicitacao == codigo,
                        Invoice.status.in_(["sent", "overdue"]),
                    )
                )
                invoice = result.scalar_one_or_none()
                if invoice:
                    invoice.status = "paid"
                    invoice.paid_date = date.today()
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
    from app.services.inter_api import inter_service
    from sqlalchemy import select

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
                reference_month=ref_month,
                due_date=due_date,
                status="pending",
            )
            db.add(invoice)
            await db.flush()
            await db.refresh(invoice)

            # Gera boleto Inter
            try:
                seu_numero = f"AQ-FX-{str(invoice.id)[:8].upper()}"
                boleto = await inter_service.emitir_cobranca(
                    valor=fixed_rate,
                    cpf_cnpj=customer.cpf_cnpj,
                    nome=customer.name,
                    email=customer.email or "",
                    endereco=customer.address,
                    numero=customer.number,
                    bairro=customer.neighborhood,
                    cidade=customer.city,
                    uf=customer.state,
                    cep=customer.zip_code,
                    data_vencimento=due_date,
                    seu_numero=seu_numero,
                    mensagem=f"Taxa fixa mensal - Ref: {ref_month}",
                )

                invoice.inter_codigo_solicitacao = boleto.get("codigoSolicitacao")
                invoice.inter_nosso_numero = boleto.get("nossoNumero")
                invoice.inter_linha_digitavel = boleto.get("linhaDigitavel")
                invoice.inter_codigo_barras = boleto.get("codigoBarras")
                invoice.status = "sent"

                if boleto.get("codigoSolicitacao"):
                    pdf = await inter_service.buscar_pdf(boleto["codigoSolicitacao"])
                    if pdf:
                        invoice.pdf_data = pdf

            except Exception as e:
                logger.error(f"Erro ao gerar boleto para {customer.name}: {e}")

        await db.commit()
        logger.info(f"Processados {len(customers)} clientes sem hidrômetro")
