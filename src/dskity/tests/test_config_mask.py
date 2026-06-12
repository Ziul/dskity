"""Tests for dskity.config.mask – secret masking in config dicts."""

from __future__ import annotations

import pytest

from dskity.config.mask import MASK, mask_secrets


# ── Basic key-based masking ───────────────────────────────────────────────────

def test_masks_password_key() -> None:
    result = mask_secrets({"password": "hunter2"})
    assert result["password"] == MASK


def test_masks_token_key() -> None:
    assert mask_secrets({"token": "abc123"})["token"] == MASK


def test_masks_secret_key() -> None:
    assert mask_secrets({"secret": "shh"})["secret"] == MASK


def test_masks_api_key_variants() -> None:
    data = {"apiKey": "key1", "api_key": "key2", "API-KEY": "key3"}
    result = mask_secrets(data)
    assert result["apiKey"] == MASK
    assert result["api_key"] == MASK
    assert result["API-KEY"] == MASK


def test_masks_access_key() -> None:
    assert mask_secrets({"accessKey": "AKID..."})["accessKey"] == MASK


def test_masks_private_key() -> None:
    assert mask_secrets({"privateKey": "-----BEGIN..."})["privateKey"] == MASK


def test_masks_credentials_key() -> None:
    assert mask_secrets({"credentials": "user:pass"})["credentials"] == MASK


def test_masks_secret_key_compound() -> None:
    # "secretKey" maps to "secretkey" after normalisation
    assert mask_secrets({"secretKey": "value"})["secretKey"] == MASK


# ── Non-sensitive keys are preserved ─────────────────────────────────────────

def test_preserves_non_sensitive_keys() -> None:
    data = {"host": "localhost", "port": 5432, "name": "mydb"}
    assert mask_secrets(data) == data


def test_preserves_empty_string_for_sensitive_key() -> None:
    # Empty string has no credential, should NOT become MASK
    result = mask_secrets({"password": ""})
    assert result["password"] == ""


def test_preserves_none_for_sensitive_key() -> None:
    result = mask_secrets({"token": None})
    assert result["token"] is None


# ── Value-pattern masking ─────────────────────────────────────────────────────

def test_masks_url_with_embedded_credentials() -> None:
    result = mask_secrets({"db_url": "postgresql://user:secret@localhost/db"})
    assert result["db_url"] == MASK


def test_preserves_url_without_credentials() -> None:
    result = mask_secrets({"db_url": "postgresql://localhost/db"})
    assert result["db_url"] == "postgresql://localhost/db"


def test_masks_vault_token_hvs_prefix() -> None:
    assert mask_secrets({"token_value": "hvs.AAAABBBCCC"})["token_value"] == MASK


def test_masks_vault_token_s_prefix() -> None:
    assert mask_secrets({"value": "s.abcdef1234"})["value"] == MASK


def test_masks_openai_api_key_sk_dash() -> None:
    assert mask_secrets({"key": "sk-abc123"})["key"] == MASK


def test_masks_stripe_api_key_sk_underscore() -> None:
    assert mask_secrets({"key": "sk_live_abc123"})["key"] == MASK


def test_preserves_value_not_matching_patterns() -> None:
    result = mask_secrets({"description": "some sk-like text middle"})
    # Pattern matches only at start (^sk[-_])
    assert result["description"] == "some sk-like text middle"


# ── Recursive structures ──────────────────────────────────────────────────────

def test_masks_nested_dict() -> None:
    data = {"db": {"host": "localhost", "password": "secret"}}
    result = mask_secrets(data)
    assert result["db"]["password"] == MASK
    assert result["db"]["host"] == "localhost"


def test_masks_deeply_nested() -> None:
    data = {"level1": {"level2": {"level3": {"token": "abc"}}}}
    result = mask_secrets(data)
    assert result["level1"]["level2"]["level3"]["token"] == MASK


def test_masks_inside_list_of_dicts() -> None:
    data = {"services": [{"name": "svc1", "token": "tok1"}, {"name": "svc2", "token": "tok2"}]}
    result = mask_secrets(data)
    assert result["services"][0]["token"] == MASK
    assert result["services"][1]["token"] == MASK
    assert result["services"][0]["name"] == "svc1"


def test_list_of_scalars_unchanged() -> None:
    data = {"tags": ["a", "b", "c"]}
    assert mask_secrets(data) == data


def test_scalar_passthrough() -> None:
    assert mask_secrets(42) == 42
    assert mask_secrets("hello") == "hello"
    assert mask_secrets(None) is None


# ── Original dict is not mutated ──────────────────────────────────────────────

def test_does_not_mutate_original() -> None:
    original = {"password": "secret", "host": "localhost"}
    mask_secrets(original)
    assert original["password"] == "secret"


# ── Mixed sensitive key + URL value ──────────────────────────────────────────

def test_key_takes_priority_over_value_pattern() -> None:
    # key is "password", value is a plain string (not a URL pattern)
    result = mask_secrets({"password": "plaintext"})
    assert result["password"] == MASK
