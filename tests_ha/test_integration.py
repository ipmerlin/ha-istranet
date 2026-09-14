"""Tests using actual HA classes in Linux CI, with no live account."""

import asyncio
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.istranet import async_setup_entry, async_unload_entry
from custom_components.istranet.api import AuthenticationError, CannotConnect, InvalidResponse
from custom_components.istranet.config_flow import IstranetConfigFlow
from custom_components.istranet.coordinator import IstranetCoordinator, account_key
from custom_components.istranet.image import SbpImage
from custom_components.istranet.payment import SbpPayment
from custom_components.istranet.sensor import SENSORS, IstranetSensor


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_entry_uses_stable_identity(self):
        flow = IstranetConfigFlow()
        with (
            patch.object(flow, "_validate", AsyncMock()),
            patch.object(flow, "async_set_unique_id", AsyncMock()) as unique,
            patch.object(flow, "_abort_if_unique_id_configured"),
        ):
            result = await flow.async_step_user({"username": " 001 ", "password": "secret"})
        unique.assert_awaited_once_with(account_key("001"))
        self.assertEqual(result["data"], {"username": "001", "password": "secret"})

    async def test_flow_errors(self):
        for err, key in (
            (AuthenticationError(), "invalid_auth"),
            (CannotConnect(), "cannot_connect"),
            (InvalidResponse(), "invalid_response"),
        ):
            flow = IstranetConfigFlow()
            with (
                self.subTest(key=key),
                patch.object(flow, "_validate", AsyncMock(side_effect=err)),
                patch.object(flow, "async_show_form", return_value={}) as show,
            ):
                await flow.async_step_user({"username": "001", "password": "secret"})
                self.assertEqual(show.call_args.kwargs["errors"], {"base": key})

    async def test_reauth_checks_identity(self):
        flow = IstranetConfigFlow()
        entry = Mock(data={"username": "001"})
        with (
            patch.object(flow, "_get_reauth_entry", return_value=entry),
            patch.object(flow, "_validate", AsyncMock()),
            patch.object(flow, "async_set_unique_id", AsyncMock()),
            patch.object(flow, "_abort_if_unique_id_mismatch") as mismatch,
            patch.object(flow, "async_update_reload_and_abort", return_value={}) as update,
        ):
            await flow.async_step_reauth_confirm({"username": "001", "password": "new"})
        mismatch.assert_called_once()
        self.assertIs(update.call_args.args[0], entry)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_profile_keeps_balance(self):
        coordinator = SimpleNamespace(
            payment=Mock(),
            client=SimpleNamespace(
                async_fetch=AsyncMock(return_value=({"balance": "100"}, [])),
                async_account_number=AsyncMock(return_value=None),
            ),
        )
        data = await IstranetCoordinator._async_update_data(coordinator)
        self.assertEqual(data["balance"], 100)
        self.assertIsNone(data["account_number"])
        coordinator.client.async_account_number.return_value = "001234"
        data = await IstranetCoordinator._async_update_data(coordinator)
        self.assertEqual(data["account_number"], "001234")

    async def test_failed_setup_closes_session(self):
        session = Mock(close=AsyncMock())
        entry = Mock(data={"username": "001", "password": "secret"})
        coordinator = Mock(async_config_entry_first_refresh=AsyncMock(side_effect=CannotConnect))
        with (
            patch("custom_components.istranet.create_session", return_value=session),
            patch("custom_components.istranet.IstranetCoordinator", return_value=coordinator),
            self.assertRaises(CannotConnect),
        ):
            await async_setup_entry(Mock(), entry)
        session.close.assert_awaited_once()

    async def test_unload_closes_only_on_success(self):
        entry = Mock()
        entry.runtime_data.client.session.close = AsyncMock()
        hass = Mock()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
        self.assertFalse(await async_unload_entry(hass, entry))
        entry.runtime_data.client.session.close.assert_not_awaited()
        hass.config_entries.async_unload_platforms.return_value = True
        self.assertTrue(await async_unload_entry(hass, entry))
        entry.runtime_data.client.session.close.assert_awaited_once()

    async def test_coordinator_errors(self):
        coordinator = SimpleNamespace(client=SimpleNamespace(async_fetch=AsyncMock()))
        for error, expected in (
            (AuthenticationError(), ConfigEntryAuthFailed),
            (CannotConnect(), UpdateFailed),
        ):
            coordinator.client.async_fetch.side_effect = error
            with self.assertRaises(expected):
                await IstranetCoordinator._async_update_data(coordinator)


