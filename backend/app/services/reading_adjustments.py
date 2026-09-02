"""Ajustes administrativos que preservam a consistencia das leituras."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.hydrometer import Hydrometer
from app.models.reading import Reading


ROLLOVER_PREVIOUS_THRESHOLD = 0.90
ACTIVE_INVOICE_STATUSES = {"pending", "sent", "paid", "overdue"}


class ReadingAdjustmentError(ValueError):
    """O ajuste solicitado quebraria um contrato operacional ou financeiro."""


def _adjusted_consumption(
    hydrometer: Hydrometer,
    reading: Reading,
    value: float,
) -> tuple[float, bool]:
    if reading.reading_kind == "installation":
        return 0.0, False

    previous_value = float(reading.previous_value)
    consumption = value - previous_value
    if consumption >= 0:
        return consumption, False

    rollover_limit = float(10 ** (hydrometer.black_digits or 4))
    if previous_value >= rollover_limit * ROLLOVER_PREVIOUS_THRESHOLD:
        return (rollover_limit - previous_value) + value, True

    raise ReadingAdjustmentError(
        "A leitura corrigida nao pode ser menor que a leitura oficial anterior. "
        "Revise o historico antes de salvar."
    )


def _adjustment_flags(
    reading: Reading,
    *,
    previous_value: float,
    current_value: float,
    rollover: bool,
) -> list[dict]:
    recalculated_codes = {
        "consumption_spike",
        "meter_regression",
        "meter_rollover",
        "reading_regression_override",
        "manual_history_adjustment",
    }
    flags = [
        flag
        for flag in (reading.validation_flags or [])
        if flag.get("code") not in recalculated_codes
    ]
    if rollover:
        flags.append({
            "code": "meter_rollover",
            "label": "Virada do hidrômetro",
            "message": "Consumo recalculado considerando a virada do mostrador.",
            "severity": "info",
        })
    flags.append({
        "code": "manual_history_adjustment",
        "label": "Leitura corrigida pelo gestor",
        "message": (
            f"Valor oficial ajustado de {previous_value:.3f} m³ "
            f"para {current_value:.3f} m³ na aba de hidrômetros."
        ),
        "severity": "info",
    })
    return flags


async def adjust_latest_approved_reading(
    db: AsyncSession,
    hydrometer: Hydrometer,
    *,
    value: float,
) -> Reading:
    """Corrige a ultima leitura e todos os seus valores-resumo dependentes.

    O hidrômetro guarda um resumo desnormalizado, mas ``Reading`` permanece a
    fonte do histórico. Capturas pendentes também guardam uma fotografia do
    valor anterior; por isso elas precisam acompanhar o ajuste.
    """
    latest = (
        await db.execute(
            select(Reading)
            .options(
                selectinload(Reading.invoice),
                selectinload(Reading.vision_inference),
            )
            .where(
                Reading.hydrometer_id == hydrometer.id,
                Reading.status == "approved",
            )
            .order_by(Reading.captured_at.desc(), Reading.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if latest is None:
        raise ReadingAdjustmentError(
            "Este hidrômetro ainda não possui uma leitura oficial para corrigir."
        )

    adjusted_value = float(value)
    old_value = float(
        latest.current_value
        if latest.current_value is not None
        else hydrometer.last_reading_value
    )
    value_changed = abs(old_value - adjusted_value) > 0.0000005
    if (
        value_changed
        and latest.reading_kind != "installation"
        and latest.invoice is not None
        and latest.invoice.status in ACTIVE_INVOICE_STATUSES
    ):
        raise ReadingAdjustmentError(
            "A última leitura possui uma cobrança ativa. Cancele ou desfaça a "
            "cobrança antes de corrigir o valor oficial."
        )

    consumption, rollover = _adjusted_consumption(hydrometer, latest, adjusted_value)

    if latest.reading_kind == "installation":
        latest.previous_value = adjusted_value
    latest.current_value = adjusted_value
    latest.consumption = consumption

    if value_changed:
        latest.validation_flags = _adjustment_flags(
            latest,
            previous_value=old_value,
            current_value=adjusted_value,
            rollover=rollover,
        )
        latest.review_adjustment_reason = "Valor oficial corrigido na aba de hidrômetros"
        if latest.vision_inference is not None:
            inference = latest.vision_inference
            inference.confirmed_value = adjusted_value
            inference.was_correct = (
                inference.predicted_value is not None
                and abs(float(inference.predicted_value) - adjusted_value) <= 0.01
            )

    pending_readings = (
        await db.execute(
            select(Reading)
            .where(
                Reading.hydrometer_id == hydrometer.id,
                Reading.status == "pending",
            )
            .with_for_update()
        )
    ).scalars().all()
    for pending in pending_readings:
        pending.previous_value = adjusted_value
        # O consumo pendente nao e oficial e sera recalculado na aprovacao.
        pending.consumption = None

    hydrometer.last_reading_value = adjusted_value
    hydrometer.last_reading_date = latest.captured_at
    await db.flush()
    return latest
