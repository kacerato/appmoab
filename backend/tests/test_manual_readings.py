"""Contratos e fluxo HTTP com PostgreSQL isolado; nunca usa o banco de produção.

MANUAL_READING_TEST_DATABASE_URL deve apontar para PostgreSQL local descartável.
Somente a Efí é simulada: cálculos, leituras, ciclos, faturas e rotas são reais.
"""

import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

import app.models  # registra todas as tabelas e relacionamentos
from app.database import Base, get_db
from app.models import Customer, Hydrometer, Invoice, InvoiceEvent, Reading, ReadingCycle, SystemSetting, TariffTier, User
from app.routers import customers, invoices, readings
from app.schemas.reading import ManualReadingCreate
from app.services.billing import DEFAULT_TIERS
from app.services.reading_cycles import create_cycle, next_reference_month
from app.utils.security import get_current_user
from app.utils.storage import build_public_upload_url


class ManualReadingContractTest(unittest.TestCase):
    def test_reason_nonfinite_values_and_photo_validation(self):
        payload = dict(hydrometer_id=uuid4(), cycle_id=uuid4(), expected_previous_value=120,
                       current_value=135, reading_date="2026-10-01", reason="Cliente informou")
        for invalid in [float("nan"), float("inf"), -1]:
            with self.assertRaises(ValidationError):
                ManualReadingCreate(**{**payload, "current_value": invalid})
        with self.assertRaises(ValidationError):
            ManualReadingCreate(**{**payload, "reason": "     "})
        with self.assertRaises(HTTPException):
            readings._save_manual_photo("data:image/png;base64,bm90LWEtcGhvdG8=")
        with self.assertRaises(HTTPException):
            readings._save_manual_photo("data:text/html;base64,PGgxPnRlc3Q8L2gxPg==")
        self.assertEqual(build_public_upload_url(""), "")


