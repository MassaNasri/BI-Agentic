from shared.utils.kafka_producer import redact_message_secrets


def test_nested_database_credentials_are_redacted_for_logs():
    message = {
        "db_type": "postgres",
        "configuration": {
            "username": "reader",
            "password": "encrypted-but-still-secret",
            "nested": {"wallet_password": "wallet-secret"},
        },
    }
    redacted = redact_message_secrets(message)
    assert redacted["configuration"]["username"] == "reader"
    assert redacted["configuration"]["password"] == "[REDACTED]"
    assert redacted["configuration"]["nested"]["wallet_password"] == "[REDACTED]"
