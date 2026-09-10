# Erros no Mac: `TypeError: | ...` e `page_source timeout 240000ms`

Dois erros diferentes, os dois já corrigidos nesta versão.

## 1. `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`

**Causa:** o ambiente é **Python 3.9**, e faltava `from __future__ import annotations`
no `ios_selectors.py` (a sintaxe `str | None` só é nativa no 3.10+).
**Correção:** já adicionada nesta versão. Se você editou o arquivo à mão, mantenha
a linha `from __future__ import annotations` no topo — está certo.

> Dica: se puder, use Python 3.10+ (`brew install python@3.12` e rode com
> `python3.12`). Não é obrigatório — o pacote funciona no 3.9 com a correção.

## 2. `Could not proxy command... page_source... timeout of 240000ms`

**Causa:** o `page_source` do iOS monta a árvore de acessibilidade INTEIRA. Na
tela de **Conversas** do WhatsApp (lista enorme), o WebDriverAgent trava nisso.
Não é o seu WhatsApp travado — é o custo de serializar a tela toda.

**O que mudou nesta versão:**
- A árvore agora é rasa (`snapshotMaxDepth: 12`) e o timeout caiu para ~60s (falha
  rápido em vez de 4 minutos).
- Novo script **`probe_ios.py`** que acha o botão **sem** usar `page_source`.

### Use o probe (é o caminho certo para a tela de Conversas)

Com o WhatsApp aberto na aba **Conversas**:
```bash
python3 probe_ios.py --wda-bundle com.seunome.WebDriverAgentRunner --out sonda.json
```
Ele consulta só os botões/textos da barra (rápido, sem timeout) e já diz se achou
o candidato **"Listas de transmissão"** e qual o `type` dele. **Envie o `sonda.json`.**

Com esse arquivo eu te devolvo as linhas exatas do `ios_selectors.py`, e o
`spike_ios.py` passa a abrir a transmissão sem depender do `page_source`.

### Se o WDA ainda travar (raro)

1. Pare o Appium (Ctrl+C) e suba de novo: `appium`.
2. No Xcode, rode o WebDriverAgentRunner uma vez (⌘U) para reinstalar/estabilizar.
3. Reabra o WhatsApp e rode o `probe_ios.py` de novo.
