"""Perfis de seletores do WhatsApp iOS, por versao.

>>> LEIA ANTES DE USAR <<<
Os valores do perfil BASELINE abaixo sao PALPITES baseados no fluxo do Android
(que foi validado em aparelho real) e nos rotulos visiveis do WhatsApp iOS.
Eles NAO foram confirmados num iPhone. O primeiro passo no Mac e rodar

    python3 diag_ios.py --inventory

em CADA tela do fluxo, e corrigir este arquivo com os valores reais. Enquanto
`version_prefixes` estiver vazio, o perfil nunca casa sozinho: os scripts exigem
--trust-profile, e a recomendacao e so operar de verdade depois de preencher a
versao validada.

Ordem de preferencia dos localizadores (nunca coordenadas, nunca XPath):
  1. accessibility id (atributo `name`)          -> mais estavel e mais rapido
  2. class chain (estrutura + tipo)              -> rapido, tolera mudanca de texto
  3. predicate por label/name/value exato        -> depende do idioma
  4. predicate por label/name CONTAINS           -> ultimo recurso
"""

from __future__ import annotations

from dataclasses import dataclass, field

BUNDLE_ID = "net.whatsapp.WhatsApp"


@dataclass(frozen=True)
class IosSelector:
    """Um alvo da UI descrito em camadas, da mais estavel a menos."""
    accessibility_id: str | None = None
    class_chain: str | None = None                 # ex.: **/XCUIElementTypeCell
    element_type: str | None = None                # ex.: XCUIElementTypeButton
    labels: tuple[str, ...] = ()                   # variantes pt-BR / en
    predicate: str | None = None                   # escape final


@dataclass(frozen=True)
class IosProfile:
    name: str
    version_prefixes: tuple[str, ...] = ()
    selectors: dict[str, IosSelector] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# BASELINE — A CONFIRMAR NO IPHONE (ver cabecalho)
# ---------------------------------------------------------------------------
BASELINE = IosProfile(
    name="ios-baseline-a-confirmar",
    version_prefixes=(),  # vazio de proposito: nunca casa sem validacao
    selectors={
        # --- entrada do fluxo -------------------------------------------------
        # FLUXO REAL — CONFIRMADO NO IPHONE (WhatsApp iOS com abas embaixo,
        # busca Meta AI; 2025-2026). Todos os `name` abaixo sao accessibility
        # ids ESTAVEIS e independentes de idioma, lidos no aparelho da Isabella:
        #   aba Conversas (TabBarButton_Chats)
        #     -> "+" Nova conversa (NavigationBar_NewChatButton)
        #     -> celula "Nova transmissao" (PickerView_NewBroadcastCell)
        #     -> seletor de contatos (PickerView_ContactCell, com o numero em
        #        PickerView_ContactCell_PhoneNumber)  -> "Criar"
        # NAO existe mais o botao "Listas de transmissao" no canto (versao antiga).
        "chats_tab": IosSelector(
            accessibility_id="TabBarButton_Chats",
        ),
        "new_chat_button": IosSelector(
            accessibility_id="NavigationBar_NewChatButton",
            labels=("Nova conversa", "New chat"),
        ),
        "new_broadcast_cell": IosSelector(
            accessibility_id="PickerView_NewBroadcastCell",
            labels=("Nova transmissão", "New Broadcast", "New broadcast"),
        ),

        # --- seletor de contatos (CONFIRMADO: e um modal sobre Conversas) -----
        # A busca e a "TokenizedSearchBar": um BOTAO abre o campo de texto.
        "picker_search_button": IosSelector(
            accessibility_id="TokenizedSearchBar_SearchButton",
            labels=("Pergunte à Meta AI ou pesquise", "Pesquisar", "Search"),
        ),
        # O campo de texto que aparece apos tocar na busca (SearchField ou TextField).
        "search_field": IosSelector(
            class_chain="**/XCUIElementTypeSearchField",
            predicate='type == "XCUIElementTypeTextField" OR type == "XCUIElementTypeSearchField"',
        ),
        "clear_search": IosSelector(
            accessibility_id="TokenizedSearchBar_DeleteButton",
            labels=("Limpar texto", "Clear text"),
        ),
        # "Cancelar" do seletor — presente inclusive com a busca ativa (quando a
        # barra de navegacao com o "Criar" fica escondida pelo teclado).
        "cancel_button": IosSelector(
            element_type="XCUIElementTypeButton",
            labels=("Cancelar", "Cancel"),
        ),
        # Ancora que prova que estamos no seletor da transmissao (id estavel).
        "picker_anchor": IosSelector(
            accessibility_id="ParticipantPickerNavigationBar_RightBarButton",
        ),
        # Linha de contato (accessibility id confirmado).
        "contact_cell": IosSelector(
            accessibility_id="PickerView_ContactCell",
            class_chain="**/XCUIElementTypeCell",
        ),
        # NUMERO do contato dentro da linha (confirmado) -> match exato por numero.
        "contact_phone": IosSelector(
            accessibility_id="PickerView_ContactCell_PhoneNumber",
        ),
        # Evidencia de "ja selecionado" DENTRO da celula (icone de check).
        # No Android 2.26 nao existe equivalente; se aqui tambem nao existir,
        # deixe vazio e a seguranca fica no match exato unico.
        "selected_indicator": IosSelector(
            element_type="XCUIElementTypeImage",
            labels=("Selecionado", "Selected"),
        ),
        # Chips/avatares dos selecionados no topo (se a UI tiver).
        "selected_chip": IosSelector(
            class_chain="**/XCUIElementTypeCollectionView/**/XCUIElementTypeCell",
        ),
        # Botao "Criar" — CONFIRMADO (id estavel). Fica DESABILITADO (enabled=false)
        # ate haver 2+ selecionados; o spike so clica quando estiver habilitado.
        "create_button": IosSelector(
            accessibility_id="ParticipantPickerNavigationBar_RightBarButton",
            labels=("Criar", "Create"),
        ),

        # --- trava de seguranca ----------------------------------------------
        # Se isto aparecer, estamos numa conversa: o spike ABORTA na hora.
        # Nunca escrevemos nem enviamos mensagem.
        "message_composer": IosSelector(
            element_type="XCUIElementTypeTextView",
            labels=("Mensagem", "Message", "Digite uma mensagem", "Type a message"),
        ),
    },
)

PROFILES: list[IosProfile] = [BASELINE]


def profile_for_version(version_name: str) -> IosProfile | None:
    """Perfil validado para a versao instalada, ou None (=> parada segura)."""
    if not version_name:
        return None
    for p in PROFILES:
        if p.version_prefixes and any(version_name.startswith(v) for v in p.version_prefixes):
            return p
    return None
