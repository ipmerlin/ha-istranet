"""Offline API contract and parsing regression tests based on the supplied script."""

import importlib
import sys
import types
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import aiohttp

# Load the pure client without importing Home Assistant on Windows.
package = types.ModuleType("istranet_test")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/istranet")]
sys.modules[package.__name__] = package
api = importlib.import_module("istranet_test.api")
parser = importlib.import_module("istranet_test.parser")


class Response:
    def __init__(self, status=200, data=None, error=None):
        self.status, self.data, self.error = status, data, error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        if self.error:
            raise self.error
        return self.data


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_id_preserves_leading_zeroes(self):
        session = Session(Response(data={"id": "001234", "login": "different-login"}))
        client = api.IstranetClient(session, "login", "secret")
        client._token = "token"
        self.assertEqual(await client.async_account_number(), "001234")
        self.assertTrue(session.calls[0][1].endswith("/profile"))

    async def test_profile_failure_is_optional(self):
        for response in (Response(503), Response(403), TimeoutError(), Response(data=[])):
            client = api.IstranetClient(Session(response), "a", "b")
            client._token = "token"
            self.assertIsNone(await client.async_account_number())

    async def test_profile_reauth(self):
        session = Session(
            Response(401), Response(data={"token": "new"}), Response(data={"id": 1234})
        )
        client = api.IstranetClient(session, "a", "b")
        client._token = "old"
        self.assertEqual(await client.async_account_number(), "1234")

    async def test_full_fetch_and_token_is_per_request(self):
        session = Session(
            Response(data={"token": "private-token"}),
            Response(data={"balance": "12"}),
            Response(data=[]),
        )
        client = api.IstranetClient(session, "001", "secret")
        self.assertEqual(await client.async_fetch(), ({"balance": "12"}, []))
        self.assertEqual(session.calls[0][2]["json"], {"login": "001", "password": "secret"})
        self.assertNotIn("Authorization", session.calls[0][2]["headers"])
        self.assertEqual(session.calls[1][2]["headers"]["Authorization"], "Token private-token")
        self.assertFalse(session.calls[0][2]["allow_redirects"])

    async def test_expired_token_reauthenticates_once(self):
        session = Session(
            Response(401),
            Response(data={"token": "new"}),
            Response(data={"balance": 0}),
            Response(data=[]),
        )
        client = api.IstranetClient(session, "001", "secret")
        client._token = "old"
        await client.async_fetch()
        self.assertEqual(client._token, "new")
        self.assertEqual(len(session.calls), 4)

    async def test_repeated_unauthorized_does_not_loop(self):
        session = Session(Response(401), Response(data={"token": "new"}), Response(401))
        client = api.IstranetClient(session, "001", "secret")
        client._token = "old"
        with self.assertRaises(api.AuthenticationError):
            await client.async_fetch()
        self.assertIsNone(client._token)
        self.assertEqual(len(session.calls), 3)

    async def test_tariff_failure_preserves_account(self):
        session = Session(
            Response(data={"token": "new"}), Response(data={"balance": 0}), Response(503)
        )
        self.assertEqual(
            await api.IstranetClient(session, "a", "b").async_fetch(), ({"balance": 0}, None)
        )

    async def test_account_error_payload_rejected(self):
        session = Session(Response(data={"token": "new"}), Response(data={"error": "bad"}))
        with self.assertRaises(api.InvalidResponse):
            await api.IstranetClient(session, "a", "b").async_fetch()

    async def test_invalid_json_and_redirect(self):
        for response in (Response(error=ValueError("sensitive body")), Response(302)):
            with self.subTest(response=response), self.assertRaises(api.InvalidResponse):
                await api.IstranetClient(Session(response), "a", "b").async_validate()

    async def test_network_and_rate_limit(self):
        for response in (TimeoutError(), aiohttp.ClientConnectionError(), Response(429)):
            with self.subTest(response=response), self.assertRaises(api.CannotConnect):
                await api.IstranetClient(Session(response), "a", "b").async_validate()

    async def test_missing_token_and_bad_credentials(self):
        with self.assertRaises(api.InvalidResponse):
            await api.IstranetClient(Session(Response(data={})), "a", "b").async_validate()
        with self.assertRaises(api.AuthenticationError):
            await api.IstranetClient(Session(Response(401)), "a", "b").async_validate()

    async def test_validate_does_not_depend_on_tariffs(self):
        session = Session(Response(data={"token": "new"}), Response(data={"balance": 0}))
        await api.IstranetClient(session, "a", "b").async_validate()
        self.assertEqual(len(session.calls), 2)

    async def test_concurrent_fetches_are_serialized(self):
        import asyncio

        client = api.IstranetClient(None, "a", "b")
        client._authenticate = AsyncMock()
        client._token = "present"
        active = 0

        async def account():
            nonlocal active
            active += 1
            self.assertEqual(active, 1)
            await asyncio.sleep(0)
            active -= 1
            return {"balance": 0}

        client._account = account
        client._get = AsyncMock(return_value=[])
        await asyncio.gather(client.async_fetch(), client.async_fetch())


