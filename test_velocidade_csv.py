"""Economias de chamadas no ciclo por contato (modo CSV) — sem iPhone.

Cada teste conta CHAMADAS ao driver, que e o que custa tempo de verdade
(~0,25 s cada no iPhone), e prova que a decisao de clicar continua a mesma:
so match exato e unico, celula "Convidar" sempre barrada, e nunca dois toques
na mesma celula.

  python3 test_velocidade_csv.py
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("LL_RAPIDO", None)      # caminho padrao (sem atributos na resposta)
os.environ.pop("LL_ATTRS", None)

from ios_selectors import BASELINE  # noqa: E402
import spike_ios  # noqa: E402

spike_ios.time.sleep = lambda s: None

CELL_ID = "PickerView_ContactCell"
PHONE_ID = "PickerView_ContactCell_PhoneNumber"
CLASS_CHAIN = "**/XCUIElementTypeCell"


class Cel:
    """Celula do picker no iPhone da operadora: rotulo "Nome, recado", SEM
    StaticText de telefone (o filho PickerView_ContactCell_PhoneNumber e vazio)."""

    def __init__(self, nome, recado="Disponivel", fone=None, marcada=False):
        self.nome, self.recado, self.fone = nome, recado, fone
        self.marcada = marcada
        self.atributos_lidos = []
        self.cliques = 0

    @property
    def label(self):
        return f"{self.nome}, {self.recado}" if self.recado else self.nome

    def get_attribute(self, a):
        self.atributos_lidos.append(a)
        if a in ("label", "name"):
            return self.label
        if a == "selected":
            return "true" if self.marcada else "false"
        return None

    @property
    def text(self):
        return ""

    def find_elements(self, by, val):
        self.atributos_lidos.append(f"find:{val}")
        return [FoneEl(self.fone)] if val == PHONE_ID and self.fone else []

    def click(self):
        self.cliques += 1
        self.marcada = not self.marcada     # como no WhatsApp: o 2o toque desmarca


class FoneEl:
    def __init__(self, fone):
        self.fone = fone

    def get_attribute(self, a):
        return self.fone if a == "label" else None


class Driver:
    """Sem id de acessibilidade nas celulas (so class chain) — o caso real."""

    def __init__(self, cels, id_acessivel=False):
        self.cels = list(cels)
        self.id_acessivel = id_acessivel
        self.finds = []
        self.profundidade = 12

    def _e_celula(self, val):
        return (val == CELL_ID and self.id_acessivel) or val == CLASS_CHAIN

    def find_elements(self, by, val):
        self.finds.append(val)
        if self._e_celula(val) and self.profundidade >= 14:
            return list(self.cels)
        return []

    def update_settings(self, s):
        if "snapshotMaxDepth" in s:
            self.profundidade = int(s["snapshotMaxDepth"])

    def execute_script(self, script, *a):
        return {"bundleId": spike_ios.BUNDLE_ID}

    def back(self):
        pass


def spike(cels, **kw):
    d = Driver(cels, **kw)
    sp = spike_ios.IosSpike(d, BASELINE, speed=0.25)
    sp.verify_selection = False          # --trust-profile, como na operacao
    sp._type_query = lambda q: None      # digitacao nao e o objeto destes testes
    return sp, d


class CamadaLembrada(unittest.TestCase):
    """O id das celulas devolve sempre vazio neste aparelho: sem memoria, cada
    contato paga essa consulta perdida."""

    def test_primeira_busca_tenta_o_id_a_segunda_nao(self):
        sp, d = spike([Cel("Ana")])
        d.profundidade = 14
        sp.find_all("contact_cell")
        self.assertIn(CELL_ID, d.finds)
        primeira = len(d.finds)
        d.finds.clear()
        sp.find_all("contact_cell")
        self.assertEqual(d.finds, [CLASS_CHAIN])
        self.assertLess(len(d.finds), primeira)

    def test_camada_lembrada_vazia_refaz_todas(self):
        """Vazio na camada lembrada nunca e definitivo (foi o que fez os contatos
        2+ sairem como 'nao encontrado' quando a arvore ficou mais funda)."""
        sp, d = spike([Cel("Ana")])
        d.profundidade = 14
        sp.find_all("contact_cell")
        d.profundidade = 12                       # as celulas somem
        d.finds.clear()
        self.assertEqual(sp.find_all("contact_cell"), [])
        self.assertIn(CELL_ID, d.finds)           # voltou a percorrer tudo
        d.profundidade = 14
        self.assertEqual(len(sp.find_all("contact_cell")), 1)

    def test_picker_novo_esquece_a_camada(self):
        sp, d = spike([Cel("Ana")])
        d.profundidade = 14
        sp.find_all("contact_cell")
        sp._camada_ok["contact_cell"] = ("x", "y")
        sp._rotulo_anterior_h = "abc"
        sp.wait_for = lambda k, timeout=0, required=True: None
        try:
            sp.open_new_broadcast()
        except Exception:
            pass                                   # so interessa o reset
        self.assertEqual(sp._camada_ok, {})
        self.assertIsNone(sp._rotulo_anterior_h)


class TelefoneNaCelulaUnica(unittest.TestCase):

    def test_uma_celula_nao_busca_o_filho_do_telefone(self):
        sp, d = spike([Cel("Ana")])
        d.profundidade = 14
        cel = sp.find_exact_cell("+5521999990001", None)
        self.assertIs(cel, d.cels[0])
        self.assertTrue(getattr(cel, "_sct", False))
        self.assertNotIn(f"find:{PHONE_ID}", cel.atributos_lidos)

    def test_a_escolha_e_a_mesma_com_telefone_que_casa(self):
        """Num aparelho onde o filho existe e casa, a celula escolhida e a mesma."""
        sp, d = spike([Cel("Ana", fone="+55 21 99999-0001")])
        d.profundidade = 14
        self.assertIs(sp.find_exact_cell("+5521999990001", None), d.cels[0])

    def test_duas_celulas_continuam_usando_o_telefone(self):
        cels = [Cel("Ana", fone="+55 21 99999-0001"), Cel("Ana", fone="+55 21 99999-0002")]
        sp, d = spike(cels)
        d.profundidade = 14
        self.assertIs(sp.find_exact_cell("+5521999990002", None), cels[1])
        self.assertIn(f"find:{PHONE_ID}", cels[0].atributos_lidos)

    def test_convite_com_uma_celula_nunca_e_tocado(self):
        sp, d = spike([Cel("Convidar para o WhatsApp", recado="")])
        d.profundidade = 14
        self.assertIsNone(sp.find_exact_cell("+5521999990001", None))


class ConviteBarato(unittest.TestCase):

    def test_reaproveita_o_rotulo_ja_lido(self):
        cel = Cel("Ana")
        sp, d = spike([cel])
        sp._cell_text(cel)                         # 1 leitura
        cel.atributos_lidos.clear()
        self.assertFalse(sp._is_invite_cell(cel))
        self.assertEqual(cel.atributos_lidos, [])  # 0 chamadas

    def test_ainda_barra_o_convite(self):
        for rotulo in ("Convidar para o WhatsApp", "Invite to WhatsApp"):
            cel = Cel(rotulo, recado="")
            sp, _ = spike([cel])
            self.assertTrue(sp._is_invite_cell(cel), rotulo)

    def test_sem_texto_algum_ainda_le_os_atributos(self):
        class Muda(Cel):
            def get_attribute(self, a):
                self.atributos_lidos.append(a)
                return "Convidar" if a == "value" else None

        cel = Muda("")
        sp, _ = spike([cel])
        self.assertTrue(sp._is_invite_cell(cel))
        self.assertIn("value", cel.atributos_lidos)


class DoisToquesNaMesmaCelula(unittest.TestCase):
    """Se a lista ainda nao refiltrou, a celula do contato anterior continua na
    tela; toca-la de novo a DESMARCA e perde dois contatos em silencio."""

    def test_celula_identica_e_ja_marcada_nao_e_tocada(self):
        cel = Cel("Ana")
        sp, d = spike([cel])
        d.profundidade = 14
        sp.search_and_select("+5521999990001", None, "c0")
        self.assertEqual(cel.cliques, 1)
        self.assertTrue(cel.marcada)
        sp.search_and_select("+5521999990002", None, "c1")   # lista nao refiltrou
        self.assertEqual(cel.cliques, 1)                    # NAO tocou de novo
        self.assertTrue(cel.marcada)                        # o anterior continua
        self.assertEqual([r["outcome"] for r in sp.results], ["selected", "not_found"])
        self.assertEqual(sp.colisoes, 1)

    def test_homonimo_nao_marcado_e_aceito(self):
        """Mesmo rotulo, mas a celula nao esta marcada: e outro contato."""
        primeiro, segundo = Cel("Ana Silva"), Cel("Ana Silva")
        sp, d = spike([primeiro])
        d.profundidade = 14
        sp.search_and_select("+5521999990001", None, "c0")
        d.cels = [segundo]
        sp.search_and_select("+5521999990002", None, "c1")
        self.assertEqual(segundo.cliques, 1)
        self.assertEqual([r["outcome"] for r in sp.results], ["selected", "selected"])

    def test_rotulo_diferente_nao_paga_nada(self):
        primeiro, segundo = Cel("Ana"), Cel("Bruno")
        sp, d = spike([primeiro])
        d.profundidade = 14
        sp.search_and_select("+5521999990001", None, "c0")
        d.cels = [segundo]
        d.finds.clear()
        sp.search_and_select("+5521999990002", None, "c1")
        self.assertEqual(segundo.cliques, 1)
        self.assertEqual(sp.colisoes, 0)
        self.assertEqual(len(d.finds), 1)          # uma unica consulta de celulas

    def test_o_rotulo_nunca_e_guardado_em_claro(self):
        sp, d = spike([Cel("Ana Maria")])
        d.profundidade = 14
        sp.search_and_select("+5521999990001", None, "c0")
        self.assertIsNotNone(sp._rotulo_anterior_h)
        self.assertEqual(len(sp._rotulo_anterior_h), 16)
        self.assertNotIn("Ana", sp._rotulo_anterior_h)


class ChaveDaDigitacao(unittest.TestCase):

    def test_usa_a_chave_que_existe_no_driver(self):
        os.environ["LL_DIGITACAO"] = "120"
        try:
            ajustes = spike_ios._ajustes_experimentais()
        finally:
            os.environ.pop("LL_DIGITACAO")
        self.assertEqual(ajustes.get("maxTypingFrequency"), 120)
        self.assertNotIn("typingFrequency", ajustes)

    def test_desligado_por_padrao(self):
        os.environ.pop("LL_DIGITACAO", None)
        self.assertEqual(spike_ios._ajustes_experimentais(), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
