# Como operar a estação — Lista Local (iPhone)

Este é o guia do dia a dia. Não é preciso saber programar. Onde aparecer um
comando, ele é para ser copiado e colado no Terminal, na pasta da estação.

Sempre que uma instrução depender de algo que ninguém mediu ainda, o texto diz
isso na própria instrução. Quando não disser, o número veio de medição.

---

## 1. O que a estação faz — e o que ela NUNCA faz

**Faz:** o Mac controla a tela do WhatsApp do iPhone por fora e monta listas de
transmissão, marcando contato por contato, até 256 por lista. É exatamente o que
você faria com o dedo, só que sem errar e sem cansar.

**Nunca faz, em nenhuma circunstância:**

- **nunca envia mensagem.** O envio é sempre manual, depois, por você. Existe uma
  trava: se um campo de escrever mensagem aparecer na tela, a estação para na hora.
- **nunca abre uma conversa** nem toca no compositor.
- **nunca toca no escuro.** Se a tela não for uma das que ela conhece, ela para e
  grava o que viu em `inventory-erro.json`. Não chuta.
- **nunca cria lista sem sua autorização explícita.** Sem marcar "Criar listas de
  verdade" (ou sem `--approve-create` no Terminal), ela seleciona e cancela.
- **nunca cria lista com menos de 2 pessoas** (o WhatsApp não deixa).
- **nunca escreve nome nem número no log.** O log mostra um código embaralhado e
  os 2 últimos dígitos, o suficiente para você conferir e nada mais.
- **nunca renomeia as listas.** Elas ficam com o nome padrão do WhatsApp. A
  nomeação automática foi retirada porque a tela de informações da lista não
  expôs os campos necessários no aparelho. Se quiser outro nome, renomeie no
  próprio WhatsApp depois.

---

## 2. Antes de começar (uma vez por dia)

1. iPhone conectado por cabo, desbloqueado, com **Ajustes › Tela e Brilho ›
   Bloqueio Automático = Nunca**. Tela que apaga derruba a operação no meio.
2. Dois cliques em **`atualizar.command`**. Ele busca a versão nova, instala o
   que faltar e abre a estação. É o único jeito de atualizar — não baixe zip.
3. Na aba **Operação**, o quadro **Estado da estação** precisa estar verde nos
   quatro itens. O que faltar aparece com o motivo e o que fazer.

Se a estação não abrir, dois cliques em `iniciar_gui.command`. Se o Mac reclamar
que "não é possível verificar o desenvolvedor", clique com o **botão direito** no
arquivo e escolha **Abrir** — só na primeira vez.

---

## 3. O dia a dia: modo lista de contatos (é o modo em uso)

É o modo que roda hoje na operação. Ele digita cada número na busca do WhatsApp,
confere e marca o contato certo. Leva **cerca de 3 segundos por contato**, ou
**cerca de 13 minutos por lista de 256**, no ritmo Turbo (o padrão da estação).
Mais devagar demora mais; a tela de Configurações mostra a estimativa do ritmo
escolhido.

### 3.1 Tirar a agenda do iPhone

No iPhone: **Contatos › Listas › Todos os Contatos › Exportar › AirDrop para o
Mac**. Vai chegar um arquivo `.vcf`. A estação também aceita `.csv` com as
colunas `name,phone`.

### 3.2 Escolher o arquivo

Na aba Operação, cartão **De onde vêm os contatos**, escolha **Importar CSV ou
VCF** e clique em **Escolher…**. O resumo aparece na hora:

- **No arquivo** — quantas linhas o arquivo tinha.
- **Números válidos** — quantos viraram número de verdade.
- **Inválidos ou repetidos** — o que foi descartado (é normal ter algum).
- **Depois do filtro** — quantos sobraram depois dos DDDs escolhidos.
- **Já em listas** — quem já entrou numa lista criada antes (ver 3.5).
- **Listas planejadas** — quantas listas saem disso.

### 3.3 Filtrar por DDD (opcional)

Cartão **Filtrar por DDD**. Marque 21, 22 e 24 direto, ou digite outros separados
por vírgula. Sem seleção, entram todos.

### 3.4 Primeiro a simulação, sempre

