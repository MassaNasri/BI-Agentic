"""Resolve an Integration execution grant without putting secrets on Kafka."""

import os
from bi_platform_shared.secret_delivery import read_secret
import uuid

import requests

from bi_platform_shared.credential_crypto import CredentialCryptoError, decrypt_credential
from shared.connectors.core import ConnectorError


def resolve_source_execution(reference, *, service):
    if service not in {"etl-connector", "etl-extractor"}:
        raise ConnectorError("CREDENTIAL_NOT_AVAILABLE", "Source credential is unavailable.", status_code=403)
    try:
        source_id = str(uuid.UUID(str(reference["source_id"])))
        job_id = str(uuid.UUID(str(reference["job_id"])))
        credential_id = str(uuid.UUID(str(reference["credential_id"])))
        version = int(reference["credential_version"])
        workspace_id = int(reference["workspace_id"])
        dataset_id = str(reference["dataset_id"])
        if version <= 0 or workspace_id <= 0 or not dataset_id:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ConnectorError("INVALID_CREDENTIAL_REFERENCE", "Invalid source execution reference.") from exc
    key_name = {
        "etl-connector": "CREDENTIAL_RESOLVER_CONNECTOR_KEY",
        "etl-extractor": "CREDENTIAL_RESOLVER_EXTRACTOR_KEY",
    }[service]
    key = read_secret(key_name)
    if not key and os.getenv("APP_ENV") != "production":
        key = read_secret("CREDENTIAL_RESOLVER_API_KEY")
    if not key:
        raise ConnectorError("CREDENTIAL_NOT_AVAILABLE", "Source credential is unavailable.", status_code=503)
    payload = {
        "source_id": source_id, "job_id": job_id, "credential_id": credential_id,
        "credential_version": version, "workspace_id": workspace_id, "dataset_id": dataset_id,
    }
    try:
        response = requests.post(
            os.getenv("QUERY_SERVICE_URL", "http://query-service:8006").rstrip("/")
            + "/internal/v1/source-credentials/resolve/",
            json=payload,
            headers={"X-Internal-Service": service, "X-Credential-Resolver-Key": key},
            timeout=8,
        )
        if response.status_code != 200:
            raise ConnectorError("CREDENTIAL_NOT_AVAILABLE", "Source credential is unavailable.", status_code=403)
        data = response.json()["data"]
        if any(str(data.get(name)) != str(value) for name, value in payload.items()):
            raise ValueError
        configuration = dict(data["connection_metadata"])
        configuration["password"] = decrypt_credential(data["key_version"], data["ciphertext"])
        configuration["transport"] = data["transport"]
        return data["engine"], configuration, data["transport"], int(data["configuration_version"])
    except ConnectorError:
        raise
    except (requests.RequestException, KeyError, ValueError, TypeError, CredentialCryptoError) as exc:
        raise ConnectorError("CREDENTIAL_NOT_AVAILABLE", "Source credential is unavailable.", status_code=503) from exc
