"""On-demand QR state, retained only in memory."""

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .api import AuthenticationError, IstranetError, PaymentError
from .const import DOMAIN
from .sbp import render_qr, validate_amount


class SbpPayment:
    def __init__(self, hass, entry, client, account_key):
        self.hass, self.entry, self.client, self.account_key = hass, entry, client, account_key
        self.amount = 890
        self.qr = None
        self.created_at = None
        self.busy = False
        self.listeners = set()
        self._cancel_expiry = None
        self._closed = False

    @callback
    def subscribe(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    @callback
    def notify(self):
        for listener in tuple(self.listeners):
            listener()

    @callback
    def clear(self, _now=None):
        if self._cancel_expiry:
            self._cancel_expiry()
            self._cancel_expiry = None
        self.qr = None
        self.created_at = None
        self.notify()

    @callback
    def set_amount(self, value):
        if self.busy:
            raise ServiceValidationError("Дождитесь получения QR")
        try:
            amount = validate_amount(value)
        except PaymentError as err:
            raise ServiceValidationError("Введите целую сумму от 10 до 100000 ₽") from err
        if amount != self.amount:
            self.amount = amount
            self.clear()

    @callback
    def close(self):
        self._closed = True
        self.clear()

    async def async_generate(self):
        if self._closed:
            raise ServiceValidationError("Интеграция выгружена")
        if self.busy:
            raise ServiceValidationError("QR уже запрашивается")
        self.busy = True
        self.clear()
        try:
            url = await self.client.async_payment_url(self.amount)
            qr = await self.hass.async_add_executor_job(render_qr, url)
            if self._closed:
                return
            self.qr = qr
            self.created_at = dt_util.utcnow()
            # UI lifetime only: the bank determines the actual payment validity.
            self._cancel_expiry = async_call_later(self.hass, 15 * 60, self.clear)
        except AuthenticationError as err:
            self.entry.async_start_reauth(self.hass)
            raise HomeAssistantError("Проверьте данные входа Istranet") from err
        except IstranetError as err:
            raise HomeAssistantError("Не удалось получить QR СБП. Попробуйте позже") from err
        finally:
            self.busy = False
            self.notify()


class PaymentEntity:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def setup_payment(self, payment, key):
        self.payment = payment
        self._attr_unique_id = f"{payment.account_key}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, payment.account_key)})

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.payment.subscribe(self.async_write_ha_state))
