"""Private key text pasted into .env must load in every common paste format (throwaway keys)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from app.config import Settings
from app.kalshi_client import load_private_key


def _pem(key: RSAPrivateKey, fmt: serialization.PrivateFormat) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, fmt, serialization.NoEncryption()
    ).decode()


def _same_key(a: RSAPrivateKey, b: object) -> bool:
    return isinstance(b, RSAPrivateKey) and a.private_numbers() == b.private_numbers()


@pytest.mark.parametrize(
    "fmt", [serialization.PrivateFormat.TraditionalOpenSSL, serialization.PrivateFormat.PKCS8]
)
def test_paste_variants_all_load(throwaway_rsa_key: RSAPrivateKey, fmt: serialization.PrivateFormat) -> None:
    pem = _pem(throwaway_rsa_key, fmt)
    lines = pem.strip().splitlines()
    variants = {
        "multi-line": pem,
        "one line with spaces": " ".join(lines),
        "literal \\n escapes": "\\n".join(lines),
        "wrapped in quotes": f'"{pem}"',
        "body only, no BEGIN/END": "".join(lines[1:-1]),
    }
    for name, text in variants.items():
        assert _same_key(throwaway_rsa_key, load_private_key(text)), name


def test_garbage_is_rejected() -> None:
    with pytest.raises(ValueError):
        load_private_key("not a key")


def test_multiline_value_in_env_file_wins_over_path(
    tmp_path: Path, throwaway_rsa_key: RSAPrivateKey
) -> None:
    pem = _pem(throwaway_rsa_key, serialization.PrivateFormat.TraditionalOpenSSL)
    env = tmp_path / ".env"
    env.write_text(
        f'KALSHI_KEY_ID=abc\nKALSHI_PRIVATE_KEY="{pem}"\n'
        "KALSHI_PRIVATE_KEY_PATH=./does/not/exist.pem\n"
    )
    config = Settings(_env_file=env)  # type: ignore[call-arg]
    assert config.credentials_configured
    text = config.private_key_text()
    assert text is not None
    assert _same_key(throwaway_rsa_key, load_private_key(text))


def test_empty_inline_key_falls_back_to_path(tmp_path: Path, throwaway_rsa_key: RSAPrivateKey) -> None:
    key_file = tmp_path / "k.pem"
    key_file.write_text(_pem(throwaway_rsa_key, serialization.PrivateFormat.PKCS8))
    env = tmp_path / ".env"
    env.write_text(f'KALSHI_KEY_ID=abc\nKALSHI_PRIVATE_KEY="\n"\nKALSHI_PRIVATE_KEY_PATH={key_file}\n')
    config = Settings(_env_file=env)  # type: ignore[call-arg]
    assert config.credentials_configured
    assert config.private_key_text() == key_file.read_text()
