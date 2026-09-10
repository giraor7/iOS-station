# Lista Local — Estação de controle iOS (pacote para o Mac)

Cria listas de transmissão nos **iPhones** usando um **Mac** para dirigir a tela
do WhatsApp (Appium + WebDriverAgent/XCUITest). É o equivalente iOS da automação
Android — que já roda de um PC comum e foi validada em aparelho real.

## Modo Scroll Livre (novo — sem CSV)

Cria as listas tocando nos contatos na ordem em que o WhatsApp os lista
(A, B, C…) e rolando a tela, 256 por lista, guardando onde parou para a
próxima começar no contato seguinte. Sem CSV, sem digitar número.
Guia completo e teste obrigatório de 5 contatos: **`MODO-SCROLL-LIVRE.md`**.

```bash
python3 run_ios_scroll.py --trust-profile --limite-por-lista 5                    # ensaio (não cria)
python3 run_ios_scroll.py --trust-profile --approve-create --max-listas 3         # 3 listas de 256
python3 run_ios_scroll.py --progresso                                             # onde parou
```

Na GUI (`gui_ios.py`): interruptor "Modo Scroll Livre" + "listas nesta rodada" + botão "Onde parou?".

## A interface (Estação iOS)

`python3 gui_ios.py` (ou dois cliques em `iniciar_gui.command`) abre a estação.
Três abas na lateral: **Operação**, **Diagnóstico** e **Configurações**.

A aba Operação é uma sequência de cinco etapas, de cima para baixo:

1. **Estado da estação** — iPhone, Appium, WebDriverAgent e fonte de contatos.
   O que faltar aparece com o motivo e o que fazer, não só apagado.
2. **De onde vêm os contatos** — dois cartões que se excluem: *Importar CSV ou
   VCF* (com resumo de quantos entraram, quantos foram descartados e quantas
   listas saem) ou *Usar Scroll Livre* (sem arquivo, de 1 a 36 listas por
   rodada, com o botão "Consultar progresso").
3. **Filtrar por DDD** — só no modo arquivo. Marque 21, 22 e 24 direto ou
   digite outros separados por vírgula. Vale combinar.
4. **Tipo de execução** — *Simulação segura* (padrão, sempre) ou *Criar listas
   de verdade*, que abre uma confirmação com modo, arquivo, DDDs, contatos e
   listas antes de começar.
5. **Execução** — o que está acontecendo em português, barra de progresso,
   "Lista X de Y", botão Parar com segurança e o log técnico completo dentro
   de "Ver detalhes técnicos".

Ao terminar, a tela diz em uma frase se concluiu, se você interrompeu ou se
parou por segurança — e o que fazer nesse caso. O código técnico fica no log.

Arquivos da interface: `gui_ios.py` (janela e fluxo), `gui_state.py` (as regras
que ela usa para decidir — testáveis sem tela) e `ui_kit.py` (tokens visuais e
componentes). A automação em si (`spike_ios.py`, `run_ios.py`,
`run_ios_scroll.py`, seletores) não foi tocada.

Testes da interface, sem iPhone: `python3 test_gui_state.py` e
`python3 test_gui_runner.py`.

## Listas em sequência (mais de 256 contatos)

Depois do "Criar", o WhatsApp abre a conversa da lista recém-criada. A estação
grava o progresso dessa lista e **volta para Conversas** antes de abrir a
seguinte — nos dois modos. Sem essa volta a segunda lista não achava o "+",
que não existe dentro de uma conversa. Confirmado no iPhone em 2026-09-09.

As listas ficam com o nome padrão do WhatsApp (a nomeação automática foi
retirada: a tela de informações da lista não expôs os elementos esperados).
Renomeie no próprio WhatsApp, se quiser.

Para validar a sequência no modo lista de contatos sem um CSV de 257 contatos,
use lotes pequenos **só no teste**:

```bash
.venv/bin/python run_ios.py --csv contatos.csv --trust-profile --approve-create --limite-por-lista 5 --max-lists 2
```

