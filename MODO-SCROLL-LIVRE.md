# Modo Scroll Livre — listas de transmissão SEM CSV (iOS via Mac/Appium)

Cria listas de transmissão tocando nos contatos **na ordem em que o próprio
WhatsApp os lista** (A, B, C…), rolando a tela, até 256 por lista. Não importa
CSV, não digita número nenhum. Guarda onde parou: a lista seguinte começa no
contato seguinte ao último da lista anterior (o "257", o "513"…).

Usa exatamente o mesmo caminho já validado no iPhone da Isabella (sessão,
WhatsApp → Conversas → "+" → "Nova transmissão" → Destinatários → "Criar").
Só a etapa de seleção muda: em vez de pesquisar cada número, toca e rola.

---

## 1. Quando usar este modo (e quando usar o CSV)

| | Scroll Livre | Modo CSV (`run_ios.py`) |
|---|---|---|
| Precisa de CSV/VCF | não | sim |
| Quem entra na lista | **todos** os contatos com WhatsApp, na ordem do app | só quem está no CSV (filtro por DDD/UF) |
| Velocidade | ~1 toque por contato (rápido) | 1 pesquisa por contato (lento) |
| Escolher por DDD/região | não | sim |
| Retomar entre rodadas | automático (arquivo de progresso) | por lote do CSV |

Regra prática: **agenda inteira → Scroll Livre. Só uma região → CSV.**

---

## 2. Primeiro teste (obrigatório, 10 minutos)

Na pasta `ios-station`, com o `appium` rodando e o iPhone desbloqueado no
WhatsApp (como no `DEVICE-TEST-IOS.md`):

```bash
# 1) ENSAIO: seleciona 5 contatos, mostra o resultado e CANCELA (não cria nada)
python3 run_ios_scroll.py --trust-profile --limite-por-lista 5

# 2) Olhe o iPhone durante o ensaio: os 5 primeiros contatos (A…) ficam com
#    o check e aparecem na faixa do topo; depois o seletor fecha sozinho.

# 3) LISTA REAL de teste com 5 contatos (aparece em Conversas; nada é enviado)
python3 run_ios_scroll.py --trust-profile --limite-por-lista 5 --approve-create

# 4) Confira onde parou
python3 run_ios_scroll.py --progresso
#   -> "1 lista(s) criada(s), 5 contato(s) ja incluidos; a proxima lista comeca no contato n. 6 ..."

# 5) Segunda lista de teste: deve começar no 6º contato (confira no iPhone)
python3 run_ios_scroll.py --trust-profile --limite-por-lista 5 --approve-create

# 6) Apague as 2 listas de teste no WhatsApp e ZERE o progresso antes da operação real
python3 run_ios_scroll.py --reset-progresso
```

Se o passo 5 começou exatamente no 6º contato, a retomada está validada.
Só então rode a operação real.

Pela GUI (`python3 gui_ios.py`): ligue **"Modo Scroll Livre"**, escolha quantas
listas nesta rodada, deixe "Criar listas de verdade" desligado para o ensaio,
e clique em Iniciar. O botão **"Onde parou?"** mostra o progresso no log.
(Pela GUI o limite é sempre 256; para o teste com 5 use a linha de comando.)

---

## 3. Operação real

```bash
# 3 listas de 256 nesta rodada (≈ 768 contatos), criando de verdade
python3 run_ios_scroll.py --trust-profile --approve-create --max-listas 3
```

- Cada lista impressa no log como `Lista 1 de 3`, `Lista 2 de 3`…
- Ao final de CADA lista criada o progresso é gravado em
  `progress.scroll.local.json` — se a rodada parar no meio (cabo, WDA, tela
  bloqueada), o que já foi criado está salvo; rode de novo e ela continua.
- A lista em andamento que NÃO chegou ao "Criar" não conta: o seletor fica
  aberto no iPhone com os contatos marcados. Feche-o (Cancelar) e rode de novo
  — a retomada usa o último contato da última lista **criada**.
