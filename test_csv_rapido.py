"""Modo arquivo (CSV/VCF): conferencia do numero em UMA chamada e volta ao
caminho antigo quando o driver nao devolve os textos. Roda sem iPhone.

  python3 test_csv_rapido.py
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["LL_RAPIDO"] = "1"      # estes testes exercitam o modo experimental

from ios_selectors import BASELINE  # noqa: E402
import spike_ios  # noqa: E402

CELL_ID = "PickerView_ContactCell"
PHONE_ID = "PickerView_ContactCell_PhoneNumber"


class Cel:
    """Celula falsa do picker: rotulo "Nome, recado" e um StaticText de telefone."""

    def __init__(self, nome, fone, recado="Disponivel"):
        self.nome, self.fone, self.recado = nome, fone, recado

    @property
    def label(self):
        return f"{self.nome}, {self.recado}" if self.recado else self.nome

    def get_attribute(self, a):
        return self.label if a in ("label", "name") else None

    @property
    def text(self):
        return ""

    def find_elements(self, by, val):           # caminho antigo: filho telefone
        return [FoneEl(self.fone)] if val == PHONE_ID and self.fone else []


class FoneEl:
    def __init__(self, fone):
        self.fone = fone

    def get_attribute(self, a):
        return self.fone if a == "label" else None


CLASS_CHAIN_CELL = "**/XCUIElementTypeCell"


class Driver:
    def __init__(self, cels, atributos=True, fones_a_menos=0, profundidade_necessaria=14,
                 id_acessivel=True):
        self.cels = cels
        self.atributos = atributos
        self.fones_a_menos = fones_a_menos
        # No iPhone da Isabella (iOS 26.6) as celulas NAO respondem ao id
        # PickerView_ContactCell; so aparecem pela class chain. id_acessivel=False
        # reproduz isso (e o id do telefone tambem some).
        self.id_acessivel = id_acessivel
        self.chamadas = []
        self.session_id = "sessao-falsa"
        self.command_executor = self      # como o cliente real: executor com execute()
        # As celulas do picker so aparecem a partir de certa profundidade da
        # arvore — e ela MUDA depois do 1o contato marcado (faixa de selecionados).
        self.profundidade = 12
        self.profundidade_necessaria = profundidade_necessaria

    def _enxerga(self):
        return self.profundidade >= self.profundidade_necessaria

    def create_web_element(self, eid):
        return self.cels[int(eid.split("-")[1])]

    def _e_celula(self, val):
        return (val == CELL_ID and self.id_acessivel) or val == CLASS_CHAIN_CELL

    def find_elements(self, by, val):
        self.chamadas.append(("find", val, self.profundidade))
        return list(self.cels) if self._e_celula(val) and self._enxerga() else []

    def execute(self, cmd, params):
        self.chamadas.append(("raw", params["value"], self.profundidade))
        if cmd != "findElements":
            raise Exception("nao suportado")
        if not self._enxerga():
            return {"value": []}
        if params["value"] == PHONE_ID and not self.id_acessivel:
            return {"value": []}
        if not self._e_celula(params["value"]) and params["value"] != PHONE_ID:
            return {"value": []}
        if self._e_celula(params["value"]):
            itens = []
            for i, c in enumerate(self.cels):
                item = {"ELEMENT": f"c-{i}"}
                if self.atributos:
                    item["label"] = c.label
                itens.append(item)
        else:
            itens = [{"ELEMENT": f"c-{i}", "label": c.fone}
                     for i, c in enumerate(self.cels) if c.fone]
            if self.fones_a_menos:
                itens = itens[: len(itens) - self.fones_a_menos]
        return {"value": itens}

    def update_settings(self, s):
        if "snapshotMaxDepth" in s:
            self.profundidade = int(s["snapshotMaxDepth"])


def spike(cels, **kw):
    d = Driver(cels, **kw)
    sp = spike_ios.IosSpike(d, BASELINE, speed=0.25)
    return sp, d


class CelulasSoPelaClassChain(unittest.TestCase):
    """O caso real do iPhone: o id PickerView_ContactCell nao existe; a celula
    so aparece pela 2a camada do seletor. A busca crua tem que percorrer as
    camadas como o find_all — e nunca tratar vazio como definitivo."""

    def test_acha_pela_segunda_camada_e_seleciona(self):
        cels = [Cel("Ana", "(21) 99999-0001")]
        sp, d = spike(cels, id_acessivel=False)
        self.assertEqual(len(sp._find_cells_escalating()), 1)       # 1o contato
        achadas = sp._find_cells_escalating()                        # 2o contato (bug antigo)
        self.assertEqual(len(achadas), 1, "vazio no id foi tratado como definitivo")
        self.assertEqual(sp._exact_matches(achadas, "+5521999990001", None), [cels[0]])

    def test_camada_usada_e_a_class_chain(self):
        cels = [Cel("Ana", "(21) 99999-0001")]
        sp, d = spike(cels, id_acessivel=False)
        sp._find_cells_escalating(); d.chamadas.clear()
        sp._find_cells_escalating()
        valores = [c[1] for c in d.chamadas if c[0] == "raw"]
        self.assertIn(CLASS_CHAIN_CELL, valores)


class ProfundidadeQueMuda(unittest.TestCase):
    """O bug relatado no iPhone: 1o contato selecionado, os seguintes 'NAO
    encontrado' com a celula visivel. A faixa de selecionados empurra a lista
    um nivel para baixo e a profundidade guardada deixa de enxergar."""

    def test_reescala_quando_a_lista_fica_mais_funda(self):
        cels = [Cel("Ana", "(21) 99999-0001")]
        sp, d = spike(cels, profundidade_necessaria=14)
        self.assertEqual(len(sp._find_cells_escalating()), 1)   # 1o contato: acha em 14
        self.assertEqual(sp._depth_ok, 14)
        d.profundidade_necessaria = 16                          # faixa apareceu: ficou mais fundo
        d.chamadas.clear()
        achadas = sp._find_cells_escalating()                   # 2o contato
        self.assertEqual(len(achadas), 1, "perdeu a celula visivel na tela")
        self.assertEqual(sp._depth_ok, 16)
        self.assertEqual(sp._exact_matches(achadas, "+5521999990001", None), [cels[0]])

    def test_nao_encontrado_de_verdade_continua_vazio(self):
        sp, d = spike([], profundidade_necessaria=14)
        self.assertEqual(sp._find_cells_escalating(), [])
        self.assertEqual(sp._depth_ok, 18)                      # proxima busca ja comeca funda
        self.assertEqual(sp._find_cells_escalating(), [])

    def test_sem_a_chave_tambem_reescala(self):
        os.environ.pop("LL_RAPIDO", None)
        try:
            cels = [Cel("Ana", "(21) 99999-0001")]
            sp, d = spike(cels, profundidade_necessaria=14)
            self.assertEqual(len(sp._find_cells_escalating()), 1)
            d.profundidade_necessaria = 16
            self.assertEqual(len(sp._find_cells_escalating()), 1)
            self.assertEqual(sp._depth_ok, 16)
        finally:
            os.environ["LL_RAPIDO"] = "1"


class CaminhoRapido(unittest.TestCase):

    def test_uma_chamada_para_os_telefones_e_match_exato(self):
        cels = [Cel("Ana", "(21) 99999-0001"), Cel("Bia", "(21) 99999-0002")]
        sp, d = spike(cels)
        sp._find_cells_escalating()            # 1a busca: descobre a profundidade
        achadas = sp._find_cells_escalating()  # 2a: resposta crua com rotulos
        self.assertEqual(sp._rotulos_celulas, [c.label for c in cels])
        d.chamadas.clear()
        out = sp._exact_matches(achadas, "+5521999990002", None)
        self.assertEqual(out, [cels[1]])
        self.assertEqual([c[:2] for c in d.chamadas], [("raw", PHONE_ID)])  # 1 chamada

    def test_convite_barrado_pelo_rotulo(self):
        cels = [Cel("Convidar para o WhatsApp", "(21) 99999-0003", recado="")]
        sp, d = spike(cels)
        achadas = sp._find_cells_escalating()
        self.assertEqual(sp._exact_matches(achadas, "+5521999990003", None), [])

    def test_ambiguo_continua_ambiguo(self):
        cels = [Cel("A", "(21) 99999-0009"), Cel("B", "(21) 99999-0009")]
        sp, d = spike(cels)
        achadas = sp._find_cells_escalating()
        self.assertEqual(len(sp._exact_matches(achadas, "+5521999990009", None)), 2)

    def test_driver_sem_atributos_cai_no_caminho_antigo(self):
        cels = [Cel("Ana", "(21) 99999-0001")]
        sp, d = spike(cels, atributos=False)
        sp._find_cells_escalating()
        achadas = sp._find_cells_escalating()   # tenta a resposta crua: sem rotulos
        self.assertIsNone(sp._rotulos_celulas)
        self.assertFalse(sp._attrs_ok)
        self.assertEqual(sp._exact_matches(achadas, "+5521999990001", None), [cels[0]])

    def test_contagem_diferente_nao_arrisca_alinhamento(self):
        cels = [Cel("Ana", "(21) 99999-0001"), Cel("Bia", "(21) 99999-0002")]
        sp, d = spike(cels, fones_a_menos=1)
        sp._find_cells_escalating()
        achadas = sp._find_cells_escalating()
        self.assertEqual(sp._exact_matches(achadas, "+5521999990002", None), [cels[1]])

    def test_checagem_de_seguranca_comeca_vencida_e_repete_a_cada_8(self):
        sp, d = spike([])
        self.assertEqual(sp._contatos_desde_check, sp._CHECAR_INTERVALO)
        self.assertEqual(sp._CHECAR_INTERVALO, 8)

    def test_sem_a_chave_o_comportamento_e_o_validado(self):
        """LL_RAPIDO desligado: checa a cada contato e nao usa a resposta crua."""
        os.environ.pop("LL_RAPIDO", None)
        try:
            cels = [Cel("Ana", "(21) 99999-0001")]
            sp, d = spike(cels)
            self.assertFalse(sp.rapido)
            self.assertEqual(sp._CHECAR_INTERVALO, 1)
            achadas = sp._find_cells_escalating()
            self.assertIsNone(sp._rotulos_celulas)
            self.assertEqual([c for c in d.chamadas if c[0] == "raw"], [])
            self.assertEqual(sp._exact_matches(achadas, "+5521999990001", None), [cels[0]])
        finally:
            os.environ["LL_RAPIDO"] = "1"


if __name__ == "__main__":
    unittest.main(verbosity=2)
