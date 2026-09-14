"""One scheduled update for all entities."""

import logging
from datetime import timedelta
from hashlib import sha256

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthenticationError, IstranetError
from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .parser import normalize
from .payment import SbpPayment


def account_key(username):
    return sha256(username.strip().encode()).hexdigest()


class IstranetCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client):
        super().__init__(
            hass,
            logging.getLogger(__name__),
            config_entry=entry,
            name=DOMAIN,
            always_update=False,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            ),
        )
        self.client = client
        self.account_key = account_key(entry.data["username"])
        self.payment = SbpPayment(hass, entry, client, self.account_key)

    async def _async_update_data(self):
        try:
            account, tariffs = await self.client.async_fetch()
            data = normalize(account, tariffs)
            data["account_number"] = await self.client.async_account_number()
            return data
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed("Check Istranet credentials") from err
        except IstranetError as err:
            raise UpdateFailed(str(err)) from err
