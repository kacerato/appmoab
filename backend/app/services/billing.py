"""
AquaMoab — Serviço de Cálculo de Faturamento.

Implementa a fórmula de tarifa por faixas de consumo:
- A tarifa é aplicada sobre TODO o consumo (não apenas excedente)
- Taxa mínima padrão: R$110
- Clientes sem hidrômetro: taxa fixa R$100/mês
"""

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tariff import TariffTier
from app.schemas.tariff import BillingCalculation

logger = logging.getLogger(__name__)

# Tarifas padrão (seed) — serão usadas se não houver nenhuma no banco
DEFAULT_TIERS = [
    {"label": "Até 10 m³",        "min_m3": 0,   "max_m3": 10,    "rate": 10.00, "order": 1},
    {"label": "10 a 15 m³",       "min_m3": 10,  "max_m3": 15,    "rate": 11.28, "order": 2},
    {"label": "15 a 20 m³",       "min_m3": 15,  "max_m3": 20,    "rate": 13.04, "order": 3},
    {"label": "20 a 30 m³",       "min_m3": 20,  "max_m3": 30,    "rate": 13.93, "order": 4},
    {"label": "30 a 40 m³",       "min_m3": 30,  "max_m3": 40,    "rate": 14.39, "order": 5},
    {"label": "40 a 50 m³",       "min_m3": 40,  "max_m3": 50,    "rate": 14.58, "order": 6},
    {"label": "50 a 90 m³",       "min_m3": 50,  "max_m3": 90,    "rate": 14.67, "order": 7},
    {"label": "90 a 150 m³",      "min_m3": 90,  "max_m3": 150,   "rate": 14.75, "order": 8},
    {"label": "Acima de 150 m³",  "min_m3": 150, "max_m3": 99999, "rate": 14.77, "order": 9},
]


async def seed_default_tariffs(db: AsyncSession) -> None:
    """Insere as tarifas padrão se a tabela estiver vazia."""
    result = await db.execute(select(TariffTier).limit(1))
    if result.scalar_one_or_none() is not None:
        return  # Já existem tarifas

    logger.info("Inserindo tarifas padrão...")
    for tier_data in DEFAULT_TIERS:
        tier = TariffTier(
            label=tier_data["label"],
            min_m3=tier_data["min_m3"],
            max_m3=tier_data["max_m3"],
            rate_per_m3=tier_data["rate"],
            minimum_charge=110.0,
            fixed_rate=100.0,
            sort_order=tier_data["order"],
            is_active=True,
        )
        db.add(tier)
    await db.commit()
    logger.info(f"Inseridas {len(DEFAULT_TIERS)} faixas de tarifa.")


async def calculate_billing(
    db: AsyncSession,
    consumption_m3: float,
) -> BillingCalculation:
    """
    Calcula o valor da fatura baseado no consumo.

    Regra: a tarifa da faixa é aplicada sobre TODO o consumo.
    O valor final é o máximo entre o bruto e a taxa mínima.

    Args:
        db: Sessão do banco
        consumption_m3: Consumo em metros cúbicos

    Returns:
        BillingCalculation com todos os detalhes do cálculo
    """
    # Busca todas as faixas ativas, ordenadas
    result = await db.execute(
        select(TariffTier)
        .where(TariffTier.is_active == True)  # noqa: E712
        .order_by(TariffTier.sort_order)
    )
    tiers = result.scalars().all()

    if not tiers:
        raise ValueError("Nenhuma faixa de tarifa configurada no sistema")

    # Encontra a faixa correta para o consumo
    selected_tier = tiers[-1]  # Default: última faixa (maior)
    for tier in tiers:
        if tier.min_m3 <= consumption_m3 < tier.max_m3:
            selected_tier = tier
            break

    # Calcula
    gross_amount = round(consumption_m3 * selected_tier.rate_per_m3, 2)
    minimum_charge = selected_tier.minimum_charge
    final_amount = max(gross_amount, minimum_charge)
    is_minimum_applied = gross_amount < minimum_charge

    logger.info(
        f"Cálculo: {consumption_m3:.2f}m³ × R${selected_tier.rate_per_m3}/m³ "
        f"= R${gross_amount:.2f} → final R${final_amount:.2f} "
        f"({'mínimo aplicado' if is_minimum_applied else 'valor bruto'})"
    )

    return BillingCalculation(
        consumption_m3=consumption_m3,
        tariff_tier_label=selected_tier.label,
        tariff_rate=selected_tier.rate_per_m3,
        gross_amount=gross_amount,
        minimum_charge=minimum_charge,
        final_amount=final_amount,
        is_minimum_applied=is_minimum_applied,
    )


async def get_fixed_rate(db: AsyncSession) -> float:
    """Retorna a taxa fixa para clientes sem hidrômetro."""
    result = await db.execute(
        select(TariffTier)
        .where(TariffTier.is_active == True)  # noqa: E712
        .order_by(TariffTier.sort_order)
        .limit(1)
    )
    tier = result.scalar_one_or_none()
    if tier:
        return tier.fixed_rate
    return 100.0  # Fallback