Em **Tipo de execução**, deixe **Simulação segura** e clique em **Iniciar
simulação**. A estação abre o WhatsApp, marca os contatos e **cancela no fim,
sem criar nada**. Serve para você ver, no aparelho, que ela está marcando as
pessoas certas.

### 3.5 Criar de verdade

Troque para **Criar listas de verdade** e clique. Vai aparecer uma caixa de
confirmação com o modo, o arquivo, os DDDs, quantos contatos e quantas listas —
e o nome das listas (o padrão do WhatsApp: a estação não renomeia). Leia e
confirme. Durante a execução, **não mexa no iPhone**.

**Na primeira vez do dia, comece pequeno.** Neste modo a tela **não** tem um
campo de "quantas listas nesta rodada" (esse campo só existe no Modo Scroll
Livre), e um clique cria **todas** as listas do arquivo em sequência. Para
conferir antes de soltar tudo, faça uma destas duas coisas:

- importe um **arquivo pequeno** (5 a 10 contatos), crie, confira no iPhone, e
  só então importe o arquivo completo; **ou**
- clique em **Parar com segurança** assim que o log mostrar a primeira lista
  criada. A lista que estiver em andamento nesse instante não é salva (§3.6);
  as já criadas ficam.

### 3.6 Dividir a criação em vários dias

Você não precisa fazer 10 mil contatos de uma vez. A estação guarda quem já
entrou numa lista **criada** (só um código embaralhado, nunca o número) no
arquivo `progress.ios.local.json`.

Para continuar amanhã: **importe o mesmo arquivo de novo**. Quem já entrou fica
de fora sozinho, e só os restantes viram listas novas. A tela mostra isso na
caixa **Já em listas**.

Detalhes que importam:

- **Simulação não marca ninguém.** Só conta quem entrou numa lista que chegou ao
  toque em "Criar".
- **Lista interrompida no meio também não marca ninguém** no modo lista de
  contatos.
- Quem saiu como **não encontrado** ou **ambíguo** também fica de fora nas
  próximas rodadas, porque cada um custa uns 3 segundos para falhar de novo.
  Para tentar esses de novo, é pelo Terminal:
  `python3 run_ios.py --csv contatos.csv --repetir-nao-encontrados`

### 3.7 Exportar os restantes

Botão **Exportar restantes…** no cartão do arquivo (ou, pelo Terminal:
`python3 run_ios.py --csv contatos.csv --exportar`).

Grava, na mesma pasta do arquivo importado e **sem tocar no iPhone**:

- `contatos.restantes.csv` — quem ainda falta;
- `contatos.adicionados.csv` — quem já está em listas;
- `contatos.nao-adicionados.csv` — quem não deu, com a coluna `motivo`.

Os três podem ser importados de volta na estação. **Os três têm nome e número em
claro** — leia a seção 8.

---

## 4. O que é o Scroll Livre, e por que ele ainda não está liberado

**O que é:** em vez de digitar cada número na busca, ele toca nos contatos **na
ordem em que o próprio WhatsApp os lista** (A, B, C…) e rola a tela. Sem arquivo,
sem digitação. Guarda onde parou: a lista seguinte começa no contato seguinte —
e agora também guarda um código embaralhado de **todo** contato que já entrou em
lista, para nunca tocar de novo em alguém que já está numa lista anterior, mesmo
que a retomada erre o ponto exato.

**Por que existe:** para a agenda inteira, digitar 10 mil números é o gargalo.
Tocar e rolar é muito menos trabalho por contato. É o caminho para operar a
agenda toda sem depender de exportação.

**Por que ele NÃO está liberado para lista cheia:** ele nunca passou de **2
listas de 5 contatos** num aparelho. Tudo acima disso é conta em cima de
simulação, não medição. Há riscos conhecidos e ainda não resolvidos no
aparelho:

1. **A tela fica mais pesada conforme você seleciona.** Cada contato marcado
   entra numa faixa no topo, e a leitura da tela custa mais. Em 2026-09-09, com
   **zero** contatos selecionados, uma única leitura levou 33,6 segundos, voltou
   vazia e derrubou a sessão. Ninguém mediu ainda quanto isso piora com 100 ou
   200 selecionados.
