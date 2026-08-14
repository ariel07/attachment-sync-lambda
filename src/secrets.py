"""Secrets Manager access, isolated in its own module for easy mocking/injection.

boto3 is not listed in requirements.txt because AWS Lambda's Python runtimes
ship it preinstalled (confirmed: AWS Lambda Python runtime preinstalled
packages include boto3/botocore for all supported versions). It IS needed as
a local dev dependency to run tests that exercise the default (non-injected)
path - tests that inject a fake client avoid needing it installed at all.
"""
from __future__ import annotations

import json
from typing import Any, Protocol


class _SecretsManagerClientProtocol(Protocol):
    def get_secret_value(self, SecretId: str) -> dict[str, Any]: ...


def get_secret_json(secret_arn: str, client: _SecretsManagerClientProtocol | None = None) -> dict[str, Any]:
    """Fetch a Secrets Manager secret and parse it as JSON.

    All secrets this Lambda uses are stored as JSON objects (see
    docs/phase1-manual-steps.md and docs/phase2-webhook-registration.md for
    the exact `create-secret` commands), not plain strings.
    """
    if client is None:
        import boto3

        client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)
    return json.loads(response["SecretString"])