@unittest.skipUnless(os.getenv("MANUAL_READING_TEST_DATABASE_URL"), "PostgreSQL local de teste não configurado")
class ManualReadingPostgresTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = os.environ["MANUAL_READING_TEST_DATABASE_URL"]
        if "@127.0.0.1:" not in url and "@localhost:" not in url:
            raise RuntimeError("Os testes exigem um banco local descartável")
        self.schema = "manual_test_" + uuid4().hex
        self.engine = create_async_engine(url, connect_args={"server_settings": {"search_path": self.schema + ",public"}})
        async with self.engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.today = datetime.now(readings.CUSTOMER_TIMEZONE).date()
        self.baseline_date = self.today - timedelta(days=65)
        self.reference = (self.today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        self.admin_id, self.customer_id, self.meter_id, self.base_id = [uuid4() for _ in range(4)]
        async with self.sessions() as db:
            user = User(id=self.admin_id, name="Gestor de teste", email=f"{uuid4()}@example.com", password_hash="test", role="admin")
            customer = Customer(id=self.customer_id, name="Cliente de teste", cpf_cnpj="00000000000", address="Rua de teste", neighborhood="Teste", city="Teste", state="CE", zip_code="60000000", due_day=10, status="active", has_hydrometer=True)
            meter = Hydrometer(id=self.meter_id, customer=customer, code="000001", last_reading_value=120, last_reading_date=datetime.combine(self.baseline_date, datetime.min.time(), tzinfo=readings.CUSTOMER_TIMEZONE), black_digits=4, red_digits=3, is_active=True, location_required=True)
            base = Reading(id=self.base_id, hydrometer=meter, collaborator_id=self.admin_id, current_value=120, previous_value=110, consumption=10, photo_url="", captured_at=meter.last_reading_date, reading_kind="water", reference_month=self.baseline_date.strftime("%Y-%m"), status="approved")
            db.add_all([user, customer, meter, base, SystemSetting(id=1, auto_send_invoice_on_approval=False, route_window_enabled=False)])
            for tier in DEFAULT_TIERS:
                db.add(TariffTier(label=tier["label"], min_m3=tier["min_m3"], max_m3=tier["max_m3"], rate_per_m3=tier["rate"], minimum_charge=110, fixed_rate=100, sort_order=tier["order"], is_active=True))
            await db.flush()
            cycle = await create_cycle(db, meter, reference=self.reference, cycle_type="water")
            self.cycle_id = cycle.id
            await db.commit()
        self.user = user
        app = FastAPI()
        app.include_router(readings.router, prefix="/api")
        app.include_router(invoices.router, prefix="/api")
        app.include_router(customers.router, prefix="/api")

        async def database():
            async with self.sessions() as db:
                try:
                    yield db
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise

        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.app = app
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local.test")
        self.provider = patch.object(readings.efi_service, "emitir_cobranca", AsyncMock(return_value={"charge_id": "test-charge", "status": "waiting", "payment_url": "https://example.invalid/test"}))
        self.emit = self.provider.start()
        self.cancel_patch = patch.object(readings.efi_service, "cancelar_cobranca", AsyncMock(return_value={"status": "canceled"}))
        self.cancel_patch.start()

    async def asyncTearDown(self):
        self.provider.stop()
        self.cancel_patch.stop()
        await self.client.aclose()
        async with self.engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.engine.dispose()

    def payload(self, **changes):
        return {"hydrometer_id": str(self.meter_id), "cycle_id": str(self.cycle_id),
                "expected_previous_value": 120, "current_value": 135,
                "reading_date": (self.today - timedelta(days=2)).isoformat(),
                "reason": "Leitura informada pelo cliente por telefone", **changes}

    async def register(self, **changes):
        payload = self.payload(**changes)
        preview = await self.client.post("/api/readings/manual/preview", json=payload)
        self.assertEqual(preview.status_code, 200, preview.text)
        response = await self.client.post("/api/readings/manual", json={**payload, "expected_amount": preview.json()["amount"]})
        return response

    async def test_records_history_tariffs_route_and_next_reading_base(self):
        before = (await self.client.get("/api/customers/route-tasks")).json()["items"]
        self.assertIn(str(self.cycle_id), [item["id"] for item in before])
        response = await self.register()
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(result["consumption_m3"], 15)
        self.assertEqual(result["amount"], 195.6)
        self.assertEqual(result["boleto_status"], "sent")
        history = (await self.client.get(f"/api/readings?customer_id={self.customer_id}&status=approved")).json()["items"]
        self.assertEqual(len(history), 2)
        new = next(item for item in history if item["id"] == result["reading_id"])
        self.assertEqual(new["photo_url"], "")
        self.assertEqual(new["previous_value"], 120)
        self.assertEqual(new["location_status"], "manual_dashboard")
        self.assertEqual(new["approved_by"], str(self.admin_id))
        self.assertIn("manual_customer_report", [flag["code"] for flag in new["validation_flags"]])
        after = (await self.client.get("/api/customers/route-tasks")).json()["items"]
        self.assertNotIn(str(self.cycle_id), [item["id"] for item in after])
        self.assertEqual(after[0]["hydrometer"]["last_reading_value"], 135)
        async with self.sessions() as db:
            base = await db.get(Reading, self.base_id)
            cycle = await db.get(ReadingCycle, self.cycle_id)
            self.assertEqual(base.current_value, 120)
            self.assertEqual(cycle.status, "invoiced")
            event = (await db.execute(select(InvoiceEvent).where(InvoiceEvent.event_type == "invoice_created_from_reading"))).scalar_one()
            self.assertEqual(event.payload["source"], "manual_customer_report")
        context = (await self.client.get(f"/api/readings/manual-context?hydrometer_id={self.meter_id}")).json()
        next_result = await self.register(cycle_id=context["cycle_id"], expected_previous_value=135, current_value=150, reading_date=(self.today - timedelta(days=1)).isoformat())
        self.assertEqual(next_result.status_code, 201, next_result.text)
        self.assertEqual(next_result.json()["consumption_m3"], 15)

    async def test_concurrent_double_click_creates_only_one_invoice(self):
        preview = (await self.client.post("/api/readings/manual/preview", json=self.payload())).json()
        payload = self.payload(expected_amount=preview["amount"])
        results = await asyncio.gather(*[self.client.post("/api/readings/manual", json=payload) for _ in range(2)])
        self.assertEqual(sorted(result.status_code for result in results), [201, 409])
        self.assertEqual(self.emit.await_count, 1)
        async with self.sessions() as db:
            self.assertEqual((await db.execute(select(func.count()).select_from(Invoice))).scalar(), 1)
            self.assertEqual((await db.execute(select(func.count()).select_from(Reading))).scalar(), 2)

    async def test_provider_failure_is_persisted_and_retry_uses_same_invoice(self):
        self.emit.side_effect = RuntimeError("Falha de teste Efí")
        response = await self.register()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["boleto_status"], "pending")
        invoice_id = response.json()["invoice_id"]
        async with self.sessions() as db:
            self.assertEqual((await db.get(Hydrometer, self.meter_id)).last_reading_value, 135)
            self.assertEqual((await db.get(ReadingCycle, self.cycle_id)).status, "invoiced")
        self.emit.side_effect = None
        retries = await asyncio.gather(*[self.client.post(f"/api/invoices/{invoice_id}/emit-boleto") for _ in range(2)])
        self.assertEqual(sorted(item.status_code for item in retries), [200, 400])
        retry = next(item for item in retries if item.status_code == 200)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["id"], invoice_id)
        self.assertEqual(retry.json()["status"], "sent")
        self.assertEqual(self.emit.await_count, 2)  # uma falha inicial e uma emissão
        async with self.sessions() as db:
            self.assertEqual((await db.execute(select(func.count()).select_from(Invoice))).scalar(), 1)

    async def test_pending_capture_blocks_manual_reading(self):
        async with self.sessions() as db:
            db.add(Reading(hydrometer_id=self.meter_id, collaborator_id=self.admin_id, cycle_id=self.cycle_id, previous_value=120, photo_url="", captured_at=datetime.now(timezone.utc), status="pending"))
            await db.commit()
        context = await self.client.get(f"/api/readings/manual-context?hydrometer_id={self.meter_id}")
        self.assertEqual(context.status_code, 409)
        response = await self.client.post("/api/readings/manual", json=self.payload(expected_amount=195.6))
        self.assertEqual(response.status_code, 409)
        self.emit.assert_not_awaited()

    async def test_reversing_manual_reading_restores_base_and_allows_replacement(self):
        registered = (await self.register()).json()
        cancelled = await self.client.post(f"/api/invoices/{registered['invoice_id']}/cancel", json={"preserve_reading": False, "reason": "Cliente corrigiu o número informado"})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Hydrometer, self.meter_id)).last_reading_value, 120)
            self.assertEqual((await db.get(Reading, registered["reading_id"])).status, "rejected")
            self.assertEqual((await db.get(ReadingCycle, self.cycle_id)).status, "recapture_required")
        replacement = await self.register(current_value=132)
        self.assertEqual(replacement.status_code, 201, replacement.text)
        self.assertEqual(replacement.json()["consumption_m3"], 12)

    async def test_later_reading_and_paid_invoice_prevent_unsafe_reversal(self):
        first = (await self.register()).json()
        context = (await self.client.get(f"/api/readings/manual-context?hydrometer_id={self.meter_id}")).json()
        second = (await self.register(cycle_id=context["cycle_id"], expected_previous_value=135, current_value=150, reading_date=(self.today - timedelta(days=1)).isoformat())).json()
        blocked = await self.client.post(f"/api/invoices/{first['invoice_id']}/cancel", json={"preserve_reading": False})
        self.assertEqual(blocked.status_code, 409, blocked.text)
        async with self.sessions() as db:
            invoice = await db.get(Invoice, second["invoice_id"])
            invoice.status = "paid"
            await db.commit()
        paid = await self.client.post(f"/api/invoices/{second['invoice_id']}/cancel", json={"preserve_reading": False})
        self.assertEqual(paid.status_code, 400)

    async def test_invalid_dates_regression_and_high_consumption(self):
        for changes in [{"current_value": 119}, {"current_value": 10000}, {"reading_date": self.baseline_date.isoformat()}, {"reading_date": (self.today + timedelta(days=1)).isoformat()}]:
            response = await self.client.post("/api/readings/manual/preview", json=self.payload(**changes))
            self.assertIn(response.status_code, [400, 422], response.text)
        preview = await self.client.post("/api/readings/manual/preview", json=self.payload(current_value=200))
        self.assertTrue(preview.json()["high_consumption"])
        response = await self.client.post("/api/readings/manual", json=self.payload(current_value=200, expected_amount=preview.json()["amount"]))
        self.assertEqual(response.status_code, 422)
        self.emit.assert_not_awaited()
        confirmed = await self.register(current_value=200, acknowledge_high_consumption=True)
        self.assertEqual(confirmed.status_code, 201, confirmed.text)

    async def test_preview_changes_and_non_admin_cannot_confirm(self):
        response = await self.client.post("/api/readings/manual", json=self.payload(expected_amount=0))
        self.assertEqual(response.status_code, 409)
        response = await self.client.post("/api/readings/manual/preview", json=self.payload(expected_previous_value=121))
        self.assertEqual(response.status_code, 409)
        self.user.role = "collaborator"
        for path in ["/api/readings/manual", "/api/readings/manual/preview"]:
            self.assertEqual((await self.client.post(path, json=self.payload())).status_code, 403)
        self.assertEqual((await self.client.get(f"/api/readings/manual-context?hydrometer_id={self.meter_id}")).status_code, 403)

    async def test_without_baseline_or_inactive_meter_cannot_register(self):
        async with self.sessions() as db:
            (await db.get(Reading, self.base_id)).status = "rejected"
            await db.commit()
        response = await self.client.get(f"/api/readings/manual-context?hydrometer_id={self.meter_id}")
        self.assertEqual(response.status_code, 409)
        async with self.sessions() as db:
            (await db.get(Hydrometer, self.meter_id)).is_active = False
            await db.commit()
        response = await self.client.post("/api/readings/manual", json=self.payload(expected_amount=195.6))
        self.assertEqual(response.status_code, 409)
        self.emit.assert_not_awaited()

    async def test_rollover_preserves_real_consumption_and_updates_base(self):
        async with self.sessions() as db:
            (await db.get(Hydrometer, self.meter_id)).last_reading_value = 9990
            (await db.get(Reading, self.base_id)).current_value = 9990
            await db.commit()
        response = await self.register(current_value=5, expected_previous_value=9990)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["consumption_m3"], 15)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Hydrometer, self.meter_id)).last_reading_value, 5)

    async def test_database_failure_rolls_back_reading_invoice_base_and_cycle(self):
        with patch.object(readings, "advance_after_approval", AsyncMock(side_effect=RuntimeError("Falha no ciclo seguinte"))):
            with self.assertRaisesRegex(RuntimeError, "Falha no ciclo seguinte"):
                await self.register()
        self.emit.assert_not_awaited()
        async with self.sessions() as db:
            self.assertEqual((await db.execute(select(func.count()).select_from(Reading))).scalar(), 1)
            self.assertEqual((await db.execute(select(func.count()).select_from(Invoice))).scalar(), 0)
            self.assertEqual((await db.get(Hydrometer, self.meter_id)).last_reading_value, 120)
            self.assertEqual((await db.get(ReadingCycle, self.cycle_id)).status, "open")