2. **Tocar de novo no mesmo contato o DESMARCA**, e não existe contador de
   selecionados confiável na tela. A estação conta por toque. Se uma leva de
   toques (modo Turbo) morrer no meio, aqueles contatos ficam em dúvida — a
   estação não os toca de novo, porque re-tocar desmarcaria quem já entrou. Por
   padrão, esses toques em dúvida **ficam de fora** da guarda contra duplicata
   (o risco aceito é duplicar, nunca pular) — a estação avisa a cada rodada
   até você conferir no iPhone e resolver com `--resolver-incertos`.

Enquanto a escada da seção 5 não chegar até 256 num iPhone, **o modo em produção
é o da seção 3**.

**Filtro de DDD no Scroll Livre:** a tela de destinatários mostra nome e recado,
nunca o número. Então o DDD não pode ser lido da tela: ele vem da agenda
exportada, cruzada **pelo nome**. Por isso, com DDD marcado, a estação também
pede o arquivo da agenda. Quem tem um número dentro e outro fora do DDD fica de
fora (o log diz quantos).

**Um aparelho por arquivo de progresso.** A estação usa sempre
`progress.scroll.local.json`. Se você operar dois iPhones no mesmo Mac, os dois
vão dividir o mesmo progresso e a retomada sai errada. Pela tela não dá para
trocar; pelo Terminal, use `--progress-file progress.<apelido>.json` para cada
aparelho.

---

## 5. A escada de ensaio: 5 → 30 → 100 → 256

Regra: **só sobe um degrau depois que o anterior fechou limpo neste iPhone.** Se
um degrau falhar, não suba; anote o que apareceu no log e pare o dia.

Antes de começar a escada, zere o progresso e apague no WhatsApp as listas de
teste da tentativa anterior:

```
cd ~/Trabalho/"Marcelo Queiroz"/ios-station
python3 run_ios_scroll.py --reset-progresso
```

### Degrau 1 — 5 contatos

```
# ensaio: marca 5 e cancela, não cria nada
python3 run_ios_scroll.py --trust-profile --limite-por-lista 5

# lista real de teste com 5
python3 run_ios_scroll.py --trust-profile --limite-por-lista 5 --approve-create

# onde parou
python3 run_ios_scroll.py --progresso

# segunda lista: tem de começar no 6º contato — confira no iPhone
python3 run_ios_scroll.py --trust-profile --limite-por-lista 5 --approve-create
```

Fechou limpo quando: a segunda lista começou exatamente no 6º contato e as duas
listas apareceram em Conversas com 5 destinatários cada.

Os degraus 1 e 2 também podem ser feitos pela tela: modo **Usar Scroll Livre** →
**Tamanho do ensaio** → *Ensaio (5 contatos)* ou *Ensaio (30 contatos)*.

### Degrau 2 — 30 contatos

```
python3 run_ios_scroll.py --trust-profile --limite-por-lista 30
python3 run_ios_scroll.py --trust-profile --limite-por-lista 30 --approve-create
```

Confira no iPhone: a lista criada tem 30 destinatários? Se tiver menos, o log diz
por quê (procure "homonimos ignorados" e "sem rotulo" no resumo da lista).

### Degrau 3 — 100 contatos

Este degrau **só existe pelo Terminal** (a tela oferece 5, 30 e lista cheia).

```
python3 run_ios_scroll.py --trust-profile --limite-por-lista 100
python3 run_ios_scroll.py --trust-profile --limite-por-lista 100 --approve-create
```

É aqui que aparece, se aparecer, a lentidão da leitura com muitos selecionados.
**Cronometre este degrau e anote o tempo** — é a primeira medição real do modo.

### Degrau 4 — 256 (lista cheia)

```
python3 run_ios_scroll.py --trust-profile --approve-create --max-listas 1
```

Sem `--limite-por-lista`, ele usa 256, que é o padrão. **Uma lista só**, e
conferir no aparelho antes de qualquer coisa.

### E o Turbo?

`--turbo` toca todos os contatos de uma tela numa requisição só. **Não ligue
antes do degrau 4 fechar limpo sem ele.** O ganho de velocidade do Turbo nunca
foi medido neste iPhone — a estimativa que circulava era conta em cima de
simulação. E o Turbo tem um custo real: um aviso que apareça no meio da tela não
barra o toque como no modo normal, então a estação interrompe a lista por
segurança quando isso acontece.

