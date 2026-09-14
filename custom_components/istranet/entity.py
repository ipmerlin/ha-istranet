"""Common device identity."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BASE_URL, DOMAIN


class IstranetEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.account_key}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.account_key)},
            name=f"Istranet {coordinator.client.username}",
            manufacturer="Istranet",
            model="Личный кабинет",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=BASE_URL,
        )
