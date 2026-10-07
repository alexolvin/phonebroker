"""Tests for SecretRef resolution."""

import os

import pytest

from phonebroker.exceptions import SecretResolutionError
from phonebroker.secrets import resolve_secret


def test_resolve_from_env():
    os.environ["TEST_SECRET_VAR"] = "test_value_123"
    try:
        assert resolve_secret("TEST_SECRET_VAR") == "test_value_123"
        assert resolve_secret("SecretRef:TEST_SECRET_VAR") == "test_value_123"
        assert resolve_secret("env:TEST_SECRET_VAR") == "test_value_123"
    finally:
        del os.environ["TEST_SECRET_VAR"]


def test_resolve_missing_raises():
    with pytest.raises(SecretResolutionError, match="TEST_MISSING_VAR"):
        resolve_secret("SecretRef:TEST_MISSING_VAR")


def test_resolve_empty_ref():
    assert resolve_secret("") == ""
    assert resolve_secret("SecretRef:") == ""
