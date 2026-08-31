"""Entitlement provider registry.

The product asks :func:`get_entitlements`; what answers depends on what is installed. The
open-source build gets :class:`UnlimitedEntitlements` and never reaches for a Stripe key;
the cloud image registers its own provider at start-up.

Deliberately a registry rather than an import: the product must not name the commercial
package, or the package is not separable.
"""

from __future__ import annotations

from app.entitlements.base import Entitlements, QuotaExceededError
from app.entitlements.unlimited import UnlimitedEntitlements

__all__ = [
    "Entitlements",
    "QuotaExceededError",
    "UnlimitedEntitlements",
    "get_entitlements",
    "reset_entitlements",
    "set_entitlements",
]

#: A one-slot holder rather than a module `global`. The two PLW0603 suppressions the
#: `global` form needed bought nothing, and the suppression ratchet asking whether they
#: were worth recording was the right prompt: the honest answer was to remove the need.
_slot: dict[str, Entitlements] = {}


def set_entitlements(provider: Entitlements) -> None:
    """Install a provider. Called once, by the cloud package, at start-up."""
    _slot["provider"] = provider


def reset_entitlements() -> None:
    """Drop back to the permissive default. For tests, and for a cloud image that has
    lost its billing configuration and should degrade to working rather than to broken."""
    _slot.pop("provider", None)


def get_entitlements() -> Entitlements:
    return _slot.get("provider") or UnlimitedEntitlements()