Um CSV com 10 contatos vira duas listas de 5 ("Transmissão 001" e "002" no
progresso). O limite nunca passa de 256 nem fica abaixo de 2; sem a opção,
a operação real segue em lotes de 256.

## Dividir a criação em dias (sessão)

O progresso (`progress.ios.local.json`, só hashes) guarda todo contato que
entrou numa lista **criada**. Em qualquer rodada seguinte, com o mesmo
arquivo ou com outro, esses contatos ficam de fora sozinhos e só os
restantes viram listas novas. Ou seja: para continuar amanhã, basta importar
o mesmo CSV de novo. A tela mostra "Já em listas" e planeja só os restantes.

Contatos que saíram como *não encontrado* ou *ambíguo* também ficam de fora
por padrão (cada um custa ~3 s para falhar de novo); `--repetir-nao-encontrados`
tenta de novo.

Para ter os arquivos em mãos (botão **Exportar restantes…** na tela, ou):

```bash
.venv/bin/python run_ios.py --csv contatos.csv --exportar
```

Grava, ao lado do CSV importado e sem tocar no iPhone: `contatos.restantes.csv`
(o que falta), `contatos.adicionados.csv` (já em listas) e, se houver,
`contatos.nao-adicionados.csv` (com a coluna `motivo`). Os três aceitam o
filtro de DDD da linha de comando e são importáveis de volta. Ficam só no Mac,
como o próprio CSV.

Uma lista só conta como criada depois do toque em "Criar": simulação e lista
interrompida não marcam ninguém como adicionado.

## Comece por aqui

```bash
cd ios-station
python3 test_local.py     # 1) valida o pacote SEM iPhone (2 min)
python3 doctor_ios.py     # 2) diz o que falta instalar no Mac
```
Depois siga, nesta ordem:
1. **`SETUP-MAC.md`** — instalação completa e passo a passo (Xcode, WDA, iPhone).
2. **`DEVICE-TEST-IOS.md`** — ordem de teste: seu iPhone primeiro, depois os outros.

## Por que uma "estação" e não um app no iPhone

O iOS **não** permite que um app controle outro app — e o **WhatsApp Web não cria
listas de transmissão** (nunca criou). Portanto a única via é um Mac dirigindo o
aparelho por fora. Não há atalho.

## Arquivos

- `run_ios_scroll.py` — **Modo Scroll Livre** (sem CSV); `test_scroll_local.py` — 15 testes offline; `MODO-SCROLL-LIVRE.md` — guia.

| Arquivo | O que faz |
|---|---|
| `doctor_ios.py` | **Diagnóstico**: checa macOS, Xcode, Appium, driver, iPhone, Modo de Desenvolvedor, WhatsApp. Rode primeiro. |
| `test_local.py` | **Testes sem iPhone**: lotes, vCard, redação, regiões, travas de segurança. |
| `diag_ios.py` | **Descoberta somente-leitura** da UI (inventário com dados pessoais redigidos). Passo obrigatório. |
| `ios_selectors.py` | Perfis de seletores por versão — **a preencher** na descoberta. |
| `spike_ios.py` | Valida o fluxo com 3 casos; para antes de criar. Caminho rápido por class chain. |
| `bench_ios.py` | Mede o tempo por contato **sem criar nada**. |
| `run_ios.py` | Runner: CSV → **filtros DDD/UF/região** → lotes de 256 → `Transmissão NNN`, com ritmo e retomada. |
| `regions.py` | Tabela DDD → UF → região (67 DDDs, 27 UFs) e filtros por área. |
| `filter_contacts.py` | Filtra/segmenta um CSV por DDD/UF/região (report, split-by, exclusões). Não toca no iPhone. |
| `vcf_to_csv.py` | Converte contatos exportados do Mac (vCard) em CSV, deduplicado e em lotes. |

## Filtros por DDD / UF / região (novo)

Antes de operar, dá para segmentar a base — igual ao Android:

