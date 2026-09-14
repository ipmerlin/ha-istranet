"""Separate cookie-free sessions for each account."""

from aiohttp import DummyCookieJar
from homeassistant.helpers.aiohttp_client import async_create_clientsession


def create_session(hass):
    return async_create_clientsession(hass, auto_cleanup=False, cookie_jar=DummyCookieJar())
