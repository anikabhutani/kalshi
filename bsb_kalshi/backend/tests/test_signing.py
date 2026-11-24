"""Signing must follow specs/auth_notes.md exactly. Uses throwaway keys only."""

from __future__ import annotations

import base64
from collections.abc import Callable

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from app.kalshi_client import auth_headers, build_sign_message, sign_message, signing_path
from tests.conftest import TEST_KEY_ID, Handler, Stack

PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH)


def test_message_is_timestamp_method_path_without_query() -> None:
    message = build_sign_message("1703123456789", "GET", "/trade-api/v2/portfolio/orders?limit=5")
    assert message == b"1703123456789GET/trade-api/v2/portfolio/orders"


def test_signing_path_includes_api_root_and_drops_host_and_query() -> None:
    for base in (
        "https://external-api.kalshi.com/trade-api/v2",
        "https://api.elections.kalshi.com/trade-api/v2/",
        "https://external-api.demo.kalshi.co/trade-api/v2",
    ):
        assert signing_path(base, "/portfolio/balance") == "/trade-api/v2/portfolio/balance"
    assert signing_path("https://h/trade-api/v2", "/markets?limit=5") == "/trade-api/v2/markets"


def test_rsa_signature_is_pss_sha256_digest_length_salt(throwaway_rsa_key: RSAPrivateKey) -> None:
    message = b"1703123456789GET/trade-api/v2/portfolio/balance"
    signature = base64.b64decode(sign_message(throwaway_rsa_key, message))
    throwaway_rsa_key.public_key().verify(signature, message, PSS, hashes.SHA256())


def test_ed25519_signs_message_directly() -> None:
    key = Ed25519PrivateKey.generate()
    message = b"1703123456789GET/trade-api/v2/portfolio/balance"
    key.public_key().verify(base64.b64decode(sign_message(key, message)), message)


def test_auth_headers_structure(throwaway_rsa_key: RSAPrivateKey) -> None:
    headers = auth_headers("key-id", throwaway_rsa_key, "GET", "/trade-api/v2/portfolio/balance")
    assert set(headers) == {
        "KALSHI-ACCESS-KEY",
        "KALSHI-ACCESS-SIGNATURE",
        "KALSHI-ACCESS-TIMESTAMP",
    }
    assert headers["KALSHI-ACCESS-KEY"] == "key-id"
    assert headers["KALSHI-ACCESS-TIMESTAMP"].isdigit()
    assert len(headers["KALSHI-ACCESS-TIMESTAMP"]) == 13


async def test_client_sends_verifiable_signature_over_full_path(
    make_stack: Callable[[Handler], Stack], throwaway_rsa_key: RSAPrivateKey
) -> None:
    stack = make_stack(lambda _: httpx.Response(200, json={"balance": 0}))
    await stack.client.call("GET", "/portfolio/balance", params={"subaccount": 0}, auth=True)
    request = stack.sent[0]
    assert request.url.params["subaccount"] == "0"
    assert request.headers["KALSHI-ACCESS-KEY"] == TEST_KEY_ID
    message = build_sign_message(
        request.headers["KALSHI-ACCESS-TIMESTAMP"], "GET", "/trade-api/v2/portfolio/balance"
    )
    signature = base64.b64decode(request.headers["KALSHI-ACCESS-SIGNATURE"])
    throwaway_rsa_key.public_key().verify(signature, message, PSS, hashes.SHA256())
