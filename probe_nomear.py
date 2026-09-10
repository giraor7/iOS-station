"""Descobre os seletores da tela que aparece DEPOIS de "Criar" a lista — para
nomear a lista ("Lista de transmissão 01") sem adivinhar.

Rode com a conversa de uma lista de transmissao ABERTA no iPhone (crie uma
lista pela estacao ou a mao e deixe a conversa na tela). O script tira tres
"fotos" da arvore (so botoes, textos, campos e barra de navegacao; nomes e
numeros sao redigidos) e pede para voce tocar no iPhone entre elas:

  1. a conversa da lista (titulo "Mensagens" no topo);
  2. depois de tocar no titulo (tela de informacoes da lista);
  3. depois de tocar no nome/editar (campo de texto do nome).

Uso (com o appium rodando):
  python3 probe_nomear.py
Saida: inventory-nomear-1.json, -2.json, -3.json — envie os tres.

Nao toca em nada sozinho: quem toca no iPhone e voce.
"""

from __future__ import annotations

import json
import sys

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import WebDriverException

from spike_ios import build_driver

TIPOS = ("XCUIElementTypeNavigationBar", "XCUIElementTypeButton",
         "XCUIElementTypeStaticText", "XCUIElementTypeTextField",
         "XCUIElementTypeTextView", "XCUIElementTypeSearchField",
         "XCUIElementTypeCell", "XCUIElementTypeSwitch")


def foto(driver, caminho: str) -> None:
    import diag_ios
    itens = []
    for tipo in TIPOS:
        try:
            els = driver.find_elements(AppiumBy.CLASS_NAME, tipo)
        except WebDriverException:
            continue
        for el in els[:80]:
            rec = {"type": tipo}
            for a in ("name", "label", "value", "enabled", "visible"):
                try:
                    v = el.get_attribute(a)
                except WebDriverException:
                    v = None
                rec[a] = diag_ios.redact(v) if a in ("name", "label", "value") and v else v
            try:
                r = el.rect
                rec["y"] = int(r.get("y", 0))
            except WebDriverException:
                pass
            if rec.get("name") or rec.get("label") or rec.get("value"):
                itens.append(rec)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump({"total": len(itens), "elementos": itens}, f, ensure_ascii=False, indent=2)
    print(f"  salvo {caminho} ({len(itens)} elementos)")


def main() -> int:
    driver = build_driver("http://127.0.0.1:4723", None)
    try:
        for depth in (12, 16, 20):
            try:
                driver.update_settings({"snapshotMaxDepth": depth})
            except WebDriverException:
                pass
            print(f"\n[profundidade {depth}]")
            input("1) Deixe a CONVERSA DA LISTA aberta no iPhone e aperte Enter... ")
            foto(driver, f"inventory-nomear-1-p{depth}.json")
            input("2) Toque no TITULO da conversa (\"Mensagens\") e aperte Enter... ")
            foto(driver, f"inventory-nomear-2-p{depth}.json")
            input("3) Toque no NOME / editar nome (ate aparecer o campo de texto) e aperte Enter... ")
            foto(driver, f"inventory-nomear-3-p{depth}.json")
            input("   Volte para a conversa da lista (2x Voltar) e aperte Enter para a proxima profundidade... ")
        print("\nEnvie os arquivos inventory-nomear-*.json.")
        return 0
    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass


if __name__ == "__main__":
    sys.exit(main())
