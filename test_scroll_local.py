"""Testes locais do MODO SCROLL LIVRE — rodam SEM iPhone e sem Appium.

Simulam o seletor de contatos do WhatsApp iOS (lista rolavel, faixa dos
selecionados que empurra a lista apos o 1o toque, celulas parcialmente
visiveis, celula "Convidar", homonimos, contato apagado entre rodadas) e
conferem a regra central: cada contato entra UMA vez, na ordem, sem pular
ninguem e sem desmarcar ninguem.

  python3 test_scroll_local.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from selenium.common.exceptions import NoSuchElementException, WebDriverException  # noqa: E402

import spike_ios  # noqa: E402
from ios_selectors import BASELINE, BUNDLE_ID  # noqa: E402
import run_ios_scroll as rs  # noqa: E402

spike_ios.time.sleep = lambda s: None   # settle() sem esperar


# ---------------------------------------------------------------------------
# simulador do seletor
# ---------------------------------------------------------------------------

class Modelo:
    """Tabela rolavel: celula i fica em y = topo + i*linha - offset.
    Apos o 1o selecionado, a faixa de chips aparece e o topo desce `faixa` pt."""

    def __init__(self, nomes, largura=390, altura=844, topo=120, linha=64, faixa=80):
        self.nomes = list(nomes)
        self.largura, self.altura = largura, altura
        self.topo0, self.linha, self.faixa = topo, linha, faixa
        self.offset = 0.0
        self.selecionados = set()
        self.toques = Counter()
        self.app_front = True
        self.composer = False
        self.rolagens = 0
        self.picker_aberto = True
        self.aceita_w3c = True
        self.rajadas = 0
        self.dialogo_apos = None   # indice de contato que abre um dialogo ao ser tocado
        self.buscas_por_valor = Counter()   # instrumentacao: quantas vezes cada
                                             # camada (by/val) foi consultada
        self.falha_na_rajada_numero = None  # rajada (1-indexada) que deve morrer no meio
        self.falha_apos_k_toques = None     # quantos toques dela ainda tem efeito
        self.rajada_sem_efeito = None       # rajada que "sai" mas nao marca ninguem
        self.ancora_oculta = False          # o botao Criar some da arvore
        self.ocultar_ancora_apos_toques = None
        self.profundidade = None            # snapshotMaxDepth pedido pelo driver
        self.profundidade_com_chips = None  # minima que enxerga celulas COM chips

    def tocar_em(self, x, y):
        """Toque por coordenada (rajada turbo). Se um dialogo estiver na frente,
        o toque cai nele e nao na lista — exatamente o risco que o turbo tem."""
        if not self.picker_aberto:
            return
        for i in range(len(self.nomes)):
            yi = self.y_de(i)
            if yi <= y < yi + self.linha:
                FakeCell(self, i).click()
                if self.dialogo_apos is not None and i == self.dialogo_apos:
                    self.picker_aberto = False   # dialogo cobre o seletor
                return

    ALT_CABECALHO = 28   # altura da linha "A", "B"... entre secoes

    @property
    def topo(self):
        return self.topo0 + (self.faixa if self.selecionados else 0)

    def y_de(self, i):
        cabs = getattr(self, "cabecalhos", ())
        extra = self.ALT_CABECALHO * sum(1 for k in cabs if k <= i)
        return self.topo + i * self.linha + extra - self.offset

    def rolar(self, delta):
        maximo = max(0.0, len(self.nomes) * self.linha - (self.altura - self.topo))
        self.offset = min(maximo, max(0.0, self.offset + delta))
        self.rolagens += 1

    def visiveis(self):
        # como o snapshot real: inclui celulas parcialmente fora da tela
        return [FakeCell(self, i) for i in range(len(self.nomes))
                if self.y_de(i) + self.linha > 0 and self.y_de(i) < self.altura]


class FakeCell:
    def __init__(self, m: Modelo, i: int):
        self.m, self.i = m, i

    @property
    def rect(self):
        return {"x": 0, "y": self.m.y_de(self.i), "width": self.m.largura, "height": self.m.linha}

    def get_attribute(self, a):
        if a == "label":
            return f"{self.m.nomes[self.i]}, recado {self.i}"
        return None

    @property
    def text(self):
        return ""

    def find_elements(self, by, val):
        return []

    def click(self):
        y = self.m.y_de(self.i)
        if y < self.m.topo - 1 or y + self.m.linha > self.m.altura:
            raise WebDriverException("element is not hittable")
        nome = self.m.nomes[self.i]
        if "convidar" in nome.lower():
            self.m.app_front = False        # abriria o app Mensagens
            return
        self.m.toques[self.i] += 1
        if self.i in self.m.selecionados:
            self.m.selecionados.remove(self.i)   # tocar de novo DESMARCA
        else:
            self.m.selecionados.add(self.i)


class BotaoCriar:
    """Stand-in do botao 'Criar' (mesmo id de acessibilidade do picker_anchor):
    'enabled' reflete o que o APARELHO tem selecionado, nao o que a estacao
    registrou — exatamente como o botao real, que nao sabe nada da estacao."""

    def __init__(self, m: Modelo):
        self.m = m

    def get_attribute(self, a):
        if a == "enabled":
            return "true" if len(self.m.selecionados) >= 2 else "false"
        return None

    def click(self):
        pass


class FakeDriver:
    def __init__(self, m: Modelo):
        self.m = m

    def get_window_size(self):
        return {"width": self.m.largura, "height": self.m.altura}

    def update_settings(self, s):
        if "snapshotMaxDepth" in s:
            self.m.profundidade = s["snapshotMaxDepth"]

    def _profundidade_alcanca(self):
        """Arvore mais funda depois do 1o chip: e o que o modo CSV ja tinha
        CONFIRMADO no aparelho (spike_ios._find_cells_escalating). Quando
        `profundidade_com_chips` esta definida, a busca so devolve celulas se
        a profundidade pedida alcancar o nivel em que elas estao AGORA."""
        minima = self.m.profundidade_com_chips
        if minima is None:
            return True
        if not self.selecionados_existem():
            return True
        return (self.m.profundidade or 0) >= minima

    def selecionados_existem(self):
        return bool(self.m.selecionados)

    def _ancora_visivel(self):
        if not self.m.picker_aberto or self.m.ancora_oculta:
            return False
        n = self.m.ocultar_ancora_apos_toques
        if n is not None and sum(self.m.toques.values()) >= n:
            return False
        return True

    def _e_celula(self, val):
        so_cc = getattr(self.m, "so_class_chain", False)
        return (val == "PickerView_ContactCell" and not so_cc) or val == "**/XCUIElementTypeCell"

    def find_elements(self, by, val):
        self.m.buscas_por_valor[val] += 1
        if self._e_celula(val):
            # seletor fechado (dialogo/conversa por cima) = nenhuma celula na tela
            if not self.m.picker_aberto or not self._profundidade_alcanca():
                return []
            return self.m.visiveis()
        if val == "ParticipantPickerNavigationBar_RightBarButton":
            return [BotaoCriar(self.m)] if self._ancora_visivel() else []
        if "XCUIElementTypeTextView" in str(val) and self.m.composer:
            return [object()]
        return []

    def find_element(self, by, val):
        if val == "ParticipantPickerNavigationBar_RightBarButton" and self._ancora_visivel():
            return BotaoCriar(self.m)
        raise NoSuchElementException(val)

    def quit(self):
        pass

    @property
    def page_source(self):
        return "<XCUIElementTypeApplication/>"

    def create_web_element(self, eid):
        return FakeCell(self.m, int(str(eid).split("-")[1]))

    def execute(self, comando, params=None):
        """Rajada W3C (--turbo) e busca com atributos na resposta
        (elementResponseAttributes), como o WDA real."""
        if comando == "findElements":
            achadas = self.find_elements(None, params["value"])
            if not getattr(self.m, "attrs_na_resposta", True):
                # driver que ignora a setting: devolve so os ids
                return {"value": [{"ELEMENT": f"cell-{c.i}"} for c in achadas]}
            if achadas:
                self.m.buscas_com_atributos = getattr(self.m, "buscas_com_atributos", 0) + 1
            return {"value": [
                {"ELEMENT": f"cell-{c.i}", "element-6066-11e4-a52e-4f735466cecf": f"cell-{c.i}",
                 "label": c.get_attribute("label"), "name": c.get_attribute("label"),
                 "rect": c.rect}
                for c in achadas]}
        if comando != "actions" or not self.m.aceita_w3c:
            raise WebDriverException("unknown command: " + str(comando))
        self.m.rajadas += 1
        numero_rajada = self.m.rajadas
        falha_num = self.m.falha_na_rajada_numero
        falha_k = self.m.falha_apos_k_toques
        tocados_nesta_rajada = 0
        if self.m.rajada_sem_efeito == numero_rajada:
            # A rajada "sai" (o driver aceita), mas nenhum toque marca ninguem
            # — e o seletor fica coberto no exato instante da conferencia.
            # E o cenario em que registrar ANTES de confirmar a ancora criaria
            # contatos fantasmas no progresso.
            self.m.ancora_oculta = True
            return {"value": None}
        for seq in params.get("actions", []):
            x = y = None
            for a in seq.get("actions", []):
                if a["type"] == "pointerMove":
                    x, y = a["x"], a["y"]
                elif a["type"] == "pointerDown":
                    if (falha_num == numero_rajada and falha_k is not None
                            and tocados_nesta_rajada >= falha_k):
                        # MeiaRajada: k toques ja surtiram efeito no aparelho
                        # (como um socket hang up de verdade) antes da queda.
                        raise WebDriverException("socket hang up")
                    self.m.tocar_em(x, y)
                    tocados_nesta_rajada += 1
        return {"value": None}

    def execute_script(self, name, args=None):
        args = args or {}
        if name == "mobile: activeAppInfo":
            return {"bundleId": BUNDLE_ID if self.m.app_front else "com.apple.MobileSMS"}
        if name == "mobile: dragFromToWithVelocity":
            self.m.rolar(args["fromY"] - args["toY"])
            return None
        if name == "mobile: swipe":
            self.m.rolar(self.m.altura * 2.5 if args.get("direction") == "up" else -self.m.altura * 2.5)
            return None
        raise WebDriverException(name)


def nomes_ordenados(n):
    return [f"Contato {i:04d}" for i in range(n)]


def novo(nomes, limite=256, **kw):
    m = Modelo(nomes, **kw)
    sp = rs.ScrollLivre(FakeDriver(m), BASELINE, limite=limite)
    return m, sp


def progresso_apos(nomes, idx, path):
    p = rs.Progresso(path)
    p.offset = idx + 1
    p.listas_criadas = 1
    p.ultimo_rotulo = nomes[idx]
    p.ultimo_hash = rs.hash_nome(nomes[idx])
    return p


# ---------------------------------------------------------------------------
# testes
# ---------------------------------------------------------------------------

class Normalizacao(unittest.TestCase):
    def test_nome_sem_recado(self):
        self.assertEqual(rs.nome_da_celula("Maria Silva, Disponível"), "Maria Silva")
        self.assertEqual(rs.nome_da_celula("Maria Silva"), "Maria Silva")
        self.assertEqual(rs.nome_da_celula("‎João‎, Oi, tudo bem"), "João")

    def test_chave_e_hash_estaveis(self):
        self.assertEqual(rs.chave_ordem("Ângela Müller"), "angela muller")
        self.assertEqual(rs.hash_nome("ÂNGELA"), rs.hash_nome("angela"))
        self.assertNotEqual(rs.hash_nome("Ana"), rs.hash_nome("Anna"))
        # o recado NAO entra na identidade (muda a toda hora)
        self.assertEqual(rs.hash_nome(rs.nome_da_celula("Ana, hoje")),
                         rs.hash_nome(rs.nome_da_celula("Ana, amanhã")))


class Selecao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "p.json")

    def test_256_na_ordem_sem_pular_sem_desmarcar(self):
        nomes = nomes_ordenados(600)
        m, sp = novo(nomes)
        qtd = sp.selecionar(rs.Progresso(self.path))
        self.assertEqual(qtd, 256)
        self.assertEqual([n for _, n in sp.ordem], nomes[:256])
        self.assertEqual(sorted(m.selecionados), list(range(256)))
        self.assertTrue(all(v == 1 for v in m.toques.values()), "algum contato foi tocado 2x")
        self.assertEqual(sp.stats["repetidos"], 0)

    def test_limite_pequeno(self):
        nomes = nomes_ordenados(50)
        m, sp = novo(nomes, limite=5)
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 5)
        self.assertEqual(sorted(m.selecionados), [0, 1, 2, 3, 4])

    def test_agenda_menor_que_o_limite_termina(self):
        nomes = nomes_ordenados(7)
        m, sp = novo(nomes)
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 7)
        self.assertEqual(sorted(m.selecionados), list(range(7)))

    def test_sem_faixa_de_chips_tambem_funciona(self):
        nomes = nomes_ordenados(300)
        m, sp = novo(nomes, faixa=0)
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 256)
        self.assertEqual(sorted(m.selecionados), list(range(256)))

    def test_retomada_continua_do_257(self):
        nomes = nomes_ordenados(600)
        m, sp = novo(nomes)
        prog = progresso_apos(nomes, 255, self.path)
        qtd = sp.selecionar(prog)
        self.assertEqual(qtd, 256)
        self.assertEqual([n for _, n in sp.ordem], nomes[256:512])
        self.assertEqual(sorted(m.selecionados), list(range(256, 512)))
        self.assertTrue(all(v == 1 for v in m.toques.values()))

    def test_retomada_no_fim_da_agenda(self):
        nomes = nomes_ordenados(300)
        m, sp = novo(nomes)
        prog = progresso_apos(nomes, 255, self.path)
        self.assertEqual(sp.selecionar(prog), 44)
        self.assertEqual(sorted(m.selecionados), list(range(256, 300)))

    def test_retomada_com_ultimo_contato_apagado(self):
        nomes = nomes_ordenados(600)
        agenda = nomes[:255] + nomes[256:]          # o contato 255 sumiu da agenda
        m, sp = novo(agenda)
        prog = progresso_apos(nomes, 255, self.path)
        qtd = sp.selecionar(prog)
        self.assertEqual(qtd, 256)
        self.assertEqual(sp.ordem[0][1], nomes[256])   # comeca no proximo alfabetico
        self.assertEqual([n for _, n in sp.ordem], nomes[256:512])

    def test_retomada_longe_usa_rolagem_rapida(self):
        nomes = nomes_ordenados(3000)
        m, sp = novo(nomes)
        prog = progresso_apos(nomes, 2559, self.path)   # 10a lista
        self.assertEqual(sp.selecionar(prog), 256)
        self.assertEqual([n for _, n in sp.ordem], nomes[2560:2816])
        self.assertLess(sp.stats["telas_retomada"], 120)

    def test_convidar_e_pulado_e_app_nao_sai(self):
        nomes = nomes_ordenados(5) + ["Convidar amigos para o WhatsApp"]
        m, sp = novo(nomes)
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 5)
        self.assertEqual(sp.stats["convites"], 1)
        self.assertTrue(m.app_front)

    def test_homonimo_nao_e_tocado_de_novo(self):
        nomes = ["Ana", "Ana", "Bruno", "Carla"]
        m, sp = novo(nomes)
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 3)
        self.assertEqual(sorted(m.selecionados), [0, 2, 3])
        self.assertEqual(sp.stats["repetidos"], 1)
        self.assertEqual(m.toques[0], 1)          # a 1a Ana continua selecionada

    def test_compositor_aborta(self):
        """Um compositor so aparece quando o seletor sumiu (abriu uma conversa).
        Nos dois casos a resposta e parada segura antes de qualquer toque novo."""
        nomes = nomes_ordenados(40)
        m, sp = novo(nomes)
        m.composer = True
        m.picker_aberto = False
        with self.assertRaises((spike_ios.UnsafeState, spike_ios.UiChanged)):
            sp.selecionar(rs.Progresso(self.path))
        self.assertLessEqual(len(m.selecionados), 1)

    def test_trava_do_compositor_continua_no_modo_csv(self):
        """assert_no_composer (usado contato a contato no modo CSV) agora faz
        UMA consulta, mas dispara igual."""
        nomes = nomes_ordenados(5)
        m, sp = novo(nomes)
        sp.assert_no_composer()            # sem compositor: nada acontece
        m.composer = True
        with self.assertRaises(spike_ios.UnsafeState):
            sp.assert_no_composer()

    def test_finish_conta_os_toques(self):
        nomes = nomes_ordenados(30)
        m, sp = novo(nomes, limite=10)
        sp.selecionar(rs.Progresso(self.path))
        self.assertEqual(sum(1 for r in sp.results if r["outcome"] == "selected"), 10)


class Turbo(unittest.TestCase):
    """--turbo: rajada W3C por tela. Mesmas garantias do modo normal."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "p.json")

    def _turbo(self, nomes, **kw):
        m, sp = novo(nomes, **kw)
        sp.turbo = True
        return m, sp

    def test_256_na_ordem_sem_pular_sem_desmarcar(self):
        nomes = nomes_ordenados(600)
        m, sp = self._turbo(nomes)
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 256)
        self.assertEqual([n for _, n in sp.ordem], nomes[:256])
        self.assertEqual(sorted(m.selecionados), list(range(256)))
        self.assertTrue(all(v == 1 for v in m.toques.values()), "toque duplo")
        self.assertGreater(m.rajadas, 0, "o turbo nao usou a rajada")

    def test_primeiro_toque_da_lista_e_sozinho(self):
        """A faixa de chips desloca a lista no 1o toque: ele nunca entra na rajada."""
        nomes = nomes_ordenados(40)
        m, sp = self._turbo(nomes, limite=10)
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 10)
        self.assertEqual(sorted(m.selecionados), list(range(10)))

    def test_retomada_continua_do_257(self):
        nomes = nomes_ordenados(600)
        m, sp = self._turbo(nomes)
        prog = progresso_apos(nomes, 255, self.path)
        self.assertEqual(sp.selecionar(prog), 256)
        self.assertEqual([n for _, n in sp.ordem], nomes[256:512])
        self.assertTrue(all(v == 1 for v in m.toques.values()))

    def test_fim_da_agenda(self):
        nomes = nomes_ordenados(300)
        m, sp = self._turbo(nomes)
        self.assertEqual(sp.selecionar(progresso_apos(nomes, 255, self.path)), 44)
        self.assertEqual(sorted(m.selecionados), list(range(256, 300)))

    def test_driver_sem_w3c_cai_para_toque_por_elemento(self):
        nomes = nomes_ordenados(300)
        m, sp = self._turbo(nomes)
        m.aceita_w3c = False
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 256)
        self.assertEqual(sorted(m.selecionados), list(range(256)))
        self.assertFalse(sp.turbo, "deveria ter desligado o turbo apos a recusa")

    def test_dialogo_no_meio_da_rajada_e_parada_segura(self):
        """Um dialogo que cobre o seletor durante a rajada => UiChanged, sem
        continuar tocando no escuro."""
        nomes = nomes_ordenados(80)
        m, sp = self._turbo(nomes)
        m.dialogo_apos = 5
        with self.assertRaises(spike_ios.UiChanged):
            sp.selecionar(rs.Progresso(self.path))

    def test_convite_e_pulado_sem_chamadas_extras(self):
        nomes = nomes_ordenados(6) + ["Convidar amigos para o WhatsApp"]
        m, sp = self._turbo(nomes)
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 6)
        self.assertEqual(sp.stats["convites"], 1)
        self.assertTrue(m.app_front)


