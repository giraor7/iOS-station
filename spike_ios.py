"""Spike iOS (Mac) — descoberta e validacao do fluxo de listas de transmissao no
WhatsApp do iPhone, via Appium + driver XCUITest (WebDriverAgent).

Equivalente do spike_a.py que ja foi VALIDADO no Android. As licoes daquele
spike estao incorporadas aqui:
  * o item da lista pode NAO refletir a selecao (no Android so aparece um chip no
    topo) -> a verificacao tenta varias evidencias e, na falta delas, a seguranca
    vem do match EXATO UNICO (nunca tocamos em resultado ambiguo);
  * a lista exige um MINIMO de destinatarios (no Android, 2) -> conferimos antes;
  * estado desconhecido = parada segura, nunca clique no escuro;
  * esperas condicionadas (sem sleep fixo) e seletores semanticos (sem coordenadas).

IMPORTANTE: os SELETORES do WhatsApp iOS ainda precisam ser descobertos no
iPhone real (rode diag_ios.py --inventory e preencha ios_selectors.py). Ate la,
use --trust-profile por sua conta e risco, sempre comecando pelo dry-run.

Seguranca: nunca envia mensagem, nunca abre conversa, nunca toca no compositor;
cria lista SOMENTE com --approve-create; logs mascarados (hash + 2 digitos).

Uso (no Mac, iPhone conectado via USB e `appium` rodando):
  python3 diag_ios.py --inventory
  python3 spike_ios.py --contacts contacts.example.csv --trust-profile
  python3 spike_ios.py --contacts contacts.example.csv --trust-profile --approve-create
"""

from __future__ import annotations

import argparse
import enum
import hashlib
import json
import logging
import os
import sys
import time

import phonenumbers
from appium import webdriver
from appium.options.ios import XCUITestOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait

import batching
from ios_selectors import BASELINE, BUNDLE_ID, IosProfile, IosSelector, profile_for_version

WAIT = 15
WAIT_SHORT = 4
BROADCAST_LIMIT = 256
MIN_RECIPIENTS = 2  # confirmado no Android; a confirmar no iOS

log = logging.getLogger("spike_ios")


def mask(value: str) -> str:
    """Nunca logar nome/numero completo."""
    if not value:
        return "<>"
    h = hashlib.sha256(value.encode()).hexdigest()[:8]
    tail = value[-2:] if len(value) >= 2 else ""
    return f"<{h}...{tail}>"


class State(enum.Enum):
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    OPENING_WHATSAPP = "OPENING_WHATSAPP"
    OPENING_NEW_BROADCAST = "OPENING_NEW_BROADCAST"
    SEARCHING = "SEARCHING"
    MATCHING = "MATCHING"
    SELECTING = "SELECTING"
    VERIFYING = "VERIFYING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    SAVING = "SAVING"
    COMPLETED = "COMPLETED"
    # excecao
    CONTACT_NOT_FOUND = "CONTACT_NOT_FOUND"
    AMBIGUOUS_CONTACT = "AMBIGUOUS_CONTACT"
    ALREADY_SELECTED = "ALREADY_SELECTED"
    UI_CHANGED = "UI_CHANGED"
    WHATSAPP_VERSION_UNSUPPORTED = "WHATSAPP_VERSION_UNSUPPORTED"
    FAILED_SAFE = "FAILED_SAFE"


class UiChanged(Exception):
    """Estado de UI nao reconhecido: paramos sem clicar."""


class UnsafeState(Exception):
    """Chegamos perto de algo proibido (ex.: compositor de mensagem)."""


