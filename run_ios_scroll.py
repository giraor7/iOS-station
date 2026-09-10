"""MODO SCROLL LIVRE — cria listas de transmissao no WhatsApp iOS selecionando
os contatos NA ORDEM EM QUE O PROPRIO WHATSAPP OS LISTA (A, B, C...), sem CSV
e sem digitar numero nenhum.

Fluxo (Mac + Appium + iPhone por USB, exatamente o mesmo caminho ja validado):
  1. abre o WhatsApp;
  2. Conversas -> "+" (Nova conversa) -> "Nova transmissao";
  3. na tela "Destinatarios", toca nos contatos visiveis de cima para baixo,
     rola UMA tela por vez (arrasto controlado, sem inercia, com sobreposicao
     de 1 linha para nao pular ninguem) e repete ate 256 selecionados;
  4. toca em "Criar" (somente com --approve-create);
  5. grava o progresso (offset = quantos ja entraram em listas + QUAL foi o
     ultimo contato) e, na proxima lista, retoma a partir do contato seguinte.

POR QUE O PROGRESSO GUARDA O ULTIMO CONTATO E NAO SO O NUMERO 256:
  se alguem for adicionado/apagado na agenda entre uma lista e outra, a
  posicao "257" muda de lugar e a lista seguinte repetiria ou pularia gente.
  Guardando o ultimo contato tocado, a retomada acha ESSE contato na lista e
  continua do proximo — o offset numerico e informativo (e mostrado no log).

SEGURANCA (igual ao fluxo validado):
  * nunca escreve nem envia mensagem, nunca toca no compositor (aborta se ele
    aparecer no meio da selecao);
  * so cria a lista com --approve-create e so se o botao "Criar" estiver
    habilitado (2+ selecionados); sem a flag, seleciona, mostra o resultado e
    CANCELA o seletor (nada fica selecionado);
  * tocar de novo num contato ja selecionado o DESMARCA: por isso cada contato
    e tocado UMA vez (controle por hash do nome, com a sobreposicao de telas);
  * logs so com hash + 2 caracteres (nunca nome/numero completo). O arquivo de
    progresso guarda o nome do ULTIMO contato selecionado (necessario para
    retomar) — trate-o como trata o contatos.csv.

USO (na pasta ios-station, com o appium rodando):
  python3 run_ios_scroll.py --trust-profile --limite-por-lista 5          # ensaio: 5 contatos, NAO cria
  python3 run_ios_scroll.py --trust-profile --limite-por-lista 5 --approve-create   # 1 lista real de teste
  python3 run_ios_scroll.py --trust-profile --approve-create --max-listas 3          # 3 listas de 256
  python3 run_ios_scroll.py --progresso                                              # mostra onde parou
  python3 run_ios_scroll.py --reset-progresso                                        # recomeca do A
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import signal
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import WebDriverException

import spike_ios
from ios_selectors import BASELINE, BUNDLE_ID, profile_for_version
from spike_ios import (BROADCAST_LIMIT, MIN_RECIPIENTS, IosSpike, State, UiChanged,
                       UnsafeState, _dump_inventory_on_fail, build_driver, mask)

log = logging.getLogger("scroll_livre")

PROGRESSO_PADRAO = "progress.scroll.local.json"
MARGEM_INFERIOR = 24        # pontos acima da borda inferior (barra home) que nao tocamos
ALTURA_MINIMA_CELULA = 20
MAX_TELAS_POR_LISTA = 400   # trava contra loop infinito (256 contatos cabem em ~30 telas)
# --turbo: rajada W3C. Toque curto e intervalo entre toques (ms). O iOS
# registra toques distintos com folga acima de ~50 ms.
TURBO_TOQUE_MS = 40
TURBO_ENTRE_TOQUES_MS = 90
_W3C_ACTIONS = "actions"    # selenium Command.W3C_ACTIONS
MAX_TELAS_RETOMADA = 600    # 10 mil contatos / ~10 por tela, com folga
CICLOS_SEM_AVANCO = 2       # telas seguidas sem contato novo => fim da lista


# ---------------------------------------------------------------------------
# normalizacao (mesmas regras nas duas rodadas => retomada estavel)
# ---------------------------------------------------------------------------

def norm_nome(label: str) -> str:
    """NFC + remove caracteres invisiveis de formatacao (LRM/RLM que o iOS injeta)."""
    s = unicodedata.normalize("NFC", label or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
    return s.strip()


def nome_da_celula(label: str) -> str:
    """A celula do seletor tem label "Nome, recado". O recado muda a toda hora;
    o nome e o que identifica o contato entre uma rodada e outra."""
    return norm_nome(label).split(", ", 1)[0].strip()


def chave_ordem(nome: str) -> str:
    """Chave de comparacao alfabetica (sem acento, sem caixa) — usada so para
    saber se ja passamos do ponto de retomada; a identidade e o hash."""
    s = unicodedata.normalize("NFKD", nome or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.casefold().strip()


def hash_nome(nome: str) -> str:
    return hashlib.sha256(chave_ordem(nome).encode("utf-8")).hexdigest()[:16]


@dataclass
class Celula:
    el: object
    nome: str
    hash: str
    y: float
    h: float
    x: float = 0.0
    w: float = 0.0

    @property
    def centro(self) -> tuple[int, int]:
        return int(self.x + self.w / 2), int(self.y + self.h / 2)


def permitidos_por_ddd(agenda: str, ddds: str, region: str = "BR") -> dict:
    """Le a agenda exportada (VCF ou CSV) e devolve os NOMES cujo numero esta
    nos DDDs pedidos, como hashes iguais aos das celulas do seletor.

    Regra conservadora: um nome que tenha numero dentro E fora do filtro e
    ambiguo e fica de fora (nao da para saber qual numero o WhatsApp mostra).
    Devolve {"permitidos": set, "ambiguos": set, "nomes": int, "sem_numero": int}."""
    import batching
    import regions
    alvo = {p.strip() for p in ddds.replace(";", ",").split(",") if p.strip()}
    if agenda.lower().endswith(".vcf"):
        import vcf_to_csv
        pares = vcf_to_csv.parse_vcf(agenda)
    else:
        pares = [(c.name, c.raw_phone) for c in batching.load_csv(agenda)]
    por_nome: dict[str, set] = {}
    sem_numero = 0
    for nome, fone in pares:
        chave = nome_da_celula(norm_nome(nome))
        if not chave:
            continue
        e164 = batching.to_e164(fone, region)
        if e164 is None:
            sem_numero += 1
            continue
        area = regions.area_de(e164)
        dentro = (not area.internacional) and (area.ddd in alvo)
        por_nome.setdefault(hash_nome(chave), set()).add(dentro)
    return {
        "permitidos": {h for h, s in por_nome.items() if s == {True}},
        "ambiguos": {h for h, s in por_nome.items() if len(s) == 2},
        "nomes": len(por_nome),
        "sem_numero": sem_numero,
    }


def eh_convite(nome_ou_rotulo: str) -> bool:
    """Celula 'Convidar para o WhatsApp' (abre o app Mensagens se tocada).
    Decidido pelo rotulo JA LIDO — sem nenhuma chamada extra ao WDA."""
    baixa = (nome_ou_rotulo or "").lower()
    return "convidar" in baixa or "invite" in baixa


# ---------------------------------------------------------------------------
# progresso
# ---------------------------------------------------------------------------

class Progresso:
    def __init__(self, path: str):
        self.path = path
        self.offset = 0
        self.listas_criadas = 0
        self.ultimo_rotulo = ""
        self.ultimo_hash = ""
        self.historico: list = []
        self.carregar()

    def carregar(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            log.warning("progresso ilegivel (%s): comecando do zero", e)
            return
        self.offset = int(d.get("offset", 0))
        self.listas_criadas = int(d.get("listas_criadas", 0))
        self.ultimo_rotulo = str(d.get("ultimo_rotulo", ""))
        self.ultimo_hash = str(d.get("ultimo_hash", ""))
        self.historico = list(d.get("historico", []))

    def salvar(self) -> None:
        d = {
            "versao": 1,
            "modo": "scroll-livre",
            "offset": self.offset,
            "proximo_contato_n": self.offset + 1,
            "listas_criadas": self.listas_criadas,
            "ultimo_rotulo": self.ultimo_rotulo,
            "ultimo_hash": self.ultimo_hash,
            "atualizado_em": datetime.now().isoformat(timespec="seconds"),
            "historico": self.historico,
        }
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def registrar_lista(self, quantidade: int, primeiro_hash: str, ultimo_hash: str,
                        ultimo_rotulo: str) -> None:
        self.listas_criadas += 1
        self.offset += quantidade
        self.ultimo_hash = ultimo_hash
        self.ultimo_rotulo = ultimo_rotulo
        self.historico.append({
            "lista": self.listas_criadas,
            "quantidade": quantidade,
            "primeiro_hash": primeiro_hash,
            "ultimo_hash": ultimo_hash,
            "criada_em": datetime.now().isoformat(timespec="seconds"),
        })
        self.salvar()

    def resumo(self) -> str:
        if not self.listas_criadas:
            return "nenhuma lista criada ainda: a proxima comeca do primeiro contato (A)"
        return (f"{self.listas_criadas} lista(s) criada(s), {self.offset} contato(s) ja "
                f"incluidos; a proxima lista comeca no contato n. {self.offset + 1} "
                f"(logo apos {mask(self.ultimo_rotulo)})")


# ---------------------------------------------------------------------------
# o modo em si
# ---------------------------------------------------------------------------

class ScrollLivre(IosSpike):
    """Reaproveita TODO o fluxo validado (sessao, abertura do seletor, travas)
    e troca apenas a etapa de selecao: em vez de buscar por numero, toca nos
    contatos na ordem da tela e rola."""

    # Checa se o WhatsApp esta em primeiro plano a cada N toques (nao a cada tela).
    # O activeAppInfo e uma chamada de rede; fazer so uma vez por tela ja economiza;
    # fazer so a cada N toques economiza ainda mais sem comprometer a seguranca.
    _CHECAR_INTERVALO = 8

    def __init__(self, driver, profile, limite: int = BROADCAST_LIMIT):
        super().__init__(driver, profile)
        self.verify_selection = False   # contagem por toque; sem varrer a arvore
        self.limite = max(MIN_RECIPIENTS, min(limite, BROADCAST_LIMIT))
        self.tocados: set = set()       # hashes ja tocados NESTA lista
        self.ignorar: set = set()       # hashes ANTES do ponto de retomada (nunca tocar)
        self.ordem: list = []           # (hash, nome) na ordem de toque
        self.stats = {"telas": 0, "toques": 0, "repetidos": 0, "convites": 0,
                      "sem_rotulo": 0, "cliques_falhos": 0, "telas_retomada": 0}
        self._tamanho = None
        self._topo = 0.0
        self._profundidade = None
        self._toques_desde_check = 0   # contador para checagem periodica de seguranca
        # --turbo: toca todas as celulas de uma tela numa UNICA requisicao W3C
        # (coordenadas lidas nesta mesma tela). Desligado por padrao: toque por
        # coordenada nao e barrado por um dialogo inesperado como o click de
        # elemento e — liga so depois de validar no aparelho.
        self.turbo = False
        # Filtro de DDD (opcional): conjunto de hashes de NOME permitidos, vindo
        # da agenda exportada — a tela do WhatsApp nao mostra o numero de contato
        # salvo, entao o DDD so pode ser decidido pelo nome. None = sem filtro.
        self.permitidos: set | None = None
        self._filtrados_vistos: set = set()
        # Leitura em UMA requisicao: o WDA pode devolver name/label/rect de
        # cada celula junto com a busca (elementResponseAttributes). Se o driver
        # nao honrar, o primeiro resultado sem esses campos desliga o atalho e
        # a leitura volta ao caminho celula a celula.
        self._attrs_na_resposta: bool | None = None   # None = ainda nao tentou

    def settle(self, timeout: float = 0.2) -> None:  # type: ignore[override]
        """Versao rapida do settle para o loop de selecao/rolagem.
        Clamp de 0.1 a 1.5s (a base em spike_ios usa 0.3–2.0s para fluxos de
        navegacao que dependem de animacoes longas do WhatsApp)."""
        time.sleep(min(max(timeout, 0.1), 1.5))

    # ---------- leitura da tela ----------

    def _tamanho_tela(self):
        if self._tamanho is None:
            s = self.d.get_window_size()
            self._tamanho = (float(s["width"]), float(s["height"]))
        return self._tamanho

    def _fixar_profundidade(self) -> None:
        """Descobre UMA vez a menor profundidade que enxerga as celulas e a
        mantem durante a lista (evita 4 update_settings por tela)."""
        if self._profundidade is not None:
            return
        for depth in (12, 14, 16, 18):
            try:
                self.d.update_settings({"snapshotMaxDepth": depth})
            except WebDriverException:
                pass
            if self.find_all("contact_cell"):
                self._profundidade = depth
                log.info("celulas visiveis na profundidade %d", depth)
                self._ligar_atributos_na_resposta()
                return
        self._restore_depth()
        raise UiChanged("nenhuma celula de contato no seletor (profundidade ate 18)")

    def _ligar_atributos_na_resposta(self) -> None:
        """Pede ao WDA para incluir name, label e rect na resposta do find.
        Busca continua pontual (por id/camada); so o formato da resposta muda."""
        if self._attrs_na_resposta is not None:
            return
        try:
            self.d.update_settings({"elementResponseAttributes": "name,label,rect",
                                    "shouldUseCompactResponses": False})
            self._attrs_na_resposta = True
            self.attrs_na_resposta = True      # habilita _find_raw (herdado)
        except WebDriverException:
            self._attrs_na_resposta = False

    def _celulas_em_uma_requisicao(self) -> list | None:
        """[(elemento, (x, y, w, h), rotulo)] com UMA chamada por camada do
        seletor, ou None quando nada veio com atributos — ai o chamador le
        como antes (find_all + rect por celula). Vazio NUNCA e definitivo."""
        if not self._attrs_na_resposta:
            return None
        cru = self._find_raw(self.p.selectors.get("contact_cell"), com_rect=True)
        if not cru:
            if self._attrs_ok is False:
                log.info("driver nao devolveu atributos na busca; lendo celula a celula")
                self._attrs_na_resposta = False
            return None
        self.stats["telas_1_requisicao"] = self.stats.get("telas_1_requisicao", 0) + 1
        return [(c["el"], c["rect"], c["label"]) for c in cru]

    def _ler_celulas(self, margem: float = MARGEM_INFERIOR) -> list:
        """Celulas visiveis, de cima para baixo.

        Otimizacao: em vez de round-trips individuais (el.rect + 3x get_attribute
        por celula = ~40 chamadas HTTP para 10 celulas), chama find_all UMA vez
        e extrai label + rect em sequencia. O custo agora e:
          - 1 find_all  (snapshot WDA)
          - N el.rect   (1 por celula, parallel no driver)
          - N get_attribute("label")  (1 por celula — APENAS "label", nao 3)
        Isso elimina as chamadas redundantes a "name" e "value" que ocorriam via
        _cell_text(), caindo de ~40 para ~20 chamadas por tela."""
        self._fixar_profundidade()
        _, altura = self._tamanho_tela()
        for tentativa in range(2):
            rapido = self._celulas_em_uma_requisicao()
            if rapido is not None:
                els = [el for el, _, _ in rapido]
                rects = [r for _, r, _ in rapido]
                rotulos = {id(el): lbl for el, _, lbl in rapido}
            else:
                els = self.find_all("contact_cell")
                rects = self._rects(els)
                rotulos = {}
            out, falhou = [], False
            for el, r in zip(els, rects):
                if r is None:
                    falhou = True
                    if tentativa == 0:
                        break
                    continue
                x, y, w, h = r
                if h < ALTURA_MINIMA_CELULA or y < self._topo or y + h > altura - margem:
                    continue
                # Rotulo: veio na propria resposta da busca (0 chamadas) ou,
                # no caminho antigo, "label" e depois "name" (1-2 chamadas).
                lbl = rotulos.get(id(el), "")
                if not lbl:
                    try:
                        lbl = (el.get_attribute("label") or "").strip()
                        if not lbl:
                            lbl = (el.get_attribute("name") or "").strip()
                    except WebDriverException:
                        lbl = ""
                nome = nome_da_celula(lbl) if lbl else ""
                if not nome:
                    falhou = True
                    if tentativa == 0:
                        break
                    self.stats["sem_rotulo"] += 1
                    continue
                out.append(Celula(el=el, nome=nome, hash=hash_nome(nome), y=y, h=h,
                                  x=x, w=w))
            if not falhou or tentativa == 1:
                break
            self.settle(0.2)   # retry rapido: a tela ja estava montada
        out.sort(key=lambda c: c.y)
        return out

    @staticmethod
    def _rect_de(el):
        try:
            r = el.rect
            return (float(r.get("x", 0)), float(r.get("y", 0)),
                    float(r.get("width", 0)), float(r.get("height", 0)))
        except (WebDriverException, TypeError, ValueError, AttributeError):
            return None

    def _rects(self, els: list) -> list:
        """Posicao de cada celula com o minimo de chamadas.

        Le so a PRIMEIRA e a ULTIMA. Se a distancia entre elas for exatamente
        (n-1) alturas, nao ha cabecalho de secao ("A", "B"...) no meio e as
        demais posicoes sao inferidas — 2 chamadas em vez de n. Qualquer
        diferenca (cabecalho, altura variavel) derruba a inferencia e le
        todas, como antes. A conferencia e exata, nao aproximada."""
        n = len(els)
        if n == 0:
            return []
        if n < 3:
            return [self._rect_de(el) for el in els]
        r0, rn = self._rect_de(els[0]), self._rect_de(els[-1])
        if r0 and rn and rn[3] == r0[3] and r0[3] >= ALTURA_MINIMA_CELULA \
                and abs((rn[1] - r0[1]) - (n - 1) * r0[3]) <= 1.0:
            x, y0, w, h = r0
            self.stats["telas_inferidas"] = self.stats.get("telas_inferidas", 0) + 1
            return [(x, y0 + i * h, w, h) for i in range(n)]
        return [r0] + [self._rect_de(el) for el in els[1:-1]] + [rn]

    def _ajustar_topo(self, hash_ref: str, y_antes: float, cels: list) -> list:
        """Depois do 1o toque da lista, a faixa dos selecionados aparece no topo
        e empurra a tabela para baixo. Mede o deslocamento pela celula que
        acabou de ser tocada e sobe o limite superior na mesma medida — o que
        ficou acima esta escondido sob a faixa e nao pode ser tocado."""
        ref = next((c for c in cels if c.hash == hash_ref), None)
        delta = 0.0
        if ref is not None:
            delta = ref.y - y_antes
            if delta > 4:
                self._topo += delta
                log.debug("faixa de selecionados: lista desceu %.0f pt", delta)
            else:
                delta = 0.0
        return [c for c in cels if c.y >= self._topo], delta

    # ---------- gestos ----------

    def _arrastar(self, de_y: float, para_y: float) -> None:
        """Arrasto controlado (velocidade moderada e pausa no fim => sem inercia).
        A lista anda exatamente |de_y - para_y| pontos."""
        largura, _ = self._tamanho_tela()
        x = largura / 2
        # turbo: pressao e espera mais curtas (a espera no fim ainda mata a inercia)
        press, hold = (0.1, 0.35) if self.turbo else (0.2, 0.6)
        try:
            self.d.execute_script("mobile: dragFromToWithVelocity", {
                "fromX": x, "fromY": de_y, "toX": x, "toY": para_y,
                "pressDuration": press, "holdDuration": hold, "velocity": 450,
            })
        except WebDriverException:
            self.d.execute_script("mobile: dragFromToForDuration", {
                "duration": 0.6, "fromX": x, "fromY": de_y, "toX": x, "toY": para_y,
            })
        self.settle(0.15)  # velocity 450 + holdDuration 0.6 => lista ja parada; 0.15s suficiente

    def _rolar_uma_tela(self, cels: list) -> None:
        """Rola a tela com sobreposicao de seguranca de 3 celulas para
        garantir que nenhum contato seja pulado. Com 3 de sobreposicao e
        ~10 celulas por tela, precisamos de ~22 rolagens em vez de ~26."""
        if len(cels) < 2:
            _, altura = self._tamanho_tela()
            self._arrastar(altura * 0.7, altura * 0.35)
            return
        # 3 celulas de sobreposicao: a ultima celula visivel vai para a posicao
        # da 4a celula visivel (indice 3). Se a tela tiver menos de 5 celulas,
        # reduz proporcionalmente para nao rolar de menos.
        sobreposicao = min(3, len(cels) - 2) if len(cels) >= 5 else max(0, len(cels) - 2)
        alvo = cels[sobreposicao]
        self._arrastar(cels[-1].y + cels[-1].h / 2, alvo.y + alvo.h / 2)

    def _voltar_uma_tela(self, cels: list) -> None:
        if len(cels) < 2:
            _, altura = self._tamanho_tela()
            self._arrastar(altura * 0.35, altura * 0.7)
            return
        sobreposicao = min(3, len(cels) - 2) if len(cels) >= 5 else max(0, len(cels) - 2)
        alvo = cels[sobreposicao]
        self._arrastar(alvo.y + alvo.h / 2, cels[-1].y + cels[-1].h / 2)

    def _fling(self, vezes: int = 1) -> None:
        """Rolagem rapida COM inercia — so na retomada (antes de qualquer toque),
        onde pular contatos nao importa porque ainda vamos procurar o ponto exato."""
        for _ in range(vezes):
            try:
                self.d.execute_script("mobile: swipe", {"direction": "up", "velocity": 2500})
            except WebDriverException:
                _, altura = self._tamanho_tela()
                self._arrastar(altura * 0.85, altura * 0.15)
        self.settle(0.5)  # fling so na retomada; pode ser um pouco mais rapido

    # ---------- retomada ----------

    def _retomar(self, prog: Progresso, cels: list) -> list:
        """Leva a lista ate o ultimo contato da rodada anterior e devolve as
        celulas da tela atual que vem DEPOIS dele."""
        alvo_hash = prog.ultimo_hash
        alvo_chave = chave_ordem(prog.ultimo_rotulo)
        log.info("retomando: procurando o ultimo contato da lista anterior (%s)",
                 mask(prog.ultimo_rotulo))
        voltou = False
        anteriores = set()
        for tela in range(MAX_TELAS_RETOMADA):
            self.stats["telas_retomada"] += 1
            if not cels:
                if self.in_picker():
                    raise UiChanged("seletor sem contatos durante a retomada")
                raise UiChanged("o seletor de contatos desapareceu durante a retomada")
            idx = next((k for k, c in enumerate(cels) if c.hash == alvo_hash), None)
            if idx is not None:
                log.info("ponto de retomada encontrado apos %d tela(s)", tela + 1)
                self.ignorar.update(c.hash for c in cels[:idx + 1])
                return cels[idx + 1:]
            chaves = [chave_ordem(c.nome) for c in cels]
            hashes = {c.hash for c in cels}
            if hashes and hashes <= anteriores:
                # a lista nao se moveu: fim (ou topo). O alvo pode ser a ultima
                # linha da agenda, colada na borda: confere sem a margem.
                extra = self._ler_celulas(margem=0)
                if any(c.hash == alvo_hash for c in extra):
                    log.info("o ultimo contato da rodada anterior era o ultimo da agenda")
                    self.ignorar.update(c.hash for c in extra)
                    return []
                break
            anteriores = hashes
            if chaves[-1] < alvo_chave:
                if voltou:
                    self._rolar_uma_tela(cels)          # devagar: ja estamos perto
                else:
                    # longe => varias rolagens rapidas por leitura; perto => 1
                    dist = ord(alvo_chave[:1] or "a") - ord(chaves[-1][:1] or "a")
                    self._fling(4 if dist >= 2 else 1)
            elif chaves[0] > alvo_chave:
                voltou = True
                self._voltar_uma_tela(cels)
            else:
                # o alvo caberia nesta tela e nao esta: foi apagado da agenda.
                # Continua do primeiro contato alfabeticamente DEPOIS dele.
                log.warning("o ultimo contato da rodada anterior nao existe mais na "
                            "agenda; continuando do proximo em ordem alfabetica")
                self.ignorar.update(c.hash for c in cels if chave_ordem(c.nome) <= alvo_chave)
                return [c for c in cels if chave_ordem(c.nome) > alvo_chave]
            cels = self._ler_celulas()
        raise UiChanged("nao encontrei o ponto de retomada. Use --reset-progresso para "
                        "recomecar do A, ou apague o progress.scroll.local.json")

    # ---------- selecao ----------

    def _tocar(self, c: Celula) -> bool:
        try:
            c.el.click()
        except WebDriverException as e:
            self.stats["cliques_falhos"] += 1
            log.debug("clique falhou em %s: %s", mask(c.nome), str(e).splitlines()[0][:120])
            return False
        self._registrar_toque(c)
        return True

    def _registrar_toque(self, c: Celula) -> None:
        self.tocados.add(c.hash)
        self.ordem.append((c.hash, c.nome))
        self.stats["toques"] += 1
        self.results.append({"label": f"s{len(self.ordem)}", "outcome": "selected"})

    def _tocar_lote(self, lote: list) -> int:
        """--turbo: toca todas as celulas do lote com UMA requisicao W3C.

        As coordenadas sao as lidas nesta mesma tela, segundos antes. Depois
        da rajada confere, com uma busca pontual, que o seletor continua na
        tela (o botao Criar existe): se um dialogo inesperado tiver aparecido
        no meio, para aqui — parada segura, como no resto do fluxo.
        Devolve quantos toques foram registrados. Se o driver nao aceitar a
        requisicao, desliga o turbo e volta ao toque por elemento."""
        if not lote:
            return 0
        acoes = []
        for c in lote:
            x, y = c.centro
            acoes += [
                {"type": "pointerMove", "duration": 0, "x": x, "y": y},
                {"type": "pointerDown", "button": 0},
                {"type": "pause", "duration": TURBO_TOQUE_MS},
                {"type": "pointerUp", "button": 0},
                {"type": "pause", "duration": TURBO_ENTRE_TOQUES_MS},
            ]
        carga = {"actions": [{"type": "pointer", "id": "dedo",
                              "parameters": {"pointerType": "touch"},
                              "actions": acoes}]}
        try:
            self.d.execute(_W3C_ACTIONS, carga)
        except WebDriverException as exc:
            log.warning("turbo: o driver recusou a rajada de toques (%s); "
                        "voltando ao toque por elemento",
                        str(exc).splitlines()[0][:100])
            self.turbo = False
            feitos = 0
            for c in lote:
                if self._tocar(c):
                    feitos += 1
            return feitos
        for c in lote:
            self._registrar_toque(c)
        # O seletor precisa continuar aqui. Um dialogo por cima (contato
        # bloqueado, aviso do sistema) teria engolido parte da rajada.
        if self.wait_for("picker_anchor", timeout=2, required=False) is None:
            raise UiChanged(
                "o seletor de contatos sumiu durante a rajada de toques (turbo). "
                "Feche o que estiver na tela, cancele o seletor e rode de novo — "
                "esta lista nao foi criada.")
        return len(lote)

    def _checar_seguranca(self, forcar: bool = False) -> None:
        """Verifica se o WhatsApp continua em primeiro plano e se o compositor
        nao apareceu. Chamada forcada (forcar=True) nos momentos criticos (falha
        de clique, fim da lista, saida do loop). Chamada periodica automatica a
        cada _CHECAR_INTERVALO toques — evita chamar activeAppInfo por tela."""
        self._toques_desde_check += 1
        if not forcar and self._toques_desde_check < self._CHECAR_INTERVALO:
            return
        self._toques_desde_check = 0
        if not self._whatsapp_in_front():
            raise UiChanged("um app externo abriu durante a selecao (celula 'Convidar'?) "
                            "— parei sem tocar em mais nada; volte ao WhatsApp e rode de novo")
        # No seletor, a prova mais forte e mais barata de que nada estranho
        # apareceu e o proprio botao Criar continuar na tela (1 busca pontual).
        # Um compositor de mensagem so existe FORA do seletor — se o seletor
        # sumiu, paramos antes de qualquer toque, que e o que a trava garante.
        if self.wait_for("picker_anchor", timeout=2, required=False) is None:
            raise UiChanged("o seletor de contatos sumiu (dialogo por cima ou tela "
                            "trocada) — parei sem tocar em mais nada; feche o que "
                            "estiver na tela e rode de novo")

    def selecionar(self, prog: Progresso) -> int:
        """Seleciona ate self.limite contatos a partir do ponto de retomada.
        Devolve quantos foram tocados."""
        self.transition(State.SELECTING)
        self.tocados, self.ignorar, self.ordem, self.results = set(), set(), [], []
        convites_vistos = set()
        self._topo = 0.0
        cels = self._ler_celulas()
        if not cels:
            raise UiChanged("nenhum contato visivel na tela Destinatarios")
        self._topo = min(c.y for c in cels) - 1.0   # tudo acima disso esta sob a barra
        if prog.ultimo_hash:
            cels = self._retomar(prog, cels)

        sem_avanco = 0
        anteriores = set()
        t0 = time.monotonic()
        for tela in range(MAX_TELAS_POR_LISTA):
            self.stats["telas"] += 1
            novos = 0
            tocados_tela = {}       # hash -> y da celula tocada NESTA tela
            falhas = {}
            lote: list = []         # turbo: celulas desta tela para a rajada
            i = 0
            while i < len(cels) and len(self.ordem) + len(lote) < self.limite:
                c = cels[i]
                i += 1
                if c.hash in self.ignorar:
                    continue                     # antes do ponto de retomada
                if self.permitidos is not None and c.hash not in self.permitidos:
                    if c.hash not in self._filtrados_vistos:
                        self._filtrados_vistos.add(c.hash)
                        self.stats["filtrados"] = self.stats.get("filtrados", 0) + 1
                    continue                     # fora do filtro de DDD
                if c.hash in self.tocados or any(c.hash == l.hash for l in lote):
                    # mesma celula relida (sobreposicao/releitura) => nada a fazer;
                    # OUTRA celula com o mesmo nome (homonimo) => nao toco, porque
                    # nao da para distinguir e tocar de novo desmarcaria o primeiro.
                    y_tocada = tocados_tela.get(c.hash)
                    mesma = y_tocada is not None and abs(c.y - y_tocada) < c.h * 0.6
                    if c.hash not in anteriores and not mesma:
                        self.stats["repetidos"] += 1
                    continue
                if falhas.get(c.hash, 0) >= 2:
                    continue                     # nao alcancavel nesta tela; segue
                # Convite decidido pelo rotulo ja lido: zero chamadas ao WDA.
                # (Antes: _is_invite_cell fazia 3-4 chamadas POR CELULA.)
                if eh_convite(c.nome):
                    if c.hash not in convites_vistos:
                        convites_vistos.add(c.hash)
                        self.stats["convites"] += 1
                    continue
                primeiro_toque = not self.ordem
                if self.turbo and not primeiro_toque:
                    lote.append(c)               # junta; toca tudo no fim da tela
                    continue
                y_antes = c.y
                if not self._tocar(c):
                    # elemento saiu do lugar: confere seguranca, rele a tela e refaz
                    falhas[c.hash] = falhas.get(c.hash, 0) + 1
                    self._checar_seguranca(forcar=True)   # clique falhou: critico
                    cels = self._ler_celulas()
                    i = 0
                    continue
                novos += 1
                tocados_tela[c.hash] = c.y
                if primeiro_toque:
                    # o 1o toque faz aparecer a faixa dos selecionados no topo e
                    # empurra a lista para baixo: mede o deslocamento e rele.
                    # Por isso o 1o toque da lista e SEMPRE sozinho, mesmo no turbo.
                    self.settle(0.2)   # animacao da faixa dura ~150-200ms
                    cels, delta = self._ajustar_topo(c.hash, y_antes, self._ler_celulas())
                    tocados_tela = {h: y + delta for h, y in tocados_tela.items()}
                    i = 0
            if lote:
                feitos = self._tocar_lote(lote)
                novos += feitos
                for c in lote[:feitos]:
                    tocados_tela[c.hash] = c.y
            # Checagem de seguranca forcada no fim de cada tela (reinicia o contador).
            # Dentro do loop de toques, ela ja roda periodicamente a cada _CHECAR_INTERVALO.
            self._checar_seguranca(forcar=True)
            log.info("tela %d: +%d (total %d/%d) — %ds", tela + 1, novos,
                     len(self.ordem), self.limite, int(time.monotonic() - t0))
            if len(self.ordem) >= self.limite:
                break
            hashes = {c.hash for c in cels}
            if novos == 0 and hashes and hashes <= anteriores:
                sem_avanco += 1
                if sem_avanco >= CICLOS_SEM_AVANCO:
                    # a lista nao rola mais: as ultimas linhas podem estar coladas
                    # na borda inferior (fora da margem). Ultima passada sem margem.
                    for c in self._ler_celulas(margem=0):
                        if len(self.ordem) >= self.limite:
                            break
                        if c.hash in self.ignorar or c.hash in self.tocados:
                            continue
                        if self.permitidos is not None and c.hash not in self.permitidos:
                            continue
                        if eh_convite(c.nome):
                            continue
                        self._tocar(c)
                    self._checar_seguranca(forcar=True)   # fim da lista: critico
                    log.info("fim da lista de contatos")
                    break
            else:
                sem_avanco = 0
            anteriores = hashes
            self._rolar_uma_tela(cels)
            cels = self._ler_celulas()
            if not cels:
                if self.in_picker():
                    log.info("fim da lista de contatos (tela vazia)")
                    break
                raise UiChanged("o seletor de contatos desapareceu durante a rolagem")
        return len(self.ordem)

    # ---------- saida ----------

    def cancelar_seletor(self) -> None:
        """Ensaio: fecha o seletor sem criar (nada fica selecionado)."""
        for depth in (12, 16, 20):
            try:
                self.d.update_settings({"snapshotMaxDepth": depth})
            except WebDriverException:
                pass
            btn = self.wait_for("cancel_button", timeout=3, required=False)
            if btn is not None:
                btn.click()
                self._restore_depth()
                self.settle(1.0)
                return
        self._restore_depth()
        log.warning("nao achei o 'Cancelar' do seletor; feche-o no iPhone antes da proxima rodada")

    def voltar_para_conversas(self) -> None:
        """Depois de criar, o WhatsApp abre a conversa da lista (com compositor —
        que NAO tocamos). Volta para a aba Conversas para a proxima lista."""
        pred = ('type == "XCUIElementTypeButton" AND (name == "back" OR '
                'name == "NavigationBar_BackButton" OR label == "Voltar" OR '
                'label == "Back" OR label == "Conversas" OR label == "Chats")')
        for _ in range(3):
            if self.wait_for("chats_tab", timeout=2, required=False) is not None:
                return
            btn = None
            try:
                found = self.d.find_elements(AppiumBy.IOS_PREDICATE, pred)
                btn = found[0] if found else None
            except WebDriverException:
                btn = None
            if btn is not None:
                btn.click()
            else:
                try:
                    self.d.back()
                except WebDriverException:
                    pass
            self.settle(1.2)
        raise UiChanged("nao consegui voltar para Conversas depois de criar a lista; "
                        "volte no iPhone e rode de novo (o progresso ja foi salvo)")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _encerrar_com_seguranca(*_):
    """SIGTERM (botao 'Parar' da estacao) vira KeyboardInterrupt: o `finally`
    roda driver.quit() e a sessao do WDA e encerrada no aparelho."""
    raise KeyboardInterrupt


def main() -> int:
    signal.signal(signal.SIGTERM, _encerrar_com_seguranca)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:4723")
    ap.add_argument("--wda-bundle", default="")
    ap.add_argument("--wa-version", default="")
    ap.add_argument("--trust-profile", action="store_true",
                    help="usar o perfil baseline (o mesmo ja validado no iPhone)")
    ap.add_argument("--approve-create", action="store_true",
                    help="cria a(s) lista(s) de verdade; sem isto e ensaio (seleciona e cancela)")
    ap.add_argument("--max-listas", type=int, default=1,
                    help="quantas listas criar nesta rodada (padrao 1)")
    ap.add_argument("--limite-por-lista", type=int, default=BROADCAST_LIMIT,
                    help=f"contatos por lista (padrao {BROADCAST_LIMIT}; use 5 no primeiro teste)")
    ap.add_argument("--progress-file", default=PROGRESSO_PADRAO)
    ap.add_argument("--progresso", action="store_true", help="so mostra onde parou e sai")
    ap.add_argument("--reset-progresso", action="store_true",
                    help="apaga o progresso: a proxima lista recomeca do primeiro contato")
    ap.add_argument("--ddd", default="",
                    help="incluir so estes DDDs (ex.: 21,22). Exige --agenda: a tela "
                         "nao mostra o numero de contato salvo, o DDD vem da agenda")
    ap.add_argument("--agenda", default="",
                    help="VCF ou CSV exportado da agenda, usado so para o filtro de DDD")
    ap.add_argument("--region", default="BR")
    ap.add_argument("--turbo", action="store_true",
                    help="toca todas as celulas de cada tela numa unica requisicao "
                         "(rajada W3C). Ligue SO depois do teste de 5 contatos passar")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")

    prog = Progresso(args.progress_file)
    if args.reset_progresso:
        if os.path.exists(args.progress_file):
            os.remove(args.progress_file)
        print("progresso apagado: a proxima lista comeca do primeiro contato.")
        return 0
    if args.progresso:
        print(prog.resumo())
        return 0

    if args.max_listas < 1:
        log.error("--max-listas deve ser >= 1")
        return 2
    if args.limite_por_lista < MIN_RECIPIENTS or args.limite_por_lista > BROADCAST_LIMIT:
        log.error("--limite-por-lista deve ficar entre %d e %d", MIN_RECIPIENTS, BROADCAST_LIMIT)
        return 2
    if not args.approve_create and args.max_listas > 1:
        log.warning("ensaio (sem --approve-create): faco 1 lista so, sem salvar progresso")
        args.max_listas = 1

    filtro = None
    if args.ddd:
        if not args.agenda:
            log.error("--ddd exige --agenda (VCF/CSV): a tela do WhatsApp nao mostra o "
                      "numero de contato salvo, entao o DDD vem da agenda exportada")
            return 2
        try:
            filtro = permitidos_por_ddd(args.agenda, args.ddd, args.region)
        except Exception as exc:
            log.error("nao consegui ler a agenda %s: %s", args.agenda, exc)
            return 2
        log.info("filtro de DDD %s pela agenda: %d nome(s) na agenda, %d permitidos, "
                 "%d ambiguos (numero dentro e fora do filtro: ficam de fora), "
                 "%d sem numero valido", args.ddd, filtro["nomes"],
                 len(filtro["permitidos"]), len(filtro["ambiguos"]), filtro["sem_numero"])
        if not filtro["permitidos"]:
            log.error("nenhum contato da agenda cai nos DDDs %s — nada a fazer", args.ddd)
            return 2
    log.info("progresso: %s", prog.resumo())
    log.info("modo: %s | %d lista(s) x ate %d contatos",
             "CRIAR DE VERDADE" if args.approve_create else "ENSAIO (nao cria)",
             args.max_listas, args.limite_por_lista)

    if not spike_ios.exigir_appium(args.server):
        return 2
    driver = build_driver(args.server, args.wda_bundle or None)
    try:
        profile = profile_for_version(args.wa_version)
        if profile is None:
            if not args.trust_profile:
                log.error("versao '%s' sem perfil validado: use --trust-profile (perfil "
                          "baseline, o mesmo do fluxo validado)", args.wa_version)
                return 3
            profile = BASELINE

        criadas = 0
        for n in range(1, args.max_listas + 1):
            numero_lista = prog.listas_criadas + 1
            print(f"Lista {n} de {args.max_listas}", flush=True)   # a GUI le esta linha
            sp = ScrollLivre(driver, profile, limite=args.limite_por_lista)
            sp.turbo = bool(args.turbo)
            sp.permitidos = filtro["permitidos"] if filtro else None
            if sp.turbo:
                log.info("turbo ligado: rajada de toques por tela (1 requisicao)")
            sp.transition(State.PREPARING)
            sp.open_new_broadcast()
            t0 = time.monotonic()
            qtd = sp.selecionar(prog)
            dur = int(time.monotonic() - t0)
            log.info("lista %d: %d contato(s) selecionado(s) em %ds — telas %d, "
                     "retomada %d tela(s), homonimos ignorados %d, convites %d, "
                     "cliques refeitos %d",
                     numero_lista, qtd, dur, sp.stats["telas"], sp.stats["telas_retomada"],
                     sp.stats["repetidos"], sp.stats["convites"], sp.stats["cliques_falhos"])

            if qtd < MIN_RECIPIENTS:
                log.info("menos de %d contatos restantes: nao ha lista a criar (fim da agenda)",
                         MIN_RECIPIENTS)
                sp.cancelar_seletor()
                break

            if not args.approve_create:
                log.info("ENSAIO: %d selecionados; cancelando o seletor sem criar. "
                         "Rode com --approve-create para criar de verdade.", qtd)
                sp.cancelar_seletor()
                break

            sp.finish(approve_create=True)     # so clica se "Criar" estiver habilitado
            criadas += 1
            prog.registrar_lista(qtd, sp.ordem[0][0], sp.ordem[-1][0], sp.ordem[-1][1])
            log.info("lista %d criada. %s", numero_lista, prog.resumo())
            if qtd < args.limite_por_lista:
                log.info("a agenda acabou nesta lista; nao ha mais o que criar")
                break
            if n < args.max_listas:
                sp.voltar_para_conversas()

        print(json.dumps({"listas_criadas_nesta_rodada": criadas, "offset": prog.offset,
                          "proximo_contato_n": prog.offset + 1,
                          "listas_criadas_total": prog.listas_criadas},
                         ensure_ascii=False, indent=2))
        return 0
    except UnsafeState as e:
        log.error("PARADA DE SEGURANCA: %s", e)
        return 5
    except UiChanged as e:
        log.error("UI_CHANGED / FAILED_SAFE: %s — nenhuma acao adicional.", e)
        _dump_inventory_on_fail(driver, "inventory-erro.json")
        return 4
    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass


if __name__ == "__main__":
    sys.exit(main())
