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


class Driver:
    def __init__(self, cels, atributos=True, fones_a_menos=0):
        self.cels = cels
        self.atributos = atributos
        self.fones_a_menos = fones_a_menos
        self.chamadas = []
        self.session_id = "sessao-falsa"
        self.command_executor = self      # como o cliente real: executor com execute()

    def create_web_element(self, eid):
        return self.cels[int(eid.split("-")[1])]

    def find_elements(self, by, val):
        self.chamadas.append(("find", val))
        return list(self.cels) if val == CELL_ID else []

    def execute(self, cmd, params):
        self.chamadas.append(("raw", params["value"]))
        if cmd != "findElements":
            raise Exception("nao suportado")
        if params["value"] == CELL_ID:
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
        pass


def spike(cels, **kw):
    d = Driver(cels, **kw)
    sp = spike_ios.IosSpike(d, BASELINE, speed=0.25)
    sp._depth_ok = 12
    return sp, d


class CaminhoRapido(unittest.TestCase):

    def test_uma_chamada_para_os_telefones_e_match_exato(self):
        cels = [Cel("Ana", "(21) 99999-0001"), Cel("Bia", "(21) 99999-0002")]
        sp, d = spike(cels)
        achadas = sp._find_cells_escalating()
        self.assertEqual(sp._rotulos_celulas, [c.label for c in cels])
        d.chamadas.clear()
        out = sp._exact_matches(achadas, "+5521999990002", None)
        self.assertEqual(out, [cels[1]])
        self.assertEqual(d.chamadas, [("raw", PHONE_ID)])   # 1 chamada, nao 3 por celula

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
        achadas = sp._find_cells_escalating()
        self.assertIsNone(sp._rotulos_celulas)
        self.assertFalse(sp._attrs_ok)
        self.assertEqual(sp._exact_matches(achadas, "+5521999990001", None), [cels[0]])

    def test_contagem_diferente_nao_arrisca_alinhamento(self):
        cels = [Cel("Ana", "(21) 99999-0001"), Cel("Bia", "(21) 99999-0002")]
        sp, d = spike(cels, fones_a_menos=1)
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