class Geometria(unittest.TestCase):
    """Posicao inferida (2 chamadas por tela) so quando a conferencia exata
    bate; com cabecalho de secao no meio, le todas — nunca chuta."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "p.json")

    def test_sem_cabecalho_infere_e_acerta(self):
        nomes = nomes_ordenados(400)
        m, sp = novo(nomes)
        m.attrs_na_resposta = False   # sem posicao na resposta: e aqui que a inferencia entra
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 256)
        self.assertEqual(sorted(m.selecionados), list(range(256)))
        self.assertGreater(sp.stats.get("telas_inferidas", 0), 10)

    def test_com_cabecalhos_cai_para_leitura_completa_e_acerta(self):
        nomes = nomes_ordenados(400)
        m, sp = novo(nomes)
        m.cabecalhos = set(range(0, 400, 7))     # um cabecalho a cada 7 contatos
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 256)
        self.assertEqual(sorted(m.selecionados), list(range(256)))
        self.assertTrue(all(v == 1 for v in m.toques.values()))

    def test_turbo_com_cabecalhos_toca_nas_coordenadas_certas(self):
        nomes = nomes_ordenados(400)
        m, sp = novo(nomes)
        sp.turbo = True
        m.cabecalhos = set(range(0, 400, 5))
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 256)
        self.assertEqual(sorted(m.selecionados), list(range(256)))
        self.assertTrue(all(v == 1 for v in m.toques.values()), "toque duplo")


class LeituraEmUmaRequisicao(unittest.TestCase):
    """elementResponseAttributes: nome e posicao vem na propria busca."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "p.json")

    def test_usa_a_resposta_e_acerta_tudo(self):
        nomes = nomes_ordenados(400)
        m, sp = novo(nomes)
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 256)
        self.assertEqual(sorted(m.selecionados), list(range(256)))
        self.assertGreater(sp.stats.get("telas_1_requisicao", 0), 20)
        self.assertGreater(getattr(m, "buscas_com_atributos", 0), 20)

    def test_driver_que_ignora_a_setting_cai_para_o_caminho_antigo(self):
        nomes = nomes_ordenados(400)
        m, sp = novo(nomes)
        m.attrs_na_resposta = False
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 256)
        self.assertEqual(sorted(m.selecionados), list(range(256)))
        self.assertFalse(sp._attrs_na_resposta)
        self.assertEqual(sp.stats.get("telas_1_requisicao", 0), 0)

    def test_celulas_so_pela_class_chain_como_no_iphone(self):
        """iOS 26.6: o id PickerView_ContactCell nao existe; a leitura rapida
        precisa cair na 2a camada e nunca tratar a 1a vazia como 'fim'."""
        nomes = nomes_ordenados(400)
        m, sp = novo(nomes)
        m.so_class_chain = True
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 256)
        self.assertEqual(sorted(m.selecionados), list(range(256)))
        self.assertGreater(sp.stats.get("telas_1_requisicao", 0), 20)

    def test_turbo_com_leitura_rapida_e_cabecalhos(self):
        nomes = nomes_ordenados(400)
        m, sp = novo(nomes)
        sp.turbo = True
        m.cabecalhos = set(range(0, 400, 6))
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 256)
        self.assertEqual(sorted(m.selecionados), list(range(256)))
        self.assertTrue(all(v == 1 for v in m.toques.values()))


