"""Generate matching English and Russian UI definitions."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components/istranet"
NAMES = {
    "account_number": ("Номер лицевого счёта", "Account number"),
    "balance": ("Баланс", "Balance"),
    "require": ("К оплате", "Amount due"),
    "account_status": ("Статус подключения", "Account status"),
    "ip": ("IP-адрес", "IP address"),
    "gateway": ("Шлюз", "Gateway"),
    "dns1": ("DNS 1", "DNS 1"),
    "dns2": ("DNS 2", "DNS 2"),
    "tariff": ("Тариф", "Tariff"),
    "tariff_price": ("Стоимость тарифа", "Tariff price"),
    "subscription_fee": ("Абонентская плата", "Subscription fee"),
    "tariff_speed": ("Скорость тарифа", "Tariff speed"),
    "next_payment": ("Дата списания", "Next payment date"),
}

for lang in ("ru", "en"):
    ru = lang == "ru"

    def tr(russian, english):
        return russian if ru else english

    credentials = {"username": tr("Логин", "Username"), "password": tr("Пароль", "Password")}
    data = {
        "title": "Istranet",
        "config": {
            "step": {
                "user": {
                    "title": "Istranet",
                    "description": tr(
                        "Введите данные входа в lk.istranet.ru.",
                        "Enter your lk.istranet.ru credentials.",
                    ),
                    "data": credentials,
                },
                "reauth_confirm": {
                    "title": tr("Повторный вход", "Sign in again"),
                    "description": tr(
                        "Введите пароль для того же логина Istranet.",
                        "Enter the password for the same Istranet username.",
                    ),
                    "data": credentials,
                },
            },
            "error": {
                "invalid_auth": tr("Неверный логин или пароль", "Invalid username or password"),
                "cannot_connect": tr("Не удалось связаться с Istranet", "Cannot reach Istranet"),
                "invalid_response": tr(
                    "ЛК вернул неожиданный ответ", "Unexpected cabinet response"
                ),
            },
            "abort": {
                "already_configured": tr("Этот логин уже добавлен", "Username already configured"),
                "reauth_successful": tr("Данные входа обновлены", "Credentials updated"),
                "unique_id_mismatch": tr(
                    "Введите исходный логин; другой добавьте отдельно",
                    "Use the original username; add another account separately",
                ),
            },
        },
        "options": {
            "step": {
                "init": {
                    "title": tr("Настройки обновления", "Polling settings"),
                    "data": {
                        "update_interval": tr(
                            "Интервал обновления (минуты)", "Update interval (minutes)"
                        )
                    },
                }
            }
        },
        "entity": {
            "sensor": {key: {"name": names[0 if ru else 1]} for key, names in NAMES.items()},
            "button": {
                "refresh": {"name": tr("Обновить данные", "Refresh data")},
                "sbp_generate": {"name": tr("Получить QR СБП", "Generate SBP QR")},
            },
            "number": {"sbp_amount": {"name": tr("Сумма пополнения СБП", "SBP top-up amount")}},
            "image": {"sbp_qr": {"name": tr("QR для оплаты СБП", "SBP payment QR")}},
        },
    }
    data["entity"]["sensor"]["account_status"]["state"] = {
        "active": tr("Активно", "Active"),
        "blocked": tr("Заблокировано", "Blocked"),
        "disabled": tr("Отключено", "Disabled"),
    }
    path = ROOT / "translations" / f"{lang}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not ru:
        (ROOT / "strings.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
