# Travou em OPENING_NEW_BROADCAST? Leia isto.

## O fluxo REAL — confirmado no iPhone (WhatsApp iOS atual)

Descoberto e validado no aparelho da Isabella (versão com abas embaixo:
Conversas · Atualizações · Comunidades · Ligações · Você, e busca com Meta AI).
**Todos os identificadores abaixo são `name` de acessibilidade estáveis, iguais
em qualquer idioma** — o pacote já usa exatamente estes:

| Passo | O que é | `name` (accessibility id) |
|---|---|---|
| 1 | aba **Conversas** | `TabBarButton_Chats` |
| 2 | botão **"+"** (Nova conversa) | `NavigationBar_NewChatButton` |
| 3 | célula **"Nova transmissão"** | `PickerView_NewBroadcastCell` |
| 4 | linhas de contato no seletor | `PickerView_ContactCell` |
| 4a | **número** dentro da linha | `PickerView_ContactCell_PhoneNumber` |
| 5 | busca do seletor (abre o campo) | `TokenizedSearchBar_SearchButton` |
| 6 | botão **Criar** (desabilitado até 2+ selecionados) | `ParticipantPickerNavigationBar_RightBarButton` |

> Nessa versão **não existe mais** o botão "Listas de transmissão" no canto
> superior (era das versões antigas). O caminho é pelo **"+"**.

O passo 4a é o melhor achado: o número do contato aparece num campo próprio,
então o pacote **casa pelo número** (E.164), não pelo nome — o jeito mais seguro.

## Por que travava antes (e o que foi corrigido no pacote)

Não era o seletor. Era o **WebDriverAgent caindo ao ler a árvore do WhatsApp**:
- **Profundidade do snapshot**: 12 funciona; 15+ e varreduras da árvore inteira
  (`**/*`, busca por classe) derrubavam o WDA (`0 elementos` / `socket hang up`).
- **`waitForQuiescence`**: o WDA esperava o app "parar" — e o WhatsApp nunca
  para (sincroniza, anima, Meta AI). Precisa ser `False`.
- **Religação ao processo**: só `activate_app` deixava o WDA preso a um processo
  velho → vazio. `forceAppLaunch` + `defaultActiveApplication` corrigem.
- `usePrebuiltWDA` reaproveitava um WDA velho e instável. Removido.

O `build_driver` do pacote já embute **exatamente** a configuração que funcionou.
**Não altere** `snapshotMaxDepth` para cima nem faça varreduras completas.

## Configuração validada (referência)

```python
waitForQuiescence=False, forceAppLaunch=True, shouldTerminateApp=True
settings: defaultActiveApplication=net.whatsapp.WhatsApp, snapshotMaxDepth=12,
          waitForIdleTimeout=0, animationCoolOffTimeout=0, useJSONSource=True
```

## Seletor de contatos — também confirmado

O seletor da transmissão é um **modal sobre a tela de Conversas**. Fatos
confirmados e já aplicados no pacote:
- O **"Criar"** (`ParticipantPickerNavigationBar_RightBarButton`) existe desde o
  início, mas fica **`enabled=false`** até 2+ selecionados. O spike **só clica se
  estiver habilitado**.
- A busca é a **TokenizedSearchBar**: o campo de texto só aparece após tocar em
  `TokenizedSearchBar_SearchButton`. O spike faz isso sozinho.
- As linhas de contato ficam **mais fundas** que a profundidade 12 nesse modal.
  Como o spike **pesquisa pelo número antes** (a lista filtra para 1 linha), ele
  sobe a profundidade em passos pequenos (12→14→16→18) **só com busca pontual por
  id** e volta para 12 depois. Não é varredura — não derruba o WDA.

## Próximo passo: o dry-run (não cria nada)

Cadastre no iPhone os 3 contatos de teste (exato / inexistente / dois com o mesmo
nome) e rode:

```bash
python3 spike_ios.py --contacts contacts.example.csv \
  --wda-bundle com.seunome.WDARunner --trust-profile
```

Esperado: `selected` / `not_found` / `ambiguous` e parada em
`WAITING_CONFIRMATION` **sem criar**. Se algum passo falhar, ele grava
`inventory-erro.json` (só controles, sem dados pessoais) — envie esse arquivo.
Passando, a lista de teste é o comando acima com `--approve-create`.

## Regras de ouro para não derrubar o WDA

1. **Nunca** suba `snapshotMaxDepth` acima de 12 nem use `**/*`.
2. **Só** buscas pontuais: `accessibility id` (preferido) ou predicado.
3. Mantenha a tela do iPhone acesa (Bloqueio Automático → Nunca).
4. Se der `socket hang up`: reinicie o `appium`, rode o WDA no Xcode (⌘U) e tente
   de novo — e mande `appium driver update xcuitest` (WDA velho para o iOS crasha).
