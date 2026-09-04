#!/usr/bin/env bash
# Atualiza a Estação iOS para a última versão publicada e abre a interface.
# Dois cliques. Não mexe no .venv nem nos arquivos de progresso.
cd "$(dirname "$0")"
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Esta pasta não veio do repositório. Peça o link 'git clone' e use-o uma vez."
    read -r -p "Pressione Enter para fechar."; exit 1
fi
echo "Buscando atualizações…"
if ! git pull --ff-only; then
    echo "Não consegui atualizar (há alteração local ou sem internet). Nada foi mudado."
    read -r -p "Pressione Enter para fechar."; exit 1
fi
PY=".venv/bin/python"; [ -f "$PY" ] || PY="python3"
"$PY" -m pip install -q -r requirements.txt
echo "Atualizado: $(git log -1 --format='%h · %ad · %s' --date=short)"
exec ./iniciar_gui.command
