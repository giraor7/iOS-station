"""Descoberta SOMENTE-LEITURA da UI do WhatsApp iOS (rode no Mac, com iPhone).

Este e o PRIMEIRO passo no iPhone. Ele inventaria os elementos da tela atual
para voce preencher ios_selectors.py com os valores REAIS. Nao clica em nada,
nao digita nada, nao cria nada.

Privacidade: por padrao, textos que parecam nome ou numero de contato sao
REDIGIDOS. So rotulos de interface conhecidos (Pesquisar, Criar, Cancelar...)
aparecem inteiros. Use --raw apenas se souber que a tela nao tem dados pessoais.

Uso (repita em CADA tela do fluxo):
  python3 diag_ios.py --inventory --wda-bundle com.voce.WDARunner
  python3 diag_ios.py --inventory --out tela-picker.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET

from spike_ios import build_driver

# Rotulos de interface que podem ser mostrados por inteiro (nao sao dados pessoais).
UI_LABELS = {
    "Pesquisar", "Search", "Cancelar", "Cancel", "Criar", "Create",
    "Concluído", "Concluido", "Done", "Avançar", "Next", "Voltar", "Back",
    "Nova lista", "New List", "Nova transmissão", "New Broadcast",
    "Listas de transmissão", "Broadcast Lists", "Listas", "Conversas", "Chats",
    "Selecionado", "Selected", "Limpar texto", "Clear text", "Editar", "Edit",
    "Adicionar", "Add", "Contatos", "Contacts", "Configurações", "Settings",
}

PHONE_RE = re.compile(r"\d")


def redact(value: str) -> str:
    """Mantem rotulos de UI; redige qualquer outro texto (pode ser dado pessoal)."""
    if not value:
        return ""
    v = value.strip()
    if v in UI_LABELS:
        return v
    if PHONE_RE.search(v):
        return "<REDIGIDO:numero-ou-texto-com-digitos>"
    return f"<REDIGIDO:texto-{len(v)}-chars>"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:4723")
    ap.add_argument("--wda-bundle", default="")
    ap.add_argument("--inventory", action="store_true", help="(padrao) inventaria a tela")
    ap.add_argument("--out", default="", help="salvar em arquivo JSON")
    ap.add_argument("--only-interactive", action="store_true",
                    help="listar apenas elementos clicaveis/habilitados")
    ap.add_argument("--raw", action="store_true",
                    help="NAO redigir textos (use so em tela sem dados pessoais)")
    args = ap.parse_args()

    d = build_driver(args.server, args.wda_bundle or None)
    try:
        try:
            source = d.page_source
        except Exception as e:
            # Na tela de Conversas do WhatsApp o page_source do iOS costuma dar
            # timeout (arvore enorme). Nesse caso, use o probe, que NAO baixa a
            # arvore toda.
            print("ERRO ao obter a arvore (page_source):", str(e)[:120], file=sys.stderr)
            print("\nEsta tela e pesada demais para o page_source. Use o probe, "
                  "que consulta so os botoes/textos (rapido, sem timeout):",
                  file=sys.stderr)
            print("  python3 probe_ios.py "
                  f"--wda-bundle {args.wda_bundle or '<bundle>'} --out sonda.json",
                  file=sys.stderr)
            return 4
        try:
            root = ET.fromstring(source)
        except ET.ParseError as e:
            print(f"nao consegui interpretar a arvore: {e}", file=sys.stderr)
            return 4

        itens = []
        for node in root.iter():
            a = node.attrib
            # No iOS a TAG e o tipo (XCUIElementTypeButton, ...); `type` pode faltar.
            etype = a.get("type") or node.tag
            name = a.get("name", "")
            label = a.get("label", "")
            value = a.get("value", "")
            enabled = a.get("enabled", "")
            visible = a.get("visible", "")
            if args.only_interactive and not (enabled == "true" and visible == "true"):
                continue
            if not (name or label or value):
                continue
            itens.append({
                "type": etype,
                "name": name if args.raw else redact(name),
                "label": label if args.raw else redact(label),
                "value": value if args.raw else redact(value),
                "enabled": enabled,
                "visible": visible,
                # sugestao de localizador pronta para colar em ios_selectors.py
                "sugestao": (f'accessibility_id="{name}"' if name and name in UI_LABELS
                             else f'class_chain="**/{etype}"'),
            })

        # Resumo por tipo — ajuda a entender a tela rapidamente.
        tipos: dict[str, int] = {}
        for it in itens:
            tipos[it["type"]] = tipos.get(it["type"], 0) + 1

        saida = {
            "bundle": "net.whatsapp.WhatsApp",
            "total_elementos": len(itens),
            "por_tipo": dict(sorted(tipos.items(), key=lambda kv: -kv[1])),
            "elementos": itens,
        }
        texto = json.dumps(saida, ensure_ascii=False, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(texto)
            print(f"inventario salvo em {args.out} ({len(itens)} elementos)")
            print("resumo por tipo:", saida["por_tipo"])
        else:
            print(texto)
        return 0
    finally:
        try:
            d.quit()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
