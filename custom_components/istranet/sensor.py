"""Account and tariff sensors."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory

from .entity import IstranetEntity

PARALLEL_UPDATES = 0


def description(key, icon, **kwargs):
    return SensorEntityDescription(key=key, translation_key=key, icon=icon, **kwargs)


MONEY = {
    "native_unit_of_measurement": "RUB",
    "device_class": SensorDeviceClass.MONETARY,
}
DIAGNOSTIC = {"entity_category": EntityCategory.DIAGNOSTIC}
SENSORS = (
    description("account_number", "mdi:identifier"),
    description("balance", "mdi:wallet", **MONEY),
    description("require", "mdi:cash-clock", **MONEY),
    description(
        "account_status",
        "mdi:check-network",
        device_class=SensorDeviceClass.ENUM,
        options=["active", "blocked", "disabled"],
    ),
    description("ip", "mdi:ip-network", **DIAGNOSTIC),
    description("gateway", "mdi:router-network", **DIAGNOSTIC),
    description("dns1", "mdi:dns", **DIAGNOSTIC),
    description("dns2", "mdi:dns", **DIAGNOSTIC),
    description("tariff", "mdi:tag"),
    description(
        "tariff_price",
        "mdi:currency-rub",
        **MONEY,
        entity_registry_enabled_default=False,
    ),
    description("subscription_fee", "mdi:cash-multiple", **MONEY),
    description(
        "tariff_speed",
        "mdi:speedometer",
        native_unit_of_measurement="Mbit/s",
        device_class=SensorDeviceClass.DATA_RATE,
    ),
    description("next_payment", "mdi:calendar-clock", device_class=SensorDeviceClass.DATE),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(IstranetSensor(entry.runtime_data, desc) for desc in SENSORS)


class IstranetSensor(IstranetEntity, SensorEntity):
    def __init__(self, coordinator, desc):
        super().__init__(coordinator, desc.key)
        self.entity_description = desc

    @property
    def available(self):
        return super().available and self.native_value is not None

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self.entity_description.key)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        if self.entity_description.key == "account_status":
            return {"enabled": data.get("enabled"), "blocked": data.get("blocked")}
        if self.entity_description.key == "ip":
            return {"mask": data.get("mask")}
        return None