class SensorTests(unittest.TestCase):
    def test_account_number_is_text_and_unavailable_when_missing(self):
        coordinator = Mock(
            data={"account_number": "001234"}, account_key="stable-key", last_update_success=True
        )
        desc = next(d for d in SENSORS if d.key == "account_number")
        sensor = IstranetSensor(coordinator, desc)
        self.assertEqual(sensor.native_value, "001234")
        self.assertTrue(sensor.available)
        self.assertEqual(sensor.unique_id, "stable-key_account_number")
        self.assertIsNone(sensor.native_unit_of_measurement)
        coordinator.data = {"account_number": None}
        self.assertFalse(sensor.available)

    def test_zero_and_individual_unavailability(self):
        coordinator = Mock(
            data={"balance": 0, "tariff": None}, account_key="001", last_update_success=True
        )
        sensors = {d.key: IstranetSensor(coordinator, d) for d in SENSORS}
        self.assertEqual(sensors["balance"].native_value, 0)
        self.assertTrue(sensors["balance"].available)
        self.assertFalse(sensors["tariff"].available)
        coordinator.last_update_success = False
        self.assertFalse(sensors["balance"].available)


class PaymentTests(unittest.IsolatedAsyncioTestCase):
    def payment(self):
        hass = Mock(async_add_executor_job=AsyncMock(return_value=b"png"))
        client = Mock(async_payment_url=AsyncMock(return_value="https://qr.nspk.ru/TEST"))
        payment = SbpPayment(hass, Mock(), client, "001")
        payment.set_tariff("PRO")
        return payment

    async def test_business_tariff_blocks_actions_and_clears_qr(self):
        payment = self.payment()
        payment.qr = b"old"
        payment.set_tariff("PRO Юр")
        self.assertFalse(payment.allowed)
        self.assertIsNone(payment.qr)
        with self.assertRaises(ServiceValidationError):
            await payment.async_generate()
        with self.assertRaises(ServiceValidationError):
            payment.set_amount(1000)
        payment.client.async_payment_url.assert_not_awaited()
        payment.set_tariff(None)
        self.assertFalse(payment.allowed)
        payment.set_tariff("PRO")
        self.assertTrue(payment.allowed)

    async def test_tariff_changes_during_qr_request(self):
        payment = self.payment()

        async def changed(amount):
            payment.set_tariff("ЮР-100")
            return "https://qr.nspk.ru/TEST"

        payment.client.async_payment_url.side_effect = changed
        with patch("custom_components.istranet.payment.async_call_later") as timer:
            await payment.async_generate()
        self.assertIsNone(payment.qr)
        timer.assert_not_called()

    async def test_success_and_expiry_clear(self):
        payment = self.payment()
        with patch(
            "custom_components.istranet.payment.async_call_later", return_value=Mock()
        ) as later:
            await payment.async_generate()
        self.assertEqual(payment.qr, b"png")
        payment.client.async_payment_url.assert_awaited_once_with(890)
        later.call_args.args[2]()
        self.assertIsNone(payment.qr)
        self.assertIsNone(payment.created_at)

    async def test_edit_amount_clears_old_qr(self):
        payment = self.payment()
        payment.qr = b"old"
        payment.set_amount(1000)
        self.assertIsNone(payment.qr)
        payment.client.async_payment_url.assert_not_awaited()
        with self.assertRaises(ServiceValidationError):
            payment.set_amount(1.5)

    async def test_failure_clears_qr_and_auth_requests_reauth(self):
        payment = self.payment()
        for error in (CannotConnect(), AuthenticationError()):
            payment.qr = b"old"
            payment.client.async_payment_url.side_effect = error
            with self.assertRaises(HomeAssistantError):
                await payment.async_generate()
            self.assertIsNone(payment.qr)
            self.assertFalse(payment.busy)
        payment.entry.async_start_reauth.assert_called_once_with(payment.hass)

    async def test_concurrent_generation_and_amount_change_blocked(self):
        payment = self.payment()
        waiting = asyncio.Event()

        async def wait_for_url(amount):
            await waiting.wait()
            return "https://qr.nspk.ru/TEST"

        payment.client.async_payment_url.side_effect = wait_for_url
        with patch("custom_components.istranet.payment.async_call_later", return_value=Mock()):
            task = asyncio.create_task(payment.async_generate())
            await asyncio.sleep(0)
            with self.assertRaises(ServiceValidationError):
                await payment.async_generate()
            with self.assertRaises(ServiceValidationError):
                payment.set_amount(1000)
            waiting.set()
            await task
        payment.client.async_payment_url.assert_awaited_once()

    async def test_image_returns_only_current_qr(self):
        payment = self.payment()
        image = SbpImage(Mock(), payment)
        self.assertFalse(image.available)
        payment.qr, payment.created_at = b"png", datetime.now(UTC)
        self.assertTrue(image.available)
        self.assertEqual(await image.async_image(), b"png")
        payment.clear()
        self.assertIsNone(await image.async_image())
