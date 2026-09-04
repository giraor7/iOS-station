"""Regras puras de contatos: normalizacao E.164, dedupe e lotes de 256.

Sem Appium aqui — testavel isoladamente (test_batching.py). Espelha a logica
do app Android (ContactNormalizer.kt), para paridade de comportamento.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass

import phonenumbers

BATCH_LIMIT = 256


@dataclass(frozen=True)
class Contact:
    name: str
    raw_phone: str


@dataclass(frozen=True)
class NormalizedContact:
    e164: str
    name: str


def to_e164(raw: str, region: str = "BR") -> str | None:
    try:
        parsed = phonenumbers.parse(raw.strip(), region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize(contacts: list[Contact], region: str = "BR") -> list[NormalizedContact]:
    """Normaliza e deduplica por numero, preservando a 1a ocorrencia."""
    seen: dict[str, NormalizedContact] = {}
    for c in contacts:
        e164 = to_e164(c.raw_phone, region)
        if e164 is None:
            continue
        seen.setdefault(e164, NormalizedContact(e164, c.name))
    return list(seen.values())


def batch(nums: list[NormalizedContact], limit: int = BATCH_LIMIT) -> list[list[NormalizedContact]]:
    return [nums[i:i + limit] for i in range(0, len(nums), limit)]


def label_for(batch_index: int) -> str:
    """1 -> 'Transmissão 001'."""
    return f"Transmissão {batch_index:03d}"


def load_csv(path: str) -> list[Contact]:
    """CSV com cabecalho: name,phone (ou nome,telefone). Tolerante a colunas extras."""
    out: list[Contact] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}
        name_col = fields.get("name") or fields.get("nome")
        phone_col = fields.get("phone") or fields.get("telefone") or fields.get("numero")
        if not phone_col:
            raise ValueError("CSV precisa de coluna 'phone'/'telefone'/'numero'")
        for row in reader:
            phone = (row.get(phone_col) or "").strip()
            name = (row.get(name_col) or "").strip() if name_col else ""
            if phone:
                out.append(Contact(name=name, raw_phone=phone))
    return out
