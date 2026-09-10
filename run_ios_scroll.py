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
import math
import os
import signal
import sys
import time
import unicodedata
from collections import Counter
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
# MEDIDO (auditoria 2026-09-10, simulador com a faixa de chips real: ~5-6
# contatos NOVOS por tela): 256 contatos = ~51 telas, NAO ~30 como este
# comentario dizia antes. Com filtro de DDD o numero de telas cresce na razao
# inversa da taxa de aprovacao do filtro — por isso o teto pode ser elevado
# dinamicamente por lista (ver `teto_telas_para`); este valor e o PISO.
MAX_TELAS_POR_LISTA = 400   # trava contra loop infinito (sem filtro, cobre ~51 telas com folga)
CONTATOS_NOVOS_POR_TELA_ESTIMADO = 5   # para estimar o teto de telas com filtro de DDD
# TETO ABSOLUTO do teto dinamico (auditoria 2026-09-10, 3a rodada): a formula de
# `teto_telas_para` nao tinha limite por cima — com um filtro de DDD de 1% ela
# valia 6.656 telas, e a ~3s por tela isso e uma rodada de 5-6 HORAS sem nenhum
# aviso ao operador. 1200 telas ~ 1 hora de rodada; acima disso a resposta certa
# nao e "continua rolando", e parar com salvamento parcial e motivo nomeado
# ("teto de telas") para o operador decidir (DDD menos raro, agenda menor).
TETO_TELAS_ABSOLUTO = 1200
# Teto de telas para uma lista de RECUPERACAO (--recomecar-do-A): ela precisa
# rolar por TODOS os contatos ja usados (a guarda bloqueia o toque, mas a
# tela ainda precisa ser lida e rolada) antes de chegar em gente nova. Maior
# que TETO_TELAS_ABSOLUTO de proposito — e um caminho de emergencia, nao a
# operacao normal, e o desfecho de estouro continua sendo nomeado (salvamento
# parcial), nunca perda.
TETO_RECUPERACAO = 2500
# Orcamento de RELOGIO por lista (--max-minutos). E a mesma grandeza que o
# teto de telas expressa em TRABALHO (TETO_TELAS_ABSOLUTO=1200 telas ~ 1h a
# 3s/tela): o teto de telas limita trabalho, o orcamento limita relogio, e o
# primeiro que estourar vence — com o MESMO desfecho (parada nomeada +
# salvamento parcial). gui_state.MAX_MINUTOS_POR_LISTA precisa bater com este
# valor (ver teste de coerencia).
ORCAMENTO_PADRAO_S = 3600.0
# Calibracao unica de "quanto custa uma tela" (leitura + toques + rolagem).
# Era o literal 3 espalhado pelo comentario do teto de telas e pela
# mensagem da lista de recuperacao; virou constante para que o teto de
# TRABALHO (telas) e o orcamento de RELOGIO (minutos) possam ser
# comparados na MESMA unidade antes de a rodada comecar (ver
# `max_telas_para_recuperacao` e a recusa antecipada em main()).
SEGUNDOS_POR_TELA_ESTIMADO = 3.0
# --turbo: rajada W3C. Toque curto e intervalo entre toques (ms). O iOS
# registra toques distintos com folga acima de ~50 ms.
TURBO_TOQUE_MS = 40
TURBO_ENTRE_TOQUES_MS = 90
MAX_LOTE_TURBO = 6          # tamanho maximo de uma rajada: reduz a janela em que
                            # as coordenadas lidas podem ficar desatualizadas
                            # (faixa de chips mudando de altura no meio da lista)
_W3C_ACTIONS = "actions"    # selenium Command.W3C_ACTIONS
MAX_TELAS_RETOMADA = 600    # 10 mil contatos / ~10 por tela, com folga
CICLOS_SEM_AVANCO = 2       # telas seguidas sem contato novo => fim da lista
LEITURA_RAPIDA_S = 2.0      # abaixo disto, uma tela vazia e fim de agenda plausivel
LEITURA_LENTA_S = 7.5       # metade do customSnapshotTimeout (15s): acima disto,
                            # tela vazia e tratada como FALHA de leitura, nunca
                            # como fim de agenda (foi exatamente isto no log de
                            # 2026-09-09: 33.6s, vazio, seguido de socket hang up)
# ATENCAO (auditoria 2026-09-10, 3a rodada): os dois numeros acima sao o tempo de
# UMA consulta ao WDA, nao o do bloco de leitura inteiro. Uma leitura de tela
# pode gastar 7-8 varreduras (camada lembrada, camada boa, fallback, re-escalada
# de profundidade); somar tudo fazia um aparelho SAUDAVEL (0,5s por consulta)
# estourar 7,5s e a lista sair parcial. Por isso `_ler_celulas` grava o PICO de
# UMA consulta (ver `_consultar`), e a re-escalada fica de fora da medicao.
LIMITE_RECTS_INDIVIDUAIS = 40   # acima disto sem conseguir inferir posicao, para
                                # em vez de pagar 1 chamada HTTP por elemento
                                # (o custo que cresce com o numero de selecionados)
# Discriminador de altura para separar, entre as celulas que a retentativa
# (releitura da tela inteira) ainda nao consegue ler, uma linha de CONTATO
# de um cabecalho de secao ("A", "B"...) ou outro elemento decorativo: a
# altura de uma celula de contato e conhecida (a moda das celulas LEGIVEIS
# desta mesma leitura).
#
# ATENCAO (auditoria 2026-09-10, 5a rodada): ate esta data o criterio era
# `abs(h - h_modal) <= TOLERANCIA_ALTURA_LINHA`, isto e, SIMETRICO. Uma linha
# de contato ilegivel 3 pt MAIS ALTA que a moda (recado que quebra em duas
# linhas, contato sem recado, Dynamic Type — a altura da linha de contato
# varia de verdade neste seletor) era classificada como "decoracao", nao
# setava corte, e a lista passava por cima da pessoa em silencio: ela ficava
# atras do ponto de retomada para sempre. Era o modo de erro 10 do projeto
# devolvido pela porta dos fundos, e 3 pt de diferenca eram a fronteira entre
# "parar para nao perder ninguem" e "perder alguem sem avisar".
#
# O criterio agora e ASSIMETRICO, e a assimetria e o que o aparelho permite
# afirmar SEM medir nada novo: uma linha de contato pode ser mais ALTA que a
# moda (conteudo a mais), nunca drasticamente mais BAIXA. Entao:
#   - h >= h_modal - TOLERANCIA_ALTURA_LINHA  -> pode ser contato: PARA.
#   - h claramente menor (<= h_modal * FRACAO_MAXIMA_DECORACAO) -> cabecalho
#     de secao / separador: ignora e segue.
#   - qualquer coisa no meio (mais baixa, mas nao a ponto de ser cabecalho)
#     -> ambigua: PARA, que e o lado seguro.
# A unica altura de cabecalho de que o repositorio tem registro (fixture do
# teste) e ~28 pt contra ~64 pt de linha de contato, ou seja 0,44 da moda —
# bem dentro de 0,6. Medir no iPhone permite apertar isto depois; nao medir
# NAO devolve o "pular contato em silencio".
TOLERANCIA_ALTURA_LINHA = 2.0
FRACAO_MAXIMA_DECORACAO = 0.6
PARADA_SEM_ROTULO = "celula sem rotulo (nao da para saber quem e)"
PARADA_SEM_RECT = "celula sem posicao legivel (o rect nao respondeu)"


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


def teto_telas_para(limite_por_lista: int, filtro: dict | None) -> int:
    """Teto de telas para UMA lista. Sem filtro, o piso MAX_TELAS_POR_LISTA ja
    cobre a lista cheia com folga (medido: ~51 telas para 256 contatos). Com
    filtro de DDD, quanto mais restritivo, mais telas sao percorridas por
    contato aprovado — se o teto ficar fixo, uma taxa de aprovacao pior que
    ~1 em 7 estoura o piso e a rodada para em silencio achando que "a agenda
    acabou" (auditoria 2026-09-10).

    A taxa usada aqui e a da AGENDA inteira (permitidos / nomes) — um TETO
    SUPERIOR da taxa real na tela, que so quem roda no aparelho conhece de
    verdade (numeros homonimos, nomes que nao casam por grafia diferente etc.
    so reduzem essa taxa). Por isso a formula usa uma folga de 1.3x.

    O resultado e limitado por TETO_TELAS_ABSOLUTO: sem esse limite a formula
    valia 6.656 telas (filtro de 1%), o que a ~3s por tela sao 5-6 HORAS de
    rodada sem nenhum aviso (auditoria 2026-09-10, 3a rodada). Estourar o teto
    e um desfecho NOMEADO com salvamento parcial, nao uma perda."""
    if not filtro or not filtro.get("nomes"):
        return MAX_TELAS_POR_LISTA
    taxa = len(filtro["permitidos"]) / filtro["nomes"]
    taxa = max(taxa, 0.01)   # nunca deixa a conta explodir com taxa=0
    telas_estimadas = math.ceil(
        (limite_por_lista / (taxa * CONTATOS_NOVOS_POR_TELA_ESTIMADO)) * 1.3)
    return min(max(MAX_TELAS_POR_LISTA, telas_estimadas), TETO_TELAS_ABSOLUTO)


def telas_para_atravessar_guarda(n_usados: int) -> int:
    """Quantas telas a lista de RECUPERACAO precisa rolar so para PASSAR por
    quem ja esta em lista, antes de chegar em alguem novo. A guarda bloqueia o
    toque, mas a tela ainda precisa ser lida e rolada."""
    return math.ceil(max(0, int(n_usados)) / CONTATOS_NOVOS_POR_TELA_ESTIMADO)


def max_telas_para_recuperacao(n_usados: int, teto_base: int) -> int:
    """Teto de telas de uma lista de RECUPERACAO (--recomecar-do-A, ou a
    primeira lista de um progresso que ja tem contatos usados e nao tem ancora
    de retomada).

    Ela rola a agenda desde o A e precisa atravessar TODOS os ja usados antes
    de achar gente nova; por isso o teto normal nao serve. Folga de 1.3x
    (mesma calibracao de `teto_telas_para`) mais o piso de uma lista comum,
    limitado por TETO_RECUPERACAO. Estourar continua sendo salvamento parcial
    com motivo nomeado, nunca perda.

    Extraida de main() em 2026-09-10 (4a rodada) porque era o unico calculo do
    caminho de emergencia sem nenhum teste: remover o bloco inteiro deixava as
    suites verdes."""
    estimado = math.ceil(telas_para_atravessar_guarda(n_usados) * 1.3) + MAX_TELAS_POR_LISTA
    return min(max(int(teto_base), estimado), TETO_RECUPERACAO)


def eh_decoracao(h: float, h_modal) -> bool:
    """A celula ilegivel de altura `h` e decoracao (cabecalho de secao,
    separador) e nao uma linha de contato?

    Criterio ASSIMETRICO de proposito — ver o comentario de
    TOLERANCIA_ALTURA_LINHA/FRACAO_MAXIMA_DECORACAO. Na duvida devolve False,
    que e o lado que PARA a lista em vez de ultrapassar alguem em silencio.
    """
    if h_modal is None:
        return False                       # sem moda nao da para comparar nada
    if h >= h_modal - TOLERANCIA_ALTURA_LINHA:
        return False                       # igual ou MAIS ALTA: pode ser contato
    return h <= h_modal * FRACAO_MAXIMA_DECORACAO


def eh_convite(nome_ou_rotulo: str) -> bool:
    """Celula 'Convidar para o WhatsApp' (abre o app Mensagens se tocada).
    Decidido pelo rotulo JA LIDO — sem nenhuma chamada extra ao WDA."""
    baixa = (nome_ou_rotulo or "").lower()
    return "convidar" in baixa or "invite" in baixa


# ---------------------------------------------------------------------------
# progresso
# ---------------------------------------------------------------------------

_CAMPOS_CONHECIDOS_PROGRESSO = {
    "versao", "modo", "sensivel", "offset", "proximo_contato_n", "listas_criadas",
    "ultimo_rotulo", "ultimo_hash", "atualizado_em", "historico",
}