class FiltroDDD(unittest.TestCase):
    """--ddd no Scroll Livre: decidido pelo NOME, a partir da agenda exportada."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "p.json")

    def _agenda(self, linhas):
        import csv
        caminho = os.path.join(self.tmp, "agenda.csv")
        with open(caminho, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f); w.writerow(["name", "phone"]); w.writerows(linhas)
        return caminho

    def test_permitidos_ambiguos_e_sem_numero(self):
        agenda = self._agenda([
            ["Ana Dentro", "+55 21 99999-0001"],
            ["Bia Fora", "+55 11 99999-0002"],
            ["Caio Ambiguo", "+55 21 99999-0003"],
            ["Caio Ambiguo", "+55 11 99999-0004"],
            ["Dora Invalida", "123"],
        ])
        r = rs.permitidos_por_ddd(agenda, "21,22")
        self.assertEqual(r["permitidos"], {rs.hash_nome("Ana Dentro")})
        self.assertEqual(r["ambiguos"], {rs.hash_nome("Caio Ambiguo")})
        self.assertEqual(r["sem_numero"], 1)
        self.assertEqual(r["nomes"], 3)

    def test_selecao_toca_so_os_permitidos_na_ordem(self):
        nomes = nomes_ordenados(300)
        m, sp = novo(nomes, limite=50)
        pares = [i for i in range(300) if i % 2 == 0]
        sp.permitidos = {rs.hash_nome(nomes[i]) for i in pares}
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 50)
        self.assertEqual(sorted(m.selecionados), pares[:50])
        self.assertEqual([n for _, n in sp.ordem], [nomes[i] for i in pares[:50]])
        self.assertGreaterEqual(sp.stats.get("filtrados", 0), 49)

    def test_filtro_com_turbo_e_retomada(self):
        nomes = nomes_ordenados(300)
        m, sp = novo(nomes, limite=20)
        sp.turbo = True
        pares = [i for i in range(300) if i % 2 == 0]
        sp.permitidos = {rs.hash_nome(nomes[i]) for i in pares}
        prog = progresso_apos(nomes, 100, self.path)      # ultimo tocado: 100
        self.assertEqual(sp.selecionar(prog), 20)
        self.assertEqual(sorted(m.selecionados), [i for i in pares if i > 100][:20])


class ProgressoArquivo(unittest.TestCase):
    def test_ida_e_volta(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "p.json")
        p = rs.Progresso(path)
        self.assertEqual(p.offset, 0)
        p.registrar_lista(256, "h1", "h256", "Contato 0255")
        p.registrar_lista(256, "h257", "h512", "Contato 0511")
        q = rs.Progresso(path)
        self.assertEqual(q.offset, 512)
        self.assertEqual(q.listas_criadas, 2)
        self.assertEqual(q.ultimo_rotulo, "Contato 0511")
        self.assertEqual(q.ultimo_hash, "h512")
        self.assertEqual(len(q.historico), 2)
        self.assertIn("513", q.resumo())
        self.assertNotIn("Contato 0511", q.resumo())   # resumo nunca mostra o nome


# ---------------------------------------------------------------------------
# auditoria 2026-09-10: ensaio de 256 contatos
# ---------------------------------------------------------------------------

class CacheDeCamada(unittest.TestCase):
    """_find_raw agora compartilha o cache de camada com find_all: a camada
    morta (accessibility id 'PickerView_ContactCell', que neste iPhone SEMPRE
    volta vazia) e tentada no maximo 1x por lista, nao a cada tela — antes
    eram ~52 buscas perdidas so nisso, em 256 contatos com --turbo."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "p.json")

    def test_camada_morta_nao_se_repete_a_cada_tela(self):
        nomes = nomes_ordenados(256)
        m, sp = novo(nomes)
        m.so_class_chain = True   # como no iPhone: o id nunca casa
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 256)
        self.assertLessEqual(m.buscas_por_valor.get("PickerView_ContactCell", 0), 2)
        # a camada que funciona continua sendo usada em toda tela
        self.assertGreater(m.buscas_por_valor.get("**/XCUIElementTypeCell", 0), 20)


