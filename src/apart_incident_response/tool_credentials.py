"""Controller-issued credentials for the constrained tool service."""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass

from .runtime import AgentIdentity
from .tool_contract import CredentialError


@dataclass(frozen=True)
class VerifiedCredentials:
    """Internal trusted identity obtained after credential verification."""

    token: str
    identity: AgentIdentity


class ControllerCredentialAuthority:
    """Issue opaque credentials and resolve them to controller identities."""

    def __init__(self) -> None:
        self._credentials: dict[str, AgentIdentity] = {}
        self._lock = threading.Lock()

    def issue(self, identity: AgentIdentity) -> str:
        if not isinstance(identity, AgentIdentity):
            raise CredentialError("only a controller-issued AgentIdentity can receive a credential")
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._credentials[token] = identity
        return token

    def verify(self, token: str) -> VerifiedCredentials:
        if not isinstance(token, str) or not token or len(token) > 256:
            raise CredentialError("request requires a valid controller credential")
        with self._lock:
            identity = self._credentials.get(token)
        if identity is None:
            raise CredentialError("request requires a valid controller credential")
        return VerifiedCredentials(token, identity)
