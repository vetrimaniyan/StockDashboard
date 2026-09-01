"""API authentication (NFR-4.5).

The service held no authentication at all until this existed, which is why
``api_host`` defaults to loopback: anything that could reach the port received
every endpoint and the whole dataset. Binding beyond loopback was a warning,
and a warning is not a control.

**The property that matters is that the API cannot be exposed unauthenticated
by accident.** Not that the token check is clever — it is deliberately dull —
but that there is no configuration in which the service listens on a public
interface with no credential. See ``guard_bind_address``: that combination
refuses to start rather than starting insecurely, because a service that
warns and then runs will be run.

Tokens are opaque bearer secrets, compared in constant time. Each carries a
label so one reviewer can be revoked without disturbing the others, which is
the whole point of handing them out individually.

Not built here, deliberately: user accounts, passwords, roles. This is a
single-operator tool shared with a handful of named reviewers. Passwords would
mean a user store, reset flows and hashing decisions — more surface, no more
safety, for an audience that fits in one line of a .env file.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

from alpha500.config import settings

log = logging.getLogger(__name__)

SESSION_COOKIE = "alpha500_session"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# Paths served without a credential. Deliberately tiny: enough for a browser
# to load the login screen and for a health probe to see the service is alive,
# and nothing that discloses market data or configuration.
PUBLIC_PATHS = frozenset({"/api/health", "/api/session"})


@dataclass(frozen=True, slots=True)
class Principal:
    """Who a request is acting as. ``label`` is for logs, never for authorisation."""

    label: str


def configured_tokens() -> dict[str, str]:
    """``{label: token}`` from settings, newest form winning.

    ``ALPHA500_API_TOKENS`` takes ``label:token`` pairs separated by commas so
    reviewers can be revoked individually. ``ALPHA500_API_TOKEN`` is the
    single-token convenience form.
    """
    tokens: dict[str, str] = {}
    raw = (settings.api_tokens or "").strip()
    if raw:
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            label, _, value = entry.partition(":")
            if not value:
                # A bare token with no label still works; it just cannot be
                # told apart from another bare one in the log.
                label, value = "unlabelled", label
            tokens[label.strip()] = value.strip()
    single = (settings.api_token or "").strip()
    if single:
        tokens.setdefault("default", single)
    return {label: value for label, value in tokens.items() if value}


def auth_required() -> bool:
    return bool(configured_tokens())


def guard_bind_address(host: str) -> None:
    """Refuse to start unauthenticated on a non-loopback interface.

    This is the control the previous warning was not. Market-data licensing
    does not permit redistribution and the dataset is not public, so an open
    port on a LAN or a tunnel is not a smaller version of the same thing — it
    is a different act.
    """
    if host in LOOPBACK_HOSTS or auth_required():
        return
    raise SystemExit(
        f"\n  Refusing to bind to {host} with no API token configured.\n\n"
        "  The API would serve every endpoint and the full dataset to anything\n"
        "  that can reach the port. Set ALPHA500_API_TOKEN (or\n"
        "  ALPHA500_API_TOKENS for one per reviewer) in .env, then start again.\n\n"
        "  Mint one with:  alpha500 token\n"
    )


def identify(presented: str | None) -> Principal | None:
    """Match a presented secret against the configured tokens.

    Every candidate is compared even after a match, so the time taken does not
    reveal which token was hit or how many are configured.
    """
    tokens = configured_tokens()
    if not tokens:
        return None
    if not presented:
        return None

    found: Principal | None = None
    for label, value in tokens.items():
        if secrets.compare_digest(presented, value):
            found = Principal(label=label)
    return found


def bearer_from_header(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None


def mint_token() -> str:
    """A new token. 32 bytes of urandom, URL-safe, ~256 bits."""
    return secrets.token_urlsafe(32)