class Progresso:
    def __init__(self, path: str):
        self.path = path
        self.offset = 0
        self.listas_criadas = 0
        self.ultimo_rotulo = ""
        self.ultimo_hash = ""
        self.historico: list = []
        # v2: hashes de TODO contato que ja entrou numa lista CRIADA (nunca
        # ensaio) — a guarda contra duplicata (ver ScrollLivre.selecionar).
        # Derivado de historico[i]['hashes'] na carga; nunca escrito por fora
        # de registrar_lista().
        self.usados: set = set()
        self.versao = 1
        # Campos desconhecidos de uma versao FUTURA do arquivo: preservados
        # tal e qual para nao serem apagados quando esta versao regravar.
        self._extra: dict = {}
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
        self.versao = int(d.get("versao", 1))
        self._extra = {k: v for k, v in d.items() if k not in _CAMPOS_CONHECIDOS_PROGRESSO}
        self.usados = set()
        for entrada in self.historico:
            for h in (entrada.get("hashes") or []):
                self.usados.add(h)
        if self.versao > 2:
            log.warning("progresso escrito por uma versao MAIS NOVA da estacao; "
                        "atualize por git pull antes de rodar")
        faltando = self.guarda_incompleta()
        if faltando:
            # A condicao era `self.versao == 1 and self.listas_criadas`
            # (auditoria 2026-09-10, 5a rodada). Bastava UMA lista nova para
            # salvar() regravar o arquivo como "versao": 2 e este aviso — o
            # UNICO que existe sobre guarda cega — nunca mais aparecer, embora
            # as listas antigas continuassem sem impressao digital. O operador
            # passava a ler so "a guarda conhece N contato(s) ja usados", uma
            # frase que afirma protecao, enquanto a guarda era cega para as
            # outras centenas. A pergunta certa nao e a versao do arquivo, e a
            # COBERTURA: quantas listas ja criadas nao gravaram hashes.
            log.warning("a guarda contra duplicata nao sabe QUEM entrou em %d de %d "
                        "lista(s) ja criada(s) (progresso da versao 1, ou entradas de "
                        "historico sem a impressao digital dos contatos): sobre essas "
                        "pessoas a guarda NAO protege — se a retomada derivar, elas "
                        "podem entrar numa segunda lista. A guarda vale integralmente "
                        "para as listas criadas de agora em diante.",
                        faltando, self.listas_criadas)

    def salvar(self) -> None:
        d = {
            "versao": 2,
            **self._extra,
            "modo": "scroll-livre",
            # O arquivo guarda o NOME do ultimo contato de cada lista
            # ("ultimo_rotulo"). Nao da para trocar por hash: a retomada compara
            # esse nome em ORDEM ALFABETICA quando o contato foi apagado da
            # agenda entre uma lista e outra, e hash/prefixo truncado nao
            # ordenam (ver a decisao registrada em MODO-SCROLL-LIVRE.md).
            # Alem disso o arquivo agora guarda tambem uma impressao digital
            # (hash) de TODO contato que ja entrou em lista — mesma
            # sensibilidade do contatos.csv (o modo CSV ja faz isso: ver
            # run_ios.py, que grava um hash por contato).
            "sensivel": ("contem o nome do ultimo contato de cada lista "
                         "(necessario para retomar) e o hash de todo contato ja "
                         "incluido em lista — trate como o contatos.csv: fica so "
                         "no Mac, nunca por e-mail/anexo"),
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

    def registrar_lista(self, ordem: list) -> None:
        """`ordem` e sp.ordem: lista de (hash, nome) na ordem de toque. Quem
        chama SEMPRE passa a lista inteira tocada nesta rodada — quantidade,
        primeiro e ultimo saem dela, nunca de parametros separados que
        poderiam dessincronizar do conteudo real."""
        quantidade = len(ordem)
        primeiro_hash = ordem[0][0]
        ultimo_hash, ultimo_rotulo = ordem[-1]
        hashes = [h for h, _ in ordem]
        self.listas_criadas += 1
        self.offset += quantidade
        self.ultimo_hash = ultimo_hash
        self.ultimo_rotulo = ultimo_rotulo
        self.historico.append({
            "lista": self.listas_criadas,
            "quantidade": quantidade,
            "primeiro_hash": primeiro_hash,
            "ultimo_hash": ultimo_hash,
            "hashes": hashes,
            "criada_em": datetime.now().isoformat(timespec="seconds"),
        })
        self.usados.update(hashes)
        self.salvar()

    def guarda_incompleta(self) -> int:
        """Quantas listas JA CRIADAS nao estao cobertas pela guarda — isto e,
        quantas nao gravaram a impressao digital (hashes) dos contatos que
        entraram nelas.

        Arquivos de versao 1 (e entradas antigas de historico) registram
        `quantidade` mas nao `hashes`: a guarda nao sabe QUEM entrou nessas
        listas. Enquanto esse numero for > 0, --recomecar-do-A duplicaria
        exatamente essas pessoas — e basta UMA lista nova (que grava hashes)
        para `usados` deixar de estar vazio, que era a unica pergunta que a
        trava antiga fazia (auditoria 2026-09-10, 4a rodada).
        """
        com_digital = sum(1 for e in self.historico if e.get("hashes"))
        return max(0, self.listas_criadas - com_digital)

    def incertos_pendentes(self) -> list:
        """[(indice_no_historico, entrada), ...] das listas com toques_incertos
        ainda nao resolvidos pelo operador (ver --resolver-incertos)."""
        return [(i, e) for i, e in enumerate(self.historico)
                if e.get("toques_incertos") and not e.get("incertos_resolvidos")]

    def resumo(self) -> str:
        if not self.listas_criadas:
            base = "nenhuma lista criada ainda: a proxima comeca do primeiro contato (A)"
        else:
            base = (f"{self.listas_criadas} lista(s) criada(s), {self.offset} contato(s) ja "
                    f"incluidos; a proxima lista comeca no contato n. {self.offset + 1} "
                    f"(logo apos {mask(self.ultimo_rotulo)})")
        if self.usados:
            base += f"; a guarda conhece {len(self.usados)} contato(s) ja usados"
        faltando = self.guarda_incompleta()
        if faltando:
            # "a guarda conhece N" sozinho afirma protecao. Sem esta frase o
            # resumo escondia que a protecao cobre so parte das listas.
            base += (f"; a guarda cobre {self.listas_criadas - faltando} de "
                     f"{self.listas_criadas} lista(s) ja criada(s) — a(s) "
                     f"{faltando} restante(s) nao gravaram impressao digital e "
                     f"podem ser duplicadas se a retomada derivar")
        pendentes = self.incertos_pendentes()
        if pendentes:
            listas = ", ".join(str(e.get("lista", "?")) for _, e in pendentes)
            qtd = sum(len(e.get("toques_incertos") or []) for _, e in pendentes)
            base += (f"; {qtd} toque(s) em duvida ainda nao resolvidos "
                     f"(lista(s) {listas})")
        return base


# ---------------------------------------------------------------------------
# o modo em si
# ---------------------------------------------------------------------------

class ScrollLivre(IosSpike):
    """Reaproveita TODO o fluxo validado (sessao, abertura do seletor, travas)
    e troca apenas a etapa de selecao: em vez de buscar por numero, toca nos
    contatos na ordem da tela e rola."""

    # NAO existe checagem "periodica a cada N toques" aqui: a checagem de
    # seguranca e SEMPRE forcada, nos momentos em que ela vale (fim de cada
    # tela, toque que falhou, fim da lista). O contador periodico que existia
    # ate 2026-09-10 era um botao morto — os tres pontos de chamada passavam
    # forcar=True, entao o intervalo nunca era consultado, e mesmo assim o
    # comentario prometia ao operador uma checagem que nunca acontecia.

    def __init__(self, driver, profile, limite: int = BROADCAST_LIMIT,
                max_telas: int = MAX_TELAS_POR_LISTA, max_segundos: float = 0.0):
        super().__init__(driver, profile)
        self.verify_selection = False   # contagem por toque; sem varrer a arvore
        self.limite = max(MIN_RECIPIENTS, min(limite, BROADCAST_LIMIT))
        self.max_telas = max(1, int(max_telas))
        # Orcamento de relogio da lista (0 = desligado, para nao mudar as
        # construcoes diretas dos testes existentes). Ver _orcamento_estourou.
        self.max_segundos = max(0.0, float(max_segundos))
        self._t_inicio_lista: float | None = None
        # Motivo do PULO (opt-in --pular-celula-ilegivel): posicoes na fila
        # (nunca hash/nome) de celulas puladas por nao devolverem rotulo/rect.
        self.pular_sem_rotulo = False
        self.pulados: list = []
        # Hashes de contatos com o MESMO NOME de alguem ja tocado NESTA lista:
        # nao sao tocados (tocar de novo desmarcaria o primeiro) e a perda e
        # PERMANENTE — a retomada os considera "ja passados". So rastreado
        # para nao ficar invisivel no log (ver main()).
        self.homonimos: list = []
        self.tocados: set = set()       # hashes ja tocados NESTA lista
        self.ignorar: set = set()       # hashes ANTES do ponto de retomada (nunca tocar)
        self.ordem: list = []           # (hash, nome) na ordem de toque
        # GUARDA contra duplicata: hashes de contatos que ja entraram numa
        # lista CRIADA em rodada(s) anteriores (referencia a prog.usados —
        # nunca uma copia; ver selecionar()). Nunca escrito por esta classe.
        self.usados: set = set()
        # Lista de RECUPERACAO (sem ancora de retomada e com a guarda ja
        # populada: --recomecar-do-A, ou um progresso v1 sem ultimo_hash).
        # Definido em selecionar() a partir do proprio Progresso. So nesse
        # modo um contato ja usado reaparecer no laco principal e ESPERADO:
        # fora dele, _retomar() ja ignorou tudo ate o ultimo tocado, entao
        # um hit na guarda so pode ser um HOMONIMO de outra lista (ver o
        # ramo `c.hash in self.usados` em selecionar()).
        self.em_recuperacao = False
        # Hashes de celulas bloqueadas pela guarda DEPOIS do ponto de retomada,
        # fora da lista de recuperacao: deriva de retomada (ninguem perdido) OU
        # homonimo de lista anterior (perda permanente) — a tela nao distingue.
        # Ver o ramo `c.hash in self.usados` em selecionar().
        self.bloqueados_apos_retomada: list = []
        self.stats = {"telas": 0, "toques": 0, "repetidos": 0, "convites": 0,
                      "sem_rotulo": 0, "cliques_falhos": 0, "telas_retomada": 0,
                      # celula que falhou 2x na MESMA tela: nao e mais abandonada
                      # em silencio (ver selecionar) — vira parada nomeada.
                      "travados": 0,
                      # bloqueado pela guarda de duplicata (ja entrou numa lista
                      # anterior): nao e uma celula pulada por engano, e a prova
                      # de que a guarda esta funcionando (ver _logar_filtrados).
                      "bloqueados_guarda": 0,
                      # linha com a altura de uma celula de contato que nao
                      # devolveu nome/posicao em duas leituras (para a lista
                      # antes de ultrapassar, ver PARADA_SEM_ROTULO/_SEM_RECT).
                      "sem_rotulo_ignorado": 0, "sem_rect": 0}
        self._tamanho = None
        self._topo = 0.0
        # y a partir do qual a leitura CORRENTE nao pode ser confiada (uma
        # celula com altura de linha de contato nao devolveu nome ou posicao
        # legivel): redefinido em TODA chamada de _ler_celulas. None = nada a
        # cortar nesta leitura.
        self._corte_y: float | None = None
        self._corte_motivo: str = ""
        # Chave alfabetica do ponto de retomada desta lista ("" quando ela
        # comeca do A). Fronteira do que ja esta em lista CRIADA — ver
        # _descartar_corte_ja_processado.
        self._chave_ancora: str = ""
        self._profundidade = None
        self._profundidade_reescalada = False   # 1 re-escalada por lista (orcamento de tempo)
        self._ultima_leitura_bruta = 0   # celulas que a BUSCA achou na ultima leitura
        # Pico (s) de UMA consulta ao WDA dentro da leitura em andamento. A
        # valvula de leitura mede ISTO, nao a soma do bloco (ver LEITURA_LENTA_S).
        self._pico_consulta = 0.0
        self._observador_consulta = self._marcar_consulta
        # Motivo de uma parada FORCADA (nao e "fim de agenda" nem "limite
        # atingido"): teto de telas, leitura que estourou o tempo, rajada
        # interrompida no meio. "" = a selecao terminou normalmente (limite
        # batido ou agenda esgotada de verdade). Quem chama (main) usa isto
        # para decidir entre salvamento parcial e o desfecho normal.
        self.parada: str = ""
        # Hashes tocados numa rajada que NAO PODE ser confirmada nem re-tocada
        # (ver _tocar_lote): fica so para auditoria no progresso, nunca no
        # self.ordem nem no self.tocados.
        self.incerteza: list = []
        # Duracao (s) das ultimas leituras de tela — usada para distinguir
        # "tela vazia = fim de agenda" (rapido) de "tela vazia = o WDA nao
        # respondeu a tempo" (lento, o sintoma exato do log de 2026-09-09).
        self._duracoes_leitura: list = []
        # --turbo: toca todas as celulas de uma tela numa UNICA requisicao W3C
        # (coordenadas lidas nesta mesma tela). Desligado por padrao: toque por
        # coordenada nao e barrado por um dialogo inesperado como o click de
        # elemento e — liga so depois de validar no aparelho.
        self.turbo = False
        # True apos a 1a rajada bem-sucedida NESTA lista: prova que o driver
        # aceita o comando 'actions'. Uma falha DEPOIS disto e uma requisicao
        # que morreu no meio (nao uma recusa do comando) — ver _tocar_lote.
        self._turbo_confirmado = False
        # A ultima rajada W3C provou, DEPOIS dos toques, que o seletor continua
        # na tela? So o envio bem-sucedido + busca da ancora prova isso.
        self._ancora_confirmada = False
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

    def _orcamento_estourou(self) -> bool:
        """True quando o orcamento de relogio da lista (--max-minutos) acabou.
        0 (desligado) ou lista ainda nao iniciada (_t_inicio_lista == 0)
        nunca estoura. Usa o `time` do MODULO (nao time.monotonic importado
        direto) de proposito: com_relogio() nos testes troca rs.time por um
        relogio falso."""
        if not self.max_segundos or self._t_inicio_lista is None:
            return False
        return (time.monotonic() - self._t_inicio_lista) >= self.max_segundos

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

    def _reescalar_profundidade_uma_vez(self) -> bool:
        """So chamado quando uma tela voltou vazia e estamos prestes a concluir
        'fim da lista': confere se subir a profundidade enxerga celulas que a
        atual nao alcanca. No modo CSV isso e CONFIRMADO (a faixa de chips
        afunda a arvore um nivel apos o 1o contato); no Scroll Livre nao foi
        confirmado no aparelho, mas o mecanismo e o mesmo — e o preco de nao
        tentar seria terminar a lista com 1 contato achando que "a agenda
        acabou". So busca pontual (find_all, nunca varredura nova) e so UMA
        vez por lista, com orcamento de tempo: nao pode ser o proximo socket
        hang up.

        O orcamento de 3s so vale se ele for conferido DEPOIS de cada busca
        (auditoria 2026-09-10, 3a rodada): conferindo so entre iteracoes, a
        primeira era incondicional — e ela e justamente a busca mais cara, na
        profundidade MAIOR que a que acabou de travar. E se a leitura que
        motivou esta chamada ja voltou LENTA, o problema nao e profundidade: e
        o WDA. Nesse caso nao se gasta nem um update_settings."""
        if self._pico_consulta >= LEITURA_LENTA_S:
            log.warning("nao subo a profundidade depois de uma consulta de %.1fs: "
                        "o sintoma e do WDA, nao da arvore (subir so aumentaria o "
                        "custo da proxima busca)", self._pico_consulta)
            return False
        if self._ultima_leitura_bruta:
            # A busca ACHA celulas; a tela ficou vazia so porque todas caem
            # fora da area tocavel (margem inferior / faixa do topo). Isso e
            # fim de agenda de verdade, nao profundidade curta: subir a
            # profundidade aqui so gastaria chamadas.
            return False
        if self._profundidade_reescalada:
            return False
        self._profundidade_reescalada = True
        base = self._profundidade or 12
        t0 = time.monotonic()
        for depth in (base + 2, base + 4, 18):
            if depth <= base:
                continue
            if time.monotonic() - t0 > 3.0:
                break
            try:
                self.d.update_settings({"snapshotMaxDepth": depth})
            except WebDriverException:
                pass
            achou = self.find_all("contact_cell")
            if not achou and time.monotonic() - t0 > 3.0:
                # orcamento estourou DENTRO desta tentativa (a busca custou mais
                # do que o orcamento inteiro): nao comeca a proxima, que seria
                # ainda mais funda.
                log.warning("orcamento da re-escalada de profundidade estourou na "
                            "profundidade %d — nao tento mais fundo", depth)
                break
            if achou:
                log.info("profundidade insuficiente: subindo de %d para %d "
                         "(a faixa de chips deve ter afundado a arvore)",
                         self._profundidade, depth)
                self._profundidade = depth
                return True
        try:
            self.d.update_settings({"snapshotMaxDepth": base})
        except WebDriverException:
            pass
        return False

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
        cru = self._find_raw(self.p.selectors.get("contact_cell"), com_rect=True,
                             chave="contact_cell")
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
        _cell_text(), caindo de ~40 para ~20 chamadas por tela.

        Cronometrada (auditoria 2026-09-10): o que fica em self._duracoes_leitura
        (ultimas 10) e o PICO de UMA consulta ao WDA desta leitura — nao a soma
        do bloco. Uma leitura gasta ate 7-8 varreduras (camada lembrada, camada
        boa, fallback, re-escalada de profundidade); somando tudo, um aparelho
        saudavel de 0,5s por consulta "estourava" os 7,5s de LEITURA_LENTA_S e a
        lista saia parcial sem nenhuma consulta individual ter sido lenta
        (3a rodada da auditoria). A valvula precisa do tempo de UMA consulta,
        que e o numero contra o qual LEITURA_LENTA_S foi calibrado."""
        t0 = time.monotonic()
        self._pico_consulta = 0.0
        try:
            cels = self._ler_celulas_impl(margem)
            # O corte e propriedade da leitura CORRENTE e nasce da tela
            # INTEIRA — inclusive da parte dela que ficou ATRAS do ponto de
            # retomada. Descartar aqui, no fim de TODA leitura, e o que faz a
            # regra valer em qualquer chamador (laco principal, ultima
            # passada, retentativa) sem depender de nenhum deles lembrar.
            self._descartar_corte_ja_processado(cels)
            return cels
        finally:
            bloco = time.monotonic() - t0
            self._duracoes_leitura.append(self._pico_consulta)
            if len(self._duracoes_leitura) > 10:
                self._duracoes_leitura.pop(0)
            log.debug("leitura da tela: bloco %.3fs, consulta mais lenta %.3fs",
                      bloco, self._pico_consulta)

    def _marcar_consulta(self, dur: float) -> None:
        """Gancho chamado a CADA consulta ao WDA (ver IosSpike._consulta_cronometrada).
        Guarda o pico de UMA consulta da leitura em andamento: e esse numero,
        nao a soma do bloco, que LEITURA_RAPIDA_S/LEITURA_LENTA_S medem."""
        if dur > self._pico_consulta:
            self._pico_consulta = dur

    def _ler_celulas_impl(self, margem: float) -> list:
        self._fixar_profundidade()
        _, altura = self._tamanho_tela()
        self._corte_y = None   # propriedade da leitura CORRENTE (ver atributo)
        self._corte_motivo = ""
        lidas: list = []
        ilegiveis: list = []      # (y, h): rect ok, rotulo vazio
        sem_posicao: list = []    # ultimo y OK antes de um elemento sem rect
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
            # Quantas a BUSCA achou, antes do filtro de margem/topo. Distingue
            # "o WDA nao acha celula nenhuma" (profundidade curta demais: a
            # faixa de chips afundou a arvore) de "achou, mas todas caem fora
            # da area tocavel" (fim de agenda de verdade). Sem isto a
            # re-escalada de profundidade rodava as cegas.
            self._ultima_leitura_bruta = len(els)
            out, falhou = [], False
            lidas, ilegiveis, sem_posicao = [], [], []
            ultimo_y_ok = None
            for el, r in zip(els, rects):
                if r is None:
                    falhou = True
                    if tentativa == 0:
                        break
                    # 2a leitura ainda sem posicao: nao descarta em silencio
                    # (ver o discriminador de altura, abaixo) — a ultima
                    # posicao boa CONHECIDA e o melhor y disponivel para o
                    # corte, ja que este elemento nao tem posicao nenhuma.
                    sem_posicao.append(ultimo_y_ok)
                    continue
                x, y, w, h = r
                ultimo_y_ok = y
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
                    # 2a leitura ainda sem rotulo: nao conta como sem_rotulo
                    # de cara — o discriminador de altura (abaixo) decide se
                    # e uma linha de CONTATO (para a lista) ou um cabecalho
                    # de secao / decoracao (ignora e segue).
                    ilegiveis.append((y, h))
                    continue
                out.append(Celula(el=el, nome=nome, hash=hash_nome(nome), y=y, h=h,
                                  x=x, w=w))
                lidas.append((y, h))
            if not falhou or tentativa == 1:
                break
            self.settle(0.2)   # retry rapido: a tela ja estava montada
        out.sort(key=lambda c: c.y)
        if ilegiveis or sem_posicao:
            alturas = Counter(round(h, 1) for _, h in lidas)
            h_modal = alturas.most_common(1)[0][0] if alturas else None
            for y, h in ilegiveis:
                if eh_decoracao(h, h_modal):
                    # claramente mais BAIXA que a linha de contato: cabecalho
                    # de secao ("A", "B"), separador, decoracao. Nao para.
                    self.stats["sem_rotulo_ignorado"] += 1
                else:
                    # pode ser a altura de uma LINHA DE CONTATO (igual, mais
                    # alta, ou so um pouco mais baixa): e um contato que nao
                    # disse o nome — nao pode ser ultrapassado em silencio.
                    self.stats["sem_rotulo"] += 1
                    if self._corte_y is None or y < self._corte_y:
                        self._corte_y, self._corte_motivo = y, PARADA_SEM_ROTULO
            for ultimo_y in sem_posicao:
                self.stats["sem_rect"] += 1
                c = 0.0 if ultimo_y is None else ultimo_y + 0.5
                if self._corte_y is None or c < self._corte_y:
                    self._corte_y, self._corte_motivo = c, PARADA_SEM_RECT
        # A BUSCA nao achou celula nenhuma? Pode ser a profundidade, e nao o
        # fim da agenda: a faixa de chips afunda a arvore um nivel depois do
        # 1o contato (CONFIRMADO no modo CSV). Reavaliar AQUI, e nao la no
        # laco de selecao, e o que importa: la a decisao ja vinha DEPOIS de
        # uma rolagem as cegas, e os contatos daquela tela eram pulados em
        # silencio (revisao adversarial 2026-09-10, 2a rodada). Vale 1 vez
        # por lista e so quando a busca voltou vazia — fim de agenda de
        # verdade (celulas achadas, todas fora da area tocavel) nao paga.
        if (not out and not self._ultima_leitura_bruta
                and self._reescalar_profundidade_uma_vez()):
            return self._ler_celulas_impl(margem)
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
        if n - 2 > LIMITE_RECTS_INDIVIDUAIS:
            # A inferencia falhou (cabecalho de secao, ou os chips da faixa de
            # selecionados misturados na mesma busca '**/XCUIElementTypeCell')
            # e a tela tem MUITOS elementos ao mesmo tempo: ler um rect por
            # elemento aqui pagaria ate ~n chamadas HTTP nesta UNICA tela — o
            # mecanismo que faz o custo crescer com o numero de selecionados
            # (auditoria 2026-09-10). Para em vez de arriscar o socket hang up
            # do log de 2026-09-09; quem chama decide o salvamento parcial.
            self.stats["rects_estourou"] = self.stats.get("rects_estourou", 0) + 1
            self.parada = "leitura sem inferencia de posicao (excesso de elementos na tela)"
            raise UiChanged(
                f"a tela tem {n} elementos e a inferencia de posicao falhou — ler um "
                "rect por elemento custaria muitas chamadas nesta tela; parando em vez "
                "de arriscar o socket hang up do log de 2026-09-09")
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

    def _registrar_bloqueio_guarda(self, c) -> None:
        """GUARDA: este contato ja entrou numa lista CRIADA em rodada(s)
        anteriores (prog.usados). Nunca e tocado.

        DUAS CAUSAS POSSIVEIS, e a tela nao permite distinguir (auditoria
        2026-09-10, 4a rodada — a hipotese de separar por ordem alfabetica foi
        TESTADA e REFUTADA: um homonimo cross-lista carrega a chave alfabetica
        do original, que e sempre <= a ancora, e a deriva de retomada devolve
        gente com chave > ancora: os dois casos caem em lados OPOSTOS do que o
        criterio previa):

         (a) DERIVA DE RETOMADA / TRAVESSIA DA LISTA DE RECUPERACAO — a mesma
             pessoa reaparecendo. Ninguem perde nada: a guarda so evita a
             duplicata.
         (b) HOMONIMO CROSS-LISTA — OUTRA pessoa com o mesmo nome de alguem de
             uma lista anterior. Ela nao pode ser tocada (tocar desmarcaria a
             primeira, e nao da para distinguir as duas) e a perda e
             PERMANENTE: a proxima ancora passa por cima dela.

        Este metodo existe porque o registro estava em UM dos tres lugares que
        a guarda bloqueia (5a rodada da auditoria):
         - o laco principal registrava, mas so quando NAO era lista de
           recuperacao — e na recuperacao o log ainda chamava a perda
           permanente de "exatamente o trabalho dela";
         - a ULTIMA PASSADA (margem=0, borda inferior da agenda) so somava o
           contador e nao gravava hash nenhum — justamente onde cai o
           homonimo da ultima linha da agenda, que a leitura com margem nunca
           enxerga.
        Registrar nos tres nao enfraquece a trava (a celula continua sem ser
        tocada): so deixa rastro de uma perda que pode ser permanente.
        """
        self.stats["bloqueados_guarda"] += 1
        self.bloqueados_apos_retomada.append(c.hash)

    def _descartar_corte_ja_processado(self, cels: list) -> None:
        """Uma celula ilegivel que esta na tela ANTES do ponto de retomada ja
        foi tratada em lista(s) anterior(es): ela nao pode barrar as celulas
        que vem DEPOIS da retomada.

        Sem isto (auditoria 2026-09-10, 5a rodada) a rodada travava para
        sempre: o corte e calculado sobre a tela INTEIRA, a primeira celula
        boa devolvida por _retomar ja caia depois dele, a lista parava com 0
        confirmados (codigo 7, progresso intacto) e a rodada seguinte, sem
        nada ter mudado, fazia exatamente o mesmo. O log ainda afirmava que a
        celula ilegivel era "a proxima da fila", quando ela ja estava numa
        lista criada.

        A fronteira e a CHAVE ALFABETICA da ancora de retomada, nao "a ultima
        celula tocada/ignorada": tudo com chave <= ancora ja entrou em lista
        criada, por definicao do progresso. Usar a ultima tocada abriria um
        buraco real — entre a ancora e o primeiro toque pode haver celulas
        puladas por filtro de DDD, convite ou guarda, e uma celula ilegivel
        entre elas seria descartada em silencio.

        Comparacao com `<=` de proposito: o corte por celula SEM RECT nasce
        em `ultimo_y_ok + 0.5`, isto e, logo ABAIXO da ultima celula legivel.
        Quando essa ultima celula legivel e a propria ancora, o elemento sem
        rect esta DEPOIS dela — e esse corte fica de pe.
        """
        if self._corte_y is None or not self._chave_ancora:
            return
        # PREFIXO da tela (as celulas ja vem ordenadas por y), nunca "toda
        # celula com chave <= ancora": a agenda e alfabetica, entao os ja
        # incluidos sao um prefixo. Parar no primeiro contato NOVO garante que
        # uma celula qualquer mais abaixo — homonimo, colisao de chave — nunca
        # empurre a fronteira para depois de uma celula ilegivel de verdade.
        ys = []
        for c in cels:
            if chave_ordem(c.nome) > self._chave_ancora:
                break
            ys.append(c.y)
        if ys and self._corte_y <= max(ys):
            log.info("uma celula ilegivel apareceu ANTES do ponto de retomada "
                     "(ela ja esta em lista anterior): o corte dela nao vale "
                     "para as celulas seguintes")
            self._corte_y, self._corte_motivo = None, ""

    def _retomar(self, prog: Progresso, cels: list) -> list:
        """Leva a lista ate o ultimo contato da rodada anterior e devolve as
        celulas da tela atual que vem DEPOIS dele."""
        alvo_hash = prog.ultimo_hash
        alvo_chave = chave_ordem(prog.ultimo_rotulo)
        # fronteira do que JA ESTA em lista criada; vale ate o fim desta lista
        # (ver _descartar_corte_ja_processado)
        self._chave_ancora = alvo_chave
        log.info("retomando: procurando o ultimo contato da lista anterior (%s)",
                 mask(prog.ultimo_rotulo))
        voltou = False
        anteriores = set()
        for tela in range(MAX_TELAS_RETOMADA):
            if self._orcamento_estourou():
                self.parada = "orcamento de tempo da lista (durante a retomada)"
                # log.error explicito: `sp.parada` ja esta setado, entao main()
                # descarta o texto da excecao (`sp.parada or str(exc)`) e o
                # operador nunca lia esta orientacao. Ate 2026-09-10 (5a
                # rodada) ela ainda dizia "aumente --max-minutos OU RODE DE
                # NOVO" — e rodar de novo e exatamente o que NAO resolve:
                # nada foi tocado, o progresso nao mudou, a rodada seguinte
                # gasta o mesmo tempo e para no mesmo lugar (livelock).
                log.error("o tempo maximo desta lista (%.0f min) acabou depois de "
                          "%d tela(s) ANTES de achar o ponto de retomada: nada foi "
                          "tocado e o progresso NAO mudou. RODAR DE NOVO NAO "
                          "RESOLVE — a proxima rodada comeca no mesmo ponto e para "
                          "no mesmo lugar. Rode pelo Terminal com --max-minutos "
                          "maior (a estacao sempre manda o padrao e nao tem campo "
                          "para mudar isso).", self.max_segundos / 60,
                          self.stats["telas_retomada"])
                raise UiChanged(
                    "o tempo maximo desta lista acabou ANTES de achar o ponto de "
                    "retomada; nada foi tocado e o progresso NAO mudou. RODAR DE "
                    "NOVO NAO RESOLVE: a proxima rodada comeca no mesmo ponto, "
                    "gasta o mesmo tempo e para no mesmo lugar. Rode pelo Terminal "
                    "com --max-minutos maior (a estacao sempre manda o padrao)")
            self.stats["telas_retomada"] += 1
            if not cels:
                if self.in_picker():
                    raise UiChanged("seletor sem contatos durante a retomada")
                raise UiChanged("o seletor de contatos desapareceu durante a retomada")
            idx = next((k for k, c in enumerate(cels) if c.hash == alvo_hash), None)
            if idx is not None:
                log.info("ponto de retomada encontrado apos %d tela(s)", tela + 1)
                self.ignorar.update(c.hash for c in cels[:idx + 1])
                self._descartar_corte_ja_processado(cels)
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
                self.ignorar.update(c.hash for c in cels
                                    if chave_ordem(c.nome) <= alvo_chave)
                self._descartar_corte_ja_processado(cels)
                return [c for c in cels if chave_ordem(c.nome) > alvo_chave]
            cels = self._ler_celulas()
        raise UiChanged(
            "nao encontrei o ponto de retomada. Use --recomecar-do-A para recomecar "
            "do primeiro contato SEM duplicar quem ja esta em lista (a guarda "
            "continua valendo); --reset-progresso tambem recomeca do A mas apaga "
            "essa memoria e duplicaria todo mundo ja incluido")

    # ---------- selecao ----------

    def _tocar(self, c: Celula) -> bool:
        if c.hash in self.usados:
            # Trava DURA, independente de qualquer `continue` do laco de
            # selecao: nunca deve ser alcancavel (o laco em selecionar() ja
            # bloqueia antes de chegar aqui), mas se algum dia um caminho
            # novo chamar _tocar diretamente, falhar alto e melhor do que
            # duplicar em silencio (mesmo raciocinio de _checar_app_em_frente).
            raise UiChanged(
                "guarda de duplicata: tentativa de tocar um contato que ja "
                "entrou em lista anterior — parei antes do toque")
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

    def _tocar_lote(self, lote: list) -> tuple[list, list]:
        """--turbo: toca todas as celulas do lote com UMA requisicao W3C.

        Devolve (tocadas, falhadas). `falhadas` so tem conteudo no caminho de
        fallback (o driver recusou 'actions' e os toques foram por elemento):
        uma celula que falhou ali NAO pode ser descartada em silencio — quem
        chama a retenta como retenta qualquer falha de clique (auditoria
        2026-09-10, 3a rodada: `[c for c in lote if self._tocar(c)]` era o
        unico lugar do codigo onde uma falha de clique nao gerava retentativa,
        e o contato sumia para sempre porque o progresso passava por cima dele).

        As coordenadas sao as lidas nesta mesma tela, segundos antes. Depois
        da rajada confere, com uma busca pontual, que o seletor continua na
        tela (o botao Criar existe) — SO ENTAO registra os toques: self.ordem
        e um limite inferior conservador, nunca um otimista (auditoria
        2026-09-10: registrar antes de confirmar deixava contatos "tocados"
        que na verdade nao entraram, se um dialogo tivesse engolido a rajada).

        Se a requisicao falhar (WebDriverException), NUNCA re-toca o lote as
        cegas — tocar de novo DESMARCA quem ja tinha entrado. Distingue dois
        casos: (1) a 1a rajada desta lista falhou — nenhum toque anterior
        provou que o driver aceita 'actions', entao e seguro cair no toque
        por elemento (como sempre foi); (2) uma rajada anterior JA teve
        sucesso — o driver aceita o comando, entao isto e uma requisicao que
        morreu NO MEIO (o cenario real do log de 2026-09-09: socket hang up
        depois de parte dos toques). Sem um contador de selecionados
        confirmado no aparelho (NAO CONFIRMADO — ver auditoria) nao ha como
        saber quantos dos toques desta rajada surtiram efeito: para aqui,
        sem registrar nada deste lote e sem tocar em mais nada, e devolve o
        controle para o salvamento parcial com o que ja estava confirmado
        ANTES desta rajada."""
        if not lote:
            return [], []
        repetidos = [c for c in lote if c.hash in self.usados]
        if repetidos:
            # Mesma trava de _tocar, para o lote inteiro: nunca deveria ser
            # alcancavel (o laco de selecao ja filtra antes de montar o lote),
            # mas falhar alto aqui e melhor do que arriscar tocar de novo em
            # alguem que ja esta numa lista anterior (o que o DESMARCARIA).
            raise UiChanged(
                f"guarda de duplicata: {len(repetidos)} contato(s) do lote ja "
                "entraram em lista anterior — parei antes de tocar")
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
            if not self._turbo_confirmado:
                log.warning("turbo: o driver recusou a 1a rajada de toques (%s); "
                            "voltando ao toque por elemento",
                            str(exc).splitlines()[0][:100])
                self.turbo = False
                # Devolve QUEM foi tocado, nao quantos: um clique pode falhar
                # no meio do lote ("element is not hittable"), e ai os N
                # primeiros do lote NAO sao os N tocados.
                #
                # E PARA no primeiro que falhar, sem tentar os seguintes: assim
                # tudo o que foi tocado esta ANTES do ponto que falhou, e o
                # ponto de retomada gravado (ultimo tocado) nunca ultrapassa a
                # celula que ficou de fora. Quem chama retenta essa celula.
                tocadas, falhadas = [], []
                for c in lote:
                    if self._tocar(c):
                        tocadas.append(c)
                    else:
                        falhadas.append(c)
                        break
                return tocadas, falhadas
            self.parada = "rajada interrompida"
            self.incerteza = [c.hash for c in lote]
            log.error("turbo: a rajada morreu no meio (%s) — %d contato(s) desta "
                      "rajada ficam em duvida (nem registrados, nem re-tocados); "
                      "%d ja confirmado(s) antes dela seguem validos",
                      str(exc).splitlines()[0][:100], len(lote), len(self.ordem))
            raise UiChanged(
                f"rajada de toques interrompida no meio ({str(exc).splitlines()[0][:100]}); "
                "nao re-toco o lote (re-tocar desmarcaria quem ja entrou) — a lista "
                "sera salva so com o que estava confirmado antes desta rajada") from exc
        self._turbo_confirmado = True
        # O seletor precisa continuar aqui. Um dialogo por cima (contato
        # bloqueado, aviso do sistema) teria engolido parte da rajada.
        self._ancora_confirmada = False
        if not self._confirmar_ancora_apos_rajada():
            # A RAJADA FOI ENVIADA COM SUCESSO: os toques podem perfeitamente
            # ter surtido efeito no aparelho e so a CONFERENCIA ter falhado
            # (neste iPhone uma consulta ja levou 33.640 ms). Este ramo nao
            # pode dizer que "a lista nao foi criada" nem seguir sem registrar
            # a duvida: quem so registra o confirmado grava um progresso MENOR
            # do que a lista que o aparelho tem, e a rodada seguinte repete
            # essas pessoas (auditoria 2026-09-10, 3a rodada).
            self.parada = ("ancora nao confirmada apos rajada turbo "
                           "(os toques podem ter surtido efeito no aparelho)")
            self.incerteza = [c.hash for c in lote]
            log.error("turbo: a rajada saiu, mas o botao Criar nao reapareceu nas "
                      "duas conferencias seguintes — %d contato(s) desta rajada "
                      "ficam EM DUVIDA (podem estar marcados no iPhone sem estarem "
                      "no progresso); %d ja confirmado(s) antes dela seguem validos",
                      len(lote), len(self.ordem))
            raise UiChanged(
                "o botao Criar do seletor nao reapareceu depois da rajada de toques "
                "(turbo). Nao da para confirmar quantos contatos entraram: confira "
                "no iPhone antes da proxima rodada.")
        # SO AQUI a ancora e uma prova valida para esta tela (ver
        # _checar_seguranca): a busca acabou de acontecer, depois dos toques.
        self._ancora_confirmada = True
        for c in lote:
            self._registrar_toque(c)
        return list(lote), []

    def _confirmar_ancora_apos_rajada(self) -> bool:
        """O botao Criar continua na tela depois da rajada?

        UMA consulta de 2s nao prova que o seletor sumiu: no log de 2026-09-09
        uma consulta a este mesmo WDA levou 33.640 ms com o seletor INTACTO.
        Tratar esse pico como "o seletor sumiu" (era o que este codigo fazia
        ate 2026-09-10) criava o pior desfecho possivel: a lista era criada
        pelo main() logo depois — quando o pico ja tinha passado — com MAIS
        contatos do que o progresso registrava, e a rodada seguinte repetia
        essas pessoas. Mesmo criterio da valvula de leitura: uma leitura lenta
        e suspeita de WDA, nao evidencia de UI trocada. Por isso: 2 tentativas,
        a segunda mais generosa, com uma pausa no meio."""
        for tentativa, espera in enumerate((2, 6), start=1):
            t0 = time.monotonic()
            achou = self.wait_for("picker_anchor", timeout=espera, required=False)
            dur = time.monotonic() - t0
            if achou is not None:
                if tentativa > 1:
                    log.warning("o botao Criar so reapareceu na 2a conferencia "
                                "(%.1fs): pico do WDA, nao troca de tela", dur)
                return True
            log.warning("conferencia %d apos a rajada: botao Criar nao encontrado "
                        "em %.1fs", tentativa, dur)
            self.settle(0.5)
        return False

    def _descarregar_lote(self, lote: list, tocados_tela: dict) -> tuple[int, list, bool, list]:
        """Envia o lote acumulado (rajada turbo) e devolve
        (novos, [], ancora_confirmada, falhadas).
        Lotes menores (MAX_LOTE_TURBO) == janela menor em que as coordenadas
        lidas podem ficar desatualizadas (faixa de chips mudando de altura).

        O 3o item e a resposta a UMA pergunta: esta rajada chegou a PROVAR,
        depois dos toques, que o seletor continua na tela? So um envio W3C
        bem-sucedido prova isso. Quando o driver recusa o comando e caimos no
        toque por elemento, NADA foi provado — e a checagem de fim de tela
        (_checar_seguranca) precisa fazer a busca da ancora normalmente.
        Antes (auditoria 2026-09-10, 2a rodada) esta funcao dizia "confirmada"
        tambem no caminho do fallback: a tela inteira ficava sem a trava."""
        if not lote:
            return 0, [], False, []
        self._ancora_confirmada = False
        tocados, falhadas = self._tocar_lote(lote)
        for c in tocados:
            tocados_tela[c.hash] = c.y
        return len(tocados), [], self._ancora_confirmada, falhadas

    def _checar_app_em_frente(self) -> None:
        """Trava DURA e INCONDICIONAL: o WhatsApp continua em primeiro plano?

        Mora numa funcao propria de proposito. Enquanto isto era a primeira
        metade de `_checar_seguranca`, a trava so sobrevivia pela ORDEM de duas
        linhas: mover o `if ancora_ja_confirmada: return` para cima (a
        refatoracao mais natural do mundo) deixava a estacao tocar dezenas de
        vezes com outro app na frente, e os 54 testes continuavam verdes
        (auditoria 2026-09-10, 3a rodada)."""
        if not self._whatsapp_in_front():
            raise UiChanged("um app externo abriu durante a selecao (celula 'Convidar'?) "
                            "— parei sem tocar em mais nada; volte ao WhatsApp e rode de novo")

    def _checar_ancora(self, ancora_ja_confirmada: bool = False) -> None:
        """O seletor continua na tela? (checagem PULAVEL — e so a economia de
        uma busca repetida, nunca a trava de app em primeiro plano.)

        `ancora_ja_confirmada=True`: uma rajada turbo desta MESMA tela ja
        provou, segundos antes, que o seletor continua aqui (_tocar_lote
        confirma antes de registrar); repetir a busca seria a 2a consulta
        identica por tela (auditoria 2026-09-10)."""
        if ancora_ja_confirmada:
            return
        # No seletor, a prova mais forte e mais barata de que nada estranho
        # apareceu e o proprio botao Criar continuar na tela (1 busca pontual).
        # Um compositor de mensagem so existe FORA do seletor — se o seletor
        # sumiu, paramos antes de qualquer toque, que e o que a trava garante.
        if self.wait_for("picker_anchor", timeout=2, required=False) is None:
            raise UiChanged("o seletor de contatos sumiu (dialogo por cima ou tela "
                            "trocada) — parei sem tocar em mais nada; feche o que "
                            "estiver na tela e rode de novo")

    def _checar_seguranca(self, forcar: bool = True, ancora_ja_confirmada: bool = False) -> None:
        """As duas checagens, nesta ordem, SEMPRE: app em primeiro plano
        (incondicional) e depois seletor na tela (pulavel). Chamada nos
        momentos que valem: fim de cada tela, toque que falhou, fim da lista.
        `forcar` continua no lugar so por compatibilidade de chamada."""
        self._checar_app_em_frente()
        self._checar_ancora(ancora_ja_confirmada)

    def _retentar_falhas(self, falhadas: list, falhas: dict) -> list:
        """Trata falha(s) de clique: conta a falha, confere seguranca e rele a
        tela para reprocessar do inicio. Vale tanto para o toque por elemento
        quanto para o fallback da rajada turbo — que ate 2026-09-10 descartava
        a celula sem nenhuma retentativa.

        Nunca re-toca quem ja teve sucesso: o laco pula quem esta em
        self.tocados, e tocar de novo DESMARCARIA o contato."""
        for c in falhadas:
            falhas[c.hash] = falhas.get(c.hash, 0) + 1
            log.debug("falha de toque em %s (%da nesta tela)", mask(c.nome),
                      falhas[c.hash])
        self._checar_seguranca()      # clique falhou: momento critico
        return self._ler_celulas()

    def selecionar(self, prog: Progresso) -> int:
        """Seleciona ate self.limite contatos a partir do ponto de retomada.
        Devolve quantos foram tocados."""
        self._t_inicio_lista = time.monotonic()   # cobre TAMBEM a retomada (ver _retomar)
        self.transition(State.SELECTING)
        self.tocados, self.ignorar, self.ordem, self.results = set(), set(), [], []
        # REFERENCIA, nao copia: se esta rodada criar varias listas, a lista
        # K+1 ja enxerga os hashes que registrar_lista() acabou de acrescentar
        # a prog.usados ao registrar a lista K. Esta classe nunca escreve
        # neste conjunto (so o le) — ver _tocar/_tocar_lote para a trava dura.
        self.usados = prog.usados
        # Ver o atributo em __init__: define se um hit na guarda dentro do laco
        # principal e re-observacao esperada (recuperacao) ou homonimo.
        self.em_recuperacao = bool(prog.usados) and not prog.ultimo_hash
        convites_vistos = set()
        self.bloqueados_apos_retomada = []
        self._chave_ancora = ""   # so _retomar define; lista do A nao tem fronteira
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
        for tela in range(self.max_telas):
            if self._orcamento_estourou():
                self.parada = "orcamento de tempo da lista"
                if self.ordem:
                    log.warning("o tempo maximo desta lista (%.0f min) acabou depois "
                                "de %d tela(s) sem terminar a lista nem esgotar a "
                                "agenda — parando com %d contato(s) confirmado(s); a "
                                "proxima rodada continua do seguinte",
                                self.max_segundos / 60, self.stats["telas"],
                                len(self.ordem))
                else:
                    # Sem NENHUM toque nao existe "seguinte": o ponto de retomada
                    # nao mudou e a proxima rodada, identica, faz o mesmo. Dizer
                    # "continua do seguinte" aqui mandava o operador esperar um
                    # avanco que nao aconteceu (auditoria 2026-09-10, 4a rodada).
                    log.warning("o tempo maximo desta lista (%.0f min) acabou depois "
                                "de %d tela(s) SEM tocar em ninguem: o progresso NAO "
                                "avancou e a proxima rodada vai comecar exatamente no "
                                "mesmo ponto. Suba o tempo maximo por lista, ou use "
                                "--reset-progresso se aceitar recomecar do zero.",
                                self.max_segundos / 60, self.stats["telas"])
                break
            self.stats["telas"] += 1
            novos = 0
            tocados_tela = {}       # hash -> y da celula tocada NESTA tela
            falhas = {}
            lote: list = []         # turbo: celulas desta tela para a rajada
            # A ULTIMA rajada desta tela chegou a provar (depois dos toques) que
            # o seletor continua aqui? So entao a checagem de fim de tela pode
            # pular a busca da ancora. Toque por elemento nao prova nada.
            ancora_provada = False
            i = 0
            while len(self.ordem) + len(lote) < self.limite:
                if i >= len(cels):
                    # fim das celulas desta tela: descarrega o que sobrou no lote
                    # AQUI DENTRO, para que uma falha de clique no fallback da
                    # rajada ainda possa ser retentada nesta mesma tela (antes
                    # esse descarregamento so acontecia depois do laco, e a
                    # celula que falhou ficava para tras — ver _tocar_lote).
                    if not lote:
                        break
                    feitos, lote, confirmou, falhadas = self._descarregar_lote(
                        lote, tocados_tela)
                    novos += feitos
                    ancora_provada = confirmou
                    if falhadas:
                        cels = self._retentar_falhas(falhadas, falhas)
                        i = 0
                        continue
                    break
                c = cels[i]
                i += 1
                if c.hash in self.ignorar:
                    continue                     # antes do ponto de retomada
                if self._corte_y is not None and c.y >= self._corte_y:
                    if self.pular_sem_rotulo:
                        self.stats["sem_rotulo_pulado"] = self.stats.get(
                            "sem_rotulo_pulado", 0) + 1
                        self.pulados.append(len(self.ordem))   # posicao na fila,
                                                                # NUNCA nome/hash
                        log.warning("--pular-celula-ilegivel: pulando uma celula "
                                    "que nao devolve nome/posicao, por decisao do "
                                    "operador. Essa pessoa NAO entra em lista "
                                    "nenhuma nesta rodada nem nas seguintes.")
                        self._corte_y = None      # segue a tela; a proxima leitura recalcula
                        # SEM continue: a celula ilegivel nunca entrou em `cels`
                        # (nao existe Celula para ela) — a celula ATUAL (c) e
                        # uma celula BOA que so caiu depois do corte por
                        # posicao; ela segue para as checagens seguintes.
                    else:
                        self.parada = self._corte_motivo or PARADA_SEM_ROTULO
                        log.error("uma celula com a altura de uma linha de contato "
                                  "voltou SEM ROTULO OU SEM POSICAO em duas leituras. "
                                  "Nao da para saber quem e — e tocar nas seguintes "
                                  "deixaria essa pessoa atras do ponto de retomada, "
                                  "fora de qualquer lista. PARANDO com %d confirmado(s); "
                                  "ela e a proxima da fila na rodada seguinte. Se a "
                                  "rodada seguinte parar no MESMO ponto (mesmo "
                                  "'proximo_contato_n' no progresso), nao e lentidao: "
                                  "e essa linha da agenda que nunca devolve nome — "
                                  "veja --pular-celula-ilegivel.", len(self.ordem))
                        self._logar_filtrados()
                        return len(self.ordem)
                if c.hash in self.usados:
                    self._registrar_bloqueio_guarda(c)
                    continue
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
                        # Perda PERMANENTE (nao so desta tela): este contato
                        # tem o MESMO NOME de alguem ja tocado e nao entra em
                        # lista nenhuma, nesta rodada nem nas seguintes (a
                        # retomada o considera "ja passado"). So rastreado —
                        # nunca deixado de fora em silencio (ver main()).
                        self.homonimos.append(c.hash)
                    continue
                if falhas.get(c.hash, 0) >= 2:
                    # DIVIDA (B), fechada em 2026-09-10 (3a rodada): aqui havia
                    # um `continue`. Era o unico caminho de "pular contato em
                    # silencio" que restava — a celula saia da lista, os
                    # contatos SEGUINTES eram tocados, e o ponto de retomada
                    # gravado (ultimo tocado) passava por cima dela: nenhuma
                    # rodada futura chegava perto desse contato.
                    #
                    # Agora e uma parada nomeada, ANTES de tocar em qualquer
                    # celula posterior desta tela. O salvamento parcial de
                    # main() cria a lista com o que foi confirmado ate aqui e
                    # grava como ponto de retomada o ULTIMO TOCADO — que, por
                    # construcao, e alfabeticamente ANTERIOR a esta celula.
                    # Na proxima lista o seletor e reaberto do zero (outra
                    # renderizacao, outra faixa de chips) e este contato e
                    # reencontrado naturalmente. Nao ha retrocesso do ancora
                    # de retomada (que duplicaria gente ja incluida em lista
                    # anterior): so parada mais cedo.
                    self.stats["travados"] += 1
                    self.parada = "contato inalcancavel (2 falhas de toque na mesma tela)"
                    log.error("o contato %s falhou 2x nesta tela (nao alcancavel: "
                              "sob a faixa de chips? 'element is not hittable'?). "
                              "PARANDO aqui em vez de pula-lo em silencio — ele "
                              "continua sendo o proximo da fila na rodada seguinte.",
                              mask(c.nome))
                    raise UiChanged(
                        "um contato nao pode ser tocado nesta tela depois de 2 "
                        "tentativas; parei antes de tocar nos seguintes para nao "
                        "deixa-lo para tras (ele e o proximo da proxima lista)")
                # Convite decidido pelo rotulo ja lido: zero chamadas ao WDA.
                # (Antes: _is_invite_cell fazia 3-4 chamadas POR CELULA.)
                if eh_convite(c.nome):
                    if c.hash not in convites_vistos:
                        convites_vistos.add(c.hash)
                        self.stats["convites"] += 1
                    continue
                primeiro_toque = not self.ordem
                if self.turbo and not primeiro_toque:
                    lote.append(c)               # junta; toca em lotes pequenos (MAX_LOTE_TURBO)
                    if len(lote) >= MAX_LOTE_TURBO:
                        feitos, lote, confirmou, falhadas = self._descarregar_lote(
                            lote, tocados_tela)
                        novos += feitos
                        ancora_provada = confirmou
                        if falhadas:
                            cels = self._retentar_falhas(falhadas, falhas)
                            i = 0
                    continue
                y_antes = c.y
                if not self._tocar(c):
                    # elemento saiu do lugar: confere seguranca, rele a tela e refaz
                    cels = self._retentar_falhas([c], falhas)
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
                # So chega aqui quando o laco parou pelo LIMITE da lista. Uma
                # falha de clique no fallback aqui nao deixa ninguem para tras:
                # o fallback para no primeiro que falha, entao tudo o que foi
                # tocado e alfabeticamente ANTERIOR a ele, e o ponto de retomada
                # gravado tambem — a proxima lista o reencontra.
                feitos, lote, confirmou, falhadas = self._descarregar_lote(lote, tocados_tela)
                novos += feitos
                ancora_provada = confirmou
                if falhadas:
                    log.warning("%d contato(s) do ultimo lote nao foram tocados "
                                "(clique falhou com a lista ja no limite); eles "
                                "continuam na fila da proxima lista", len(falhadas))
            # Checagem de seguranca no fim de cada tela: app em primeiro plano
            # (sempre) + seletor na tela. Se uma rajada desta tela ja confirmou
            # o picker_anchor, so a busca da ancora e dispensada.
            self._checar_seguranca(ancora_ja_confirmada=ancora_provada)
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
                        if c.hash in self.ignorar or c.hash in self.tocados or c.hash in self.usados:
                            if (c.hash in self.usados and c.hash not in self.ignorar
                                    and c.hash not in self.tocados):
                                # mesmo registro do laco principal: aqui e a
                                # ULTIMA linha da agenda, o unico lugar onde um
                                # homonimo cross-lista pode ser bloqueado sem
                                # que o laco principal chegue a ve-lo.
                                self._registrar_bloqueio_guarda(c)
                            continue
                        if self._corte_y is not None and c.y >= self._corte_y:
                            if self.pular_sem_rotulo:
                                self.stats["sem_rotulo_pulado"] = self.stats.get(
                                    "sem_rotulo_pulado", 0) + 1
                                self.pulados.append(len(self.ordem))
                                log.warning("--pular-celula-ilegivel: pulando uma "
                                            "celula que nao devolve nome/posicao "
                                            "na ultima passada.")
                                self._corte_y = None
                                # SEM continue (ver o mesmo raciocinio no laco
                                # principal): a celula ATUAL e boa.
                            else:
                                self.parada = self._corte_motivo or PARADA_SEM_ROTULO
                                log.error("uma celula ilegivel (sem rotulo/posicao) na "
                                          "ultima passada; parando com %d confirmado(s) "
                                          "para nao deixa-la para tras", len(self.ordem))
                                self._logar_filtrados()
                                return len(self.ordem)
                        if self.permitidos is not None and c.hash not in self.permitidos:
                            continue
                        if eh_convite(c.nome):
                            continue
                        if not self._tocar(c):
                            # Mesma regra da divida (B): parar em vez de seguir
                            # tocando nos POSTERIORES, senao o ponto de retomada
                            # gravado passa por cima deste contato e ele nunca
                            # mais volta. Aqui e a ultima passada da agenda, mas
                            # o raciocinio e identico.
                            self.stats["travados"] += 1
                            self.parada = ("contato inalcancavel na ultima passada "
                                           "(borda inferior da agenda)")
                            log.error("o contato %s nao pode ser tocado na ultima "
                                      "passada; parando com %d confirmado(s) para "
                                      "nao deixa-lo para tras", mask(c.nome),
                                      len(self.ordem))
                            self._logar_filtrados()
                            return len(self.ordem)
                    self._checar_seguranca()   # fim da lista: critico
                    log.info("fim da lista de contatos (a agenda esgotou de verdade)")
                    break
            else:
                sem_avanco = 0
            anteriores = hashes
            self._rolar_uma_tela(cels)
            cels = self._ler_celulas()
            if not cels:
                dur = self._duracoes_leitura[-1] if self._duracoes_leitura else 0.0
                # ORDEM (auditoria 2026-09-10, 3a rodada): quem decide primeiro e
                # o RELOGIO, nao o in_picker(). No log de 2026-09-09 a leitura
                # voltou vazia em 33,6s e a chamada seguinte morreu com socket
                # hang up: nesse estado o in_picker() engole WebDriverException
                # camada por camada, devolve False e o operador lia "o seletor
                # sumiu" quando o que caiu foi o WDA — com N contatos ainda
                # marcados no iPhone. Uma consulta LENTA nao e evidencia sobre a
                # UI; e evidencia sobre o WDA, e ai a resposta certa e parar com
                # salvamento parcial, sem gastar mais nenhuma chamada.
                if dur >= LEITURA_LENTA_S:
                    self.parada = "leitura vazia lenta (nao e fim de agenda)"
                    log.error("leitura vazia apos consulta de %.1fs ao WDA: tratando "
                              "como falha de leitura, NAO como fim de agenda nem como "
                              "seletor sumido — parando com %d confirmado(s)",
                              dur, len(self.ordem))
                    self._logar_filtrados()
                    return len(self.ordem)
                estado = self.in_picker_status()
                if estado != "sim":
                    raise UiChanged(self._msg_sem_seletor(estado))
                # Vazio LENTO nao e "fim de agenda": e o sintoma exato do log de
                # 2026-09-09 (33.6s, vazio, seguido de socket hang up).
                if LEITURA_RAPIDA_S <= dur < LEITURA_LENTA_S:
                    # ambiguo: pode ter sido so um pico passageiro do WDA — uma
                    # unica retentativa barata antes de desconfiar de verdade.
                    log.warning("leitura vazia lenta (%.1fs) — retentando uma vez "
                                "antes de decidir se e fim de agenda ou falha de "
                                "leitura", dur)
                    self.settle(1.0)
                    cels = self._ler_celulas()
                    dur = self._duracoes_leitura[-1] if self._duracoes_leitura else dur
                # (A conferencia de profundidade nao mora mais aqui: ela roda
                # dentro da propria leitura — ver _ler_celulas_impl. Aqui ela
                # chegava tarde demais, depois de uma rolagem as cegas.)
                if not cels:
                    if dur >= LEITURA_LENTA_S:
                        self.parada = "leitura vazia lenta (nao e fim de agenda)"
                        log.error("a retentativa tambem voltou vazia apos uma consulta "
                                  "de %.1fs: falha de leitura, NAO fim de agenda — "
                                  "parando com %d confirmado(s)", dur, len(self.ordem))
                        self._logar_filtrados()
                        return len(self.ordem)
                    estado = self.in_picker_status()
                    if estado != "sim":
                        raise UiChanged(self._msg_sem_seletor(estado))
                    if dur < LEITURA_RAPIDA_S:
                        log.info("fim da lista de contatos (tela vazia, leitura "
                                 "rapida — %.2fs)", dur)
                        break
                    self.parada = "leitura vazia lenta (nao e fim de agenda)"
                    log.error("leitura vazia lenta persistiu (%.1fs): tratando como "
                              "falha de leitura, NAO como fim de agenda — parando "
                              "com %d confirmado(s)", dur, len(self.ordem))
                    self._logar_filtrados()
                    return len(self.ordem)
        else:
            self.parada = "teto de telas"
            log.warning("teto de telas atingido (%d telas) sem terminar a lista nem "
                        "esgotar a agenda (filtro de DDD muito restritivo?) — "
                        "parando com %d contato(s) confirmado(s)",
                        self.max_telas, len(self.ordem))
        self._logar_filtrados()
        return len(self.ordem)

    @staticmethod
    def _msg_sem_seletor(estado: str) -> str:
        """Diagnostico honesto: 'o seletor sumiu' e uma afirmacao sobre a TELA,
        e so pode ser feita quando o WDA respondeu. Quando TODAS as consultas
        levantaram excecao (sessao caida, socket hang up), o que aconteceu foi
        outra coisa — e o operador precisa ler outra coisa."""
        if estado == "sem_resposta":
            return ("o WDA nao respondeu a nenhuma consulta (sessao caida / socket "
                    "hang up?) durante a rolagem — nao da para afirmar o que esta na "
                    "tela do iPhone; confira o aparelho antes da proxima rodada")
        return "o seletor de contatos desapareceu durante a rolagem"

    def _logar_filtrados(self) -> None:
        """stats['filtrados'] era coletado e nunca impresso. Vale para TODOS
        os desfechos, inclusive os que saem pelo meio do laco."""
        if self.stats.get("filtrados"):
            log.info("filtro de DDD: %d contato(s) descartado(s) por nao casarem "
                     "nesta lista (telas percorridas: %d)",
                     self.stats["filtrados"], self.stats["telas"])
        if self.stats.get("bloqueados_guarda"):
            if self.em_recuperacao:
                # NUNCA afirmar "era exatamente o trabalho dela": a travessia
                # da lista de recuperacao e a causa da MAIORIA desses
                # bloqueios, mas a tela nao permite provar que e a causa de
                # TODOS. Um homonimo cross-lista (outra pessoa com o mesmo
                # nome) cai neste mesmo contador e a perda dele e permanente.
                # Ate 2026-09-10 (5a rodada) esta linha saia em INFO
                # anunciando trabalho esperado.
                log.warning("guarda: %d celula(s) ja em lista anterior foram "
                            "atravessadas sem toque nesta lista de recuperacao. A "
                            "maior parte e a travessia esperada (as MESMAS pessoas, "
                            "nada perdido), mas a tela nao distingue delas um "
                            "homonimo — outra pessoa com o mesmo nome de alguem ja "
                            "incluido, que nao entra em lista nenhuma. Os codigos "
                            "ficam no progresso, em bloqueados_apos_retomada.",
                            self.stats["bloqueados_guarda"])
            else:
                log.warning("guarda: %d celula(s) nao foram tocadas porque o contato "
                            "ja entrou numa lista anterior (ninguem foi duplicado)",
                            self.stats["bloqueados_guarda"])
        if self.bloqueados_apos_retomada and not self.em_recuperacao:
            # Na lista de RECUPERACAO o aviso acima ja nomeia as duas causas
            # com os mesmos numeros; repetir aqui so trocaria o vocabulario
            # ("depois da retomada" numa lista que nao tem retomada).
            # Duas causas, e a tela nao distingue (ver selecionar). Nomear as
            # duas e o unico jeito honesto: dizer so "deriva de retomada"
            # mandava o operador para o problema errado quando a causa era a
            # segunda, e a segunda e uma PERDA.
            # ATENCAO ao texto: a GUI casa frases por SUBSTRING (gui_state.
            # etapa_humana). Escrever "ponto de retomada" aqui fazia a tela
            # exibir "Ponto de retomada encontrado." — uma frase de sucesso —
            # em cima de um aviso de possivel PERDA. Por isso "depois da
            # retomada", nunca "depois do ponto de retomada".
            log.warning("%d celula(s) apareceram depois da retomada com o "
                        "contato ja em lista anterior. Ou a retomada parou cedo e a "
                        "tela reofereceu as MESMAS pessoas (nada perdido), ou sao "
                        "pessoas DIFERENTES com o mesmo nome de alguem ja incluido "
                        "— e essas nao entram em lista nenhuma, nesta rodada nem "
                        "nas seguintes. Nao da para distinguir pela tela: se faltar "
                        "gente no fim da agenda, e por aqui que se procura (os "
                        "codigos ficam no progresso, em bloqueados_apos_retomada).",
                        len(set(self.bloqueados_apos_retomada)))
        if self.homonimos:
            log.warning("%d contato(s) com o MESMO NOME de alguem que ja entrou "
                        "nesta lista ou numa lista anterior nao foram tocados "
                        "(tocar de novo DESMARCARIA o primeiro, e nao ha como "
                        "distinguir os dois pela tela). Eles nao entram em lista "
                        "nenhuma desta rodada nem das seguintes — se a agenda tem "
                        "nomes repetidos de verdade, esses precisam ser adicionados "
                        "a mao.", len(set(self.homonimos)))

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


def _avisar_incertos_pendentes(prog: Progresso) -> None:
    """Toques em duvida (rajada turbo nao confirmada) que ainda nao foram
    resolvidos pelo operador: aviso repetido a CADA rodada ate serem
    resolvidos — uma decisao humana que nao pode se perder entre rodadas."""
    pendentes = prog.incertos_pendentes()
    if not pendentes:
        return
    for _, entrada in pendentes:
        n = len(entrada.get("toques_incertos") or [])
        lista = entrada.get("lista", "?")
        log.warning(
            "%d toque(s) em duvida na lista %s ainda nao resolvidos: esses "
            "contatos podem estar na lista %s do iPhone SEM estarem no "
            "progresso; eles NAO estao bloqueados, entao podem entrar de novo "
            "na proxima lista. Confira o numero de destinatarios da lista %s "
            "no iPhone e rode --resolver-incertos entraram (bloqueia: nunca "
            "mais tocados) ou --resolver-incertos nao-entraram (mantem na "
            "fila)", n, lista, lista, lista)


def construir_parser() -> argparse.ArgumentParser:
    """O parser vive numa funcao propria para que o TESTE possa perguntar a ele
    o default de verdade de cada opcao (parser.get_default(...)), em vez de
    comparar duas constantes que podem nao ser lidas por codigo nenhum — que
    foi exatamente o caso de ORCAMENTO_PADRAO_S ate 2026-09-10 (4a rodada):
    trocar `--max-minutos` de 60 para 5 ou 999 deixava as 10 suites verdes."""
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
                    help="APAGA TUDO, inclusive a memoria de quem ja entrou em lista "
                         "(a guarda): a proxima lista recomeca do primeiro contato E "
                         "duplicaria todo mundo ja incluido. Normalmente voce quer "
                         "--recomecar-do-A, nao isto")
    ap.add_argument("--recomecar-do-A", action="store_true",
                    help="a proxima lista recomeca do primeiro contato (A) sem tentar "
                         "retomada posicional, MAS preserva a guarda: ninguem que ja "
                         "esta numa lista anterior e re-tocado. Use quando a retomada "
                         "normal nao encontra o ponto (ver a mensagem de erro)")
    ap.add_argument("--resolver-incertos", choices=("entraram", "nao-entraram"), default="",
                    help="resolve toque(s) em duvida (rajada turbo nao confirmada): "
                         "'entraram' bloqueia esses hashes na guarda (nunca mais "
                         "tocados); 'nao-entraram' descarta a duvida e os deixa na "
                         "fila. Confira o numero de destinatarios no iPhone antes "
                         "de decidir")
    ap.add_argument("--lista", type=int, default=0,
                    help="com --resolver-incertos: resolve so esta lista (numero do "
                         "historico); sem isto, resolve todas as pendentes")
    ap.add_argument("--ddd", default="",
                    help="incluir so estes DDDs (ex.: 21,22). Exige --agenda: a tela "
                         "nao mostra o numero de contato salvo, o DDD vem da agenda")
    ap.add_argument("--agenda", default="",
                    help="VCF ou CSV exportado da agenda, usado so para o filtro de DDD")
    ap.add_argument("--region", default="BR")
    ap.add_argument("--turbo", action="store_true",
                    help="toca todas as celulas de cada tela numa unica requisicao "
                         "(rajada W3C). Ligue SO depois do teste de 5 contatos passar")
    ap.add_argument("--max-minutos", type=float, default=ORCAMENTO_PADRAO_S / 60,
                    help="tempo maximo de UMA lista, em minutos (0 = sem limite). "
                         "Estourou: para com salvamento parcial, igual ao teto de "
                         f"telas (padrao {ORCAMENTO_PADRAO_S / 60:.0f})")
    ap.add_argument("--pular-celula-ilegivel", action="store_true",
                    help="PULA (em vez de parar) uma celula que nao devolve nome nem "
                         "posicao legivel. Ela NAO entra em lista nenhuma e fica "
                         "registrada no progresso. Use so quando a rodada travar "
                         "duas vezes no mesmo ponto")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


def _gravar_avisos_no_historico(prog: Progresso, sp) -> None:
    """Grava na ULTIMA entrada do historico os avisos que dizem quem pode ter
    ficado de fora desta lista.

    Existe como funcao unica porque o bloco estava DUPLICADO entre o ramo de
    lista completa e o de lista parcial, e so o da completa tinha teste:
    apagar o do ramo parcial deixava a suite inteira verde e o unico rastro de
    uma perda permanente (homonimo cross-lista, bloqueio da guarda, celula
    pulada) sumia do progresso — justamente no desfecho mais comum das duas
    paradas novas (auditoria 2026-09-10, 5a rodada).
    """
    ent = prog.historico[-1]
    if sp.homonimos:
        ent["homonimos_ignorados"] = list(dict.fromkeys(sp.homonimos))
        ent["homonimos_aviso"] = (
            "contato(s) com o mesmo nome de alguem ja tocado nao entraram em "
            "lista nenhuma (perda permanente)")
    if sp.bloqueados_apos_retomada:
        ent["bloqueados_apos_retomada"] = list(
            dict.fromkeys(sp.bloqueados_apos_retomada))
        ent["bloqueados_apos_retomada_aviso"] = (
            "celulas ja em lista anterior que a guarda bloqueou: ou a retomada "
            "parou cedo / a lista de recuperacao estava atravessando quem ja "
            "entrou (nada perdido), ou sao pessoas diferentes com o mesmo nome "
            "de alguem ja incluido (essas nao entram em lista nenhuma)")
    if sp.pulados:
        ent["celulas_sem_rotulo_puladas"] = list(sp.pulados)
        # "ate": este numero conta OBSERVACOES de celula ilegivel, nao pessoas.
        # A mesma celula reaparece na sobreposicao de 3 celulas entre telas e
        # e contada de novo; e uma celula ilegivel antes do ponto de retomada
        # pode ser alguem que JA ESTA numa lista criada. Afirmar "N pessoas
        # nao entraram em lista nenhuma" e um numero que o codigo nao sustenta
        # (auditoria 2026-09-10, 5a rodada).
        ent["aviso"] = (
            f"ate {len(sp.pulados)} pessoa(s) nao entraram em lista nenhuma: a "
            "celula nao devolvia nome/posicao e o operador autorizou pular. "
            "Pode ser menos (a mesma celula e reobservada entre telas, e uma "
            "celula ja incluida em lista anterior tambem entra nesta conta)")
    prog.salvar()


def main() -> int:
    signal.signal(signal.SIGTERM, _encerrar_com_seguranca)
    args = construir_parser().parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")

    prog = Progresso(args.progress_file)
    if args.reset_progresso:
        if os.path.exists(args.progress_file):
            os.remove(args.progress_file)
        print("progresso apagado: a proxima lista comeca do primeiro contato.")
        return 0
    if args.recomecar_do_A:
        # A pergunta certa nao e "a guarda esta VAZIA?", e "a guarda cobre TODAS
        # as listas ja criadas?". Ate 2026-09-10 (4a rodada) era a primeira:
        # num progresso v1 com 1 lista antiga, bastava criar UMA lista nova
        # (que grava hashes) para `usados` deixar de estar vazio e a trava
        # liberar — e a lista seguinte comecava no A e re-tocava, inteira, a
        # lista antiga que a guarda nao conhece.
        faltando = prog.guarda_incompleta()
        if faltando:
            log.error("a guarda nao sabe QUEM entrou em %d de %d lista(s) ja "
                      "criada(s) (arquivo de versao 1, ou entradas de historico "
                      "sem a impressao digital dos contatos): recomecar do A "
                      "re-tocaria exatamente essas pessoas, que entrariam numa "
                      "SEGUNDA lista de transmissao. Use --reset-progresso so se "
                      "voce aceitar essa duplicacao.", faltando, prog.listas_criadas)
            return 2
        prog.ultimo_hash = ""
        prog.ultimo_rotulo = ""
        prog.historico.append({"evento": "recomecar-do-A",
                               "em": datetime.now().isoformat(timespec="seconds")})
        prog.salvar()
        print(f"progresso mantido ({len(prog.usados)} contato(s) na guarda); a "
              "proxima lista recomeca do primeiro contato (A) SEM retomada "
              "posicional — a guarda impede que quem ja esta em lista seja "
              "tocado de novo.")
        return 0
    if args.progresso:
        print(prog.resumo())
        _avisar_incertos_pendentes(prog)
        return 0

    if args.resolver_incertos:
        pendentes = prog.incertos_pendentes()
        if args.lista:
            pendentes = [(i, e) for i, e in pendentes if e.get("lista") == args.lista]
            if not pendentes:
                log.error("nenhuma pendencia de toques incertos na lista %d", args.lista)
                return 2
        if not pendentes:
            print("nenhum toque em duvida pendente.")
            return 0
        agora = datetime.now().isoformat(timespec="seconds")
        for _, entrada in pendentes:
            if args.resolver_incertos == "entraram":
                hashes = list(entrada.get("toques_incertos") or [])
                ja_tinha = entrada.get("hashes") or []
                # Idempotencia: resolver duas vezes nao pode contar duas vezes.
                novos = [h for h in dict.fromkeys(hashes) if h not in ja_tinha]
                entrada["hashes"] = list(dict.fromkeys(list(ja_tinha) + hashes))
                prog.usados.update(hashes)
                # A lista do iPhone tem esses destinatarios a mais: se o
                # contador de contatos incluidos nao subir junto, o resumo
                # passa a relatar MENOS gente do que ha de verdade, para
                # sempre (a retomada usa ultimo_hash, mas o operador le isto).
                entrada["quantidade"] = len(entrada["hashes"])
                prog.offset += len(novos)
            entrada["incertos_resolvidos"] = True
            entrada["incertos_decisao"] = args.resolver_incertos
            entrada["incertos_resolvidos_em"] = agora
        prog.salvar()
        print(f"{len(pendentes)} pendencia(s) resolvida(s) como '{args.resolver_incertos}'.")
        return 0

    if args.max_listas < 1:
        log.error("--max-listas deve ser >= 1")
        return 2
    if args.limite_por_lista < MIN_RECIPIENTS or args.limite_por_lista > BROADCAST_LIMIT:
        log.error("--limite-por-lista deve ficar entre %d e %d", MIN_RECIPIENTS, BROADCAST_LIMIT)
        return 2
    if args.max_minutos < 0:
        log.error("--max-minutos nao pode ser negativo (0 desliga o limite)")
        return 2
    if 0 < args.max_minutos < 1:
        log.warning("--max-minutos %.2f e menor que 1 minuto — a lista provavelmente "
                    "vai parar antes de tocar em qualquer contato", args.max_minutos)
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
    _avisar_incertos_pendentes(prog)
    log.info("modo: %s | %d lista(s) x ate %d contatos",
             "CRIAR DE VERDADE" if args.approve_create else "ENSAIO (nao cria)",
             args.max_listas, args.limite_por_lista)

    max_telas = teto_telas_para(args.limite_por_lista, filtro)
    if max_telas > MAX_TELAS_POR_LISTA:
        log.info("teto de telas elevado para %d nesta lista (filtro de DDD "
                 "restritivo: a taxa de aprovacao na AGENDA e um teto superior "
                 "da taxa real na tela)", max_telas)
    if not prog.ultimo_hash and prog.usados:
        # Lista de RECUPERACAO (--recomecar-do-A ou primeira lista de um
        # progresso ja com contatos usados): sem ancora de retomada, ela rola
        # a agenda desde o A e precisa passar por TODOS os ja usados (a
        # guarda bloqueia o toque, mas a tela ainda precisa ser lida e
        # rolada) antes de achar gente nova.
        max_telas = max_telas_para_recuperacao(len(prog.usados), max_telas)
        # As duas travas (teto de TELAS e orcamento de RELOGIO) usam a mesma
        # calibracao e ate 2026-09-10 (4a rodada) nunca se falavam: o teto
        # prometia ~125 min de rolagem enquanto o orcamento que a GUI sempre
        # manda (60 min) cortava em ~1200 telas — antes de a lista chegar em
        # QUALQUER contato novo. A rodada terminava com 0 toques, nada era
        # criado, o progresso nao avancava, e a rodada seguinte fazia
        # exatamente a mesma coisa (livelock). Agora isso e recusado na
        # largada, com o numero que resolve.
        travessia = telas_para_atravessar_guarda(len(prog.usados))
        telas_orcamento = (int(args.max_minutos * 60 / SEGUNDOS_POR_TELA_ESTIMADO)
                           if args.max_minutos > 0 else 0)
        if telas_orcamento and telas_orcamento < travessia:
            minutos_minimos = math.ceil(
                (travessia + MAX_TELAS_POR_LISTA) * SEGUNDOS_POR_TELA_ESTIMADO / 60)
            log.error("esta lista de recuperacao nao cabe no tempo maximo: para "
                      "atravessar os %d contato(s) que ja estao em lista ela precisa "
                      "de ~%d telas (~%d min a %.0fs/tela), e o tempo maximo de "
                      "%.0f min so alcanca ~%d telas. Ela gastaria a rodada inteira "
                      "sem tocar em NINGUEM novo e sem avancar o progresso — a "
                      "rodada seguinte faria exatamente o mesmo. Suba --max-minutos "
                      "para pelo menos %d; se voce aceitar duplicar quem ja entrou, "
                      "--reset-progresso.",
                      len(prog.usados), travessia,
                      math.ceil(travessia * SEGUNDOS_POR_TELA_ESTIMADO / 60),
                      SEGUNDOS_POR_TELA_ESTIMADO, args.max_minutos, telas_orcamento,
                      minutos_minimos)
            return 8
        telas_efetivo = min(max_telas, telas_orcamento) if telas_orcamento else max_telas
        log.warning("lista de recuperacao (sem retomada posicional): ela vai rolar "
                    "ate ~%d telas (~%.0f min a %.0fs/tela) porque a guarda ja tem "
                    "%d contato(s) usados; as primeiras ~%d telas sao so travessia, "
                    "sem tocar em ninguem. Estourar continua sendo salvamento "
                    "parcial, nao perda.", telas_efetivo,
                    telas_efetivo * SEGUNDOS_POR_TELA_ESTIMADO / 60,
                    SEGUNDOS_POR_TELA_ESTIMADO, len(prog.usados), travessia)
    if args.turbo and args.limite_por_lista > 30:
        log.warning("ATENCAO: --turbo com --limite-por-lista %d e sem nenhum "
                    "contador de selecionados confirmado no aparelho (item em "
                    "aberto da auditoria de 2026-09-10) — se uma rajada morrer "
                    "no meio, os toques dessa rajada ficam em duvida (nem "
                    "contados, nem re-tocados: re-tocar desmarcaria quem ja "
                    "entrou). Confira SEMPRE no iPhone quantos contatos "
                    "entraram na transmissao.", args.limite_por_lista)

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
            sp = ScrollLivre(driver, profile, limite=args.limite_por_lista, max_telas=max_telas,
                             max_segundos=args.max_minutos * 60)
            sp.turbo = bool(args.turbo)
            sp.permitidos = filtro["permitidos"] if filtro else None
            sp.pular_sem_rotulo = bool(args.pular_celula_ilegivel)
            if sp.turbo:
                log.info("turbo ligado: rajada de toques por tela (1 requisicao)")
            sp.transition(State.PREPARING)
            sp.open_new_broadcast()
            t0 = time.monotonic()
            falha_infra = False   # o WDA/driver morreu (nao foi regra da estacao)
            try:
                qtd = sp.selecionar(prog)
            except (UiChanged, WebDriverException) as exc:
                # ORIGEM da parada. UiChanged e uma regra NOMEADA da estacao
                # (tom "atencao" na GUI); uma WebDriverException crua e o
                # WebDriverAgent caindo — "socket hang up", porta 8100 recusada
                # — e precisa sair como ERRO, com as instrucoes de recuperacao
                # do WDA. Ate 2026-09-10 (4a rodada) os dois saiam como codigo
                # 7 ("parou por uma regra da estacao... Nada foi perdido") e a
                # operadora re-rodava contra um WDA morto.
                falha_infra = (isinstance(exc, WebDriverException)
                               and not isinstance(exc, UiChanged))
                # SALVAMENTO PARCIAL: uma excecao aqui (rajada interrompida,
                # seletor sumiu) NAO pode custar os toques ja confirmados desta
                # lista. sp.ordem so contem toques CONFIRMADOS (ver _tocar_lote e
                # _registrar_toque) — nunca os da rajada que falhou.
                qtd = len(sp.ordem)
                # So a 1a linha e truncada: o motivo vai para o progresso, que
                # e arquivo, e mensagem de driver pode ser longa. Nenhum
                # seletor deste modo carrega nome/numero (busca por class chain
                # e accessibility id), mas nao ha razao para gravar mais texto
                # de terceiro do que o necessario para explicar a parada.
                sp.parada = sp.parada or str(exc).splitlines()[0][:200]
            dur = int(time.monotonic() - t0)
            log.info("lista %d: %d contato(s) selecionado(s) em %ds — telas %d, "
                     "retomada %d tela(s), homonimos ignorados %d, convites %d, "
                     "cliques que falharam e foram refeitos %d, sem rotulo %d, "
                     "sem posicao legivel %d, travados %d",
                     numero_lista, qtd, dur, sp.stats["telas"], sp.stats["telas_retomada"],
                     sp.stats["repetidos"], sp.stats["convites"], sp.stats["cliques_falhos"],
                     sp.stats["sem_rotulo"], sp.stats.get("sem_rect", 0), sp.stats["travados"])
            if sp.stats["sem_rotulo"]:
                # stats['sem_rotulo'] era escrito e NUNCA lido, apesar de a tabela
                # de diagnostico do MODO-SCROLL-LIVRE.md mandar o operador
                # procurar este numero no resumo (auditoria 2026-09-10, 3a rodada).
                # A partir da mudanca do discriminador de altura, uma celula SEM
                # ROTULO com a altura de uma linha de contato PARA a lista (ver
                # PARADA_SEM_ROTULO) em vez de ser so descartada.
                log.warning("%d celula(s) voltaram SEM ROTULO em duas leituras: "
                            "elas podem ter ficado de fora desta lista, ou terem "
                            "parado a selecao (ver o motivo da parada, se houver). "
                            "Se faltar alguem, e por aqui que se comeca a procurar.",
                            sp.stats["sem_rotulo"])
            if sp.stats.get("sem_rotulo_ignorado"):
                # WARNING, e sem afirmar a hipotese: "cabecalho de secao" era
                # so a explicacao mais provavel, e a linha saia em INFO como
                # se nao houvesse nada a conferir.
                log.warning("%d linha(s) sem rotulo foram IGNORADAS por serem bem "
                            "mais baixas que a linha de contato (cabecalho de secao, "
                            "separador). A lista seguiu por cima delas: se faltar "
                            "alguem nesta lista, e por aqui que se comeca a procurar",
                            sp.stats["sem_rotulo_ignorado"])
            if sp.stats.get("sem_rect"):
                log.warning("%d celula(s) sem posicao legivel (o rect nao "
                            "respondeu) — quase sempre um elemento que ficou "
                            "obsoleto porque a lista se moveu.", sp.stats["sem_rect"])

            if sp.parada:
                log.warning("selecao desta lista foi interrompida: %s", sp.parada)
                criada_parcial = False
                if qtd >= MIN_RECIPIENTS and args.approve_create:
                    ancora = None
                    try:
                        ancora = sp.wait_for("picker_anchor", timeout=3, required=False)
                    except WebDriverException:
                        ancora = None
                    if ancora is not None:
                        try:
                            sp.finish(approve_create=True)
                            criada_parcial = True
                        except (UiChanged, WebDriverException) as exc2:
                            log.error("o seletor ainda estava na tela, mas salvar o "
                                      "parcial tambem falhou (%s); nada foi criado, "
                                      "progresso intacto", exc2)
                    else:
                        log.error("o seletor de contatos ja nao esta mais na tela: "
                                  "nao ha como confirmar a criacao da lista parcial")
                if criada_parcial:
                    criadas += 1
                    prog.registrar_lista(sp.ordem)
                    prog.historico[-1]["parcial"] = True
                    prog.historico[-1]["motivo_da_parada"] = sp.parada
                    _gravar_avisos_no_historico(prog, sp)
                    if sp.incerteza:
                        # Janela de incerteza: hashes tocados numa rajada que nao
                        # pode ser confirmada nem re-tocada (nunca nomes/numeros).
                        prog.historico[-1]["toques_incertos"] = list(sp.incerteza)
                        prog.historico[-1]["conferir_no_iphone"] = (
                            f"a lista pode ter ate {len(sp.incerteza)} destinatario(s) "
                            "a mais do que o progresso registra; esses contatos podem "
                            "reaparecer na proxima lista")
                        # Ficam FORA da guarda por padrao (nunca em prog.usados):
                        # o risco aceito e DUPLICAR, nunca PULAR. So entram na
                        # guarda quando o operador confirmar com --resolver-incertos
                        # entraram (ver _avisar_incertos_pendentes / a decisao no
                        # topo de main()).
                        prog.historico[-1]["incertos_resolvidos"] = False
                        prog.historico[-1]["incertos_decisao"] = None
                    prog.salvar()
                    log.warning("lista %d criada PARCIAL: %d de ate %d contato(s) "
                                "pedidos (motivo da parada: %s). %s", numero_lista,
                                qtd, args.limite_por_lista, sp.parada, prog.resumo())
                    if sp.incerteza:
                        log.warning("CONFIRA NO IPHONE o numero de destinatarios da "
                                    "lista %d: %d toque(s) ficaram em duvida (a rajada "
                                    "saiu, mas nao deu para confirmar). Se a lista "
                                    "tiver mais gente do que o progresso diz, esses "
                                    "contatos vao aparecer TAMBEM na proxima lista — "
                                    "e melhor repetir do que deixar alguem de fora, "
                                    "mas o operador precisa saber.",
                                    numero_lista, len(sp.incerteza))
                    print(json.dumps({
                        "listas_criadas_nesta_rodada": criadas, "offset": prog.offset,
                        "proximo_contato_n": prog.offset + 1,
                        "listas_criadas_total": prog.listas_criadas,
                        "parcial": True, "motivo_da_parada": sp.parada,
                    }, ensure_ascii=False, indent=2))
                    return 6
                if not args.approve_create:
                    # Ensaio: nada seria criado de qualquer jeito. Deixar o
                    # seletor marcado no iPhone obrigaria o operador a limpar
                    # na mao antes da proxima escada (5 -> 30 -> 256).
                    log.info("ENSAIO interrompido (%s) com %d selecionado(s); "
                             "cancelando o seletor sem criar nada.", sp.parada, qtd)
                    if falha_infra:
                        log.error("o motivo foi uma falha do WebDriverAgent, nao uma "
                                  "regra da estacao — confira o iPhone antes da "
                                  "proxima rodada.")
                    try:
                        sp.cancelar_seletor()
                    except (UiChanged, WebDriverException) as exc3:
                        log.warning("nao consegui cancelar o seletor (%s): cancele "
                                    "na mao no iPhone antes da proxima rodada", exc3)
                    print(json.dumps({
                        "listas_criadas_nesta_rodada": criadas, "offset": prog.offset,
                        "proximo_contato_n": prog.offset + 1,
                        "listas_criadas_total": prog.listas_criadas,
                        "parcial": False, "motivo_da_parada": sp.parada,
                    }, ensure_ascii=False, indent=2))
                    if falha_infra:
                        # ENSAIO tambem: o motivo foi o driver, nao uma regra.
                        _dump_inventory_on_fail(driver, "inventory-erro.json")
                        return 4
                    return 7
                if falha_infra:
                    log.error("a selecao parou porque o WebDriverAgent falhou (%s): "
                              "%d toque(s) confirmado(s) ficam de fora e o progresso "
                              "NAO avancou. Isto NAO e uma regra da estacao — "
                              "confira o iPhone antes de rodar de novo.",
                              sp.parada, qtd)
                    _dump_inventory_on_fail(driver, "inventory-erro.json")
                    print(json.dumps({
                        "listas_criadas_nesta_rodada": criadas, "offset": prog.offset,
                        "proximo_contato_n": prog.offset + 1,
                        "listas_criadas_total": prog.listas_criadas,
                        "parcial": False, "motivo_da_parada": sp.parada,
                    }, ensure_ascii=False, indent=2))
                    return 4
                log.error("selecao interrompida por uma regra da estacao e nao deu "
                         "para salvar nada: %d toque(s) confirmado(s) ficam de fora, "
                         "progresso NAO avancou (motivo: %s)", qtd, sp.parada)
                # O seletor fica ABERTO e MARCADO no iPhone se ninguem fechar:
                # este ramo (rodada de verdade, menos de MIN_RECIPIENTS
                # confirmados) nao passava nem pelo cancelamento do ensaio nem
                # pelo do fim de agenda. Com as duas paradas novas (orcamento
                # de relogio e celula sem rotulo) ele deixou de ser raro
                # (auditoria 2026-09-10, 5a rodada).
                try:
                    sp.cancelar_seletor()
                except (UiChanged, WebDriverException) as exc4:
                    log.warning("nao consegui cancelar o seletor (%s): ele pode ter "
                                "ficado ABERTO no iPhone com %d contato(s) marcado(s) "
                                "— confira e feche na mao antes da proxima rodada",
                                exc4, qtd)
                print(json.dumps({
                    "listas_criadas_nesta_rodada": criadas, "offset": prog.offset,
                    "proximo_contato_n": prog.offset + 1,
                    "listas_criadas_total": prog.listas_criadas,
                    "parcial": False, "motivo_da_parada": sp.parada,
                }, ensure_ascii=False, indent=2))
                return 7

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
            prog.registrar_lista(sp.ordem)
            _gravar_avisos_no_historico(prog, sp)
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
