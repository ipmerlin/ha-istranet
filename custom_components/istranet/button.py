"""Request an update from the device page or an automation."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .entity import IstranetEntity
from .payment import PaymentEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [IstranetRefreshButton(entry.runtime_data), SbpGenerateButton(entry.runtime_data.payment)]
    )


class IstranetRefreshButton(IstranetEntity, ButtonEntity):
    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "refresh")

    @property
    def available(self):
        return True

    async def async_press(self):
        await self.coordinator.async_request_refresh()


class SbpGenerateButton(PaymentEntity, ButtonEntity):
    _attr_icon = "mdi:qrcode-plus"

    def __init__(self, payment):
        self.setup_payment(payment, "sbp_generate")

    @property
    def available(self):
        return not self.payment.busy

    async def async_press(self):
        await self.payment.async_generate()