class RajadaInterrompida(unittest.TestCase):
    """Se uma rajada morre no meio (o cenario real do log de 2026-09-09:
    socket hang up depois de parte dos toques), o codigo NUNCA re-toca o lote
    inteiro (re-tocar desmarca quem ja entrou) e nunca registra o que nao foi
    confirmado pela ancora do picker. Gemeo do teste que ja existia (driver
    que recusa 'actions' ANTES de qualquer toque): esse continua caindo no
    fallback por elemento, que e o comportamento correto la."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "p.json")

    def test_nao_re_toca_e_ordem_nunca_supera_o_confirmado(self):
        nomes = nomes_ordenados(60)
        m, sp = novo(nomes, limite=60)
        sp.turbo = True
        m.falha_na_rajada_numero = 3   # as 2 primeiras rajadas (lotes de 6 e 2) saem bem
        m.falha_apos_k_toques = 3      # a 3a (lote de 5) morre apos 3 toques
        with self.assertRaises(spike_ios.UiChanged):
            sp.selecionar(rs.Progresso(self.path))
        # nenhum toque foi refeito (re-tocar desmarca)
        self.assertTrue(all(v == 1 for v in m.toques.values()), "algum toque foi refeito")
        # self.ordem e um LIMITE INFERIOR conservador: nunca reivindica mais
        # do que o aparelho realmente tem confirmado por evidencia (a ancora).
        # Sem contador de selecionados (item NAO CONFIRMADO no aparelho), o
        # codigo NUNCA registra os toques incertos da rajada que falhou.
        self.assertLessEqual(len(sp.ordem), len(m.selecionados))
        self.assertEqual(sp.parada, "rajada interrompida")
        self.assertEqual(sp.incerteza, [rs.hash_nome(n) for n in nomes[9:14]])
        self.assertTrue(sp.turbo, "a recusa foi no MEIO da rajada: turbo continua ligado")

    def test_recusa_no_inicio_continua_caindo_no_fallback_por_elemento(self):
        """Gemeo: nenhuma rajada teve sucesso ainda nesta lista, entao a
        recusa e tratada como 'o driver nao aceita o comando' — comportamento
        antigo, que continua correto."""
        nomes = nomes_ordenados(300)
        m, sp = novo(nomes)
        sp.turbo = True
        m.aceita_w3c = False
        self.assertEqual(sp.selecionar(rs.Progresso(self.path)), 256)
        self.assertEqual(sorted(m.selecionados), list(range(256)))
        self.assertFalse(sp.turbo)
        self.assertEqual(sp.parada, "")


class SalvamentoParcial(unittest.TestCase):
    """Reproduz as decisoes que main() toma quando sp.selecionar() e
    interrompida (sp.parada preenchido ou excecao) — nao chama main() (que
    precisa de um driver Appium de verdade), mas exercita o MECANISMO que ele
    usa: sp.ordem so com toques confirmados, sp.parada nomeando o motivo, e
    prog.registrar_lista so avancando pelo que foi de fato confirmado."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "p.json")

    @staticmethod
    def _rodada(sp, prog):
        """As mesmas decisoes de run_ios_scroll.main() apos uma excecao."""
        try:
            qtd = sp.selecionar(prog)
        except (spike_ios.UiChanged, WebDriverException) as exc:
            qtd = len(sp.ordem)
            sp.parada = sp.parada or str(exc)
        if sp.parada:
            if qtd >= 2 and sp.wait_for("picker_anchor", timeout=1, required=False) is not None:
                sp.finish(approve_create=True)
                prog.registrar_lista(qtd, sp.ordem[0][0], sp.ordem[-1][0], sp.ordem[-1][1])
                return "parcial", qtd
            return "perdido", qtd
        return "completo", qtd

    def test_rajada_interrompida_ainda_cria_lista_parcial_com_o_confirmado(self):
        nomes = nomes_ordenados(60)
        m, sp = novo(nomes, limite=60)
        sp.turbo = True
        m.falha_na_rajada_numero = 3
        m.falha_apos_k_toques = 3
        prog = rs.Progresso(self.path)
        desfecho, qtd = self._rodada(sp, prog)
        self.assertEqual(desfecho, "parcial")
        self.assertGreaterEqual(qtd, spike_ios.MIN_RECIPIENTS)
        self.assertLess(qtd, 60)
        # o progresso avanca EXATAMENTE pelo que foi confirmado — nunca mais.
        self.assertEqual(prog.offset, qtd)
        self.assertTrue(sp.lista_criada)

    def test_picker_fechado_nao_avanca_progresso(self):
        """Quando o seletor ja nao esta mais na tela, nao ha como confirmar
        nada: o progresso tem de continuar intacto (nada e criado)."""
        nomes = nomes_ordenados(40)
        m, sp = novo(nomes, limite=40)
        sp.turbo = True
        m.dialogo_apos = 3   # fecha o picker no meio da 1a rajada da lista
        prog = rs.Progresso(self.path)
        desfecho, _ = self._rodada(sp, prog)
        self.assertEqual(desfecho, "perdido")
        self.assertEqual(prog.offset, 0)
        self.assertEqual(prog.listas_criadas, 0)