class IosSpike:
    def __init__(self, driver, profile: IosProfile, speed: float = 1.0):
        self.d = driver
        self.p = profile
        self.state = State.IDLE
        self.results: list[dict] = []
        # Quando a UI nao expoe evidencia de selecao, confiamos no match exato
        # unico (mesma decisao tomada no Android 2.26).
        self.verify_selection = True
        # speed: multiplicador de velocidade (1.0 = seguro, 0.6 = rapido, 0.4 = turbo).
        # Escalona TODAS as chamadas a settle(). ScrollLivre tem seu proprio settle,
        # portanto nao e afetado por este parametro.
        self.speed = max(0.25, min(float(speed), 1.0))
        # Profundidade em que as celulas do picker apareceram da ultima vez.
        # Descoberta uma vez por sessao; evita subir 12->14->16->18 a cada contato.
        self._depth_ok: int | None = None
        self._composer_pred: str | None = None
        # Campo de busca do picker, reaproveitado entre contatos (1 busca a menos
        # por contato). Refeito quando o elemento expira ou o picker reabre.
        self._search_box = None
        # Checagens de seguranca (compositor, app em primeiro plano) a cada N
        # contatos, nao a cada um: a celula "Convidar" — motivo original delas —
        # ja e barrada ANTES do toque pelo rotulo. Comeca "vencido" para checar
        # no 1o contato de cada lista.
        # LL_RAPIDO=1 liga o modo experimental (checagens a cada 8 contatos,
        # rotulos na resposta da busca). Desligado: checa a CADA contato e le
        # celula a celula — o comportamento que criou listas no iPhone.
        # Chaves separadas para isolar a causa no aparelho:
        #   LL_RAPIDO=1     liga tudo abaixo de uma vez
        #   LL_CHECAGEM=8   checagens de seguranca a cada 8 contatos (padrao: cada 1)
        #   LL_ATTRS=1      rotulos na resposta da busca (conferencia em 1 chamada)
        #   LL_DIGITACAO=N  caracteres por segundo ao digitar (padrao do WDA: 60)
        self.rapido = os.environ.get("LL_RAPIDO") == "1"
        self.attrs_na_resposta = self.rapido or os.environ.get("LL_ATTRS") == "1"
        # PADRAO: a cada 8 contatos (medido no iPhone: activeAppInfo custa ~0,8 s
        # por contato, o item mais caro do ciclo). A seguranca nao depende disto:
        # se o seletor sumir, a busca do contato seguinte falha sozinha e a
        # estacao para; e a celula "Convidar" e barrada pelo rotulo ANTES do
        # toque. LL_CHECAGEM=1 volta a checar a cada contato.
        intervalo = os.environ.get("LL_CHECAGEM", "8").strip()
        self._CHECAR_INTERVALO = int(intervalo) if intervalo.isdigit() and int(intervalo) > 0 else 8
        self.checagem_periodica = self._CHECAR_INTERVALO > 1
        self._contatos_desde_check = self._CHECAR_INTERVALO
        # Textos das celulas vindos na propria resposta da busca
        # (elementResponseAttributes). None = ainda nao se sabe se o driver honra.
        self._attrs_ok: bool | None = None
        self._rotulos_celulas: list | None = None

    # ---------------- infra ----------------

    def transition(self, s: State) -> None:
        log.info("estado: %s -> %s", self.state.value, s.value)
        self.state = s

    def settle(self, timeout: float = 1.5) -> None:
        """Pausa curta para animacoes assentarem. Escalada por self.speed.

        O floor impede que pausas criticas (ativacao do WhatsApp, abertura do
        picker) sejam encurtadas demais: nunca abaixo de max(0.25s, 25% do
        timeout). No speed=1.0 o comportamento e identico ao original."""
        floor = max(0.25, timeout * 0.25)
        t = min(max(timeout * self.speed, floor), 2.0)
        time.sleep(t)

    def _locators(self, sel: IosSelector):
        """Camadas, da mais estavel a menos. Class chain antes de XPath (XPath no
        iOS e lento e fragil; aqui nao usamos XPath)."""
        if sel.accessibility_id:
            yield AppiumBy.ACCESSIBILITY_ID, sel.accessibility_id
        if sel.class_chain:
            yield AppiumBy.IOS_CLASS_CHAIN, sel.class_chain
        for lb in sel.labels:
            tipo = f'type == "{sel.element_type}" AND ' if sel.element_type else ""
            yield (AppiumBy.IOS_PREDICATE,
                   f'{tipo}(label == "{lb}" OR name == "{lb}" OR value == "{lb}")')
        for lb in sel.labels:
            tipo = f'type == "{sel.element_type}" AND ' if sel.element_type else ""
            yield (AppiumBy.IOS_PREDICATE,
                   f'{tipo}(label CONTAINS[c] "{lb}" OR name CONTAINS[c] "{lb}")')
        if sel.element_type and not sel.labels and not sel.accessibility_id:
            yield AppiumBy.IOS_PREDICATE, f'type == "{sel.element_type}"'
        if sel.predicate:
            yield AppiumBy.IOS_PREDICATE, sel.predicate

    def wait_for(self, key: str, timeout: int = WAIT, required: bool = True):
        sel = self.p.selectors[key]
        locs = list(self._locators(sel))
        if not locs:
            if required:
                raise UiChanged(f"seletor '{key}' vazio no perfil {self.p.name}")
            return None
        per = max(2, timeout // max(1, len(locs)))
        for by, val in locs:
            try:
                return WebDriverWait(self.d, per).until(
                    lambda drv, b=by, v=val: drv.find_element(b, v))
            except (TimeoutException, WebDriverException):
                continue
        if required:
            raise UiChanged(f"elemento '{key}' nao localizado por nenhuma camada")
        return None

    def find_all(self, key: str) -> list:
        sel = self.p.selectors[key]
        for by, val in self._locators(sel):
            try:
                els = self.d.find_elements(by, val)
            except WebDriverException:
                continue
            if els:
                return els
        return []

    # ---------------- seguranca ----------------

    def _whatsapp_in_front(self) -> bool:
        try:
            info = self.d.execute_script("mobile: activeAppInfo") or {}
            return info.get("bundleId") == BUNDLE_ID
        except WebDriverException:
            return False

    def assert_no_composer(self) -> None:
        """Trava dura: se um compositor de mensagem aparecer, abortamos.
        O produto NUNCA escreve nem envia mensagem."""
        sel = self.p.selectors.get("message_composer")
        if not sel:
            return
        # UMA consulta em vez de uma por rotulo (eram ate 8 chamadas por contato):
        # o mesmo criterio, todos os rotulos num so predicado. A trava continua
        # rodando a cada contato; so ficou barata.
        if self._composer_pred is None:
            partes = []
            for lb in sel.labels:
                partes += [f'label == "{lb}"', f'name == "{lb}"', f'value == "{lb}"',
                           f'label CONTAINS[c] "{lb}"', f'name CONTAINS[c] "{lb}"']
            tipo = f'type == "{sel.element_type}" AND ' if sel.element_type else ""
            self._composer_pred = tipo + "(" + " OR ".join(partes) + ")" if partes else ""
        if not self._composer_pred:
            return
        try:
            achou = self.d.find_elements(AppiumBy.IOS_PREDICATE, self._composer_pred)
        except WebDriverException:
            achou = []
            # se o predicado unico falhar no driver, cai nas camadas originais
            for by, val in self._locators(sel):
                try:
                    if self.d.find_elements(by, val):
                        achou = [True]
                        break
                except WebDriverException:
                    continue
        if achou:
            raise UnsafeState("compositor de mensagem detectado — abortando sem tocar em nada")

    def in_picker(self) -> bool:
        """Ainda estamos no seletor de contatos? (usado para distinguir
        'nenhum resultado' de 'a tela mudou').

        Durante a busca ativa (teclado aberto) o iOS ESCONDE a barra de
        navegacao — e com ela o "Criar" (picker_anchor). Por isso as ancoras
        incluem controles que existem justamente enquanto se pesquisa:
        o campo/botao de busca, o "Limpar texto" e o "Cancelar"."""
        for key in ("search_field", "clear_search", "picker_search_button",
                    "cancel_button", "contact_cell", "picker_anchor"):
            sel = self.p.selectors.get(key)
            if not sel:
                continue
            for by, val in self._locators(sel):
                try:
                    if self.d.find_elements(by, val):
                        return True
                except WebDriverException:
                    continue
        return False


    # ---------------- fluxo ----------------

    def open_new_broadcast(self) -> None:
        """Fluxo CONFIRMADO no iPhone (ids de acessibilidade estaveis):
        aba Conversas -> "+" Nova conversa -> celula "Nova transmissao" -> picker."""
        self.transition(State.OPENING_WHATSAPP)
        # Cada lista abre um picker novo: o que foi cacheado no anterior expirou.
        self._depth_ok = None
        self._search_box = None
        self._contatos_desde_check = self._CHECAR_INTERVALO
        # A sessao abre VAZIA (autoLaunch=False). Ativa o WhatsApp apenas se
        # ele nao estiver ja em frente — chamar activate_app com o app ja ativo
        # pode causar Code=41 em sessoes WDA degradadas apos crash.
        if not self._whatsapp_in_front():
            try:
                self.d.activate_app(BUNDLE_ID)
            except WebDriverException as exc:
                msg = str(exc)
                if "41" in msg or "Not authorized" in msg or "locked" in msg.lower():
                    raise UiChanged(
                        "iPhone nao autorizou a automacao (XCTDaemonErrorDomain Code=41). "
                        "Possiveis causas: (1) tela bloqueada — desbloqueie; "
                        "(2) WDA em estado ruim apos crash — feche e reabra a Estacao iOS; "
                        "(3) iPhone nao confia no Mac — Ajustes > Geral > VPN e Gestao do Dispositivo"
                    ) from exc
                raise
            self.settle(2.5)   # ativacao real: WhatsApp estava em 2o plano, aguarda subir
        else:
            # WhatsApp ja esta em frente (caso mais comum nas listas 2a, 3a...
            # Aguarda apenas o WDA sincronizar a sessao com o processo em execucao.
            self.settle(0.8)

        self.transition(State.OPENING_NEW_BROADCAST)

        # Tenta encontrar o botao "+" em ate 2 tentativas.
        # Na 1a tentativa: 6s (nao bloqueia muito se o picker ja estiver aberto).
        # Se falhar, tenta fechar qualquer picker/modal aberto e repete com 12s.
        new_chat_btn = None
        for attempt in range(2):
            # Garante aba Conversas (se a tab bar estiver visivel)
            tab = self.wait_for("chats_tab", timeout=4, required=False)
            if tab is not None:
                tab.click()
                self.settle(0.8)  # animacao de troca de aba no iPhone (~400ms)

            new_chat_btn = self.wait_for(
                "new_chat_button",
                timeout=10 if attempt == 0 else 15,
                required=False,
            )
            if new_chat_btn is not None:
                break  # encontrou — segue o fluxo normal

            # Nao encontrou. Tenta fechar picker ou modal que esteja cobrindo a tela.
            log.warning(
                "tentativa %d: 'new_chat_button' nao visivel — "
                "tentando fechar picker/modal aberto", attempt + 1
            )
            # Dentro de uma conversa (a lista recem-criada, por exemplo) o "+"
            # nao existe: primeiro tenta VOLTAR; so depois procura Cancelar.
            voltar = self.wait_for("back_button", timeout=2, required=False)
            if voltar is not None:
                voltar.click()
                self.settle(1.5)
                continue
            # Procura Cancelar em qualquer profundidade antes de desistir
            for depth in (12, 16, 20):
                try:
                    self.d.update_settings({"snapshotMaxDepth": depth})
                except WebDriverException:
                    pass
                cancel = self.wait_for("cancel_button", timeout=3, required=False)
                if cancel is not None:
                    cancel.click()
                    self._restore_depth()
                    self.settle(2.0)
                    break
            else:
                self._restore_depth()
                self.settle(1.5)

        if new_chat_btn is None:
            raise UiChanged(
                "elemento 'new_chat_button' nao localizado por nenhuma camada"
            )

        new_chat_btn.click()
        self.settle(0.8)  # menu de nova conversa abre em ~400ms
        self.wait_for("new_broadcast_cell").click()   # "Nova transmissao"
        self.settle(0.8)  # picker de contatos abre em ~500ms
        # confirma que o picker abriu pela ancora ESTAVEL (o botao Criar do
        # ParticipantPicker existe mesmo desabilitado); fallback: botao de busca.
        if self.wait_for("picker_anchor", timeout=8, required=False) is None \
                and self.wait_for("picker_search_button", timeout=4, required=False) is None:
            raise UiChanged("seletor de contatos da transmissao nao abriu")
        self.assert_no_composer()

    def _type_query(self, query: str) -> None:
        # A busca do picker e a TokenizedSearchBar: o campo so existe depois de
        # tocar no botao de busca (CONFIRMADO no iPhone).
        # VELOCIDADE: o campo cacheado do contato anterior costuma continuar
        # valido; so refazemos a busca do elemento se ele tiver expirado.
        box = self._search_box
        if box is not None:
            try:
                box.clear()
            except WebDriverException:
                box = None
                self._search_box = None
        if box is None:
            box = self.wait_for("search_field", timeout=3, required=False)
            if box is None:
                btn = self.wait_for("picker_search_button", timeout=4, required=False)
                if btn is not None:
                    btn.click()
                    self.settle()
                box = self.wait_for("search_field")
            try:
                box.clear()
            except WebDriverException:
                # alguns campos de busca do iOS nao aceitam clear(): usa o botao limpar
                btn = self.wait_for("clear_search", timeout=2, required=False)
                if btn is not None:
                    btn.click()
            self._search_box = box
        # set_value (extensao Appium) e mais rapido, mas NAO existe no WebElement
        # de todas as versoes do cliente (no Python 3.9 da Isabella nao existia e
        # dava AttributeError). send_keys e universal: e o caminho padrao.
        setter = getattr(box, "set_value", None)
        try:
            if setter is not None:
                setter(query)
            else:
                box.send_keys(query)
        except (WebDriverException, AttributeError):
            box.send_keys(query)

    def find_exact_cell(self, e164: str | None, name: str | None):
        """Pesquisa e devolve a UNICA celula com match exato, ou None.
        Levanta UiChanged se a tela nao for mais o picker.

        Nota: um 'caminho rapido' por class chain (1 consulta) foi avaliado e
        REMOVIDO porque, no iOS, casar por StaticText solta a folha em vez da
        celula, pula o guard in_picker() e conta nos ocultos (falso-ambiguo) —
        riscos que corromperiam a escolha do destinatario. So voltara a ser
        considerado DEPOIS de validado num iPhone real, resolvendo para a
        celula ancestral, exigindo in_picker() e contando celulas visiveis."""
        query = e164 or name
        if not query:
            return None
        self._type_query(query)
        self.settle()

        cells = self._find_cells_escalating()
        # Diagnostico barato e decisivo: 0 celulas = a busca nao filtrou (texto
        # digitado errado/incompleto?); 2+ = ha celulas a mais na tela (chips?).
        log.info("busca: %d celula(s) na tela", len(cells))
        if not cells:
            if self.in_picker():
                return None  # simplesmente nao ha resultado
            raise UiChanged("o seletor de contatos desapareceu durante a busca")

        exact = self._exact_matches(cells, e164, name)
        if len(exact) > 1:
            raise Ambiguous(len(exact))
        if exact:
            return exact[0]

        # FALLBACK — single-cell trust:
        # O WhatsApp ja filtrou a lista pelo numero que digitamos (E.164).
        # Se sobrou EXATAMENTE 1 celula e a busca foi por numero, esse e o
        # contato certo — mas SOMENTE se nao for celula de convite.
        if e164 and len(cells) == 1 and not self._is_invite_cell(cells[0]):
            log.debug("single-cell-trust: 1 celula apos busca por E.164 "
                      "— formato exibido nao casou, mas o WhatsApp ja filtrou")
            cells[0]._sct = True  # atributo dinamico lido em search_and_select
            return cells[0]

        return None


    def _is_invite_cell(self, cell) -> bool:
        """Retorna True se a celula e 'Convidar para WhatsApp' (nao e contato
        no picker — clicar nela abre o app de Mensagens do iOS)."""
        for attr in ("label", "name", "value"):
            try:
                v = cell.get_attribute(attr) or ""
            except WebDriverException:
                v = ""
            low = v.lower()
            if "convidar" in low or "invite" in low:
                return True
        # fallback: texto agregado da celula
        txt = self._cell_text(cell)
        if txt:
            low = txt.lower()
            if "convidar" in low or "invite" in low:
                return True
        return False


    def _find_cells_escalating(self) -> list:
        """As linhas do picker (modal) ficam mais fundas que a profundidade 12.
        Sobe a profundidade em passos PEQUENOS, so com busca pontual por id
        (nunca varredura), e volta para 12 depois — 15+ com varredura derruba
        o WDA; com busca pontual e lista ja filtrada pelo numero, e seguro."""
        # Caminho rapido: a profundidade que funcionou continua valendo dentro
        # do mesmo picker. Uma consulta, sem mexer nas settings.
        if self._depth_ok is not None:
            cells = self._find_cells_com_rotulos()
            if cells:
                return cells
            # Vazio na profundidade conhecida NAO e "nao encontrado" ainda: apos o
            # 1o contato marcado, o WhatsApp acrescenta a faixa de selecionados e a
            # lista fica um nivel mais fundo — a profundidade valida muda. (Foi
            # exatamente isso que fez os contatos 2+ sairem como "nao encontrado"
            # com a celula visivel na tela.) Re-escala antes de concluir.
        for depth in (12, 14, 16, 18):
            if depth == self._depth_ok:
                continue   # ja consultada acima
            try:
                self.d.update_settings({"snapshotMaxDepth": depth})
            except WebDriverException:
                pass
            cells = self.find_all("contact_cell")
            if cells:
                # Mantem a profundidade (so buscas pontuais; sem varredura).
                if self._depth_ok != depth:
                    log.info("celulas do seletor agora na profundidade %d", depth)
                self._depth_ok = depth
                self._rotulos_celulas = None
                return cells
        # Nao encontrado de verdade: guarda a maior profundidade tentada para a
        # proxima busca comecar por ela (a lista nao volta a ficar mais rasa).
        self._depth_ok = 18
        self._rotulos_celulas = None
        return []

    def _find_raw(self, sel, com_rect: bool = False):
        """Busca pontual CRUA, percorrendo as camadas do seletor na mesma ordem
        de find_all (accessibility id -> class chain -> predicados) e lendo os
        atributos da propria resposta (elementResponseAttributes).

        Devolve [{"el", "label", "rect"}] da PRIMEIRA camada com resultado, ou
        None quando: a chave esta desligada, o driver nao devolveu os atributos,
        ou NENHUMA camada achou nada — vazio nunca e resposta definitiva aqui,
        quem decide "nao encontrado" e o caminho antigo (find_all).

        Licao do iPhone da Isabella (iOS 26.6): as celulas do seletor NAO tem o
        id PickerView_ContactCell; so aparecem pela class chain. Uma busca crua
        que so olhava o id devolvia [] e os contatos 2+ saiam "nao encontrado"."""
        if self._attrs_ok is False or not self.attrs_na_resposta or sel is None:
            return None
        executor = getattr(self.d, "command_executor", None)
        usa_executor = executor is not None and hasattr(executor, "execute")
        for by, val in self._locators(sel):
            params = {"using": by, "value": val}
            try:
                if usa_executor:
                    resp = executor.execute("findElements",
                                            {"sessionId": self.d.session_id, **params})
                else:
                    resp = self.d.execute("findElements", params)
            except Exception:                # driver falso nos testes, WDA antigo...
                self._attrs_ok = False
                return None
            if not isinstance(resp, dict) or resp.get("status") not in (None, 0):
                self._attrs_ok = False
                return None
            itens = resp.get("value") or []
            if isinstance(itens, dict):      # erro W3C vem como {"error": ...}
                continue                     # camada invalida neste driver: proxima
            if not itens:
                continue                     # nada nesta camada: tenta a proxima
            out = []
            for it in itens:
                if not isinstance(it, dict) or ("label" not in it and "name" not in it
                                                and "value" not in it):
                    self._attrs_ok = False
                    return None
                if com_rect and not isinstance(it.get("rect"), dict):
                    self._attrs_ok = False
                    return None
                eid = it.get("element-6066-11e4-a52e-4f735466cecf") or it.get("ELEMENT")
                if not eid:
                    self._attrs_ok = False
                    return None
                r = it.get("rect") or {}
                out.append({
                    "el": self.d.create_web_element(eid),
                    "label": (it.get("label") or it.get("name") or it.get("value") or "").strip(),
                    "rect": (float(r.get("x", 0)), float(r.get("y", 0)),
                             float(r.get("width", 0)), float(r.get("height", 0)))
                    if r else None,
                })
            self._attrs_ok = True
            return out
        return None

    def _find_cells_com_rotulos(self) -> list:
        """Celulas do picker; quando a resposta crua traz os rotulos, guarda-os
        alinhados em self._rotulos_celulas (0 chamadas extras). Vazio na busca
        crua => find_all decide (percorre as mesmas camadas)."""
        cru = self._find_raw(self.p.selectors.get("contact_cell"))
        if not cru:
            self._rotulos_celulas = None
            return self.find_all("contact_cell")
        self._rotulos_celulas = [c["label"] for c in cru]
        return [c["el"] for c in cru]

    def _textos_em_lote(self, cells) -> tuple[list, list] | None:
        """(telefones, rotulos) alinhados com `cells`, em UMA chamada para os
        telefones (os rotulos ja vieram com as celulas). None => usar o caminho
        celula a celula. Exige contagem igual: cada celula tem seu StaticText de
        telefone/recado; se nao bater, nao arrisca."""
        rotulos = self._rotulos_celulas
        if not rotulos or len(rotulos) != len(cells):
            return None
        cru = self._find_raw(self.p.selectors.get("contact_phone"))
        if not cru or len(cru) != len(cells):
            return None
        return [c["label"] for c in cru], list(rotulos)

    def _restore_depth(self) -> None:
        try:
            self.d.update_settings({"snapshotMaxDepth": 12})
        except WebDriverException:
            pass

    def search_and_select(self, e164: str | None, name: str | None, label: str) -> None:
        self.transition(State.SEARCHING)
        # Periodica: 1 vez a cada _CHECAR_INTERVALO contatos (e no 1o de cada
        # lista). Se o seletor sumir no meio, a busca seguinte ja falha sozinha
        # (campo de busca nao encontrado => UiChanged) — a trava nao depende disto.
        self._contatos_desde_check += 1
        checar = self._contatos_desde_check >= self._CHECAR_INTERVALO
        if checar:
            self._contatos_desde_check = 0
            self.assert_no_composer()
        query = e164 or name or ""

        self.transition(State.MATCHING)
        try:
            cell = self.find_exact_cell(e164, name)
        except Ambiguous as a:
            self.results.append({"label": label, "outcome": "ambiguous",
                                 "detail": f"{a.count} matches exatos"})
            log.info("caso %s: AMBIGUO (%d) — nao seleciono", label, a.count)
            return

        if cell is None:
            self.results.append({"label": label, "outcome": "not_found"})
            log.info("caso %s: NAO encontrado (%s)", label, mask(query))
            return

        # Cada numero e pesquisado uma vez (o CSV ja vem deduplicado): sem
        # verificacao de selecao, esta consulta (3 chamadas) nao decide nada.
        if self.verify_selection and self._looks_selected(cell):
            self.results.append({"label": label, "outcome": "already_selected"})
            log.info("caso %s: ja selecionado — nao clico de novo", label)
            return

        self.transition(State.SELECTING)
        if getattr(cell, "_sct", False):
            log.info("caso %s: 1 resultado no picker — selecionando (formato local)", label)
        before = self._selected_count() if self.verify_selection else -1
        cell.click()
        self.transition(State.VERIFYING)
        # O clique so marca a linha (animacao curta). O caso que exigia espera
        # longa — celula "Convidar" abrindo o app Mensagens — agora e barrado
        # antes do clique (_rotulo_convite); a checagem abaixo fica como reserva.
        self.settle(0.5)

        # SEGURANCA: verifica se ainda estamos no WhatsApp. Se o clique abriu
        # o app de Mensagens (celula 'Convidar para WhatsApp' passou pelos filtros),
        # volta ao WhatsApp automaticamente e descarta o contato. Periodica
        # (mesmo ritmo da checagem do compositor): o convite ja e barrado antes.
        if checar and not self._whatsapp_in_front():
            log.warning(
                "caso %s: clique saiu do WhatsApp (app externo abriu — "
                "'Convidar para WhatsApp'?) — voltando ao WhatsApp", label
            )
            try:
                self.d.activate_app(BUNDLE_ID)
                self.settle(2.5)
            except WebDriverException:
                pass
            self.results.append({"label": label, "outcome": "not_found",
                                  "detail": "app externo abriu apos clique"})
            log.warning("caso %s: contato ignorado (app externo estava na frente)", label)
            if not self.in_picker():
                raise UiChanged(
                    "picker fechou apos app externo — reconecte e rode de novo"
                )
            return

        if self.verify_selection:
            after = self._selected_count()
            ok = (after > before) or self._looks_selected_again(e164, name)
            if not ok and before >= 0 and after == before:
                # Sem evidencia observavel de selecao. Igual ao Android 2.26:
                # aceitamos porque o match era EXATO E UNICO, mas registramos.
                log.warning("caso %s: sem evidencia de selecao na arvore "
                            "(match exato unico) — registrando mesmo assim", label)
                self.results.append({"label": label, "outcome": "selected",
                                     "detail": "sem evidencia de UI"})
                return
        self.results.append({"label": label, "outcome": "selected"})
        log.info("caso %s: selecionado", label)

    # ---------------- deteccao ----------------

    def _cell_text(self, cell) -> str:
        for attr in ("label", "name", "value"):
            try:
                v = cell.get_attribute(attr)
            except WebDriverException:
                v = None
            if v:
                return str(v).strip()
        try:
            return (cell.text or "").strip()
        except WebDriverException:
            return ""

    def _exact_matches(self, cells, e164: str | None, name: str | None) -> list:
        """Match EXATO: numero normalizado igual OU nome exatamente igual.
        Nunca aceita 'contem' — foi a fragilidade das referencias auditadas."""
        out = []
        lote = self._textos_em_lote(cells)
        if lote is not None:
            # CAMINHO RAPIDO: mesmas regras, textos ja em maos (1 chamada no
            # total, em vez de 3 por celula). Convite barrado pelo rotulo.
            fones, rotulos = lote
            for c, fone, rot in zip(cells, fones, rotulos):
                baixa = rot.lower()
                if "convidar" in baixa or "invite" in baixa:
                    continue
                if e164 and fone:
                    if self._to_e164(fone) == e164:
                        out.append(c)
                    continue          # tinha numero e nao bateu: nao e este contato
                if not rot:
                    continue
                if e164 and self._to_e164(rot) == e164:
                    out.append(c)
                elif name and rot == name.strip():
                    out.append(c)
            return out
        for c in cells:
            if e164:
                # PREFERENCIA: o numero fica num StaticText proprio dentro da
                # celula (PickerView_ContactCell_PhoneNumber, confirmado). Casar
                # por numero e a regra mais segura — nao depende do nome.
                fone = self._cell_phone(c)
                if fone is not None:
                    if self._to_e164(fone) == e164 and not self._rotulo_convite(c):
                        out.append(c)
                    continue  # tinha numero e nao bateu: nao e este contato
            # fallback: texto agregado da celula (numero ou nome exato)
            txt = self._cell_text(c)
            if not txt:
                continue
            baixa = txt.lower()
            if "convidar" in baixa or "invite" in baixa:
                continue  # linha "Convidar para o WhatsApp": nunca e destinatario
            if e164 and self._to_e164(txt) == e164:
                out.append(c)
            elif name and txt == name.strip():
                out.append(c)
        return out

    def _rotulo_convite(self, cell) -> bool:
        """Numero sem WhatsApp aparece na secao "Convidar" COM o numero: casaria
        pelo telefone e o clique abriria o app Mensagens. Uma leitura do rotulo
        (1 chamada) barra isso ANTES do clique — o que permite encurtar a espera
        depois dele."""
        try:
            lbl = (cell.get_attribute("label") or "").lower()
        except WebDriverException:
            return False
        return "convidar" in lbl or "invite" in lbl

    def _cell_phone(self, cell) -> str | None:
        """Numero exibido na linha (PickerView_ContactCell_PhoneNumber), se houver."""
        sel = self.p.selectors.get("contact_phone")
        if not sel:
            return None
        for by, val in self._locators(sel):
            try:
                els = cell.find_elements(by, val)
            except WebDriverException:
                continue
            if els:
                for attr in ("label", "value", "name"):
                    try:
                        v = els[0].get_attribute(attr)
                    except WebDriverException:
                        v = None
                    if v:
                        return str(v).strip()
        return None

    @staticmethod
    def _to_e164(texto: str) -> str | None:
        for pedaco in (texto, texto.replace("‑", "-"), texto.replace("‎", "")):
            try:
                parsed = phonenumbers.parse(pedaco, "BR")
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            except phonenumbers.NumberParseException:
                continue
        return None

    def _looks_selected(self, cell) -> bool:
        """Evidencias possiveis de 'ja selecionado' no iOS."""
        for attr in ("selected", "value"):
            try:
                v = cell.get_attribute(attr)
            except WebDriverException:
                continue
            if v in ("true", True, "1", "selected"):
                return True
        sel = self.p.selectors.get("selected_indicator")
        if sel:
            for by, val in self._locators(sel):
                try:
                    if cell.find_elements(by, val):
                        return True
                except WebDriverException:
                    continue
        return False

    def _looks_selected_again(self, e164, name) -> bool:
        try:
            cell = self.find_exact_cell(e164, name)
        except (UiChanged, Ambiguous):
            return False
        return bool(cell) and self._looks_selected(cell)

    def _selected_count(self) -> int:
        """Quantos aparecem como selecionados (chips no topo, se existirem)."""
        chips = self.find_all("selected_chip")
        if chips:
            return len(chips)
        return len([c for c in self.find_all("contact_cell") if self._looks_selected(c)])

    # ---------------- conclusao ----------------

    def finish(self, approve_create: bool) -> None:
        self.transition(State.WAITING_CONFIRMATION)
        self.assert_no_composer()
        selecionados = sum(1 for r in self.results if r["outcome"] == "selected")
        log.info("selecionados: %d (limite %d)", selecionados, BROADCAST_LIMIT)

        if selecionados < MIN_RECIPIENTS:
            log.warning("apenas %d selecionado(s): o WhatsApp exige pelo menos %d "
                        "para criar uma lista — nao ha o que criar.",
                        selecionados, MIN_RECIPIENTS)
            self.transition(State.COMPLETED)
            return

        btn = self.wait_for("create_button", required=False)
        if not approve_create:
            log.info("PARADA SEGURA: sem --approve-create, nao toco no botao de criar.")
            self.transition(State.COMPLETED)
            return
        if btn is None:
            raise UiChanged("botao de criar nao localizado; nao crio a lista")
        # CONFIRMADO: o "Criar" fica enabled=false ate 2+ selecionados.
        try:
            habilitado = btn.get_attribute("enabled") in ("true", True, "1")
        except WebDriverException:
            habilitado = False
        if not habilitado:
            raise UiChanged("botao Criar esta DESABILITADO (menos de 2 selecionados?); nao clico")

        self.transition(State.SAVING)
        btn.click()
        self.settle()
        # Nao confirmamos nada alem da criacao: nao tocamos em compositor/envio.
        # (O WhatsApp abre a conversa da lista; quem chama decide quando
        # voltar para Conversas — ver voltar_para_conversas.)
        self.transition(State.COMPLETED)
        log.info("lista criada (nenhuma mensagem enviada).")

    # ---------------- depois de criar: volta para Conversas ----------------

    def voltar_para_conversas(self) -> None:
        """Da conversa da lista de volta para a aba Conversas — sem tocar no
        compositor. Precondicao da proxima lista (o "+" nao existe dentro de
        uma conversa). CONFIRMADO no iPhone em 2026-09-09: dentro da conversa
        o botao Voltar nao casa com o seletor e driver.back() resolve."""
        for _ in range(4):
            if self.wait_for("chats_tab", timeout=2, required=False) is not None:
                return
            voltar = self.wait_for("back_button", timeout=2, required=False)
            if voltar is not None:
                voltar.click()
            else:
                try:
                    self.d.back()
                except WebDriverException:
                    pass
            self.settle(1.2)
        raise UiChanged("nao consegui voltar para Conversas depois de criar a lista; "
                        "volte no iPhone e rode de novo (o progresso ja foi salvo)")


class Ambiguous(Exception):
    def __init__(self, count: int):
        super().__init__(f"{count} matches exatos")
        self.count = count


# ---------------- driver ----------------

def appium_disponivel(server: str, timeout: float = 3.0) -> bool:
    """GET /status no servidor Appium. Evita abrir sessao contra a porta
    fechada — que rende 3 tentativas e 60 linhas de traceback para dizer
    'nao esta rodando'."""
    import urllib.request
    try:
        with urllib.request.urlopen(server.rstrip("/") + "/status", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def exigir_appium(server: str) -> bool:
    """Loga a instrucao certa quando o Appium nao responde. True = pode seguir."""
    if appium_disponivel(server):
        return True
    log.error("o Appium nao esta rodando em %s. Abra OUTRO terminal e deixe rodando "
              "`appium --log-level info` (ou abra a estacao pelo gui_ios.py, que o "
              "inicia sozinha), depois rode este comando de novo.", server)
    return False


def _ajustes_experimentais() -> dict:
    """Settings de sessao opcionais, cada um com sua chave de ambiente, para
    isolar no aparelho o que ajuda e o que atrapalha (ver IosSpike.__init__)."""
    tudo = os.environ.get("LL_RAPIDO") == "1"
    ajustes: dict = {}
    digitacao = os.environ.get("LL_DIGITACAO", "200" if tudo else "")
    if digitacao.isdigit() and int(digitacao) > 0:
        ajustes["typingFrequency"] = int(digitacao)
    if tudo or os.environ.get("LL_ATTRS") == "1":
        ajustes["elementResponseAttributes"] = "name,label,value,rect"
        ajustes["shouldUseCompactResponses"] = False
    if ajustes:
        log.info("ajustes experimentais de sessao: %s", ajustes)
    return ajustes


def build_driver(server: str, wda_bundle: str | None, *,
                 wda_timeout: int = 240):
    """Sessao XCUITest com capabilities de estabilidade e velocidade.

    O UDID nao e informado pela aplicacao: o Appium seleciona automaticamente
    o unico iPhone conectado por USB usando o valor especial "auto"."""
    opts = XCUITestOptions()
    opts.udid = "auto"
    opts.bundle_id = BUNDLE_ID
    opts.no_reset = True
    opts.set_capability("autoAcceptAlerts", False)
    opts.set_capability("autoDismissAlerts", False)
    # --- CONFIGURACAO VALIDADA NO IPHONE (a unica que leu a arvore com
    # --- estabilidade; as variacoes derrubavam o WDA):
    opts.set_capability("waitForQuiescence", False)   # o WhatsApp nunca fica "parado"
    # NAO lancar o WhatsApp dentro do pedido de sessao: abrir um app pesado no
    # mesmo instante em que o WDA nasce derruba o WDA ("socket hang up" em
    # establishProxySession). A sessao abre VAZIA (leve) e o open_new_broadcast
    # ativa o WhatsApp depois — o que tambem religa o WDA a um processo novo.
    opts.set_capability("autoLaunch", False)
    opts.set_capability("wdaLaunchTimeout", wda_timeout * 1000)
    opts.set_capability("wdaConnectionTimeout", wda_timeout * 1000)
    # Se o xcodebuild falhar (codigo 65), o log do servidor Appium mostra o
    # motivo real (assinatura, perfil, DerivedData) em vez de uma mensagem generica.
    opts.set_capability("showXcodeLog", True)
    opts.set_capability("wdaStartupRetries", 2)
    # LL_PREBUILT_WDA=1 usa o WDA que voce ja compilou/instalou pelo Xcode (⌘U),
    # pulando o xcodebuild completo a cada sessao. Util quando o build falha.
    if os.environ.get("LL_PREBUILT_WDA") == "1":
        opts.set_capability("usePrebuiltWDA", True)
    opts.set_capability("skipLogCapture", True)
    opts.set_capability("reduceMotion", True)
    if wda_bundle:
        # WDA pre-instalado via Xcode (⌘U): conecta ao app ja existente no
        # iPhone sem recompilar. usePrebuiltWDA=True pula o xcodebuild.
        # wdaBundleId aponta para o bundle exato instalado.
        # NAO use updatedWDABundleId aqui — essa capability renomeia o bundle
        # durante o build, nao serve para conectar a um WDA pre-existente.
        opts.set_capability("usePrebuiltWDA", True)
        opts.set_capability("wdaBundleId", wda_bundle)
    elif os.environ.get("LL_PREBUILT_WDA") == "1":
        opts.set_capability("usePrebuiltWDA", True)


    driver = webdriver.Remote(server, options=opts)
    try:
        # PROFUNDIDADE 12 e a que funciona nesta tela; 15+ e varreduras
        # ("**/*", por classe) derrubam o WDA. Use SO buscas pontuais.
        driver.update_settings({
            "defaultActiveApplication": BUNDLE_ID,  # consultar sempre o WhatsApp
            "snapshotMaxDepth": 12,
            "customSnapshotTimeout": 15,
            "waitForIdleTimeout": 0,
            "animationCoolOffTimeout": 0,
            # EXPERIMENTAL (LL_RAPIDO=1): digitacao a 200 chars/s e rotulos na
            # propria resposta das buscas. Desligado por padrao: uma rodada com
            # isto ligado deixou contatos sem selecionar no iPhone (em apuracao).
            **_ajustes_experimentais(),
            "useJSONSource": True,
            "pageSourceExcludedAttributes": "visible,accessible,frame,index",
        })
    except WebDriverException:
        log.warning("nao consegui aplicar settings de velocidade (segue mais lento)")
    return driver


# ---------------- main ----------------

def _dump_inventory_on_fail(driver, path: str) -> None:
    """Salva os elementos da tela atual (redigidos) quando o fluxo falha.

    Usa consultas DIRETAS por tipo (nao page_source), porque na tela de Conversas
    do WhatsApp o page_source do iOS costuma dar timeout. Assim o diagnostico nao
    trava junto com o erro."""
    try:
        import diag_ios  # reusa a redacao de dados pessoais
        tipos = ("XCUIElementTypeButton", "XCUIElementTypeStaticText",
                 "XCUIElementTypeNavigationBar", "XCUIElementTypeSearchField",
                 "XCUIElementTypeTextField")
        itens = []
        for tipo in tipos:
            try:
                els = driver.find_elements(AppiumBy.CLASS_NAME, tipo)
            except WebDriverException:
                continue
            for el in els[:60]:
                rec = {"type": tipo}
                for a in ("name", "label", "value", "enabled"):
                    try:
                        v = el.get_attribute(a)
                    except WebDriverException:
                        v = None
                    rec[a] = diag_ios.redact(v) if a in ("name", "label", "value") and v else v
                if rec.get("name") or rec.get("label") or rec.get("value"):
                    itens.append(rec)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"total": len(itens), "elementos": itens}, f, ensure_ascii=False, indent=2)
        log.error(">>> inventario da tela salvo em %s — ENVIE este arquivo para "
                  "identificarmos o botao certo e preencher ios_selectors.py.", path)
    except Exception as e:  # diagnostico e best-effort; nunca mascara o erro real
        log.warning("nao consegui salvar o inventario de erro: %s", e)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:4723")
    ap.add_argument("--wda-bundle", default="",
                    help="updatedWDABundleId (ex.: com.seunome.WebDriverAgentRunner)")
    ap.add_argument("--contacts", required=True, help="CSV name,phone (casos de teste)")
    ap.add_argument("--wa-version", default="")
    ap.add_argument("--region", default="BR")
    ap.add_argument("--approve-create", action="store_true",
                    help="cria a lista de teste (sem isto, para antes de criar)")
    ap.add_argument("--trust-profile", action="store_true",
                    help="usar o perfil baseline mesmo sem versao validada (apenas dev)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    nums = batching.normalize(batching.load_csv(args.contacts), args.region)
    log.info("%d numero(s) valido(s) no CSV", len(nums))
    if nums and all(n.e164.startswith("+552190000") for n in nums):
        log.warning("=" * 70)
        log.warning("ATENCAO: o CSV contem apenas os NUMEROS DE EXEMPLO do "
                    "contacts.example.csv (+55 21 90000-000x). Eles nao existem em "
                    "contato nenhum, entao TODOS sairao como 'nao encontrado'.")
        log.warning("Edite o CSV com os seus 3 contatos de teste reais (name,phone) "
                    "e rode de novo.")
        log.warning("=" * 70)
    if len(nums) > BROADCAST_LIMIT:
        log.error("mais de %d contatos: divida em lotes (use run_ios.py)", BROADCAST_LIMIT)
        return 2

    driver = build_driver(args.server, args.wda_bundle or None)
    try:
        profile = profile_for_version(args.wa_version)
        if profile is None:
            if not args.trust_profile:
                log.error("WHATSAPP_VERSION_UNSUPPORTED: versao '%s' sem perfil validado. "
                          "Rode diag_ios.py --inventory, preencha ios_selectors.py e "
                          "registre a versao em version_prefixes.", args.wa_version)
                return 3
            profile = BASELINE
            log.warning("usando perfil baseline NAO validado (--trust-profile)")

        spike = IosSpike(driver, profile)
        spike.transition(State.PREPARING)
        spike.open_new_broadcast()
        for i, nc in enumerate(nums):
            spike.search_and_select(nc.e164, nc.name or None, label=f"c{i}")
        spike.finish(args.approve_create)
        print(json.dumps(spike.results, ensure_ascii=False, indent=2))
        return 0
    except UnsafeState as e:
        log.error("PARADA DE SEGURANCA: %s", e)
        return 5
    except UiChanged as e:
        log.error("UI_CHANGED / FAILED_SAFE: %s — nenhuma acao adicional.", e)
        # Vira DIAGNOSTICO: salva o inventario da tela atual (redigido) para a
        # pessoa preencher ios_selectors.py com os nomes REAIS, sem adivinhar.
        _dump_inventory_on_fail(driver, "inventory-erro.json")
        return 4
    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass


if __name__ == "__main__":
    sys.exit(main())
