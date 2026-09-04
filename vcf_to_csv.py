"""Converte contatos exportados do Mac (Contatos.app -> vCard .vcf) para o CSV
que os scripts usam (name,phone).

Por que existe: no Android da para puxar os contatos por adb; no iPhone NAO.
O caminho suportado e exportar do app Contatos do macOS (que sincroniza com o
iCloud do iPhone) e converter aqui.

Uso:
  python3 vcf_to_csv.py contatos.vcf -o contatos.csv
  python3 vcf_to_csv.py contatos.vcf -o contatos.csv --region BR --split 256

--split N grava tambem contatos.lote001.csv, contatos.lote002.csv ... com N
contatos cada (util para operar uma lista por vez).

Privacidade: le e escreve apenas localmente; nao imprime numeros completos.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys

try:
    import phonenumbers
except ImportError:  # o conversor funciona sem, mas sem validacao E.164
    phonenumbers = None

# Linhas dobradas do vCard continuam com espaco/tab no inicio (RFC 6350).
FOLD_RE = re.compile(r"\r?\n[ \t]")
TEL_RE = re.compile(r"^TEL[^:]*:(.+)$", re.IGNORECASE)
FN_RE = re.compile(r"^FN[^:]*:(.+)$", re.IGNORECASE)
N_RE = re.compile(r"^N[^:]*:(.+)$", re.IGNORECASE)


def _decode_quoted_printable(value: str) -> str:
    if "=" not in value:
        return value
    try:
        import quopri
        return quopri.decodestring(value.encode("utf-8", "ignore")).decode("utf-8", "ignore")
    except Exception:
        return value


def parse_vcf(path: str) -> list[tuple[str, str]]:
    """Retorna [(nome, telefone), ...] — um item por telefone encontrado."""
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    raw = FOLD_RE.sub("", raw)  # desdobra linhas continuadas

    out: list[tuple[str, str]] = []
    name = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("BEGIN:VCARD"):
            name = ""
            continue
        if upper.startswith("END:VCARD"):
            name = ""
            continue

        m = FN_RE.match(line)
        if m:
            name = _decode_quoted_printable(m.group(1).strip())
            continue
        if not name:
            m = N_RE.match(line)
            if m:
                parts = [p.strip() for p in m.group(1).split(";")]
                # N:Sobrenome;Nome;...  -> "Nome Sobrenome"
                given = parts[1] if len(parts) > 1 else ""
                family = parts[0] if parts else ""
                name = _decode_quoted_printable(" ".join(x for x in (given, family) if x)).strip()
                continue
        m = TEL_RE.match(line)
        if m:
            phone = _decode_quoted_printable(m.group(1).strip())
            if phone:
                out.append((name, phone))
    return out


def to_e164(raw: str, region: str) -> str | None:
    if phonenumbers is None:
        digits = re.sub(r"\D", "", raw)
        return f"+{digits}" if len(digits) >= 10 else None
    try:
        parsed = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def write_csv(rows: list[tuple[str, str]], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "phone"])
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vcf", help="arquivo .vcf exportado do Contatos.app")
    ap.add_argument("-o", "--out", default="contatos.csv")
    ap.add_argument("--region", default="BR", help="regiao padrao para numeros sem DDI")
    ap.add_argument("--split", type=int, default=0,
                    help="tambem gerar arquivos por lote de N contatos (ex.: 256)")
    args = ap.parse_args()

    if not os.path.exists(args.vcf):
        print(f"arquivo nao encontrado: {args.vcf}", file=sys.stderr)
        return 2

    pairs = parse_vcf(args.vcf)
    seen: dict[str, tuple[str, str]] = {}
    invalidos = 0
    for name, phone in pairs:
        e164 = to_e164(phone, args.region)
        if e164 is None:
            invalidos += 1
            continue
        seen.setdefault(e164, (name, e164))

    rows = list(seen.values())
    write_csv(rows, args.out)
    print(f"vCard: {len(pairs)} telefones lidos")
    print(f"validos e unicos: {len(rows)}  |  descartados (invalidos): {invalidos}")
    print(f"CSV gravado: {args.out}")

    if args.split and rows:
        base, ext = os.path.splitext(args.out)
        n = 0
        for i in range(0, len(rows), args.split):
            n += 1
            part = f"{base}.lote{n:03d}{ext}"
            write_csv(rows[i:i + args.split], part)
        print(f"{n} arquivo(s) de lote gerados ({args.split} por lote)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
