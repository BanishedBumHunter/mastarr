"""API-key encryption at rest and log redaction."""

from __future__ import annotations

import logging
import stat

import httpx
import respx

from mastarr.config import get_settings
from mastarr.crypto import DecryptionError, KeyCipher, get_cipher, load_or_create_key
from mastarr.logging import REDACTED, RedactionFilter, redact, register_secret

from . import fixtures as fx

SECRET = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


# ------------------------------------------------------------------ at rest


def test_key_round_trips(isolated_env):
    cipher = get_cipher()
    assert cipher.decrypt(cipher.encrypt(SECRET)) == SECRET


def test_ciphertext_does_not_contain_the_plaintext(isolated_env):
    assert SECRET not in get_cipher().encrypt(SECRET)


def test_encryption_is_non_deterministic(isolated_env):
    """Fernet includes an IV, so identical keys on two services aren't correlatable."""
    cipher = get_cipher()
    assert cipher.encrypt(SECRET) != cipher.encrypt(SECRET)


def test_generated_key_file_is_0600(isolated_env, tmp_path):
    load_or_create_key(get_settings())
    mode = (tmp_path / "secret.key").stat().st_mode
    assert not mode & stat.S_IRGRP
    assert not mode & stat.S_IROTH


def test_key_persists_across_restarts(isolated_env, tmp_path):
    """A regenerated key on restart would make every stored API key unreadable."""
    first = load_or_create_key(get_settings())
    assert load_or_create_key(get_settings()) == first


def test_wrong_key_raises_a_helpful_error_without_leaking(isolated_env):
    from cryptography.fernet import Fernet

    ciphertext = get_cipher().encrypt(SECRET)
    other = KeyCipher(Fernet.generate_key())
    try:
        other.decrypt(ciphertext)
    except DecryptionError as exc:
        assert SECRET not in str(exc)
        assert "secret key has likely changed" in str(exc)
    else:
        raise AssertionError("expected DecryptionError")


def test_api_key_is_encrypted_in_the_database_file(admin_client, tmp_path):
    """End-to-end: the plaintext key must not appear on disk."""
    admin_client.post(
        "/api/services",
        json={
            "name": "Sonarr",
            "service_type": "sonarr",
            "url": "http://host.test:8989",
            "api_key": SECRET,
        },
    )
    assert SECRET.encode() not in (tmp_path / "mastarr.db").read_bytes()


def test_api_is_never_echoed_back(admin_client):
    """No endpoint returns a stored key — only whether one is set."""
    admin_client.post(
        "/api/services",
        json={
            "name": "Sonarr",
            "service_type": "sonarr",
            "url": "http://host.test:8989",
            "api_key": SECRET,
        },
    )
    body = admin_client.get("/api/services").text
    assert SECRET not in body
    assert admin_client.get("/api/services").json()[0]["has_api_key"] is True


# ----------------------------------------------------------------- redaction


def test_registered_secret_is_redacted_anywhere():
    register_secret(SECRET)
    assert SECRET not in redact(f"connecting with {SECRET} now")


def test_header_pattern_is_redacted_without_registration():
    """Catches keys we were never told about — someone else's service, a typo in a form."""
    assert "abc123def456" not in redact("X-Api-Key: abc123def456")


def test_query_param_pattern_is_redacted():
    text = redact("GET http://sonarr:8989/api/v3/series?apikey=abc123def456xyz")
    assert "abc123def456xyz" not in text
    assert REDACTED in text


def test_bearer_token_is_redacted():
    assert "eyJhbGciOi" not in redact("Authorization: Bearer eyJhbGciOi.payload.sig")


def test_short_strings_are_not_registered():
    """Avoids redacting common words if a trivially short key is ever stored."""
    register_secret("abc")
    assert redact("abc def") == "abc def"


def test_filter_scrubs_log_records(caplog):
    register_secret(SECRET)
    logger = logging.getLogger("mastarr.test.redaction")
    logger.addFilter(RedactionFilter())

    with caplog.at_level(logging.INFO):
        logger.info("using key %s for service", SECRET)

    assert SECRET not in caplog.text


def test_no_key_material_reaches_logs_during_a_real_call(admin_client, caplog):
    """The end-to-end secrets check: exercise a service call and grep the log output."""
    register_secret(SECRET)
    with caplog.at_level(logging.DEBUG):
        with respx.mock:
            respx.get("http://host.test:8989/api/v3/system/status").mock(
                return_value=httpx.Response(200, json=fx.SONARR_STATUS)
            )
            respx.get("http://host.test:8989/api/v3/health").mock(
                return_value=httpx.Response(200, json=fx.HEALTH_WARNINGS)
            )
            respx.get("http://host.test:8989/api/v3/diskspace").mock(
                return_value=httpx.Response(500)
            )
            respx.get("http://host.test:8989/api/v3/queue").mock(
                return_value=httpx.Response(500)
            )

            admin_client.post(
                "/api/services",
                json={
                    "name": "Sonarr",
                    "service_type": "sonarr",
                    "url": "http://host.test:8989",
                    "api_key": SECRET,
                },
            )
            admin_client.get("/api/dashboard")

    assert SECRET not in caplog.text
