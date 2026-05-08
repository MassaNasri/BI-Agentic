from __future__ import annotations

from dataclasses import dataclass

from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.settings import api_settings


@dataclass
class JWTPrincipal:
    id: str
    role: str
    email: str
    token_type: str

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    @property
    def is_active(self) -> bool:
        return True

    @property
    def username(self) -> str:
        return self.email or self.id

    def __str__(self) -> str:
        return self.username or "jwt-principal"


class VoiceJWTAuthentication(JWTAuthentication):
    """JWT authentication that does not require a local Django user model."""

    def get_user(self, validated_token):
        user_id_claim = str(api_settings.USER_ID_CLAIM)
        raw_user_id = validated_token.get(user_id_claim)
        if raw_user_id in (None, ""):
            raw_user_id = validated_token.get("sub")
        if raw_user_id in (None, ""):
            raise exceptions.AuthenticationFailed("Token missing user identifier")

        role = str(validated_token.get("role") or validated_token.get("user_role") or "").strip().lower()
        email = str(validated_token.get("email") or validated_token.get("user_email") or "").strip()
        token_type = str(validated_token.get("token_type") or "").strip().lower()
        return JWTPrincipal(
            id=str(raw_user_id).strip(),
            role=role,
            email=email,
            token_type=token_type,
        )