### O tempo máximo de uma lista

Toda lista do Scroll Livre tem um **orçamento de tempo** (padrão 60 minutos):
passou disso, a estação salva o que já confirmou e para — o mesmo desfecho do
teto de telas. Não precisa mexer em nada.

**Isso existe só no Scroll Livre.** O modo lista de contatos (seção 3, o que
está em uso) **não tem corte por relógio**: ele para pelos limites que já tinha —
256 por lista e o teto de páginas de busca. Se uma rodada do modo lista de
contatos travar de madrugada, ela fica travada: quem corta é você.

---

## 6. O que observar no log

O log fica dentro de **Ver detalhes técnicos**, na tela de Execução. Vale abrir e
olhar de vez em quando. O que procurar:

- **`Lista 2 de 5`** — o andamento das listas da rodada.
- **`busca: N celula(s) na tela`** (modo lista de contatos) — `1` é o normal.
  `0` significa que a busca não filtrou; `2` ou mais significa que havia mais de
  um candidato na tela.
- **o resumo no fim de cada lista** — traz `homonimos ignorados`, `sem rotulo`,
  `sem posicao legivel`, `cliques que falharam e foram refeitos` e `travados`.
  Se a lista saiu menor do que você esperava, a resposta está nesses números.
- **`sem rotulo`** com número acima de zero — vem também como aviso separado.
  São células que não devolveram o nome em duas leituras. Se a altura da célula
  pode ser a de uma linha de contato, a lista **para** antes de ultrapassá-la
  (em vez de descartar em silêncio) — ela é a próxima da fila na rodada
  seguinte. Só um cabeçalho de seção (bem mais baixo) não para a lista, e mesmo
  esse aparece no log como aviso.
- **linhas começando com `WARNING` / `ERROR`** — aparecem em amarelo e vermelho.

O log **não** mostra nome nem número de ninguém. Um contato aparece como um
código embaralhado com os 2 últimos dígitos, por exemplo `<a1b2c3d4...78>`.

No fim, a estação diz numa frase se concluiu, se você interrompeu ou se parou por
segurança — e o que fazer nesse caso.

---

## 7. Cada parada nomeada, em português, e o que fazer

### "Lista parcial criada" (o código 6)

**O que aconteceu:** a seleção foi interrompida no meio, mas já havia pelo menos
2 contatos confirmados e o seletor ainda estava na tela — então a estação clicou
em "Criar" com o que tinha, em vez de perder tudo.

No log o motivo aparece como `motivo_da_parada`. **O tempo máximo da lista
(`orcamento de tempo da lista`) cai aqui**, e não no código 7, sempre que no
momento do estouro já havia 2 ou mais contatos confirmados, o modo era "criar de
verdade" e o seletor ainda estava na tela: nesse caso a lista **é criada**, com
menos gente do que você pediu, e o progresso avança por cima dessas pessoas.

**O que fazer:** confira no iPhone quantos destinatários a lista tem. Depois é só
rodar de novo: a próxima lista continua automaticamente do contato seguinte.
Esta parada é **normal** e não é erro.

### "Parou por uma regra da estação" (o código 7)

**O que aconteceu:** a estação parou sozinha por uma regra dela e **não** criou
lista nenhuma, nem parcial. O progresso não avançou: ninguém entrou duas vezes e
ninguém ficou para trás. Os motivos que caem aqui são:

- `orcamento de tempo da lista (durante a retomada)` — o tempo máximo acabou
  antes de a estação chegar no ponto onde a rodada anterior parou. **Sempre**
  código 7: nada foi tocado;
- `orcamento de tempo da lista` **com menos de 2 contatos confirmados** (com 2 ou
  mais, e o seletor ainda na tela, vira código 6 — lista parcial criada, ver
  acima);
- as paradas por célula ilegível (a seção logo abaixo), quando a lista para com
  menos de 2 confirmados;
- `contato inalcancavel` — uma linha que não aceitou o toque duas vezes.

A estação tenta fechar o seletor sozinha antes de sair. Se o log disser que não
conseguiu, **feche o seletor no iPhone** antes da próxima rodada.

