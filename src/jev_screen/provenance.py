"""Canonical screening context and checksums. These are consistency checks, not signatures."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .client import FakeJev, JevClient
from .criteria import Criteria
from .records import Record

ENGINE_VERSION = "0.2.0"
RULE_VERSION = "include-exclude-maybe-v1"
MESSAGES = {
    "context": "Reprise : fournissez les dossiers et le fournisseur / Resume requires records and provider / La reanudación requiere registros y proveedor",
    "header": "Colonnes incompatibles : utilisez une nouvelle sortie / Columns do not match: use a new output / Las columnas no coinciden: use una salida nueva",
    "protocol": "Protocole modifié : utilisez une nouvelle sortie / Protocol changed: use a new output / Protocolo modificado: use una salida nueva",
    "record": "Dossier modifié ou absent : utilisez une nouvelle sortie / Record changed or absent: use a new output / Registro modificado o ausente: use una salida nueva",
    "row": "Ligne modifiée, incomplète ou dupliquée : utilisez une nouvelle sortie / Edited, incomplete or duplicate row: use a new output / Fila modificada, incompleta o duplicada: use una salida nueva",
    "provider": "Fournisseur personnalisé : resume_identity et model sont requis / Custom provider requires resume_identity and model / El proveedor personalizado requiere resume_identity y model",
    "cache": "Réponse en cache invalide : utilisez un nouveau cache / Invalid cached response: use a new cache / Respuesta en caché inválida: use una caché nueva",
    "answer": "Réponse du fournisseur invalide / Invalid provider response / Respuesta del proveedor inválida",
    "receipt": "Le reçu exige un nouveau chemin distinct des entrées et de la sortie CSV / Receipt requires a new path distinct from inputs and CSV output / El recibo requiere una ruta nueva distinta de las entradas y la salida CSV",
}


class ProtocolError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(MESSAGES[code])


def fingerprint(value: Any) -> str:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        raise ProtocolError("provider") from None


def provider_identity(provider: Any) -> dict[str, str]:
    if type(provider) is FakeJev:
        identity = {
            "kind": "fixtures",
            "fixtures_sha256": fingerprint(provider.fixtures),
        }
    elif type(provider) is JevClient:
        identity = {"kind": "api", "endpoint_sha256": fingerprint(provider.endpoint)}
    else:
        if getattr(provider, "resume_identity", None) is None:
            raise ProtocolError("provider")
        identity = {
            "kind": "custom",
            "identity_sha256": fingerprint(provider.resume_identity),
            "type": type(provider).__module__ + "." + type(provider).__qualname__,
        }
    model = getattr(provider, "model", None)
    if not isinstance(model, str) or not model:
        raise ProtocolError("provider")
    return {**identity, "model": model}


def protocol_snapshot(
    criteria: Criteria, provider: Any, *, title_only: bool = False
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "rule_version": RULE_VERSION,
        "criteria": asdict(criteria),
        "questions": criteria.questions(),
        "title_only": bool(title_only),
        "provider": provider_identity(provider),
    }


def record_fingerprint(record: Record) -> str:
    return fingerprint(record.to_dict())


def row_fingerprint(row: dict[str, Any]) -> str:
    return fingerprint(
        {key: str(value) for key, value in row.items() if key != "row_sha256"}
    )


@dataclass(frozen=True)
class ScreeningContext:
    snapshot: dict[str, Any]
    protocol_sha256: str
    provider_sha256: str

    @classmethod
    def build(
        cls, criteria: Criteria, provider: Any, *, title_only: bool = False
    ) -> "ScreeningContext":
        snapshot = protocol_snapshot(criteria, provider, title_only=title_only)
        return cls(snapshot, fingerprint(snapshot), fingerprint(snapshot["provider"]))

    def cache_key(self, request_key: str) -> str:
        # Policy thresholds affect decisions, not the raw model answer. Cache reuse under a
        # changed policy is legitimate in a NEW output, with the rule applied again.
        return fingerprint(
            {
                "schema_version": 1,
                "provider_sha256": self.provider_sha256,
                "request_key": request_key,
            }
        )
