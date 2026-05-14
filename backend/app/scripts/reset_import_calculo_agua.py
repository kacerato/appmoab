"""Reset parcial e importacao da planilha Calculo Agua em PDF.

Uso:
  python -m app.scripts.reset_import_calculo_agua "C:\\path\\Calculo Agua (3).pdf" --dry-run
  python -m app.scripts.reset_import_calculo_agua "C:\\path\\Calculo Agua (3).pdf" --apply

Reseta somente a base operacional: clientes, hidrometros, leituras, faturas,
notificacoes e anexos. Preserva usuarios, tarifas, configuracoes e deducoes.
Importa apenas os clientes da tabela principal de leituras, sem adicionar
clientes antigos encontrados apenas no bloco de status.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select

from app.database import Base, async_session_factory, engine
from app.models.customer import Customer
from app.models.customer_attachment import CustomerAttachment
from app.models.hydrometer import Hydrometer
from app.models.invoice import Invoice
from app.models.notification import Notification
from app.models.reading import Reading
from app.models.kimi_memory import KimiVisionMemory
from app.models.user import User
from app.utils.schema_bootstrap import ensure_runtime_schema


MONEY_OR_NUMBER = r"\d{1,3}(?:\.\d{3})*,\d{3}|\d+,\d{3}|\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}"


@dataclass
class ImportedCustomer:
    name: str
    previous_reading: float | None
    current_reading: float | None
    consumption: float | None
    status: str = "active"


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _name_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", _normalize_name(value))
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return without_accents.upper()


def _clean_status_name(value: str) -> str:
    value = re.sub(r"^.*?12/2025", "", value)
    value = re.sub(r"^(?:ok|OK)+", "", value)
    value = re.sub(r"^(?:\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})", "", value)
    return _normalize_name(value)


def _parse_decimal(value: str) -> float:
    return float(value.replace(".", "").replace(",", "."))


def _placeholder_cpf(name: str) -> str:
    digest = hashlib.sha1(name.upper().encode("utf-8")).hexdigest()
    number = int(digest[:10], 16) % 10_000_000_000
    return f"9{number:010d}"


def _meter_code(index: int) -> str:
    return f"{index:06d}"


def extract_text(pdf_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Dependencia ausente: instale o requirements do backend antes de importar "
            "(pip install -r requirements.txt)."
        ) from exc

    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_status_block(text: str) -> dict[str, str]:
    first_table = text.find("Cliente Vcto")
    status_text = text[:first_table if first_table >= 0 else len(text)]
    statuses: dict[str, str] = {}
    pattern = re.compile(r"(.+?)(Instalado|Desligado|Cortado)", re.IGNORECASE)
    for match in pattern.finditer(status_text):
        name = _clean_status_name(match.group(1))
        status_word = match.group(2).lower()
        if not name or name.lower().startswith("nome do"):
            continue
        statuses[_name_key(name)] = "active" if status_word == "instalado" else "disconnected"
    return statuses


def parse_latest_readings(text: str) -> list[ImportedCustomer]:
    start = text.find("Cliente Vcto")
    if start < 0:
        raise ValueError("Nao encontrei a tabela 'Cliente Vcto' no PDF")
    next_table = text.find("Cliente Vcto", start + 20)
    table_text = text[start:next_table if next_table >= 0 else len(text)]

    rows: list[ImportedCustomer] = []
    row_re = re.compile(
        rf"(?P<name>.+?)\s+(?P<prev>{MONEY_OR_NUMBER})\s+(?P<curr>{MONEY_OR_NUMBER})\s+"
        rf"(?P<cons>{MONEY_OR_NUMBER})\s+(?P<value>\d{{1,3}}(?:\.\d{{3}})*,\d{{2}}|\d+,\d{{2}})"
    )
    for raw_line in table_text.splitlines():
        line = _normalize_name(raw_line)
        if not line or line.startswith("Cliente ") or line.startswith("POCO") or line.startswith("POÇO"):
            continue
        match = row_re.match(line)
        if not match:
            continue
        rows.append(
            ImportedCustomer(
                name=_normalize_name(match.group("name")),
                previous_reading=_parse_decimal(match.group("prev")),
                current_reading=_parse_decimal(match.group("curr")),
                consumption=_parse_decimal(match.group("cons")),
            )
        )
    return rows


async def reset_operational_data() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_runtime_schema(conn)

    async with async_session_factory() as db:
        for model in (
            KimiVisionMemory,
            Notification,
            Invoice,
            Reading,
            CustomerAttachment,
            Hydrometer,
            Customer,
        ):
            await db.execute(delete(model))
        await db.commit()


async def import_customers(customers: list[ImportedCustomer], dry_run: bool) -> None:
    async with async_session_factory() as db:
        user = (await db.execute(select(User).order_by(User.created_at).limit(1))).scalar_one_or_none()
        if not user:
            raise RuntimeError("Nao existe usuario no banco para vincular leituras importadas")

        captured_at = datetime.now(timezone.utc)
        for index, item in enumerate(customers, start=1):
            customer = Customer(
                name=item.name,
                cpf_cnpj=_placeholder_cpf(item.name),
                phone=None,
                email=None,
                address="Endereco nao informado",
                number="S/N",
                neighborhood="Nao informado",
                city="Moab",
                state="PA",
                zip_code="00000-000",
                due_day=10,
                has_hydrometer=True,
                status=item.status,
                notes="Importado do PDF Calculo Agua. Revisar endereco/telefone/CPF quando possivel.",
            )
            db.add(customer)
            await db.flush()

            current = item.current_reading or 0.0
            previous = item.previous_reading if item.previous_reading is not None else current
            hydrometer = Hydrometer(
                customer_id=customer.id,
                code=_meter_code(index),
                red_digits=3,
                black_digits=None,
                location_description="Importado do PDF Calculo Agua",
                last_reading_value=current,
                last_reading_date=captured_at,
                is_active=item.status == "active",
                disconnected_at=captured_at if item.status != "active" else None,
            )
            db.add(hydrometer)
            await db.flush()

            db.add(
                Reading(
                    hydrometer_id=hydrometer.id,
                    collaborator_id=user.id,
                    current_value=current,
                    previous_value=previous,
                    consumption=max(0.0, current - previous),
                    photo_url="imported/calculo_agua.pdf",
                    photo_extracted_code=hydrometer.code,
                    photo_extracted_value=current,
                    ocr_confidence=None,
                    latitude=None,
                    longitude=None,
                    captured_at=captured_at,
                    status="approved",
                    approved_by=user.id,
                    approved_at=captured_at,
                )
            )

        if dry_run:
            await db.rollback()
        else:
            await db.commit()


def apply_status_to_readings(readings: list[ImportedCustomer], statuses: dict[str, str]) -> list[ImportedCustomer]:
    merged = []
    for item in readings:
        item.status = statuses.get(_name_key(item.name), item.status)
        merged.append(item)
    return merged


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--apply", action="store_true", help="Executa reset e importacao de verdade")
    parser.add_argument("--dry-run", action="store_true", help="Apenas mostra o que seria importado")
    args = parser.parse_args()

    if not args.pdf.exists():
        raise FileNotFoundError(args.pdf)
    if not args.apply and not args.dry_run:
        raise SystemExit("Use --dry-run primeiro ou --apply para executar.")

    text = extract_text(args.pdf)
    readings = parse_latest_readings(text)
    statuses = parse_status_block(text)
    customers = apply_status_to_readings(readings, statuses)

    print(f"Clientes importados da tabela principal: {len(customers)}")
    for item in customers[:40]:
        print(f"- {item.name} | status={item.status} | anterior={item.previous_reading} | atual={item.current_reading}")

    if args.apply:
        await reset_operational_data()
        await import_customers(customers, dry_run=False)
        print("Reset e importacao concluidos.")
    else:
        print("Dry-run concluido. Nada foi alterado.")


if __name__ == "__main__":
    asyncio.run(main())
