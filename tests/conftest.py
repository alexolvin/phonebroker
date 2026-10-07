"""Pytest fixtures for phonebroker tests."""

import os

os.environ.setdefault("PHONEBROKER_TOKEN_CLIENT_A", "test_token_client_a")
os.environ.setdefault("PHONEBROKER_TOKEN_CLIENT_B", "test_token_client_b")
os.environ.setdefault("PHONEBROKER_TOKEN_OWNER", "test_token_owner")
