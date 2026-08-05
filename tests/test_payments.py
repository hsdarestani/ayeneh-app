from app.config import Settings
from app.payments import payment_signature, valid_payment_signature, zibal_payment_url


def test_payment_signature_rejects_tampering():
    settings = Settings(
        bot_token="123456:test-secret",
        zibal_merchant="merchant",
        domain="ayeneh.hamooncloud.ir",
    )
    signature = payment_signature(settings, 42)

    assert valid_payment_signature(settings, 42, signature)
    assert not valid_payment_signature(settings, 43, signature)
    assert not valid_payment_signature(settings, 42, signature[:-1] + "0")


def test_amount_and_urls_are_normalized():
    settings = Settings(
        bot_token="token",
        price_toman=99_000,
        domain="ayeneh.hamooncloud.ir/",
    )

    assert settings.price_rial == 990_000
    assert settings.public_base_url == "https://ayeneh.hamooncloud.ir"
    assert settings.payment_callback_url == "https://ayeneh.hamooncloud.ir/payment/callback"
    assert zibal_payment_url(1234) == "https://gateway.zibal.ir/start/1234"