class ParserTests(unittest.TestCase):
    def test_business_tariff_payment_rule(self):
        for name in ("Юр PRO", "PRO ЮР", "юр-100", "Тариф Юридический"):
            self.assertFalse(parser.payment_eligible(name))
        for name in ("PRO", "Домашний 100"):
            self.assertTrue(parser.payment_eligible(name))
        for name in (None, "", " "):
            self.assertIsNone(parser.payment_eligible(name))

    def test_account_number_is_profile_id_only(self):
        self.assertEqual(parser.account_number({"id": 1234}), "1234")
        self.assertEqual(parser.account_number({"id": " 001234 "}), "001234")
        for profile in (
            None,
            [],
            {},
            {"login": "1234"},
            {"id": True},
            {"id": 12.5},
            {"id": 0},
            {"id": " "},
            {"id": "x" * 256},
        ):
            self.assertIsNone(parser.account_number(profile))

    def test_account_network_and_zero(self):
        values = parser.normalize(
            {
                "balance": "0",
                "require": "1,50",
                "block": "0",
                "enabled": "1",
                "ips": {
                    "ipv4": {
                        "addresses": [
                            {"ip": "192.0.2.1", "mask": "255.255.255.0", "gateway": "192.0.2.254"}
                        ],
                        "dns": ["192.0.2.2", "192.0.2.3"],
                    }
                },
            },
            [],
        )
        self.assertEqual(values["balance"], Decimal(0))
        self.assertEqual(values["require"], Decimal("1.50"))
        self.assertEqual(values["account_status"], "active")
        self.assertEqual(values["dns2"], "192.0.2.3")

    def test_missing_fields_are_unavailable_not_zero_or_active(self):
        values = parser.normalize({"ips": None}, None)
        for key in ("balance", "require", "tariff_speed", "subscription_fee", "account_status"):
            self.assertIsNone(values[key])

    def test_invalid_nested_fields(self):
        values = parser.normalize(
            {"ips": {"ipv4": {"addresses": [None], "dns": None}}},
            {"services": [None], "period": "Infinity"},
        )
        self.assertIsNone(values["ip"])
        self.assertIsNone(values["subscription_fee"])
        self.assertIsNone(values["next_payment"])

    def test_current_tariff_preferred_over_enabled_offer(self):
        values = parser.normalize(
            {},
            [
                {"name": "Offer", "enabled": True},
                {
                    "name": "Current",
                    "type": "current",
                    "speed": 100,
                    "cost": 999,
                    "services": [{"cost": "500"}, {"cost": "25.5"}],
                },
            ],
        )
        self.assertEqual(values["tariff"], "Current")
        self.assertEqual(values["subscription_fee"], Decimal("526"))
        self.assertEqual(values["tariff_price"], values["subscription_fee"])

    def test_ambiguous_and_inactive_offers_not_selected(self):
        for tariffs in (
            [{"name": "Offer"}],
            [{"active": True}, {"active": True}],
            [{"active": "false"}],
            [],
        ):
            self.assertIsNone(parser.choose_tariff(tariffs))

    def test_base_cost_and_free_tariff(self):
        self.assertEqual(parser.normalize({}, {"cost": 500})["subscription_fee"], 500)
        self.assertEqual(parser.normalize({}, {"cost": 0})["subscription_fee"], 0)
        self.assertIsNone(
            parser.normalize({}, {"cost": 500, "services": [{"cost": "bad"}]})["subscription_fee"]
        )

    def test_moscow_payment_date_and_bad_timestamp(self):
        self.assertEqual(
            parser.normalize({}, {"period": 1767218400})["next_payment"], date(2026, 1, 1)
        )
        for value in ("bad", "1e1000", -1, None):
            self.assertIsNone(parser.normalize({}, {"period": value})["next_payment"])

    def test_nonfinite_and_bool_numbers_rejected(self):
        for value in (True, False, "NaN", "Infinity", "-Infinity", "bad", {}):
            self.assertIsNone(parser.number(value))

    def test_service_discounts_match_cabinet_rounding(self):
        self.assertEqual(parser.service_cost({"cost": 891, "discount": 10}), 802)
        self.assertEqual(parser.service_cost({"cost": 891, "discount": 100}), 0)
        self.assertIsNone(parser.service_cost({"cost": 891, "discount": "bad"}))
        self.assertEqual(
            parser.normalize({}, {"cost": 891, "services": [{"cost": 891, "discount": 100}]})[
                "subscription_fee"
            ],
            0,
        )

    def test_blocked_and_disabled(self):
        self.assertEqual(parser.normalize({"block": True}, None)["account_status"], "blocked")
        self.assertEqual(parser.normalize({"enabled": False}, None)["account_status"], "disabled")


if __name__ == "__main__":
    unittest.main()