- 10 mil contatos ≈ 40 listas. Faça em rodadas (ex.: `--max-listas 5`) e
  confira o iPhone entre elas.

### Progresso: o que é guardado e por quê

```json
{
  "offset": 512,                 // contatos já incluídos em listas
  "proximo_contato_n": 513,      // informativo
  "listas_criadas": 2,
  "ultimo_rotulo": "Nome do último contato selecionado",
  "ultimo_hash": "…",
  "historico": [ { "lista": 1, "quantidade": 256, ... }, ... ]
}
```

A retomada **não** conta "pula 512 linhas": se alguém for adicionado ou apagado
na agenda entre uma rodada e outra, a linha 513 muda de lugar e a lista
seguinte repetiria ou pularia pessoas. Em vez disso, o script rola até
encontrar o **último contato** da lista anterior e continua do seguinte. Se
esse contato foi apagado da agenda, continua do primeiro em ordem alfabética
depois dele (com aviso no log).

O arquivo guarda o nome do último contato selecionado — trate-o como trata o
`contatos.csv` (fica só no Mac; o log nunca mostra nome nem número).

Comandos de progresso:

```bash
python3 run_ios_scroll.py --progresso          # onde parou
python3 run_ios_scroll.py --reset-progresso    # recomeça do primeiro contato (A)
```

Um arquivo de progresso por iPhone: ao trocar de aparelho, use
`--progress-file progress.<apelido>.json` (ou zere com `--reset-progresso`).

---

## 4. Como funciona por dentro (para quem for dar manutenção)

1. Abre o seletor "Destinatários" pelo fluxo validado (`IosSpike.open_new_broadcast`).
2. Lê as células `PickerView_ContactCell` **inteiramente visíveis** (posição +
   rótulo; 2 chamadas por célula, nunca varredura da árvore — profundidade 12–18
   fixada uma vez por lista).
3. Toca de cima para baixo. Cada contato é identificado pelo **nome** (o rótulo
   é "Nome, recado"; o recado muda a toda hora e é descartado) via hash.
   Tocar de novo num contato **desmarca** — por isso um hash só é tocado uma vez.
4. O 1º toque da lista faz aparecer a faixa dos selecionados no topo e empurra
   a tabela para baixo: o script mede o deslocamento e sobe o limite superior
   (o que ficou sob a faixa não é tocado).
5. Rola com **arrasto controlado** (`mobile: dragFromToWithVelocity`, segura no
   fim → sem inércia): do centro da última célula inteira ao centro da
   primeira. A última vira a primeira — 1 linha de sobreposição, nunca um
   buraco. Sobreposição é resolvida pelo hash.
6. Fim da agenda: quando a lista não rola mais, relê sem a margem inferior
   (as últimas linhas ficam coladas na borda) e toca o que faltou.
7. Célula "Convidar para o WhatsApp" é pulada. Homônimos (dois contatos com o
   mesmo nome exibido) — o segundo **não** é tocado (não dá para distinguir
   com segurança e tocar desmarcaria o primeiro); o log conta quantos foram.
8. Retomada: rolagem rápida (com inércia) enquanto o último nome visível vem
   antes do alvo em ordem alfabética; perto do alvo, uma tela por vez; achou o
   hash → continua da linha seguinte.
9. "Criar" só com `--approve-create` e só se o botão estiver **habilitado**
   (2+ selecionados). Depois de criar, volta para Conversas e começa a próxima.

Travas mantidas do fluxo validado: aborta se um compositor de mensagem
aparecer; aborta se um app externo vier para frente; nunca digita nada;
qualquer tela desconhecida = parada segura + `inventory-erro.json`.

---

## 5. Tempo esperado (a confirmar no primeiro teste)

Por tela (≈ 10–12 contatos): ler ≈ 3–5 s, tocar ≈ 3–4 s, rolar ≈ 1 s.
Lista de 256 ≈ 22 telas ≈ **3–5 min**. Retomada em listas avançadas (rolar
até o ponto) soma 1–5 min. Meça no primeiro teste e anote aqui.

