# Estação de controle iOS — passo a passo (MacBook Pro)

Objetivo: usar o Mac para dirigir a tela do WhatsApp de cada iPhone e criar as
listas de transmissão — do mesmo jeito que o PC faz com os Androids.
**O iPhone não roda nenhum app nosso**; quem comanda é o Mac.

> **Por que assim?** O iOS não permite que um app controle outro app. A única
> forma de automatizar o WhatsApp no iPhone é um computador dirigindo o aparelho
> por fora (Appium + WebDriverAgent). Não existe atalho por WhatsApp Web: a
> interface web **não cria** listas de transmissão.

> **Estado honesto:** as regras de contatos/lotes já são as mesmas validadas no
> Android (rodando de verdade). O **modo lista de contatos (CSV/VCF) já está
> validado no iPhone da operação e em uso diário** — os seletores em
> `ios_selectors.py` foram lidos no aparelho (ver os comentários "CONFIRMADO NO
> IPHONE" no próprio arquivo). A seção 6 (descoberta) continua obrigatória para
> um **aparelho novo** ou uma **versão nova do WhatsApp**. O Modo Scroll Livre é
> a parte ainda não validada em escala — ver `COMO-OPERAR.md` §4.

---

## 0. Antes de tudo: valide o pacote sem iPhone (2 minutos)

```bash
cd ios-station
python3 test_local.py
```
Esperado: `todos os testes locais passaram.` Isso confirma regras de lote,
conversão de contatos, redação de dados pessoais e as travas de segurança.

### 0.1 Abrir a estação

Depois do setup, o dia a dia é dois cliques em `iniciar_gui.command` (e
`atualizar.command` para atualizar). O guia da operação é o `COMO-OPERAR.md`.

---

## 1. Pré-requisitos

| Item | Observação |
|---|---|
| macOS | Apple Silicon ou Intel |
| **Xcode** | instale pela App Store e **abra uma vez** (aceita a licença). É grande — comece por ele. |
| Apple ID | o grátis funciona, mas exige **reassinar o WebDriverAgent a cada 7 dias**. Para 20 aparelhos, vale o **Apple Developer Program (US$99/ano)**. |
| Cabo USB | um por aparelho; evite hubs baratos (quedas de conexão travam a sessão). |

## 2. Instalação automática

```bash
cd ios-station
chmod +x setup_mac.sh
./setup_mac.sh
```
Instala Homebrew, Node, Python, libimobiledevice, Appium 2 + driver XCUITest,
dependências Python, abre o projeto do WebDriverAgent e roda o diagnóstico.

A qualquer momento, para saber o que está faltando:
```bash
python3 doctor_ios.py
```

## 3. Assinar o WebDriverAgent (uma vez por Mac)

O WebDriverAgent (WDA) é o app que o Appium instala no iPhone para controlá-lo.
Ele precisa ser assinado com a sua conta Apple.

1. Abra o projeto:
   ```bash
   appium driver run xcuitest open-wda
   ```
2. No Xcode: selecione o alvo **WebDriverAgentRunner** → aba **Signing &
   Capabilities** → marque **Automatically manage signing** → escolha seu **Team**.
3. Troque o **Bundle Identifier** para um único seu, ex.
   `com.seunome.WebDriverAgentRunner`. **Anote** — é o `--wda-bundle` dos comandos.
   *(Se aparecer "Failed to register bundle identifier", troque para outro nome
   ainda mais único, ex. `com.seunome.wda2026`.)*
4. Conecte o iPhone, selecione-o como destino e rode **Product → Test** (⌘U) uma vez.
5. No iPhone, confie no certificado:
   **Ajustes → Geral → VPN e Gerenciamento de Dispositivos → (seu perfil) → Confiar**.

## 4. Preparar cada iPhone

1. Conecte por USB, desbloqueie e toque **Confiar** neste computador.
2. **Modo de Desenvolvedor** (iOS 16+):
   **Ajustes → Privacidade e Segurança → Modo de Desenvolvedor → Ativar** (reinicia).
   *O item só aparece depois que o Xcode tentar rodar algo no aparelho (passo 3.4).*
3. Descubra o UDID:
   ```bash
   idevice_id -l
   ```
4. Anote a versão do WhatsApp: no iPhone, **WhatsApp → Ajustes → Ajuda**.
5. **Mantenha a tela ligada** durante a operação
   (**Ajustes → Tela e Brilho → Bloqueio Automático → Nunca**). Tela bloqueada
   derruba a automação.

## 5. Subir o Appium

Num terminal separado, deixe rodando:
```bash
appium
```

## 6. Descobrir os seletores — obrigatório para um aparelho NOVO ou uma versão nova do WhatsApp

No aparelho da operação isso já foi feito; `version_prefixes` continua vazio de
propósito, então os scripts pedem `--trust-profile` — e a estação passa esse
argumento sozinha.

Abra o WhatsApp no iPhone e, **em cada tela do fluxo**, rode:

```bash
python3 diag_ios.py --inventory \
  --wda-bundle com.seunome.WebDriverAgentRunner \
  --out tela-1-conversas.json
```
Repita para: tela inicial → entrada de listas de transmissão → nova lista →
seletor de contatos. (Use `--only-interactive` para ver só o que é clicável.)

O inventário **não clica em nada** e **redige nomes/números** automaticamente.
Cada elemento vem com uma linha `sugestao` pronta para colar.

Agora edite **`ios_selectors.py`**:
- preencha `accessibility_id`, `class_chain`, `labels` e `element_type` reais;
- registre a versão em `version_prefixes`, ex.: `version_prefixes=("24.",)`.

Enquanto `version_prefixes` estiver vazio, os scripts **exigem `--trust-profile`**
— é o sinal de que ainda não foi validado.

## 7. Dry-run dos casos de teste (não cria nada)

Cadastre no iPhone 3 contatos de teste: um **exato** (com WhatsApp), um
**inexistente**, e dois com o **mesmo nome** (ambíguo). Depois:

```bash
python3 spike_ios.py --contacts contacts.example.csv \
  --wda-bundle com.seunome.WebDriverAgentRunner --trust-profile
```

Esperado: `selected` / `not_found` / `ambiguous`, terminando em
`WAITING_CONFIRMATION` **sem criar nada**. Ajuste `ios_selectors.py` até os três
casos saírem certos. **Só então** prossiga.

## 8. Medir o tempo (opcional, sem criar nada)

```bash
python3 bench_ios.py --csv contatos.csv --n 20 --with-tap --trust-profile
```
Dá o tempo por contato e extrapola para 256/lista e 40 listas.
Referência medida NESTE fluxo: **~3 s/contato no ritmo Turbo → ~13 min por
lista de 256** (ver a tabela do `DEVICE-TEST-IOS.md`).

## 9. Criar UMA lista de teste (com aprovação explícita)

```bash
python3 spike_ios.py --contacts contacts.example.csv \
  --wda-bundle com.seunome.WebDriverAgentRunner --trust-profile --approve-create
```
Confirme no iPhone que a lista existe e que **nenhuma mensagem foi enviada**.
Apague a lista de teste depois.

> **A lista exige pelo menos 2 destinatários.** No Android confirmamos que o
> botão "Criar" só aparece com 2+ selecionados; o pacote já valida isso.

## 10. Preparar os contatos (10 mil por aparelho)

No iPhone não dá para puxar contatos por linha de comando. Caminho suportado:

1. No Mac, abra **Contatos** (sincronizado com o iCloud do iPhone).
2. Selecione os contatos → **Arquivo → Exportar → Exportar vCard…** → salve `contatos.vcf`.
3. Converta e já divida em lotes:
   ```bash
   python3 vcf_to_csv.py contatos.vcf -o contatos.csv --split 256
   ```
   Gera `contatos.csv` (tudo) e `contatos.lote001.csv`, `lote002.csv`, … (256 cada),
   já normalizados em E.164 e **sem duplicados**.

### 10.1 Filtrar por DDD / UF / região (opcional)

```bash
# ver a distribuição da base
python3 filter_contacts.py contatos.csv --report

# só um estado / uma região
python3 filter_contacts.py contatos.csv --uf RJ,ES -o rj-es.csv --split 256
python3 filter_contacts.py contatos.csv --regiao Sudeste -o sudeste.csv

# um arquivo por UF de uma vez
python3 filter_contacts.py contatos.csv --split-by uf
```
Ou aplicar o filtro direto no runner (sem gerar CSV): `--uf RJ`, `--ddd 21,22`,
`--regiao Sudeste`, `--excluir-ddd 11`.

## 11. Operar em lote

```bash
# 1) planejar (não toca no iPhone)
python3 run_ios.py --csv contatos.csv --dry-run

# 2) criar SÓ a primeira lista e conferir
python3 run_ios.py --csv contatos.csv \
  --wda-bundle com.seunome.WebDriverAgentRunner --wa-version <versao> \
  --approve-create --max-lists 1

# 3) seguir com o resto (retoma sozinho se cair)
python3 run_ios.py --csv contatos.csv \
  --wda-bundle com.seunome.WebDriverAgentRunner --wa-version <versao> \
  --approve-create --pace 1.0
```

O progresso fica em `progress.ios.local.json` (apenas hashes). Se a execução cair,
rode de novo: ele **pula as listas já concluídas**.

---

## Riscos de bloqueio de conta (leia antes de escalar)

Criar ~40 listas seguidas numa conta é um padrão que o WhatsApp pode interpretar
como automação abusiva. Mitigações que o pacote oferece — **use-as**:

- `--pace 1.0` (padrão) espaça os contatos; `--pace-lists 30` espaça as listas.
- Comece com `--max-lists 1`, confira, e só então libere o resto.
- Não rode os 20 aparelhos na mesma conta nem no mesmo minuto.
- **Pare imediatamente** ao primeiro aviso do WhatsApp e não retome no mesmo dia.
- Lembre: lista de transmissão **só entrega para quem tem o seu número salvo**.

## Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `xcodebuild failed` / WDA não sobe | assinatura do WDA | refaça a seção 3; troque o bundle id |
| WDA cai a cada 7 dias | Apple ID grátis | use o Apple Developer Program |
| `Could not connect to server` | Appium não está rodando | abra outro terminal e rode `appium` |
| Sessão trava no meio | tela bloqueou | Bloqueio Automático → Nunca (seção 4.5) |
| `elemento nao localizado` | seletor não confere | refaça a seção 6 nessa tela |
| Aparelho some do `idevice_id -l` | cabo/hub ruim | troque o cabo, ligue direto no Mac |
| `versao sem perfil validado` | falta registrar a versão | preencha `version_prefixes` em `ios_selectors.py` |

## Se quiser que o Claude valide o iOS ao vivo

Instale o **Claude Code** no Mac (https://claude.com/claude-code) e peça para ele
seguir a seção 6 com o iPhone conectado — ele preenche `ios_selectors.py` e roda
o dry-run, como foi feito no Android. Sem isso, siga este passo a passo à mão;
os scripts já estão prontos.
