"""Ultimo probe: abre o seletor de contatos da "Nova transmissao" pelo fluxo
CONFIRMADO e lista APENAS os controles dessa tela (campo de busca, botoes,
contagem de linhas). NAO toca em nenhum contato, NAO cria nada, NAO mostra
nomes nem numeros.

Serve para fixar os ultimos seletores: campo de busca e botao "Criar".

Uso (WhatsApp aberto na aba Conversas, appium rodando):
  python3 probe_picker.py --wda-bundle com.voce.WDARunner
"""

from __future__ import annotations

import argparse
import sys
import time

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import WebDriverException

from spike_ios import build_driver

CONTROLES = ("XCUIElementTypeButton", "XCUIElementTypeSearchField",
             "XCUIElementTypeTextField", "XCUIElementTypeNavigationBar")
CRIAR = ('label CONTAINS[c] "criar" OR label CONTAINS[c] "create" OR '
         'label CONTAINS[c] "conclu" OR label CONTAINS[c] "done" OR '
         'name CONTAINS[c] "create" OR name CONTAINS[c] "done" OR '
         'name CONTAINS[c] "Confirm"')


def acc(d, acc_id):
    try:
        els = d.find_elements(AppiumBy.ACCESSIBILITY_ID, acc_id)
    except WebDriverException:
        return None
    return els[0] if els else None


def attrs(el):
    out = {}
    for a in ("type", "name", "label", "value", "enabled"):
        try:
            out[a] = el.get_attribute(a)
        except WebDriverException:
            out[a] = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:4723")
    ap.add_argument("--wda-bundle", default="")
    args = ap.parse_args()

    d = build_driver(args.server, args.wda_bundle or None)
    try:
        time.sleep(3)
        tab = acc(d, "TabBarButton_Chats")
        if tab:
            tab.click(); time.sleep(1.5)
        mais = acc(d, "NavigationBar_NewChatButton")
        if not mais:
            print("NAO achei o '+' (NavigationBar_NewChatButton). Confirme a aba Conversas.")
            return 2
        mais.click(); time.sleep(2.5)
        cel = acc(d, "PickerView_NewBroadcastCell")
        if not cel:
            print("NAO achei 'Nova transmissao' (PickerView_NewBroadcastCell).")
            return 3
        cel.click(); time.sleep(3)
        print("=== seletor da TRANSMISSAO aberto ===")

        # linhas de contato: so a CONTAGEM (sem nomes/numeros)
        try:
            n_rows = len(d.find_elements(AppiumBy.ACCESSIBILITY_ID, "PickerView_ContactCell"))
            n_fone = len(d.find_elements(AppiumBy.ACCESSIBILITY_ID, "PickerView_ContactCell_PhoneNumber"))
        except WebDriverException:
            n_rows = n_fone = -1
        print(f"linhas de contato: {n_rows} | com campo de numero: {n_fone}")

        # controles (botoes/busca): rotulos de UI, sem dados pessoais
        for tipo in CONTROLES:
            try:
                els = d.find_elements(AppiumBy.CLASS_NAME, tipo)
            except WebDriverException:
                els = []
            print(f"== {tipo}: {len(els)}")
            for e in els[:15]:
                a = attrs(e)
                print(f"   name={a['name']!r} label={a['label']!r} value={a['value']!r} en={a['enabled']}")

        # botao de criar (provavelmente so aparece com 2+ selecionados)
        try:
            cr = d.find_elements(AppiumBy.IOS_PREDICATE, CRIAR)
        except WebDriverException:
            cr = []
        print(f"=== candidatos a botao CRIAR: {len(cr)} (0 e normal sem selecao)")
        for e in cr:
            a = attrs(e)
            print(f"   type={a['type']!r} name={a['name']!r} label={a['label']!r} en={a['enabled']}")
        print("\nNADA foi selecionado nem criado. Envie esta saida.")
        return 0
    finally:
        try:
            d.quit()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
