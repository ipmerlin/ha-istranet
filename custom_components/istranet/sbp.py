"""Validate payment inputs and encode the exact NSPK URL locally."""

from decimal import Decimal, InvalidOperation
from io import BytesIO
from urllib.parse import urlsplit

import segno

from .api import PaymentError

MIN_AMOUNT = 10
MAX_AMOUNT = 100000


def validate_amount(value):
    if isinstance(value, bool):
        raise PaymentError("Invalid amount")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as err:
        raise PaymentError("Invalid amount") from err
    if (
        not amount.is_finite()
        or amount != amount.to_integral_value()
        or not MIN_AMOUNT <= amount <= MAX_AMOUNT
    ):
        raise PaymentError("Use whole rubles between 10 and 100000")
    return int(amount)


def validate_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
        raise PaymentError("Invalid payment link")
    try:
        url = urlsplit(value)
        valid = (
            url.scheme == "https"
            and url.hostname == "qr.nspk.ru"
            and url.port in (None, 443)
            and not url.username
            and not url.password
            and not url.fragment
            and len(url.path) > 1
            and "\\" not in value
        )
    except ValueError as err:
        raise PaymentError("Invalid payment link") from err
    if not valid:
        raise PaymentError("Unexpected payment link destination")
    return value


def render_qr(url):
    output = BytesIO()
    segno.make_qr(validate_url(url), error="q").save(output, kind="png", scale=8, border=4)
    return output.getvalue()
