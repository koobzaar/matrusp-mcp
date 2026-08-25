"""Overrides de campus explícitos, versionados e auditáveis.

O crawler não infere ``Outro``: ausência de mapeamento permanece ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .domain import Unit
from .normalize import normalize_text

_CANONICAL = {
    "sao paulo": "São Paulo",
    "cidade universitaria": "São Paulo",
    "butanta": "São Paulo",
    "ribeirao preto": "Ribeirão Preto",
    "sao carlos": "São Carlos",
    "piracicaba": "Piracicaba",
    "pirassununga": "Pirassununga",
    "lorena": "Lorena",
    "bauru": "Bauru",
    "santos": "Santos",
    "araraquara": "Araraquara",
}


def normalize_campus(value: str | None) -> str | None:
    """Return a canonical campus name without inventing an ``Outro`` bucket."""
    if value is None or not value.strip():
        return None
    cleaned = " ".join(value.split())
    if normalize_text(cleaned) == "outro":
        return None
    return _CANONICAL.get(normalize_text(cleaned), cleaned)


@dataclass(frozen=True, slots=True)
class CampusOverride:
    unit_code: str
    campus: str
    version: str
    provenance: str


def apply_campus_override(unit: Unit, override: CampusOverride | None) -> Unit:
    if override is None:
        return unit
    if (
        override.unit_code != unit.code
        or not override.campus.strip()
        or override.campus.casefold() == "outro"
    ):
        raise ValueError("invalid campus override")
    return Unit(
        unit.code,
        unit.name,
        normalize_campus(override.campus),
        unit.source_campus_name,
        f"{override.version}:{override.provenance}",
    )