class TetoDeTelas(unittest.TestCase):
    """MAX_TELAS_POR_LISTA nao pode mais ser um fim de `for` silencioso: e um
    desfecho NOMEADO (self.parada), para nunca ser confundido com fim real de
    agenda (o bug: main() dizia 'a agenda acabou' com milhares de contatos
    ainda por vir, so porque um filtro de DDD restritivo estourou o teto)."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "p.json")

    def test_estoura_o_teto_vira_desfecho_nomeado(self):
        nomes = nomes_ordenados(5000)
        m, sp = novo(nomes, limite=256)
        sp.max_telas = 5
        qtd = sp.selecionar(rs.Progresso(self.path))
        self.assertLess(qtd, 256)
        self.assertGreater(qtd, 0)
        self.assertEqual(sp.parada, "teto de telas")
        self.assertEqual(sp.stats["telas"], 5)

    def test_terminando_a_tempo_parada_fica_vazia(self):
        nomes = nomes_ordenados(50)
        m, sp = novo(nomes, limite=10)
        qtd = sp.selecionar(rs.Progresso(self.path))
        self.assertEqual(qtd, 10)
        self.assertEqual(sp.parada, "")


class TetoDerivado(unittest.TestCase):
    """teto_telas_para: sem filtro, o piso de sempre; com filtro de DDD
    restritivo, o teto sobe — senao uma taxa de aprovacao pior que ~1 em 7
    estoura o piso de 400 e a rodada para em silencio (auditoria 2026-09-10)."""

    def test_sem_filtro_usa_o_piso(self):
        self.assertEqual(rs.teto_telas_para(256, None), rs.MAX_TELAS_POR_LISTA)

    def test_filtro_restritivo_eleva_o_teto(self):
        filtro = {"permitidos": set(range(100)), "nomes": 1000}   # taxa 1 em 10
        teto = rs.teto_telas_para(256, filtro)
        self.assertGreater(teto, rs.MAX_TELAS_POR_LISTA)

    def test_filtro_frouxo_nao_precisa_de_teto_maior(self):
        filtro = {"permitidos": set(range(500)), "nomes": 1000}   # taxa 1 em 2
        self.assertEqual(rs.teto_telas_para(256, filtro), rs.MAX_TELAS_POR_LISTA)


class LeituraVaziaLenta(unittest.TestCase):
    """Uma tela vazia RAPIDA e fim de agenda plausivel; uma tela vazia LENTA
    e o sintoma exato do log de 2026-09-09 (33.6s, vazio, socket hang up
    logo depois) — NUNCA pode virar 'fim da lista de contatos' com a agenda
    pela metade."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "p.json")

    def test_leitura_vazia_lenta_nao_e_tratada_como_fim_de_agenda(self):
        nomes = nomes_ordenados(50)
        m, sp = novo(nomes, limite=30)
        original = sp._ler_celulas

        def sempre_vazia_e_lenta(margem=rs.MARGEM_INFERIOR):
            sp._duracoes_leitura.append(rs.LEITURA_LENTA_S + 1)
            return []

        def troca_apos_5_confirmados(margem=rs.MARGEM_INFERIOR):
            if len(sp.ordem) >= 5:
                sp._ler_celulas = sempre_vazia_e_lenta
                return sempre_vazia_e_lenta(margem)
            return original(margem)

        sp._ler_celulas = troca_apos_5_confirmados
        qtd = sp.selecionar(rs.Progresso(self.path))
        self.assertGreaterEqual(qtd, 5)
        self.assertLess(qtd, 30)
        self.assertEqual(sp.parada, "leitura vazia lenta (nao e fim de agenda)")

    def test_leitura_vazia_rapida_continua_sendo_fim_de_agenda(self):
        """O caminho feliz de sempre (agenda menor que o limite) nao pode
        regredir: continua terminando normalmente, sem self.parada."""
        nomes = nomes_ordenados(7)
        m, sp = novo(nomes)
        qtd = sp.selecionar(rs.Progresso(self.path))
        self.assertEqual(qtd, 7)
        self.assertEqual(sp.parada, "")


