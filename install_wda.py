#!/usr/bin/env python3
"""Instala ou repara o WebDriverAgent no iPhone via Appium.

Executado pela GUI (DiagTab > Instalar WDA).
Saidas parseadas pela GUI:
  WDA_BUNDLE:<bundle-id>   → sucesso, bundle ID detectado
  WDA_ERROR:<msg>          → falha
"""
import sys
import os
import subprocess
import shutil

sys.path.insert(0, os.path.dirname(__file__))

APPIUM_URL = "http://127.0.0.1:4723"
BUNDLE_ID  = "net.whatsapp.WhatsApp"


def _detect_bundle_via_ideviceinstaller() -> str:
    ii = shutil.which("ideviceinstaller")
    if not ii:
        return ""
    try:
        out = subprocess.run([ii, "-l"], capture_output=True, text=True, timeout=15)
        for line in out.stdout.splitlines():
            low = line.lower()
            if "webdriveragent" in low or ("runner" in low and "xctrunner" in low):
                parts = line.split(",")
                if parts:
                    return parts[0].strip()
    except Exception:
        pass
    return ""


def main():
    try:
        from appium import webdriver
        from appium.options import XCUITestOptions
    except ImportError:
        print("WDA_ERROR:appium-python-client nao instalado no venv")
        sys.exit(1)

    print("INFO Iniciando instalação do WebDriverAgent...")
    print("INFO Isso pode levar de 3 a 7 minutos na primeira vez.")
    print("INFO Xcode vai compilar o WDA em segundo plano — aguarde.")
    sys.stdout.flush()

    opts = XCUITestOptions()
    opts.udid                          = "auto"
    opts.bundle_id                     = BUNDLE_ID
    opts.no_reset                      = True
    opts.set_capability("autoAcceptAlerts",     False)
    opts.set_capability("autoDismissAlerts",    False)
    opts.set_capability("waitForQuiescence",    False)
    opts.set_capability("autoLaunch",           False)
    opts.set_capability("wdaLaunchTimeout",     600_000)   # 10 min
    opts.set_capability("wdaConnectionTimeout", 600_000)
    opts.set_capability("showXcodeLog",         True)
    opts.set_capability("wdaStartupRetries",    3)
    opts.set_capability("usePrebuiltWDA",       False)     # força reinstalação

    try:
        driver = webdriver.Remote(APPIUM_URL, options=opts)
    except Exception as exc:
        msg = str(exc)
        if "41" in msg or "Not authorized" in msg:
            print("WDA_ERROR:iPhone nao autorizou — desbloqueie e tente novamente")
        elif "not initialized" in msg.lower():
            print("WDA_ERROR:Falha ao compilar WDA. Verifique se o Xcode está instalado "
                  "e se o Mac está autorizado a desenvolver para este iPhone "
                  "(Ajustes > Geral > VPN e Gestão do Dispositivo).")
        else:
            print(f"WDA_ERROR:{exc}")
        sys.exit(1)

    # Detecta o bundle ID
    wda_bundle = ""
    try:
        caps = driver.capabilities or {}
        wda_bundle = (
            caps.get("wdaBundleId") or
            caps.get("updatedWDABundleId") or
            ""
        )
    except Exception:
        pass

    try:
        driver.quit()
    except Exception:
        pass

    if not wda_bundle:
        wda_bundle = _detect_bundle_via_ideviceinstaller()

    if wda_bundle:
        print(f"INFO WDA instalado com sucesso!")
        print(f"WDA_BUNDLE:{wda_bundle}")
    else:
        # WDA instalou mas nao conseguimos detectar o bundle ID
        print("INFO WDA instalado. Bundle ID nao detectado automaticamente.")
        print("INFO Deixe o campo 'WDA Bundle ID' vazio — o Appium vai reusar o WDA instalado.")
        print("WDA_BUNDLE:")


if __name__ == "__main__":
    main()