Este código é sempre uma **regra da estação**. Se o problema tiver sido o
WebDriverAgent caindo no meio da seleção ("socket hang up"), a estação **não**
usa o código 7: ela sai como erro (código 4, tela vermelha) com as instruções de
recuperação do WDA. Ler "regra da estação" e rodar de novo contra um WDA morto
era exatamente o que não podia acontecer.

**O que fazer:** o motivo exato está na última linha do log técnico. Se a rodada
seguinte parar **no mesmo ponto** (mesmo `proximo_contato_n` no progresso),
repetir não resolve — e há **duas** causas possíveis, que o log distingue:

1. **uma linha da agenda que nunca devolve nome** (`celula sem rotulo` / `celula
   sem posicao legivel`): veja `--pular-celula-ilegivel` na seção abaixo;
2. **tempo máximo insuficiente para a travessia** (`orcamento de tempo da lista`,
   com ou sem `(durante a retomada)`, e também `teto de telas`): acontece quando
   a agenda é grande, o iPhone está lento, ou o filtro de DDD só libera contatos
   lá no fim da agenda. Aqui `--pular-celula-ilegivel` não muda nada. A estação
   **sempre** manda o tempo máximo padrão e não tem campo na tela para mudá-lo:
   é preciso rodar essa rodada pelo Terminal com `--max-minutos` maior.

### "celula sem rotulo" e "celula sem posicao legivel"

**O que quer dizer:** uma linha da agenda com a **altura de uma linha de contato**
não devolveu o nome (`celula sem rotulo (nao da para saber quem e)`) ou não
devolveu onde está na tela (`celula sem posicao legivel (o rect nao respondeu)`),
em **duas** leituras seguidas.

**Por que a estação para em vez de seguir:** tocar nas linhas seguintes deixaria
essa pessoa atrás do ponto de retomada — fora de qualquer lista, hoje e sempre,
em silêncio. Parando, ela é a próxima da fila na rodada seguinte. Só é ignorada
(sem parar a lista) a linha **bem mais baixa** que a linha de contato — um
cabeçalho de seção ("A", "B"), um separador. Uma linha mais alta, ou só um pouco
mais baixa, para a lista: a altura de uma linha de contato varia de verdade
(recado que quebra em duas linhas, contato sem recado, Dynamic Type), e na
dúvida a estação prefere parar a ultrapassar alguém.

**O que fazer:** rode de novo. Se a rodada seguinte parar **no mesmo ponto**
(mesmo `proximo_contato_n` no progresso), não é lentidão: é essa linha da agenda
que nunca devolve nome. Aí sim use
`python3 run_ios_scroll.py --trust-profile --pular-celula-ilegivel …`
(terminal-only): ela é pulada, **não entra em lista nenhuma**, e isso fica
registrado no progresso.

### "A lista de recuperação não cabe no tempo máximo" (o código 8)

**O que quer dizer:** depois de `--recomecar-do-A` (ou num progresso sem ponto de
retomada), a estação precisa **rolar por cima de todo mundo que já entrou em
lista** antes de chegar em alguém novo. Com a guarda grande, essa travessia
sozinha passa do tempo máximo por lista — a rodada gastaria a hora inteira e
terminaria com zero contatos, sem avançar o progresso, e a rodada seguinte faria
o mesmo. A estação recusa **na largada**, sem tocar em nada.

**O que fazer:** a última linha do log diz de quantos minutos ela precisa. Suba
`--max-minutos` para pelo menos esse número. Se você aceitar duplicar quem já
entrou em listas, `--reset-progresso` também resolve — mas aí todo mundo entra de
novo.

### "contato inalcancavel" (também aparece como "contato inalcancavel na ultima passada")

**O que quer dizer:** um contato apareceu na tela e o toque não pegou nele duas
vezes seguidas. A variante "na ultima passada" é o mesmo problema, só que
descoberto na última leitura da agenda (quando a lista já não rola mais).

**Por que a estação para em vez de pular:** pular deixaria essa pessoa para trás
para sempre, em silêncio. Parando, ela é a primeira da fila na próxima rodada.

**O que fazer:** rode de novo. Se acontecer sempre no mesmo ponto, rode o ensaio
com `-v` e mande o log ao suporte.

### "ancora nao confirmada apos rajada turbo"

