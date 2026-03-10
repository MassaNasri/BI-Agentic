"""
JWT Embedding Service (Metabase Self-Hosted)

Generates JWT tokens for Metabase embedded dashboards/questions.
Uses the same secret as configured in Metabase Admin > Settings > Embedding.
Optional: only needed if you use embedded iframes; API uses Session Auth only.
"""

import jwt
import time
import os
import logging
from typing import Dict, Optional
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class JWTEmbeddingService:
    """
    JWT token generation for Metabase self-hosted embedding.
    Requires METABASE_SECRET_KEY to match Metabase Admin embedding secret.
    """
    
    def __init__(self):
        """Initialize from environment (METABASE_SECRET_KEY required for embedding)."""
        self.secret_key = os.getenv("METABASE_SECRET_KEY")
        self.embed_exp_seconds = int(
            os.getenv("METABASE_EMBED_EXP_SECONDS", str(60 * 60 * 24))
        )
        self.metabase_url = (os.getenv("METABASE_URL") or "http://localhost:3000").rstrip("/")

        if not self.secret_key:
            logger.error("METABASE_SECRET_KEY is missing; secure embedding is disabled")
    
    def _ensure_secret(self) -> None:
        if not self.secret_key:
            raise ImproperlyConfigured(
                "METABASE_SECRET_KEY must be set for embedding charts"
            )

    def _to_metabase_resource(self, resource: Dict) -> Dict[str, int]:
        """
        Normalize resource payload to Metabase signed-embed format:
        {"question": <id>} or {"dashboard": <id>}.
        """
        if not isinstance(resource, dict):
            raise ValueError("Resource must be a dictionary")

        # Backward-compatible input shape: {"type": "...", "id": ...}
        if "type" in resource and "id" in resource:
            resource_type = str(resource["type"]).strip().lower()
            resource_id = resource["id"]
            if resource_type not in ("dashboard", "question"):
                raise ValueError("Resource type must be 'dashboard' or 'question'")
            if not isinstance(resource_id, int):
                raise ValueError("Resource id must be an integer")
            return {resource_type: resource_id}

        # Native Metabase input shape: {"question": ...} or {"dashboard": ...}
        for key in ("question", "dashboard"):
            if key in resource:
                resource_id = resource[key]
                if not isinstance(resource_id, int):
                    raise ValueError("Resource id must be an integer")
                return {key: resource_id}

        raise ValueError(
            "Resource must have either {'type','id'} or {'question'|'dashboard': id}"
        )

    def _validate_resource(self, resource: Dict) -> None:
        if not isinstance(resource, dict):
            raise ValueError("Payload resource must be a dictionary")
        if len(resource) != 1:
            raise ValueError("Payload resource must include exactly one key")
        resource_type = next(iter(resource.keys()))
        resource_id = resource[resource_type]
        if resource_type not in ("dashboard", "question"):
            raise ValueError("Payload resource key must be 'dashboard' or 'question'")
        if not isinstance(resource_id, int):
            raise ValueError("Payload resource id must be an integer")

    def _validate_payload(self, payload: Dict) -> None:
        """
        Validate JWT payload structure before signing.
        """
        required_keys = {"resource", "params", "iat", "exp"}
        missing_keys = required_keys.difference(payload.keys())
        if missing_keys:
            raise ValueError(f"Invalid embed payload structure. Missing: {missing_keys}")
        if not isinstance(payload["resource"], dict):
            raise ValueError("Payload resource must be a dictionary")
        if not isinstance(payload["params"], dict):
            raise ValueError("Payload params must be a dictionary")
        if not isinstance(payload["iat"], int) or not isinstance(payload["exp"], int):
            raise ValueError("Payload iat/exp must be integers")
        if payload["exp"] <= payload["iat"]:
            raise ValueError("Payload exp must be greater than iat")
        self._validate_resource(payload["resource"])

    def generate_embed_token(self, resource: Dict, params: Optional[Dict] = None,
                            exp_seconds: Optional[int] = None) -> str:
        """
        Generate JWT token for embedding.
        
        Args:
            resource: {'type': 'dashboard'|'question', 'id': int}
            params: Optional parameters (must match Metabase embed filters)
            exp_seconds: Token expiration in seconds (default: 24 hours)
        
        Returns:
            str: JWT token
        
        Raises:
            ValueError: If resource/payload is invalid
            ImproperlyConfigured: If METABASE_SECRET_KEY is missing
        """
        self._ensure_secret()
        metabase_resource = self._to_metabase_resource(resource)
        if params is not None and not isinstance(params, dict):
            raise ValueError("Params must be a dictionary")

        current_time = int(time.time())
        expires_in_seconds = exp_seconds if exp_seconds is not None else self.embed_exp_seconds
        if expires_in_seconds <= 0:
            raise ValueError("Token expiration must be greater than 0 seconds")
        payload = {
            "resource": metabase_resource,
            "params": params or {},
            "iat": current_time,
            "exp": current_time + expires_in_seconds,
        }
        self._validate_payload(payload)
        token = jwt.encode(payload, self.secret_key, algorithm="HS256")
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        resource_type = next(iter(metabase_resource.keys()))
        resource_id = metabase_resource[resource_type]
        logger.info("Generated JWT token for %s %s", resource_type, resource_id)
        return token
    
    def generate_dashboard_token(self, dashboard_id: int, params: Optional[Dict] = None) -> str:
        """
        Generate token specifically for dashboard embedding.
        
        Args:
            dashboard_id: Metabase dashboard ID
            params: Optional dashboard parameters
        
        Returns:
            str: JWT token
        """
        resource = {'dashboard': dashboard_id}
        return self.generate_embed_token(resource, params)
    
    def generate_question_token(self, question_id: int, params: Optional[Dict] = None) -> str:
        """
        Generate token specifically for question embedding.
        
        Args:
            question_id: Metabase question ID
            params: Optional question parameters
        
        Returns:
            str: JWT token
        """
        resource = {'question': question_id}
        return self.generate_embed_token(resource, params)
    
    def get_embed_url(self, resource_type: str, resource_id: int,
                      params: Optional[Dict] = None) -> str:
        """
        Get full embed URL with JWT token (requires METABASE_SECRET_KEY).
        """
        resource = {"type": resource_type, "id": resource_id}
        token = self.generate_embed_token(resource, params)
        embed_url = f"{self.metabase_url}/embed/{resource_type}/{token}#bordered=true&titled=true"
        logger.info("Generated embed URL for %s %s", resource_type, resource_id)
        return embed_url
    
    def get_dashboard_embed_url(self, dashboard_id: int) -> str:
        """
        Dashboard URL using secure JWT embed only.
        """
        return self.get_embed_url("dashboard", dashboard_id, params={})

    def get_question_embed_url(self, question_id: int) -> str:
        """
        Question URL using secure JWT embed only.
        """
        return self.get_embed_url("question", question_id, params={})
    
    def verify_token(self, token: str) -> Optional[Dict]:
        """Verify and decode JWT token; returns None if secret not set or invalid."""
        if not self.secret_key:
            return None
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=["HS256"],
                options={"require": ["exp", "iat"]},
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("JWT token has expired")
            return None
        except jwt.InvalidTokenError:
            return None
        except Exception as e:
            logger.error("JWT verification error: %s", e)
            return None
    
    def is_token_expired(self, token: str) -> bool:
        """
        Check if token is expired.
        
        Args:
            token: JWT token string
        
        Returns:
            bool: True if expired or invalid
        """
        payload = self.verify_token(token)
        return payload is None


# Singleton instance
_jwt_service = None

def get_jwt_service() -> JWTEmbeddingService:
    """Get or create JWT service singleton."""
    global _jwt_service
    if _jwt_service is None:
        _jwt_service = JWTEmbeddingService()
    return _jwt_service

