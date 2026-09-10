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

## 2. Primeiro teste (obrigatório) — primeiro degrau da escada

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
Só então rode a operação real. Os degraus 30 e 100 e o resto da escada de
ensaio estão em `COMO-OPERAR.md` §5.

Pela GUI (`python3 gui_ios.py`): ligue **"Modo Scroll Livre"**, escolha quantas
listas nesta rodada, o **Tamanho do ensaio** oferece 5, 30 e lista cheia (o
degrau de 100 só existe pela linha de comando), deixe "Criar listas de verdade"
desligado para o ensaio, e clique em Iniciar. O botão **Consultar progresso**
mostra onde parou logo abaixo do campo de listas.

Sem `--approve-create`, o runner reduz `--max-listas` para 1 sozinho (é ensaio:
nada seria criado mesmo).

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

O arquivo guarda o nome do último contato selecionado (campo `ultimo_rotulo`)
— trate-o como trata o `contatos.csv`: fica só no Mac, nunca sai por e-mail,
anexo ou backup em claro (o log nunca mostra nome nem número). O próprio JSON
carrega esse aviso no campo `sensivel`.

**Por que não dá para guardar só o hash** (dívida avaliada e mantida em
2026-09-10): o hash já é a identidade usada na retomada; o nome é usado para
outra coisa — a comparação **alfabética**. Quando o último contato da rodada
anterior foi apagado da agenda, `_retomar` precisa decidir quem vem antes e
quem vem depois dele para continuar do contato certo. Hash não ordena, e
prefixo truncado ordena errado: com prefixo de 3 caracteres, todo mundo que
compartilha o prefixo entra na faixa "já passou" e seria **pulado para
sempre** (uma família inteira de nomes "Mar…", por exemplo). Entre gravar um
nome no Mac e pular pessoas, o nome fica. O caminho que eliminaria o campo é
outro: guardar o conjunto de hashes já usados e parar de retomar por posição
— mudança grande, que troca o modelo de retomada inteiro e precisa de rodada
própria.

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
2. Lê as células do seletor pela class chain `**/XCUIElementTypeCell` —
   **neste iPhone o accessibility id `PickerView_ContactCell` não devolve
   nada**, e o filho `PickerView_ContactCell_PhoneNumber` volta vazio (o
   rótulo é "Nome, recado"). 1 chamada por tela quando o driver devolve os
   atributos na resposta da busca (`elementResponseAttributes`); se não
   devolver, cai para célula a célula (nunca varredura da árvore —
   profundidade 12–18 fixada uma vez por lista).
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

**Não medido em aparelho.** O único dado real que existe é o log de
2026-09-09: uma única leitura de tela, com zero contatos selecionados, levou
33,6 s e voltou vazia, seguida de socket hang up. Qualquer minuto escrito
aqui antes de medir nos degraus 3/4 da escada (`COMO-OPERAR.md` §5) seria
inventado — por isso este documento não promete um número. Cronometre o
degrau de 100 contatos e anote o resultado aqui.

---

## 5b. Velocidade: o que dá e o que não dá

O limite é físico, não de código: cada leitura, toque ou rolagem passa pelo
WebDriverAgent no iPhone (0,1 a 0,2 s por chamada) e o WhatsApp precisa
desenhar a tela. Por isso **não existe "100 vezes mais rápido"** numa
automação de interface. O que existe é cortar chamadas desperdiçadas:

| Modo | Chamadas ao iPhone | Estimativa por lista de 256 |
|---|---|---|
| Arquivo (CSV/VCF) antes da 4ª rodada | ~28 por contato | 15 a 20 min |
| Arquivo (CSV/VCF) agora | 5 por contato + 0,95 s de pausas (Turbo) | **~13 min esperado (3 s/contato).** A medição de 3,8 s/contato (~16 min) é de ANTES de as três consultas saírem, em 2026-09-10; remedir com `bench_ios.py`. |
| Arquivo (CSV/VCF), preset Máximo | 5 por contato + 0,675 s de pausas | ~12 min (mede antes: pausa curta gera "não encontrado" falso) |
| Scroll Livre antes da 3ª rodada | ~44 por tela | **não medido em aparelho** (a única medição existente é a leitura de 33,6 s de 2026-09-09, que voltou vazia e derrubou a sessão) |
| Scroll Livre agora (padrão) | ~13 por tela | **não medido em aparelho** (idem) |
| Scroll Livre com `--turbo` | ~7 por tela, 2 delas varrendo a árvore inteira (~51 telas para 256) | **não medido em aparelho** (idem). Não prometa "~1 min" antes de medir no aparelho. |

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
- **Modo arquivo (4ª rodada, 2026-09-10)**: três consultas por contato deixaram de
  existir, medidas no log do Appium (~0,25 s cada). A camada de seletor que encontra
  as células é lembrada dentro do picker (neste iPhone o id de acessibilidade sempre
  volta vazio, e essa tentativa era repetida a cada contato); com **uma** célula na
  tela o filho do telefone não é mais procurado, porque não muda a decisão — se
  casasse, escolheria a mesma célula que o single-cell-trust escolhe; e a checagem
  da linha "Convidar" passou a reaproveitar o rótulo já lido, em vez de reler quatro
  atributos. Junto veio uma trava nova: se a única célula da tela tiver o mesmo
  rótulo da que acabou de ser selecionada, a estação **não toca de novo** — o
  segundo toque desmarcaria o contato anterior e os dois se perderiam em silêncio.
