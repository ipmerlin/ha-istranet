"""Payment contract, input validation and local QR rendering."""

import importlib
import unittest

from test_client import Response, Session, api

sbp = importlib.import_module("istranet_test.sbp")
URL = "https://qr.nspk.ru/TEST_ONLY_NOT_A_PAYMENT"
METHODS = {"types": [{"type": "qr", "title": "СБП"}, {"type": "card", "title": "Картой"}]}


class PaymentTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_amount_type_and_idempotency(self):
        session = Session(Response(data=METHODS), Response(data={"url": URL}))
        client = api.IstranetClient(session, "a", "b")
        client._token = "token"
        self.assertEqual(await client.async_payment_url(890), URL)
        call = session.calls[-1]
        self.assertEqual(call[0], "POST")
        self.assertEqual(call[2]["json"], {"type": "qr", "amount": 890})
        self.assertTrue(call[2]["headers"]["Idempotency-Key"])

    async def test_reauth_reuses_key(self):
        session = Session(
            Response(data=METHODS),
            Response(401),
            Response(data={"token": "new"}),
            Response(data={"url": URL}),
        )
        client = api.IstranetClient(session, "a", "b")
        client._token = "old"
        await client.async_payment_url(890)
        self.assertEqual(
            session.calls[1][2]["headers"]["Idempotency-Key"],
            session.calls[3][2]["headers"]["Idempotency-Key"],
        )

    async def test_timeout_not_retried(self):
        session = Session(Response(data=METHODS), TimeoutError())
        client = api.IstranetClient(session, "a", "b")
        client._token = "token"
        with self.assertRaises(api.CannotConnect):
            await client.async_payment_url(890)
        self.assertEqual(len(session.calls), 2)

    async def test_unavailable_sbp_does_not_create_payment(self):
        session = Session(Response(data={"types": [{"type": "card"}]}))
        client = api.IstranetClient(session, "a", "b")
        client._token = "token"
        with self.assertRaises(api.PaymentError):
            await client.async_payment_url(890)
        self.assertEqual(len(session.calls), 1)

    async def test_wrong_destination_rejected(self):
        session = Session(Response(data=METHODS), Response(data={"url": "https://example.com"}))
        client = api.IstranetClient(session, "a", "b")
        client._token = "token"
        with self.assertRaises(api.PaymentError):
            await client.async_payment_url(890)

    async def test_invalid_amount_makes_no_request(self):
        session = Session()
        with self.assertRaises(api.PaymentError):
            await api.IstranetClient(session, "a", "b").async_payment_url(0)
        self.assertFalse(session.calls)


class ValidationTests(unittest.TestCase):
    def test_valid_whole_rubles(self):
        for value in (10, 890, "890", 890.0, 100000):
            self.assertEqual(sbp.validate_amount(value), int(value))

    def test_invalid_amounts(self):
        for value in (True, None, -1, 0, 9, 100001, 890.1, "NaN", "Infinity", "bad"):
            with self.subTest(value=value), self.assertRaises(api.PaymentError):
                sbp.validate_amount(value)

    def test_disallowed_urls(self):
        for url in (
            None,
            "http://qr.nspk.ru/test",
            "https://qr.nspk.ru.evil.test/test",
            "https://qr.nspk.ru@evil.test/test",
            "https://user@qr.nspk.ru/test",
            "https://qr.nspk.ru:999/test",
            "https://qr.nspk.ru/",
            "https://qr.nspk.ru/test#other",
            "javascript:alert(1)",
            "https://qr.nspk.ru/test\n",
            "https://qr.nspk.ru:bad/test",
        ):
            with self.subTest(url=url), self.assertRaises(api.PaymentError):
                sbp.validate_url(url)

    def test_full_url_kept_and_rendered_as_png(self):
        url = URL + "?type=02&sum=89000&cur=RUB"
        self.assertEqual(sbp.validate_url(url), url)
        png = sbp.render_qr(url)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(png), 200)