---

## 5b. Velocidade: o que dá e o que não dá

O limite é físico, não de código: cada leitura, toque ou rolagem passa pelo
WebDriverAgent no iPhone (0,1 a 0,2 s por chamada) e o WhatsApp precisa
desenhar a tela. Por isso **não existe "100 vezes mais rápido"** numa
automação de interface. O que existe é cortar chamadas desperdiçadas:

| Modo | Chamadas ao iPhone | Estimativa por lista de 256 |
|---|---|---|
| Arquivo (CSV/VCF) até a V15 | ~28 por contato | 15 a 20 min |
| Arquivo (CSV/VCF) agora | ~6 por contato + 0,85 s de pausas (Turbo) | 5,5 a 7 min |
| Arquivo (CSV/VCF), preset Máximo | ~9 por contato + 0,6 s de pausas | 5 a 7 min |
| Scroll Livre até a V14 | ~44 por tela | ~4 min |
| Scroll Livre agora (padrão) | ~13 por tela | ~1,5 min |
| Scroll Livre com `--turbo` | ~5 por tela | ~1 min |

De onde saiu o ganho, sem afrouxar trava nenhuma:

- **Modo arquivo (3ª rodada)**: **checagens de segurança a cada 8 contatos
  viraram padrão** (medido no iPhone: a checagem "WhatsApp em primeiro plano"
  custava 0,8 s por contato, o item mais caro do ciclo; a segurança não
  depende dela — se o seletor sumir, a busca seguinte falha sozinha, e a linha
  "Convidar" é barrada antes do toque). `LL_CHECAGEM=1` volta a checar a cada
  contato. Ainda experimentais, desligadas por padrão: `LL_DIGITACAO=200`
  (digitação rápida), `LL_ATTRS=1` (rótulos na resposta da busca; agora
  percorre todas as camadas do seletor), `LL_RAPIDO=1` (as duas).
  Exemplo: `LL_DIGITACAO=200 python3 gui_ios.py`.
  O log agora imprime `busca: N celula(s) na tela` a cada contato: 0 = a
  busca não filtrou (texto digitado incompleto); 2+ = há células a mais.
- **Modo arquivo (2ª rodada)**: o campo de busca é reaproveitado entre contatos (1 busca a menos); um "não encontrado" não sobe mais a profundidade 14→16→18 (até 8 chamadas) — a profundidade do seletor não muda dentro da lista; a linha "Convidar" é barrada ANTES do clique lendo o rótulo, o que permitiu encurtar a pausa depois do clique (de 1,5×ritmo para 0,5×ritmo). Preset **Máximo** em Configurações leva as pausas ao piso do runner (0,375 s após digitar): use só depois de medir.
- **Modo arquivo (1ª rodada)**: a trava do compositor de mensagem fazia até 8 consultas
  por contato (uma por rótulo); agora é 1 consulta com o mesmo critério. A
  profundidade em que as células aparecem é descoberta uma vez por sessão, não
  a cada contato. A verificação "já selecionado" (3 chamadas) só roda quando a
  verificação de seleção está ligada, e ela não está no fluxo validado.
- **Scroll Livre (3ª rodada)**: nome e posição de todas as células vêm na própria resposta da busca (`elementResponseAttributes`): ler uma tela é 1 chamada em vez de ~15. Se o driver não devolver os atributos, a leitura volta sozinha ao modo célula a célula. A digitação do modo arquivo subiu de 60 para 200 caracteres por segundo (`typingFrequency`).
- **Scroll Livre (rodadas anteriores)**: a checagem de célula "Convidar" fazia 3 a 4 chamadas por
  contato com o rótulo já lido; agora é pelo rótulo, sem chamada. A posição das
  células é lida só na primeira e na última da tela: se a distância entre elas
  for exatamente (n−1) alturas, não há cabeçalho de seção no meio e as demais
  são inferidas; qualquer diferença faz ler todas. A checagem de segurança por
  tela passou a ser "o botão Criar continua na tela" (1 consulta), que é a prova
  mais forte de que nenhum diálogo apareceu.

