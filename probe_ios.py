"""Sonda a tela do WhatsApp SEM usar page_source (evita o timeout de 240s do
WDA na tela de Conversas, que e enorme).

Em vez de baixar a arvore inteira, faz consultas DIRETAS por elemento
(find_elements por tipo/predicado) — o WDA responde rapido porque nao serializa
tudo. Lista os botoes e textos da tela (poucos, na barra de navegacao) com seus
rotulos, para voce achar o botao "Listas de transmissao".

Nao clica em nada. Rotulos que parecam nome/numero de contato sao redigidos.

Uso (na aba Conversas do WhatsApp):
  python3 probe_ios.py --wda-bundle com.voce.WDARunner
  python3 probe_ios.py --out sonda-conversas.json
"""

from __future__ import annotations

import argparse
import json
import sys

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import WebDriverException

import diag_ios  # reusa a redacao
from spike_ios import build_driver

# Tipos que costumam conter a acao/entrada de tela (poucos = consulta barata).
TIPOS = [
    "XCUIElementTypeButton",
    "XCUIElementTypeStaticText",
    "XCUIElementTypeNavigationBar",
    "XCUIElementTypeTabBar",
    "XCUIElementTypeCell",
    "XCUIElementTypeOther",
]

# Candidatos ao botao "Listas de transmissao" (pt-BR / en).
CANDIDATOS = [
    "Listas de transmissão", "Listas de transmissao", "Broadcast Lists",
    "Listas", "Broadcast", "Nova lista", "New List",
]


def _safe(tipo: str, key: str, val: str | None) -> str | None:
    """Rotulos de CONTROLE (botoes, barra de navegacao, busca) sao chrome da UI —
    mostramos inteiros, pois e o que precisamos para achar o botao. Ja StaticText
    e Cell podem conter nome/numero de contato -> redigimos com a regra normal."""
    if not val:
        return val
    controles = ("Button", "NavigationBar", "SearchField", "TabBar", "SegmentedControl")
    if any(c in (tipo or "") for c in controles):
        return val  # controle: sem redacao
    return diag_ios.redact(val)


def attrs(el) -> dict:
    out = {}
    for a in ("type", "name", "label", "value", "enabled", "visible"):
        try:
            v = el.get_attribute(a)
        except WebDriverException:
            v = None
        out[a] = v
    tipo = out.get("type") or ""
    for k in ("name", "label", "value"):
        out[k] = _safe(tipo, k, out.get(k))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:4723")
    ap.add_argument("--wda-bundle", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--limite", type=int, default=40,
                    help="max de elementos por tipo (evita telas pesadas)")
    args = ap.parse_args()

    d = build_driver(args.server, args.wda_bundle or None)
    resultado: dict = {"candidatos_encontrados": [], "por_tipo": {}}
    try:
        # 1) checa diretamente cada candidato ao botao de transmissao
        for texto in CANDIDATOS:
            pred = (f'label == "{texto}" OR name == "{texto}" '
                    f'OR label CONTAINS "{texto}" OR name CONTAINS "{texto}"')
            try:
                els = d.find_elements(AppiumBy.IOS_PREDICATE, pred)
            except WebDriverException:
                els = []
            for el in els:
                info = attrs(el)
                info["casou_com"] = texto
                resultado["candidatos_encontrados"].append(info)

        # 2) lista os elementos de cada tipo (barra de navegacao = poucos)
        for tipo in TIPOS:
            try:
                els = d.find_elements(AppiumBy.CLASS_NAME, tipo)
            except WebDriverException:
                els = []
            lista = []
            for el in els[: args.limite]:
                info = attrs(el)
                # so vale a pena listar o que tem algum rotulo
                if info.get("name") or info.get("label") or info.get("value"):
                    lista.append(info)
            resultado["por_tipo"][tipo] = {"total": len(els), "amostra": lista}

        texto = json.dumps(resultado, ensure_ascii=False, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(texto)
            print(f"sonda salva em {args.out}")
            enc = resultado["candidatos_encontrados"]
            if enc:
                print(f"CANDIDATOS AO BOTAO DE TRANSMISSAO encontrados: {len(enc)}")
                for c in enc:
                    print(f"  type={c.get('type')} casou_com={c.get('casou_com')} "
                          f"enabled={c.get('enabled')} visible={c.get('visible')}")
            else:
                print("Nenhum candidato 'Listas de transmissao' encontrado nesta tela.")
                print("Confirme que esta na aba CONVERSAS (Chats). Envie o arquivo.")
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