**O que quer dizer:** a leva de toques do modo Turbo saiu, mas o botão "Criar"
não reapareceu em duas conferências. Os toques daquela leva ficaram **em dúvida**
— podem ter pegado, podem não ter.

**O que fazer:** **confira no iPhone quantos destinatários a lista tem.** Ela
pode ter mais gente do que o progresso registra, e esses contatos podem aparecer
de novo na lista seguinte (repetir é melhor do que deixar alguém de fora, mas
você precisa saber). A estação avisa isso a cada rodada até você resolver com
`python3 run_ios_scroll.py --resolver-incertos entraram` (se contou no
iPhone e eles JÁ estão numa lista: bloqueia, nunca mais tocados) ou
`--resolver-incertos nao-entraram` (mantém na fila). Depois: desligue o
`--turbo` e continue sem ele.

### "leitura vazia lenta"

**O que quer dizer:** a estação pediu a lista de contatos da tela, o iPhone
demorou demais e devolveu vazio. **Não é fim de agenda** — é o aparelho ou o
WebDriverAgent engasgando.

**O que fazer:** a lista é salva parcial (código 6) e a rodada seguinte continua
sozinha. Se repetir, feche e reabra a estação (isso reinicia o Appium) e não use
`--turbo`.

### "leitura sem inferencia de posicao (excesso de elementos na tela)"

**O que quer dizer:** a tela ficou com elementos demais ao mesmo tempo e a
estação não conseguiu descobrir a posição das linhas de um jeito barato. Ler uma
por uma custaria centenas de consultas nessa única tela — que é exatamente o que
derrubou a sessão em 2026-09-09. Ela prefere parar.

**O que fazer:** igual à anterior — a lista é salva parcial e a rodada seguinte
continua. Se acontecer sempre no mesmo tamanho de lista, é o limite deste
aparelho: opere com listas menores (por exemplo `--limite-por-lista 100`) e
avise o suporte.

### "teto de telas"

**O que quer dizer:** a estação rolou o número máximo de telas previsto para esta
lista e ainda não completou a quantidade pedida. **Não é fim de agenda.**

**Quase sempre a causa é o filtro de DDD ser mais restritivo do que o teto
suporta** — ela rola a agenda inteira, mas só toca em quem passa no filtro.

**O que fazer:** **não adianta aumentar `--limite-por-lista`** (o teto cresce
junto). Use um DDD menos raro, quebre a agenda em arquivos menores, ou confira se
o filtro não está descartando muita gente por homônimo ou por número ausente (o
log diz quantos, na linha "filtro de DDD").

### "rajada interrompida"

**O que quer dizer:** o modo Turbo mandou os toques de uma tela numa requisição
só e ela morreu no meio.

**O que fazer:** o mesmo da "ancora nao confirmada": confira o número de
destinatários no iPhone e desligue o Turbo.

### "nao encontrei o ponto de retomada"

**O que quer dizer:** a estação retoma procurando o **último contato da lista
anterior**. Esse contato mudou de nome, foi apagado da agenda, ou a ordem não
bateu.

**O que fazer:** antes de qualquer coisa, **apague no WhatsApp as listas que
seriam repetidas** (para não duplicar). Depois use
`python3 run_ios_scroll.py --recomecar-do-A`: ele recomeça do primeiro
contato SEM tentar retomada posicional, mas **preserva a guarda** — ninguém que
já está numa lista anterior é re-tocado. É a saída recomendada, porque não
duplica. `--reset-progresso` também recomeça do A, mas **apaga essa memória** e
duplicaria todo mundo já incluído — use só se aceitar isso.

Se a estação **recusar** o `--recomecar-do-A` dizendo que "a guarda não sabe quem
entrou em N de M listas", é porque o arquivo de progresso é antigo (versão 1) e
não guardou o código dos contatos daquelas listas. Recomeçar do A re-tocaria
exatamente essas pessoas, que entrariam numa **segunda** lista de transmissão.
Nesse caso a saída é apagar no WhatsApp as listas antigas e usar
`--reset-progresso`, aceitando refazer tudo.

### "botao Criar esta DESABILITADO"

**O que quer dizer:** havia menos de 2 selecionados. Ou a agenda acabou, ou os
toques não estão marcando.

**O que fazer:** se a agenda não acabou, rode o ensaio de 5 com `-v` e mande o
log.