- **Modo arquivo (1ª rodada)**: a trava do compositor de mensagem fazia até 8 consultas
  por contato (uma por rótulo); agora é 1 consulta com o mesmo critério. A
  profundidade em que as células aparecem é descoberta uma vez por sessão, não
  a cada contato. A verificação "já selecionado" (3 chamadas) só roda quando a
  verificação de seleção está ligada, e ela não está no fluxo validado.
- **Scroll Livre (3ª rodada)**: nome e posição de todas as células vêm na própria resposta da busca (`elementResponseAttributes`): ler uma tela é 1 chamada em vez de ~15. Se o driver não devolver os atributos, a leitura volta sozinha ao modo célula a célula. **Correção (2026-09-10):** a digitação NUNCA subiu. A chave enviada era `typingFrequency`, que não existe no driver XCUITest nem no WebDriverAgent — a chave real é `maxTypingFrequency`, e chaves desconhecidas são ignoradas em silêncio. Já corrigida, mas continua desligada por padrão (`LL_DIGITACAO=120` liga). Pela mesma razão, os contatos que ficaram sem selecionar numa rodada com `LL_RAPIDO=1` não podem ter sido causados pela digitação: o suspeito é `LL_ATTRS` (atributos na resposta).
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
| `nao encontrei o ponto de retomada` | O último contato mudou de nome/apagado e a ordem não bateu. Use `--recomecar-do-A` (recomeça do A SEM duplicar: preserva a guarda contra duplicata); `--reset-progresso` também recomeça mas apaga essa memória e duplicaria todo mundo já incluído. Antes, apague no WhatsApp as listas que seriam repetidas. `--recomecar-do-A` é **recusado** (código 2) enquanto houver lista criada cujo histórico não tenha a impressão digital dos contatos (arquivo de progresso versão 1): sem ela, a guarda cobriria só parte de quem já entrou, e o resto entraria numa segunda lista. |
| `um app externo abriu durante a selecao` | Uma célula "Convidar" passou pelo filtro. Volte ao WhatsApp, feche o seletor, rode de novo (nada foi criado). |
| `o seletor de contatos desapareceu` | WhatsApp trocou de tela (chamada, notificação, tela bloqueada). Deixe Bloqueio Automático = Nunca; rode de novo. |
| `o WDA nao respondeu a nenhuma consulta` | Diferente do anterior: a sessão do WebDriverAgent caiu (socket hang up). A tela do iPhone pode estar intacta, com contatos marcados. Confira o aparelho, cancele o seletor e veja `TRAVOU-EM-OPENING-BROADCAST.md`. |
| `ancora nao confirmada apos rajada turbo` | A rajada saiu e o botão "Criar" não voltou em duas conferências. Os toques dessa rajada ficam EM DÚVIDA: o progresso grava `toques_incertos` e a lista pode ter mais destinatários do que o progresso diz. **Confira no iPhone** — esses contatos podem reaparecer na lista seguinte. |
| `a lista de recuperacao nao cabe no tempo maximo` (código 8) | Depois de `--recomecar-do-A`, a lista precisa rolar por cima de **todos** os já usados antes de chegar em alguém novo, e essa travessia sozinha passa do `--max-minutos`. A estação recusa na largada, sem tocar em nada — a rodada gastaria a hora inteira e terminaria com zero contatos, sem avançar o progresso. O log diz de quantos minutos ela precisa. |
| aviso `celula(s) apareceram depois da retomada` (ou, na lista de recuperação, `guarda: N celula(s) ja em lista anterior`) | Contatos já em lista anterior foram bloqueados pela guarda. Ou é reobservação esperada (a retomada parou cedo, ou a lista de recuperação está atravessando quem já entrou: as MESMAS pessoas, nada perdido), ou são pessoas **diferentes** com o mesmo nome de alguém já incluído — e essas não entram em lista nenhuma. A tela não distingue as duas; os códigos ficam no progresso, em `bloqueados_apos_retomada`, **nos dois casos** (até 2026-09-10 a lista de recuperação não registrava nada). |
| `botao Criar esta DESABILITADO` | Menos de 2 selecionados. Fim da agenda ou o toque não está marcando: rode o ensaio com `-v` e mande o log. |
| `nenhuma celula de contato no seletor` | Profundidade da árvore mudou (WhatsApp novo). Rode `probe_picker.py` e mande o resultado. |
| WDA caiu / `socket hang up` | Igual ao fluxo validado: veja `TRAVOU-EM-OPENING-BROADCAST.md`. |
| Contato pulado | Compare o total do log com o esperado. O resumo de cada lista imprime `homonimos ignorados`, `sem rotulo`, `cliques que falharam e foram refeitos` e `travados`; `sem rotulo` também sai como aviso separado. Desde 2026-09-10 um contato que não pode ser tocado PARA a lista (código 6) em vez de ser pulado em silêncio — ele é o próximo da fila na rodada seguinte. |
| `teto de telas atingido` | NÃO é fim de agenda — o filtro de DDD é mais restritivo do que o teto suporta. O teto sobe sozinho quando há `--ddd`, até o teto absoluto de 1200 telas (~1 h de rodada). **Não adianta aumentar `--limite-por-lista`**: ele é o numerador da fórmula, o teto e o alvo crescem juntos. Use um DDD menos raro, quebre a agenda em arquivos menores, ou confira se o filtro está descartando por homônimo/número ausente. |
| `leitura vazia lenta` / `rajada interrompida` | O WDA não respondeu a tempo (o sintoma do log de 2026-09-09). A lista é salva PARCIAL com o que já estava confirmado (código de saída 6) — a próxima rodada continua do contato seguinte automaticamente. Confira no iPhone o número de destinatários da lista criada. |
| `leitura sem inferencia de posicao (excesso de elementos na tela)` | A tela ficou com elementos demais e a inferência de posição falhou; ler um rect por elemento custaria centenas de chamadas nesta única tela. A lista é salva PARCIAL (código 6) e a rodada seguinte continua. Se repetir sempre no mesmo tamanho, opere com `--limite-por-lista` menor. |
| `celula sem rotulo (nao da para saber quem e)` / `sem posicao legivel` | Uma célula com a altura de uma linha de contato não devolveu nome/posição em duas leituras. A lista para ANTES dela (código 6 ou 7) para não ultrapassá-la em silêncio — ela é a próxima da fila. Se a rodada seguinte parar no MESMO ponto, é essa linha da agenda: veja `--pular-celula-ilegivel` em `COMO-OPERAR.md` §7. |
| `orcamento de tempo da lista` | A lista passou do tempo máximo (`--max-minutos`, padrão 60). Mesmo desfecho do teto de telas: salva parcial (código 6) e a rodada seguinte continua. |

