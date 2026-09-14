"""Normalize cabinet values without inventing zero balances or tariffs."""

from datetime import datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from zoneinfo import ZoneInfo


def account_number(profile):
    """Preserve the profile identifier as text, including leading zeroes."""
    value = profile.get("id") if isinstance(profile, dict) else None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, str) and value.strip() and len(value.strip()) <= 255:
        return value.strip()
    return None


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).strip().replace(" ", "").replace(",", "."))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def flag(value):
    if isinstance(value, bool):
        return value
    if value in (1, "1", "true", "True"):
        return True
    if value in (0, "0", "false", "False"):
        return False
    return None


def mapping(value):
    return value if isinstance(value, dict) else {}


def text(value):
    return value if isinstance(value, str) and value.strip() else None


def service_cost(item):
    """Match the cabinet's cost minus percentage discount, rounded up to rubles."""
    if not isinstance(item, dict):
        return None
    cost = number(item.get("cost"))
    discount = number(item.get("discount", 0))
    if cost is None or discount is None or not 0 <= discount <= 100:
        return None
    return (cost * (100 - discount) / 100).quantize(Decimal(1), rounding=ROUND_CEILING)


def choose_tariff(data):
    if isinstance(data, dict):
        return data or None
    if not isinstance(data, list):
        return None
    candidates = [item for item in data if isinstance(item, dict) and item]
    current = [item for item in candidates if item.get("type") == "current"]
    if len(current) == 1:
        return current[0]
    active = [
        item
        for item in candidates
        if flag(item.get("enabled")) is True or flag(item.get("active")) is True
    ]
    if not current and len(active) == 1:
        return active[0]
    # Never report the first available offer as the customer's current tariff.
    return None


def normalize(account, tariffs):
    blocked, enabled = flag(account.get("block")), flag(account.get("enabled"))
    status = (
        "blocked"
        if blocked is True
        else (
            "disabled"
            if enabled is False
            else "active"
            if enabled is True and blocked is False
            else None
        )
    )
    ipv4 = mapping(mapping(account.get("ips")).get("ipv4"))
    addresses, dns = ipv4.get("addresses"), ipv4.get("dns")
    primary = mapping(addresses[0]) if isinstance(addresses, list) and addresses else {}
    dns = dns if isinstance(dns, list) else []
    result = {
        "balance": number(account.get("balance")),
        "require": number(account.get("require")),
        "account_status": status,
        "enabled": enabled,
        "blocked": blocked,
        "ip": text(primary.get("ip")),
        "mask": text(primary.get("mask")),
        "gateway": text(primary.get("gateway")),
        "dns1": text(dns[0]) if dns else None,
        "dns2": text(dns[1]) if len(dns) > 1 else None,
        "tariff": None,
        "tariff_price": None,
        "tariff_speed": None,
        "subscription_fee": None,
        "next_payment": None,
    }
    tariff = choose_tariff(tariffs)
    if tariff is None:
        return result
    result["tariff"] = next(
        (
            text(tariff.get(key))
            for key in ("name", "title", "tariff_name")
            if text(tariff.get(key))
        ),
        None,
    )
    result["tariff_speed"] = next(
        (
            number(tariff.get(key))
            for key in ("speed", "speed_down", "download_speed")
            if number(tariff.get(key)) is not None
        ),
        None,
    )
    # The live cabinet rounds each discounted service price before summing.
    services = tariff.get("services", [])
    fee = None
    if isinstance(services, list):
        costs = [service_cost(item) for item in services]
        if all(cost is not None for cost in costs):
            total = sum(costs, Decimal(0))
            fee = total if services else number(tariff.get("cost"))
    result["tariff_price"] = result["subscription_fee"] = fee
    timestamp = number(tariff.get("period"))
    if timestamp is not None and timestamp > 0:
        try:
            result["next_payment"] = datetime.fromtimestamp(
                float(timestamp), ZoneInfo("Europe/Moscow")
            ).date()
        except (ValueError, OverflowError, OSError):
            pass
    return result
