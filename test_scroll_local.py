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


class FakeDriver:
    def __init__(self, m: Modelo):
        self.m = m

    def get_window_size(self):
        return {"width": self.m.largura, "height": self.m.altura}

    def update_settings(self, s):
        pass

    def find_elements(self, by, val):
        if val == "PickerView_ContactCell":
            # seletor fechado (dialogo/conversa por cima) = nenhuma celula na tela
            return self.m.visiveis() if self.m.picker_aberto else []
        if val == "ParticipantPickerNavigationBar_RightBarButton":
            return [object()] if self.m.picker_aberto else []
        if "XCUIElementTypeTextView" in str(val) and self.m.composer:
            return [object()]
        return []

    def find_element(self, by, val):
        if val == "ParticipantPickerNavigationBar_RightBarButton" and self.m.picker_aberto:
            return object()
        raise NoSuchElementException(val)

    def create_web_element(self, eid):
        return FakeCell(self.m, int(str(eid).split("-")[1]))

    def execute(self, comando, params=None):
        """Rajada W3C (--turbo) e busca com atributos na resposta
        (elementResponseAttributes), como o WDA real."""
        if comando == "findElements":
            if not getattr(self.m, "attrs_na_resposta", True):
                # driver que ignora a setting: devolve so os ids
                return {"value": [{"ELEMENT": f"cell-{c.i}"} for c in self.find_elements(None, params["value"])]}
            self.m.buscas_com_atributos = getattr(self.m, "buscas_com_atributos", 0) + 1
            return {"value": [
                {"ELEMENT": f"cell-{c.i}", "element-6066-11e4-a52e-4f735466cecf": f"cell-{c.i}",
                 "label": c.get_attribute("label"), "name": c.get_attribute("label"),
                 "rect": c.rect}
                for c in self.find_elements(None, params["value"])]}
        if comando != "actions" or not self.m.aceita_w3c:
            raise WebDriverException("unknown command: " + str(comando))
        self.m.rajadas += 1
        for seq in params.get("actions", []):
            x = y = None
            for a in seq.get("actions", []):
                if a["type"] == "pointerMove":
                    x, y = a["x"], a["y"]
                elif a["type"] == "pointerDown":
                    self.m.tocar_em(x, y)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