O `--turbo` toca todas as células de uma tela numa única requisição (rajada
W3C, com as coordenadas lidas naquela mesma tela). Vem **desligado**: um toque
por coordenada não é barrado por um aviso que apareça no meio da tela, como o
toque por elemento é. Depois de cada rajada o script confere que o seletor
continua na tela; se não estiver, para por segurança. Ligue só depois de o
teste de 5 contatos ter passado neste iPhone.

```bash
python3 run_ios_scroll.py --trust-profile --limite-por-lista 5 --turbo            # ensaio turbo
python3 run_ios_scroll.py --trust-profile --approve-create --max-listas 5 --turbo  # operação
```

Para a frota, o multiplicador real é **paralelismo**: cada Mac opera um iPhone
por vez; dois Macs, dois iPhones ao mesmo tempo.

Todos os números são estimativas por contagem de chamadas — meça no primeiro
teste e anote aqui.

## 5c. Filtro por DDD no Scroll Livre

A tela de destinatários do WhatsApp mostra **nome e recado** do contato salvo,
nunca o número. Então o DDD não pode ser lido da tela: ele vem da **agenda
exportada** (o mesmo VCF ou CSV do modo arquivo), cruzada pelo nome.

```bash
python3 run_ios_scroll.py --trust-profile --approve-create --max-listas 5     --ddd 21,22 --agenda ~/Downloads/contatos.vcf
```

Regras, para não errar destinatário:

- Entra quem tem **todos** os números da agenda dentro dos DDDs pedidos.
- Nome que tem um número dentro e outro fora é **ambíguo** e fica de fora (o
  log diz quantos). Homônimos com DDDs diferentes caem aqui.
- Contato que aparece no WhatsApp mas não está na agenda fica de fora.
- A rolagem percorre a lista inteira; só os toques são filtrados. Uma agenda
  com 60% no DDD 21 gera ~60% dos toques, com o mesmo tempo de rolagem.

Na interface: com "Scroll Livre" marcado, o cartão de DDD continua visível e
aparece o campo "Agenda para filtrar por DDD (opcional)". Sem agenda e com DDD
marcado, o botão Iniciar explica o que falta.

## 6. Problemas comuns

| Sintoma no log | O que fazer |
|---|---|
| `nao encontrei o ponto de retomada` | O último contato mudou de nome/apagado e a ordem não bateu. `--reset-progresso` e recomece, ou use `--progress-file` novo. Antes, apague no WhatsApp as listas que seriam repetidas. |
| `um app externo abriu durante a selecao` | Uma célula "Convidar" passou pelo filtro. Volte ao WhatsApp, feche o seletor, rode de novo (nada foi criado). |
| `o seletor de contatos desapareceu` | WhatsApp trocou de tela (chamada, notificação, tela bloqueada). Deixe Bloqueio Automático = Nunca; rode de novo. |
| `botao Criar esta DESABILITADO` | Menos de 2 selecionados. Fim da agenda ou o toque não está marcando: rode o ensaio com `-v` e mande o log. |
| `nenhuma celula de contato no seletor` | Profundidade da árvore mudou (WhatsApp novo). Rode `probe_picker.py` e mande o resultado. |
| WDA caiu / `socket hang up` | Igual ao fluxo validado: veja `TRAVOU-EM-OPENING-BROADCAST.md`. |
| Contato pulado | Compare o total do log com o esperado; homônimos e "sem rótulo" são contados no resumo de cada lista. |

Testes locais (sem iPhone): `python3 test_scroll_local.py` — simula o
seletor (faixa de chips, células parciais, homônimos, convite, contato apagado,
retomada longe, fim da agenda). 15 casos.
