"""Allowlisted diagnostics without credentials, balances, IPs or raw API responses."""


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "last_update_success": coordinator.last_update_success,
        "update_interval_minutes": coordinator.update_interval.total_seconds() / 60,
        "available_fields": sorted(
            key for key, value in (coordinator.data or {}).items() if value is not None
        ),
    }