class RectsSemLimite(unittest.TestCase):
    """Sem elementResponseAttributes, quando a inferencia de posicao falha
    (cabecalho de secao) e a tela tem MUITOS elementos ao mesmo tempo, ler um
    rect por elemento poderia significar dezenas de chamadas HTTP nesta UNICA
    tela — o mecanismo que faz o custo crescer sem limite (auditoria
    2026-09-10). O codigo agora para com um motivo nomeado em vez de pagar
    isso."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "p.json")

    def test_para_em_vez_de_ler_um_rect_por_elemento_sem_limite(self):
        nomes = nomes_ordenados(400)
        m, sp = novo(nomes, altura=5000)   # tela gigante: muitas celulas visiveis
        m.attrs_na_resposta = False        # forca o caminho antigo (o que usa _rects)
        m.cabecalhos = set(range(0, 400, 7))   # inferencia falha (cabecalho no meio)
        with self.assertRaises(spike_ios.UiChanged):
            sp.selecionar(rs.Progresso(self.path))
        self.assertIn("leitura", sp.parada)


# ---------------------------------------------------------------------------
# revisao adversarial 2026-09-10 (2a rodada)
# ---------------------------------------------------------------------------

class ProfundidadeDepoisDoPrimeiroChip(unittest.TestCase):
    """A faixa de selecionados afunda a arvore um nivel depois do 1o contato —
    no modo CSV isso esta CONFIRMADO no aparelho. Quando isso acontece, a
    busca volta vazia DE IMEDIATO (rapida), e o codigo tratava vazio rapido
    como "fim da agenda": a lista terminava com 1 contato e o operador ouvia
    que a agenda tinha acabado. A re-escalada de profundidade existia, mas so
    era chamada no caminho do vazio LENTO — nunca neste."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "p.json")

    def test_reescala_a_profundidade_em_vez_de_dizer_fim_da_agenda(self):
        nomes = nomes_ordenados(40)
        m, sp = novo(nomes, limite=20)
        m.profundidade_com_chips = 14   # 12 basta sem chips; com chips, nao
        qtd = sp.selecionar(rs.Progresso(self.path))
        self.assertEqual(qtd, 20, "a lista parou cedo: a profundidade nao foi reavaliada")
        self.assertEqual(sorted(m.selecionados), list(range(20)))
        self.assertEqual(sp.parada, "")
        self.assertGreaterEqual(m.profundidade, 14)

    def test_fim_de_agenda_real_nao_paga_reescalada(self):
        """Quando a busca ACHA celulas e elas so nao cabem na area tocavel,
        isso e fim de agenda de verdade: nao se gasta chamada subindo a
        profundidade."""
        nomes = nomes_ordenados(7)
        m, sp = novo(nomes)
        qtd = sp.selecionar(rs.Progresso(self.path))
        self.assertEqual(qtd, 7)
        self.assertFalse(sp._profundidade_reescalada)