### "nenhuma celula de contato no seletor"

**O que quer dizer:** a estação abriu a tela de destinatários e não achou linha
de contato nenhuma. Normalmente é o WhatsApp que mudou de versão.

**O que fazer:** não force. Rode `python3 probe_picker.py` e mande o
resultado ao suporte.

### "o seletor de contatos desapareceu"

**O que quer dizer:** o WhatsApp trocou de tela no meio — chamada, notificação,
tela bloqueada.

**O que fazer:** Bloqueio Automático em **Nunca**, silencie o aparelho e rode de
novo.

### "um app externo abriu durante a selecao"

**O que quer dizer:** um toque caiu numa linha "Convidar para o WhatsApp" e o
iPhone abriu o app Mensagens.

**O que fazer:** volte ao WhatsApp, feche o seletor com Cancelar e rode de novo.
**Nada foi criado.**

### "o WDA nao respondeu a nenhuma consulta" / "socket hang up"

**O que quer dizer:** o componente que o Mac instala no iPhone para controlá-lo
caiu. A tela do aparelho pode estar intacta, com contatos marcados.

**O que fazer, nesta ordem:** 1) iPhone desbloqueado, Bloqueio Automático em
Nunca, confiando neste Mac. 2) Se o Xcode estiver aberto rodando o
WebDriverAgent, feche-o. 3) Feche e reabra a estação. 4) Aba **Diagnóstico** →
**Instalar ou reparar WDA**. 5) Se repetir, veja `TRAVOU-EM-OPENING-BROADCAST.md`.

### "A tela do WhatsApp mudou" / UI_CHANGED (código 4)

**O que quer dizer:** a estação chegou numa tela que não reconhece e parou **sem
tocar em nada**. Ela salvou o que viu em `inventory-erro.json`.

**O que fazer:** feche o seletor no iPhone e tente de novo. Se repetir, mande
esse arquivo ao suporte — ele **não** tem nome nem número de ninguém (os textos
de tela são redigidos).

---

## 8. Arquivos que nunca saem do Mac

Estes ficam na pasta da estação e **não vão por e-mail, anexo, WhatsApp, Drive,
nem backup em claro**. Nenhum deles é enviado para o repositório (o `.gitignore`
já barra).

| Arquivo | Por que é sensível |
|---|---|
| `contatos.vcf`, `contatos.csv` e qualquer arquivo que você importar | nome e número de todo mundo, em claro |
| `contatos.restantes.csv`, `contatos.adicionados.csv`, `contatos.nao-adicionados.csv` | idem — são gerados pelo botão "Exportar restantes…" |
| `progress.scroll.local.json` (Scroll Livre) | além dos códigos embaralhados, guarda o **nome do último contato de cada lista** e o **código de todo contato já usado** (a guarda contra duplicata). É o que permite retomar na ordem certa quando esse contato é apagado da agenda. Trate como o próprio arquivo de contatos. |
| `progress.ios.local.json` (modo lista de contatos) | só códigos embaralhados, mas é o histórico da operação |
| `inventory-erro.json` | textos de tela, já redigidos — pode ser enviado ao suporte |

O **log** pode ser enviado ao suporte: ele nunca mostra nome nem número inteiro.

---

## 9. Perguntas rápidas

**As listas saíram com nome estranho.** É o nome padrão do WhatsApp. A estação
não renomeia. Renomeie no WhatsApp.

**Quanto tempo leva uma lista de 256?** No modo lista de contatos, cerca de 13
minutos no ritmo Turbo (o padrão). No Scroll Livre, ninguém mediu ainda — ver
seção 4.

**Posso parar no meio?** Pode. Botão **Parar com segurança**. As listas já
criadas continuam salvas e a próxima rodada retoma daí.

**Criei listas demais e o WhatsApp avisou alguma coisa.** Pare na hora e não
retome no mesmo dia. Criar dezenas de listas em sequência numa conta é um padrão
que pode gerar bloqueio.

**A lista de transmissão não chegou em todo mundo.** Lista de transmissão **só
entrega para quem tem o seu número salvo**. Isso é regra do WhatsApp, não da
estação.

**Como eu atualizo a estação?** Dois cliques em `atualizar.command`. Nunca por
zip.