```
# ver a distribuição da base por DDD/UF/região
python3 filter_contacts.py contatos.csv --report

# criar CSV só com RJ e ES, já em lotes de 256
python3 filter_contacts.py contatos.csv --uf RJ,ES -o sudeste.csv --split 256

# um arquivo por UF (contatos.RJ.csv, contatos.SP.csv, ...)
python3 filter_contacts.py contatos.csv --split-by uf
```

Ou direto no runner, sem CSV intermediário:

```
python3 run_ios.py --csv contatos.csv --udid <UDID> --uf RJ --dry-run
python3 run_ios.py --csv contatos.csv --udid <UDID> --regiao Sudeste --excluir-ddd 11 --dry-run
```
| `batching.py` | Regras puras (E.164, dedupe, lotes) — idênticas às do Android. |
| `setup_mac.sh` | Instalador (Homebrew, Node, Appium, driver XCUITest, deps). |
| `contacts.example.csv` | Modelo de CSV (`name,phone`). |

## Estado honesto deste pacote

- ✅ **Regras de contatos/lotes**: testadas e idênticas às já validadas no Android.
- ✅ **Travas de segurança**: testadas (nunca envia, exige aprovação, para em UI desconhecida).
- ⚠️ **Fluxo de tela do WhatsApp iOS**: **ainda não confirmado num iPhone**. Os
  seletores em `ios_selectors.py` são palpites marcados "A CONFIRMAR". Por isso a
  seção 6 do `SETUP-MAC.md` (descoberta) é obrigatória antes de criar listas.
  Enquanto a versão não for registrada, os scripts exigem `--trust-profile`.

## Segurança (igual ao Android)

- **Nunca** envia mensagem, abre conversa ou toca no compositor — há uma trava
  que aborta a execução se um campo de mensagem aparecer na tela.
- Estado de UI desconhecido ⇒ para (`UI_CHANGED`), sem clicar no escuro.
- Só seleciona **match exato e único**; ambíguo nunca é tocado.
- Sem coordenadas fixas, sem XPath, sem esperas fixas.
- **Logs** sempre mascarados (hash + 2 dígitos): nunca mostram número nem nome.
- **Progresso**: `progress.ios.local.json` (modo CSV) só tem hashes.
  `progress.scroll.local.json` (Modo Scroll Livre) guarda, além dos hashes, o
  **nome do último contato de cada lista** — é o que permite retomar na ordem
  alfabética quando esse contato é apagado da agenda entre uma lista e outra
  (`MODO-SCROLL-LIVRE.md`). Por isso esse arquivo é tão sensível quanto o
  `contatos.csv`: fica só no Mac, nunca vai por e-mail, anexo ou backup em claro.
- Criação de lista só com `--approve-create`; mínimo de 2 destinatários.

## Contatos (CSV)

```
name,phone
Fulano,+55 21 99999-0001
```
`phone` em qualquer formato — é normalizado para E.164 (padrão BR) e deduplicado.
Para gerar a partir do iPhone: Contatos.app → Exportar vCard → `vcf_to_csv.py`
(ver `SETUP-MAC.md` seção 10).

## Tempo esperado

~3,8 s/contato **medido neste iPhone** no modo lista de contatos (Appium, 2026-09-04) ⇒ **~16 min por lista de 256**. Cerca de 2,5 s disso são chamadas ao aparelho e ~1 s são pausas. As três consultas retiradas em 2026-09-10 devem levar a ~3 s/contato (~13 min): confirme com `bench_ios.py --with-tap` antes e depois. Um minuto por lista **não é alcançável neste modo**: só limpar o campo, digitar e tocar já custa ~1,55 s por contato, ou 6,6 min por lista, sem contar a leitura da tela.
**~8-10 h** para 10 mil contatos num aparelho. Aparelhos em paralelo ≈ tempo de um.
Confirme no seu caso com `bench_ios.py`.

## Atenção operacional

Lista de transmissão **só entrega para quem tem o seu número salvo**. E criar ~40
listas seguidas numa conta é um padrão que pode gerar bloqueio — use `--pace`,
comece com `--max-lists 1` e pare ao primeiro aviso do WhatsApp.
