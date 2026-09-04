#!/usr/bin/env bash
# Atalho para iniciar a interface da Estação iOS no macOS com 2 cliques.
# Escolhe o Python certo (Tk 8.6+) e instala o que faltar no .venv.
cd "$(dirname "$0")"

# Arquivos baixados pelo navegador vêm com a marca de quarentena do macOS e o
# Finder pede confirmação para cada um. Depois que ESTE atalho foi aberto uma
# vez (botão direito › Abrir), tira a marca da pasta inteira: os próximos não
# perguntam mais.
xattr -dr com.apple.quarantine . 2>/dev/null || true

# Aberto pelo Finder, o PATH vem mínimo: sem Homebrew nem npm, o `appium` e o
# `idevice_id` não são encontrados. Acrescenta as pastas usuais.
for d in /opt/homebrew/bin /opt/homebrew/opt/node/bin /usr/local/bin \
         "$HOME/.npm-global/bin" "$HOME"/.nvm/versions/node/*/bin; do
    [ -d "$d" ] && PATH="$d:$PATH"
done
export PATH

if [ -f ".venv/bin/python" ]; then
    PY=".venv/bin/python"
elif [ -x "/opt/homebrew/bin/python3.12" ]; then
    PY="/opt/homebrew/bin/python3.12"
else
    PY="python3"
fi

# Dependências: um .venv recém-criado vem vazio. Instala só se faltar algo.
if ! "$PY" -c "import customtkinter, phonenumbers, appium, selenium" 2>/dev/null; then
    echo "Instalando dependências da estação (só na primeira vez)..."
    "$PY" -m pip install -q -r requirements.txt || {
        echo "Não consegui instalar. Rode à mão: $PY -m pip install -r requirements.txt"
        read -r -p "Pressione Enter para fechar."
        exit 1
    }
fi

exec "$PY" gui_ios.py
