from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hydrometer import Hydrometer


def normalize_hydrometer_code(value: str | None) -> str | None:
    if value is None:
        return None
    digits = "".join(char for char in value if char.isdigit())
    return digits or None


def format_hydrometer_code(number: int) -> str:
    return f"{number:06d}"


async def _list_hydrometer_codes(db: AsyncSession) -> list[str]:
    result = await db.execute(select(Hydrometer.code))
    return [code for code in result.scalars().all() if code]


async def get_next_hydrometer_code(
    db: AsyncSession,
    reserved_codes: set[str] | None = None,
) -> str:
    reserved_codes = reserved_codes or set()
    existing_codes = set(await _list_hydrometer_codes(db)) | reserved_codes
    numeric_values = [int(code) for code in existing_codes if code.isdigit()]
    next_value = (max(numeric_values) if numeric_values else 0) + 1

    candidate = format_hydrometer_code(next_value)
    while candidate in existing_codes:
        next_value += 1
        candidate = format_hydrometer_code(next_value)
    return candidate


async def ensure_numeric_hydrometer_codes(db: AsyncSession) -> int:
    result = await db.execute(select(Hydrometer).order_by(Hydrometer.created_at, Hydrometer.id))
    hydrometers = list(result.scalars().all())

    used_codes = {hydrometer.code for hydrometer in hydrometers if hydrometer.code and hydrometer.code.isdigit()}
    numeric_values = [int(code) for code in used_codes]
    next_value = max(numeric_values) if numeric_values else 0
    updated_count = 0

    for hydrometer in hydrometers:
        if hydrometer.code and hydrometer.code.isdigit():
            continue

        next_value += 1
        new_code = format_hydrometer_code(next_value)
        while new_code in used_codes:
            next_value += 1
            new_code = format_hydrometer_code(next_value)

        hydrometer.code = new_code
        used_codes.add(new_code)
        updated_count += 1

    if updated_count:
        await db.flush()

    return updated_count


async def assign_numeric_code_if_needed(
    db: AsyncSession,
    preferred_code: str | None = None,
    current_hydrometer_id: uuid.UUID | None = None,
) -> str:
    normalized = normalize_hydrometer_code(preferred_code)
    if normalized:
        result = await db.execute(select(Hydrometer).where(Hydrometer.code == normalized))
        existing = result.scalar_one_or_none()
        if existing and existing.id != current_hydrometer_id:
            raise ValueError("Este codigo ja esta em uso")
        return normalized

    return await get_next_hydrometer_code(db)