### Código de saída 6 — lista parcial criada

Desde a auditoria de 2026-09-10, uma interrupção no meio da seleção (rajada
`--turbo` que morreu no meio, leitura que estourou o tempo, teto de telas)
NÃO perde mais os toques já confirmados: se houver pelo menos 2 e o seletor
ainda estiver na tela, a estação clica em "Criar" com o que tem e sai com o
código 6. O progresso avança exatamente por essa quantidade — nunca mais do
que o confirmado, nunca menos. Sem isso, uma falha que se repete no mesmo
ponto (porque depende do tamanho da árvore) fazia a lista de 256 nunca
fechar.

### Profundidade da árvore depois do 1º contato

A faixa de selecionados afunda a árvore um nível assim que o 1º contato é
marcado — no modo CSV isso está CONFIRMADO no aparelho. Quando acontece, a
busca por célula volta **vazia e rápida**, que é indistinguível de "fim da
agenda" pelo tempo. Por isso a reavaliação de profundidade mora dentro da
própria leitura (`_ler_celulas`), e não no laço de seleção: no laço ela só
seria consultada depois de uma rolagem às cegas, e os contatos daquela tela
eram pulados em silêncio. Vale **uma vez por lista**, com orçamento de 3 s
conferido DEPOIS de cada busca (não só entre elas: até 2026-09-10 a primeira
tentativa era incondicional — e ela é justamente a mais cara, numa
profundidade MAIOR que a que acabou de travar), e só dispara quando a busca
não achou célula nenhuma. Fim de agenda de verdade (células achadas, todas
fora da área tocável) não paga nada por isso, e **uma leitura que já voltou
lenta também não**: nesse caso o problema é o WDA, não a árvore, e subir a
profundidade só aumentaria o custo da próxima varredura.

**Enquanto não houver um contador de selecionados confirmado no aparelho**
(item em aberto: nenhum candidato — botão Criar, título da NavigationBar,
faixa do topo — foi confirmado como contador; ver `probe_picker.py`), uma
rajada `--turbo` que morre no meio NUNCA é re-tocada (re-tocar desmarca) e os
toques dessa rajada específica ficam de fora da lista — nem contados, nem
perdidos: a próxima rodada tenta esses contatos de novo. Por isso o runner
avisa alto quando `--turbo` vem com `--limite-por-lista` acima de 30: confira
sempre no iPhone o número de destinatários da lista recém-criada.

Testes locais (sem iPhone): `python3 test_scroll_local.py` — simula o
seletor (faixa de chips, células parciais, homônimos, convite, contato apagado,
retomada longe, fim da agenda, rajada interrompida, teto de telas, leitura
lenta, profundidade que muda depois do 1o chip, guarda contra duplicata,
orçamento de tempo, célula sem rótulo/sem posição legível, e o proprio `main()`
criando a lista parcial). 135 casos.
