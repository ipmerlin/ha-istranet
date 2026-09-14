"""Remove payment controls for business tariffs, retaining entity identities."""

from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

PAYMENT_KEYS = ("sbp_amount", "sbp_generate", "sbp_qr")


@callback
def sync_payment_registry(hass, entry):
    coordinator = entry.runtime_data
    registry = er.async_get(hass)
    unique_ids = {f"{coordinator.account_key}_{key}" for key in PAYMENT_KEYS}
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.platform != DOMAIN or entity.unique_id not in unique_ids:
            continue
        changes = {}
        if coordinator.payment.allowed:
            if entity.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
                changes["disabled_by"] = None
            if entity.hidden_by == er.RegistryEntryHider.INTEGRATION:
                changes["hidden_by"] = None
        else:
            if entity.disabled_by is None:
                changes["disabled_by"] = er.RegistryEntryDisabler.INTEGRATION
            if entity.hidden_by is None:
                changes["hidden_by"] = er.RegistryEntryHider.INTEGRATION
        if changes:
            registry.async_update_entity(entity.entity_id, **changes)


@callback
def watch_payment_eligibility(hass, entry):
    coordinator = entry.runtime_data
    allowed = coordinator.payment.allowed

    @callback
    def updated():
        nonlocal allowed
        if allowed == coordinator.payment.allowed:
            return
        allowed = coordinator.payment.allowed
        sync_payment_registry(hass, entry)
        hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))

    entry.async_on_unload(coordinator.async_add_listener(updated))
