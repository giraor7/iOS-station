"""Checagem de ambiente ANTES de operar (rode isto primeiro no Mac).

Verifica, em ordem, tudo que costuma falhar: macOS, Xcode, ferramentas de linha
de comando, Appium + driver XCUITest, dependencias Python, iPhone conectado,
Modo de Desenvolvedor e se o WhatsApp esta instalado no aparelho.

Uso:
  python3 doctor_ios.py

Nao toca no WhatsApp e nao instala nada: apenas diagnostica e diz o que fazer.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys

OK = "OK  "
WARN = "AVISO"
FAIL = "FALHA"

results: list[tuple[str, str, str]] = []  # (status, item, dica)


def check(status: str, item: str, dica: str = "") -> None:
    results.append((status, item, dica))
    line = f"[{status}] {item}"
    if dica and status != OK:
        line += "\n        -> " + dica
    print(line, flush=True)


def run(cmd: list[str], timeout: int = 25) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def check_macos() -> None:
    if platform.system() != "Darwin":
        check(FAIL, "Sistema: " + platform.system() + " (precisa ser macOS)",
              "A automacao de iPhone SO funciona a partir de um Mac. "
              "Um PC Windows nao consegue controlar a tela do iPhone.")
        return
    check(OK, f"macOS {platform.mac_ver()[0]} ({platform.machine()})")


def check_xcode() -> None:
    code, out = run(["xcodebuild", "-version"])
    if code != 0:
        check(FAIL, "Xcode nao encontrado",
              "Instale o Xcode pela App Store e abra-o uma vez para aceitar a licenca.")
        return
    ver = out.strip().splitlines()[0] if out.strip() else "?"
    check(OK, ver)

    code, out = run(["xcode-select", "-p"])
    if code != 0 or "CommandLineTools" in out:
        check(WARN, "xcode-select aponta para Command Line Tools, nao para o Xcode",
              "Rode: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer")
    else:
        check(OK, "xcode-select: " + out.strip())


def check_tools() -> None:
    for tool, dica, hard in (
        ("node", "Instale com: brew install node", True),
        ("python3", "Instale com: brew install python@3.12", True),
        ("idevice_id", "Instale com: brew install libimobiledevice", False),
    ):
        if shutil.which(tool):
            check(OK, tool + " presente")
        else:
            check(FAIL if hard else WARN, tool + " ausente", dica)


def check_appium() -> None:
    if not shutil.which("appium"):
        check(FAIL, "Appium ausente", "Instale com: npm install -g appium")
        return
    code, out = run(["appium", "-v"])
    if code == 0:
        check(OK, "Appium " + out.strip())
    else:
        check(WARN, "Appium nao respondeu -v", "Reinstale com: npm install -g appium")

    code, out = run(["appium", "driver", "list", "--installed"], timeout=90)
    if "xcuitest" in out.lower():
        m = re.search(r"xcuitest@([\d.]+)", out)
        check(OK, "driver XCUITest " + (m.group(1) if m else "instalado"))
    else:
        check(FAIL, "driver XCUITest ausente",
              "Instale com: appium driver install xcuitest")


def check_python_deps() -> None:
    missing = []
    for mod in ("appium", "selenium", "phonenumbers"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        check(FAIL, "Dependencias Python faltando: " + ", ".join(missing),
              "Rode: python3 -m pip install -r requirements.txt")
    else:
        check(OK, "Dependencias Python (appium, selenium, phonenumbers)")


def check_appium_server() -> None:
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:4723/status", timeout=3) as r:
            data = json.loads(r.read().decode())
        ver = data.get("value", {}).get("build", {}).get("version", "?")
        check(OK, "Servidor Appium respondendo (v" + str(ver) + ")")
    except Exception:
        check(WARN, "Servidor Appium nao esta rodando",
              "Abra outro terminal e deixe rodando: appium")



def check_device() -> None:
    """Verifica se ha exatamente um iPhone conectado por USB.

    A identidade fisica (UDID) nao e capturada nem exibida: o Device Gateway
    (Appium) fara a selecao automatica via USB usando o valor 'auto'."""
    if not shutil.which("idevice_id"):
        check(WARN, "idevice_id ausente (libimobiledevice)",
              "Instale com: brew install libimobiledevice — "
              "necessario para confirmar que o iPhone esta conectado")
        return

    code, out = run(["idevice_id", "-l"])
    count = len([u for u in out.splitlines() if u.strip()]) if code == 0 else 0

    if count == 0:
        check(WARN, "Nenhum iPhone detectado por USB",
              "Conecte o iPhone, desbloqueie e toque em Confiar neste computador.")
        return
    if count > 1:
        check(WARN, f"{count} iPhones conectados",
              "Deixe apenas UM iPhone conectado: o Appium usa 'auto' e "
              "pode escolher o errado com multiplos dispositivos.")
    else:
        check(OK, "1 iPhone conectado por USB")

    code, out = run(["ideviceinfo", "-k", "ProductVersion"])
    if code == 0 and out.strip():
        ios = out.strip()
        check(OK, "iOS " + ios)
        try:
            if int(ios.split(".")[0]) >= 16:
                check(WARN, "iOS 16+ exige Modo de Desenvolvedor ATIVADO",
                      "No iPhone: Ajustes > Privacidade e Seguranca > Modo de Desenvolvedor "
                      "> Ativar (o aparelho reinicia). O item so aparece depois que o Xcode "
                      "tentar rodar algo no aparelho pela primeira vez.")
        except ValueError:
            pass
    else:
        check(WARN, "Nao consegui ler a versao do iOS",
              "Verifique se o aparelho esta desbloqueado e confiou no computador.")

    if shutil.which("ideviceinstaller"):
        code, out = run(["ideviceinstaller", "-l"], timeout=90)
        if code == 0 and "whatsapp" in out.lower():
            check(OK, "WhatsApp detectado no aparelho")
        elif code == 0:
            check(FAIL, "WhatsApp NAO encontrado no aparelho",
                  "Instale e faca login no WhatsApp antes de automatizar.")
        else:
            check(WARN, "Nao consegui listar apps do aparelho",
                  "Normal em iOS recentes; confirme manualmente que o WhatsApp esta instalado "
                  "e que voce anotou a versao (WhatsApp > Ajustes > Ajuda).")
    else:
        check(WARN, "ideviceinstaller ausente (opcional)",
              "brew install ideviceinstaller — ajuda a confirmar a versao do WhatsApp.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    args = ap.parse_args()

    print("=== Lista Local - diagnostico da estacao iOS ===\n")
    check_macos()
    check_xcode()
    check_tools()
    check_appium()
    check_python_deps()
    check_appium_server()
    check_device()

    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN]
    print("\n=== RESUMO ===")
    print("OK: %d  |  avisos: %d  |  falhas: %d"
          % (len(results) - len(fails) - len(warns), len(warns), len(fails)))
    if fails:
        print("\nCorrija as FALHAS antes de continuar:")
        for _, item, dica in fails:
            print("  - " + item)
            if dica:
                print("    " + dica)
        return 1
    if warns:
        print("\nAvisos (podem impedir a execucao dependendo do caso):")
        for _, item, _ in warns:
            print("  - " + item)
    print("\nProximo passo: SETUP-MAC.md secao 6 (descoberta de seletores).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