class TravaDeFimDeTelaNoFallback(unittest.TestCase):
    """A checagem de seguranca de fim de tela so pode pular a busca da ancora
    quando uma rajada W3C acabou de PROVAR que o seletor continua na tela.
    Quando o driver recusa o comando "actions" e os toques vao por elemento,
    nada foi provado — pular a busca deixaria a tela inteira sem trava."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "p.json")

    def test_ancora_e_conferida_mesmo_quando_a_rajada_caiu_no_fallback(self):
        nomes = nomes_ordenados(5)
        m, sp = novo(nomes, limite=5)
        sp.turbo = True
        m.aceita_w3c = False               # forca o toque por elemento
        m.ocultar_ancora_apos_toques = 3   # o seletor some no meio da tela
        with self.assertRaises(spike_ios.UiChanged):
            sp.selecionar(rs.Progresso(self.path))


class MainSalvamentoParcial(unittest.TestCase):
    """Exercita o main() DE VERDADE (nao uma copia da logica dele dentro do
    teste): e no main que mora a decisao de criar a lista parcial e de quanto
    o progresso avanca. Um teste que reimplementa essa decisao continua verde
    mesmo com o main revertido."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "p.json")

    def _rodar(self, m, argv):
        """Roda rs.main() com o FakeDriver no lugar do Appium."""
        driver = FakeDriver(m)
        orig = {
            "build": rs.build_driver, "exigir": spike_ios.exigir_appium,
            "abrir": rs.ScrollLivre.open_new_broadcast,
            "voltar": rs.ScrollLivre.voltar_para_conversas,
            "dump": rs._dump_inventory_on_fail, "argv": sys.argv,
        }
        rs.build_driver = lambda *a, **k: driver
        spike_ios.exigir_appium = lambda *a, **k: True
        rs.ScrollLivre.open_new_broadcast = lambda self: None
        rs.ScrollLivre.voltar_para_conversas = lambda self: None
        rs._dump_inventory_on_fail = lambda *a, **k: None
        sys.argv = ["run_ios_scroll.py", "--progress-file", self.path] + argv
        try:
            return rs.main()
        finally:
            rs.build_driver = orig["build"]
            spike_ios.exigir_appium = orig["exigir"]
            rs.ScrollLivre.open_new_broadcast = orig["abrir"]
            rs.ScrollLivre.voltar_para_conversas = orig["voltar"]
            rs._dump_inventory_on_fail = orig["dump"]
            sys.argv = orig["argv"]

    def test_rajada_morre_no_meio_cria_parcial_e_avanca_so_o_confirmado(self):
        m = Modelo(nomes_ordenados(60))
        m.falha_na_rajada_numero = 3
        m.falha_apos_k_toques = 3
        codigo = self._rodar(m, ["--trust-profile", "--approve-create", "--turbo",
                                 "--limite-por-lista", "60", "--max-listas", "1"])
        self.assertEqual(codigo, 6, "o salvamento parcial nao rodou pelo main()")
        prog = rs.Progresso(self.path)
        self.assertEqual(prog.listas_criadas, 1)
        self.assertGreaterEqual(prog.offset, spike_ios.MIN_RECIPIENTS)
        self.assertLess(prog.offset, 60)
        # NUNCA reivindicar mais do que o aparelho tem: gravar a mais deixaria
        # gente de fora PARA SEMPRE (a proxima rodada comeca depois do ultimo
        # gravado). Gravar a menos so gera repetido, que e recuperavel.
        self.assertLessEqual(prog.offset, len(m.selecionados))
        self.assertTrue(prog.historico[-1]["parcial"])
        self.assertEqual(prog.historico[-1]["motivo_da_parada"], "rajada interrompida")

    def test_rajada_sem_efeito_com_ancora_fora_nao_inventa_contato(self):
        """A rajada e aceita pelo driver mas nao marca ninguem, e o seletor
        fica coberto no exato instante da conferencia (volta logo depois).
        Registrar ANTES de confirmar a ancora gravaria contatos fantasmas — e
        a proxima rodada PULARIA essas pessoas para sempre."""
        m = Modelo(nomes_ordenados(60))
        m.rajada_sem_efeito = 2
        orig_sel = rs.ScrollLivre.selecionar

        def selecionar_e_devolver_a_ancora(sp, prog):
            try:
                return orig_sel(sp, prog)
            finally:
                m.ancora_oculta = False   # o dialogo passou; o seletor voltou
        rs.ScrollLivre.selecionar = selecionar_e_devolver_a_ancora
        try:
            codigo = self._rodar(m, ["--trust-profile", "--approve-create", "--turbo",
                                     "--limite-por-lista", "60", "--max-listas", "1"])
        finally:
            rs.ScrollLivre.selecionar = orig_sel
        self.assertEqual(codigo, 6)
        prog = rs.Progresso(self.path)
        self.assertEqual(prog.offset, len(m.selecionados),
                         "o progresso avancou por toques que o aparelho nao tem")

    def test_sem_seletor_na_tela_nada_e_criado_e_progresso_fica_intacto(self):
        m = Modelo(nomes_ordenados(40))
        m.dialogo_apos = 3            # o seletor some e nao volta
        codigo = self._rodar(m, ["--trust-profile", "--approve-create", "--turbo",
                                 "--limite-por-lista", "40", "--max-listas", "1"])
        self.assertEqual(codigo, 4)
        self.assertFalse(os.path.exists(self.path))

    def test_ensaio_interrompido_cancela_o_seletor_em_vez_de_deixar_sujo(self):
        """Sem --approve-create nada seria criado de qualquer jeito. Deixar o
        seletor marcado no iPhone obrigaria o operador a limpar na mao antes
        do proximo degrau da escada de ensaio (5 -> 30 -> 256)."""
        m = Modelo(nomes_ordenados(60))
        m.falha_na_rajada_numero = 3
        m.falha_apos_k_toques = 3
        cancelou = []
        orig_cancel = rs.ScrollLivre.cancelar_seletor
        rs.ScrollLivre.cancelar_seletor = lambda self: cancelou.append(True)
        try:
            codigo = self._rodar(m, ["--trust-profile", "--turbo",
                                     "--limite-por-lista", "60", "--max-listas", "1"])
        finally:
            rs.ScrollLivre.cancelar_seletor = orig_cancel
        self.assertEqual(codigo, 4)
        self.assertTrue(cancelou, "o ensaio parou e deixou o seletor marcado no iPhone")
        self.assertFalse(os.path.exists(self.path))

    def test_lista_completa_continua_saindo_com_codigo_0(self):
        """O caminho feliz do main() nao pode regredir."""
        m = Modelo(nomes_ordenados(300))
        codigo = self._rodar(m, ["--trust-profile", "--approve-create",
                                 "--limite-por-lista", "20", "--max-listas", "1"])
        self.assertEqual(codigo, 0)
        prog = rs.Progresso(self.path)
        self.assertEqual(prog.offset, 20)
        self.assertEqual(sorted(m.selecionados), list(range(20)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
