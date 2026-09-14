"""Asynchronous client for the API used by the supplied AppDaemon script."""

import asyncio
from uuid import uuid4

import aiohttp

from .const import API_URL


class IstranetError(Exception):
    """Base error, containing no response bodies or credentials."""


class AuthenticationError(IstranetError):
    """Credentials rejected."""


class CannotConnect(IstranetError):
    """Network or server failure."""


class InvalidResponse(IstranetError):
    """Unexpected API payload."""


class PaymentError(IstranetError):
    """Cannot generate a payment QR."""


class IstranetClient:
    def __init__(self, session, username, password):
        self.session = session
        self.username = username
        self._password = password
        self._token = None
        self._lock = asyncio.Lock()

    async def _request(self, method, path, *, authenticated=True, payload=None, request_id=None):
        headers = {
            "X-User-Agent": "Istranet/104 (web)",
            "Accept": "application/json",
        }
        if authenticated and self._token:
            headers["Authorization"] = f"Token {self._token}"
        if request_id:
            headers["Idempotency-Key"] = request_id
        try:
            async with self.session.request(
                method,
                f"{API_URL}/{path}",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=False,
            ) as response:
                if response.status == 401:
                    raise AuthenticationError("Authentication rejected")
                if response.status >= 500 or response.status == 429:
                    raise CannotConnect("Istranet temporarily unavailable")
                if not 200 <= response.status < 300:
                    raise InvalidResponse(f"Unexpected HTTP status {response.status}")
                try:
                    return await response.json()
                except (ValueError, aiohttp.ContentTypeError) as from_error:
                    raise InvalidResponse("Expected a JSON response") from from_error
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect("Unable to reach Istranet") from err

    async def _authenticate(self):
        self._token = None
        result = await self._request(
            "POST",
            "auth/signin",
            authenticated=False,
            payload={"login": self.username, "password": self._password},
        )
        token = result.get("token") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise InvalidResponse("Authentication response contains no token")
        self._token = token

    async def _get(self, path):
        try:
            return await self._request("GET", path)
        except AuthenticationError:
            await self._authenticate()
            try:
                return await self._request("GET", path)
            except AuthenticationError:
                self._token = None
                raise

    async def async_validate(self):
        """Validate credentials and account shape without requiring tariff availability."""
        async with self._lock:
            await self._authenticate()
            return await self._account()

    async def _account(self):
        account = await self._get("account")
        if not isinstance(account, dict) or not any(
            key in account for key in ("balance", "enabled", "block", "ips", "require")
        ):
            raise InvalidResponse("Unexpected account structure")
        return account

    async def async_fetch(self):
        """Allow the account sensors to update when the tariff endpoint fails."""
        async with self._lock:
            if not self._token:
                await self._authenticate()
            account = await self._account()
            try:
                tariffs = await self._get("tariffs")
                if not isinstance(tariffs, (dict, list)):
                    raise InvalidResponse("Unexpected tariff structure")
            except (CannotConnect, InvalidResponse):
                tariffs = None
            return account, tariffs

    async def async_payment_url(self, amount):
        """Create one SBP link on explicit demand, never during regular polling."""
        from .sbp import validate_amount, validate_url

        amount = validate_amount(amount)
        async with self._lock:
            if not self._token:
                await self._authenticate()
            methods = await self._get("payment")
            if not isinstance(methods, dict) or not isinstance(methods.get("types"), list):
                raise PaymentError("Unexpected payment methods response")
            if not any(
                isinstance(item, dict) and item.get("type") == "qr" for item in methods["types"]
            ):
                raise PaymentError("SBP is unavailable for this account")
            request_id = str(uuid4())
            kwargs = {"payload": {"type": "qr", "amount": amount}, "request_id": request_id}
            try:
                result = await self._request("POST", "payment", **kwargs)
            except AuthenticationError:
                await self._authenticate()
                # Reuse the idempotency key for the same logical request.
                result = await self._request("POST", "payment", **kwargs)
            return validate_url(result.get("url") if isinstance(result, dict) else None)
