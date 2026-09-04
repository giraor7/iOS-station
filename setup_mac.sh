#!/usr/bin/env bash
# Setup da estacao de controle iOS no macOS (Apple Silicon ou Intel).
# Idempotente: pode rodar de novo sem quebrar. NAO instala o Xcode (App Store).
#
# Uso:
#   chmod +x setup_mac.sh
#   ./setup_mac.sh
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
echo "=== Lista Local - setup da estacao iOS ==="
echo

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERRO: este script so roda no macOS. A automacao de iPhone exige um Mac."
  exit 1
fi

echo "==> 1/7 Xcode (pre-requisito manual)"
if ! xcodebuild -version >/dev/null 2>&1; then
  echo "    ATENCAO: Xcode nao encontrado."
  echo "    Instale pela App Store, abra uma vez e aceite a licenca, depois rode este script de novo."
  echo "    Se ja instalou, rode: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"
  exit 1
fi
xcodebuild -version | head -1
sudo xcodebuild -license accept 2>/dev/null || true

echo
echo "==> 2/7 Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
else
  echo "    ja instalado: $(brew --version | head -1)"
fi

echo
echo "==> 3/7 Node, Python e ferramentas de dispositivo"
brew install node python@3.12 libimobiledevice ideviceinstaller || true

echo
echo "==> 4/7 Appium 2 + driver XCUITest"
if ! command -v appium >/dev/null 2>&1; then
  npm install -g appium
else
  echo "    appium ja instalado: $(appium -v)"
fi
if appium driver list --installed 2>&1 | grep -qi xcuitest; then
  appium driver update xcuitest || true
else
  appium driver install xcuitest
fi

echo
echo "==> 5/7 Dependencias Python"
python3 -m pip install --user --upgrade -r "$AQUI/requirements.txt"

echo
echo "==> 6/7 Abrindo o projeto do WebDriverAgent no Xcode"
echo "    (assine o alvo WebDriverAgentRunner com a sua conta - ver SETUP-MAC.md secao 3)"
appium driver run xcuitest open-wda || \
  echo "    nao consegui abrir automaticamente; veja o caminho na secao 3 do SETUP-MAC.md"

echo
echo "==> 7/7 Diagnostico"
python3 "$AQUI/doctor_ios.py" || true

echo
echo "=== Proximos passos ==="
echo "1. SETUP-MAC.md secao 3: assinar o WebDriverAgent no Xcode (uma vez)."
echo "2. SETUP-MAC.md secao 4: preparar o iPhone (Modo de Desenvolvedor + confiar)."
echo "3. Rodar: python3 test_local.py    (valida o pacote sem iPhone)"
echo "4. Rodar: appium                   (deixe em outro terminal)"
echo "5. SETUP-MAC.md secao 6: descobrir os seletores com diag_ios.py"
