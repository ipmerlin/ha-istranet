"""Payment controls must disappear for business accounts without losing user settings."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.helpers import entity_registry as er

from custom_components.istranet.button import async_setup_entry as setup_buttons
from custom_components.istranet.eligibility import sync_payment_registry, watch_payment_eligibility
from custom_components.istranet.image import async_setup_entry as setup_images
from custom_components.istranet.number import async_setup_entry as setup_numbers


class RegistryTests(unittest.TestCase):
    def entry(self, allowed):
        return SimpleNamespace(
            entry_id="entry",
            runtime_data=SimpleNamespace(
                account_key="key", payment=SimpleNamespace(allowed=allowed)
            ),
        )

    def test_business_disables_and_hides_only_payment_entities(self):
        entities = [
            SimpleNamespace(
                entity_id="number.pay",
                platform="istranet",
                unique_id="key_sbp_amount",
                disabled_by=None,
                hidden_by=None,
            ),
            SimpleNamespace(
                entity_id="sensor.balance",
                platform="istranet",
                unique_id="key_balance",
                disabled_by=None,
                hidden_by=None,
            ),
        ]
        registry = Mock()
        with (
            patch("custom_components.istranet.eligibility.er.async_get", return_value=registry),
            patch(
                "custom_components.istranet.eligibility.er.async_entries_for_config_entry",
                return_value=entities,
            ),
        ):
            sync_payment_registry(Mock(), self.entry(False))
        registry.async_update_entity.assert_called_once_with(
            "number.pay",
            disabled_by=er.RegistryEntryDisabler.INTEGRATION,
            hidden_by=er.RegistryEntryHider.INTEGRATION,
        )

    def test_residential_restores_only_integration_settings(self):
        entities = [
            SimpleNamespace(
                entity_id="number.pay",
                platform="istranet",
                unique_id="key_sbp_amount",
                disabled_by=er.RegistryEntryDisabler.USER,
                hidden_by=er.RegistryEntryHider.USER,
            ),
            SimpleNamespace(
                entity_id="button.pay",
                platform="istranet",
                unique_id="key_sbp_generate",
                disabled_by=er.RegistryEntryDisabler.INTEGRATION,
                hidden_by=er.RegistryEntryHider.INTEGRATION,
            ),
        ]
        registry = Mock()
        with (
            patch("custom_components.istranet.eligibility.er.async_get", return_value=registry),
            patch(
                "custom_components.istranet.eligibility.er.async_entries_for_config_entry",
                return_value=entities,
            ),
        ):
            sync_payment_registry(Mock(), self.entry(True))
        registry.async_update_entity.assert_called_once_with(
            "button.pay", disabled_by=None, hidden_by=None
        )


class PlatformTests(unittest.IsolatedAsyncioTestCase):
    async def test_business_creates_only_refresh_button(self):
        entry = Mock()
        entry.runtime_data.payment.allowed = False
        for setup in (setup_numbers, setup_images):
            add = Mock()
            await setup(Mock(), entry, add)
            add.assert_not_called()
        add = Mock()
        await setup_buttons(Mock(), entry, add)
        self.assertEqual(len(add.call_args.args[0]), 1)
        self.assertEqual(add.call_args.args[0][0].translation_key, "refresh")

    async def test_tariff_change_reloads_once(self):
        entry = Mock()
        entry.runtime_data.payment.allowed = True
        hass = Mock()
        # Close the scheduled coroutine instead of running a real HA reload.
        hass.config_entries.async_reload = AsyncMock()
        hass.async_create_task.side_effect = lambda coro: coro.close()
        watch_payment_eligibility(hass, entry)
        callback = entry.runtime_data.async_add_listener.call_args.args[0]
        with patch("custom_components.istranet.eligibility.sync_payment_registry") as sync:
            callback()
            sync.assert_not_called()
            entry.runtime_data.payment.allowed = False
            callback()
            callback()
            sync.assert_called_once_with(hass, entry)
        hass.async_create_task.assert_called_once()
