"""Listas em sequencia no modo lista de contatos (CSV) — sem iPhone.

O que precisa valer, aconteca o que acontecer na tela:
  * depois de cada lista criada, a estacao volta para Conversas ANTES de
    abrir a proxima;
  * o progresso da lista e gravado antes da volta (se a volta falhar, a lista
    criada nao e refeita na retomada);
  * uma lista ja concluida e pulada na retomada;
  * o lote nunca passa de 256 nem fica abaixo de 2.

  python3 test_sequencia.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run_ios  # noqa: E402
import spike_ios  # noqa: E402
from ios_selectors import BASELINE  # noqa: E402

spike_ios.time.sleep = lambda s: None
run_ios.time.sleep = lambda s: None


# ---------------- parte 1: voltar_para_conversas com uma tela falsa ----------------

class El:
    def __init__(self, tela, nome):
        self.tela, self.nome = tela, nome

    def click(self):
        self.tela.tocou(self.nome)

    def get_attribute(self, a):
        return "true"


class Tela:
    """Depois de 'Criar': conversa -> Conversas. (info = tela de informacoes.)"""

    def __init__(self, botao_voltar_na_conversa=True, presa=False):
        self.estado = "conversa"
        self.backs = 0
        self.botao_voltar_na_conversa = botao_voltar_na_conversa
        self.presa = presa

    def tocou(self, nome):
        if nome == "back_button":
            self.backs += 1
            if not self.presa:
                self.estado = {"info": "conversa", "conversa": "conversas"}.get(self.estado, self.estado)

    def elemento(self, chave):
        disponiveis = {
            "info": {"back_button": True},
            "conversa": {"back_button": self.botao_voltar_na_conversa},
            "conversas": {"chats_tab": True},
        }
        return El(self, chave) if disponiveis.get(self.estado, {}).get(chave) else None


class Driver:
    def __init__(self, tela):
        self.tela = tela

    def find_elements(self, by, val):
        return []

    def back(self):
        self.tela.tocou("back_button")


def spike(tela):
    sp = spike_ios.IosSpike(Driver(tela), BASELINE)
    sp.wait_for = lambda chave, timeout=0, required=True: tela.elemento(chave)
    return sp


class VoltarParaConversas(unittest.TestCase):

    def test_da_conversa_ate_conversas(self):
        tela = Tela()
        spike(tela).voltar_para_conversas()
        self.assertEqual(tela.estado, "conversas")
        self.assertEqual(tela.backs, 1)

    def test_das_informacoes_ate_conversas(self):
        tela = Tela()
        tela.estado = "info"
        spike(tela).voltar_para_conversas()
        self.assertEqual(tela.estado, "conversas")
        self.assertEqual(tela.backs, 2)

    def test_sem_botao_voltar_usa_back_do_driver(self):
        """Como no iPhone real (2026-09-09): dentro da conversa o seletor do
        Voltar nao casa; driver.back() tem de resolver."""
        tela = Tela(botao_voltar_na_conversa=False)
        spike(tela).voltar_para_conversas()
        self.assertEqual(tela.estado, "conversas")

    def test_tela_presa_levanta_ui_changed(self):
        tela = Tela(presa=True)
        with self.assertRaises(spike_ios.UiChanged):
            spike(tela).voltar_para_conversas()
        self.assertLessEqual(tela.backs, 4)

    def test_ja_em_conversas_nao_toca_em_nada(self):
        tela = Tela()
        tela.estado = "conversas"
        spike(tela).voltar_para_conversas()
        self.assertEqual(tela.backs, 0)


# ---------------- parte 2: run_ios.main() com um IosSpike falso ----------------

CHAMADAS: list[tuple] = []


class SpikeFalso:
    """Registra a ordem das chamadas; nao toca em nada."""
    instancias = 0
    volta_falha = False

    def __init__(self, driver, profile, speed=1.0):
        SpikeFalso.instancias += 1
        self.n = SpikeFalso.instancias
        self.state = spike_ios.State.IDLE
        self.results = []
        self.verify_selection = True

    def transition(self, s):
        self.state = s

    def open_new_broadcast(self):
        CHAMADAS.append(("abrir", self.n))

    def search_and_select(self, e164, name=None, label=""):
        CHAMADAS.append(("selecionar", self.n))
        self.results.append({"outcome": "selected"})

    def finish(self, approve_create):
        CHAMADAS.append(("criar" if approve_create else "parar", self.n))
        self.state = spike_ios.State.COMPLETED

    def voltar_para_conversas(self):
        CHAMADAS.append(("voltar", self.n))
        if SpikeFalso.volta_falha:
            raise spike_ios.UiChanged("tela presa (simulado)")


class DriverFalso:
    def quit(self):
        pass


def csv_de(n, pasta):
    p = os.path.join(pasta, "contatos.csv")
    with open(p, "w", encoding="utf-8") as f:
        f.write("name,phone\n")
        for i in range(1, n + 1):
            f.write(f"Contato {i:02d},+55 21 99876-54{i:02d}\n")
    return p


def rodar(argv):
    CHAMADAS.clear()
    SpikeFalso.instancias = 0
    run_ios.IosSpike = SpikeFalso
    run_ios.build_driver = lambda server, bundle=None: DriverFalso()
    run_ios.exigir_appium = lambda server: True
    velho = sys.argv
    sys.argv = ["run_ios.py"] + argv
    try:
        return run_ios.main()
    finally:
        sys.argv = velho


def progresso(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["lists"]


class ListasEmSequencia(unittest.TestCase):

    def setUp(self):
        self.pasta = tempfile.mkdtemp()
        self.csv = csv_de(10, self.pasta)
        self.prog = os.path.join(self.pasta, "progress.json")
        SpikeFalso.volta_falha = False

    def comuns(self, *extras):
        return ["--csv", self.csv, "--trust-profile", "--progress", self.prog,
                "--pace", "0", "--pace-lists", "0", "--limite-por-lista", "5", *extras]

    def test_duas_listas_volta_para_conversas_entre_elas(self):
        rc = rodar(self.comuns("--approve-create"))
        self.assertEqual(rc, 0)
        esperado = ([("abrir", 1)] + [("selecionar", 1)] * 5 + [("criar", 1), ("voltar", 1)]
                    + [("abrir", 2)] + [("selecionar", 2)] * 5 + [("criar", 2), ("voltar", 2)])
        self.assertEqual(CHAMADAS, esperado)
        listas = progresso(self.prog)
        self.assertTrue(listas["Transmissão 001"]["completed"])
        self.assertTrue(listas["Transmissão 002"]["completed"])
        self.assertEqual(len(listas["Transmissão 002"]["results"]), 5)

    def test_max_lists_para_depois_da_primeira(self):
        rc = rodar(self.comuns("--approve-create", "--max-lists", "1"))
        self.assertEqual(rc, 0)
        self.assertEqual(SpikeFalso.instancias, 1)
        self.assertIn(("voltar", 1), CHAMADAS)     # volta mesmo sendo a ultima
        listas = progresso(self.prog)
        self.assertTrue(listas["Transmissão 001"]["completed"])
        self.assertNotIn("Transmissão 002", listas)

    def test_retomada_pula_lista_concluida(self):
        rodar(self.comuns("--approve-create", "--max-lists", "1"))
        rc = rodar(self.comuns("--approve-create"))
        self.assertEqual(rc, 0)
        self.assertEqual(SpikeFalso.instancias, 1)          # so a 002
        self.assertEqual(CHAMADAS[0], ("abrir", 1))
        self.assertTrue(progresso(self.prog)["Transmissão 002"]["completed"])

    def test_progresso_gravado_antes_da_volta(self):
        SpikeFalso.volta_falha = True
        rc = rodar(self.comuns("--approve-create"))
        self.assertEqual(rc, 4)                              # UI_CHANGED
        listas = progresso(self.prog)
        self.assertTrue(listas["Transmissão 001"]["completed"])   # criada: nao refazer
        self.assertNotIn("Transmissão 002", listas)
        self.assertNotIn(("abrir", 2), CHAMADAS)

    def test_sem_approve_nao_cria_e_nao_volta(self):
        rc = rodar(self.comuns())
        self.assertEqual(rc, 0)
        self.assertNotIn(("criar", 1), CHAMADAS)
        self.assertNotIn(("voltar", 1), CHAMADAS)
        self.assertFalse(progresso(self.prog)["Transmissão 001"]["completed"])


class LimiteDeLote(unittest.TestCase):

    def test_padrao_e_256(self):
        self.assertEqual(run_ios.limite_de_lote(0), 256)
        self.assertEqual(run_ios.limite_de_lote(-3), 256)
        self.assertEqual(run_ios.limite_de_lote(None), 256)

    def test_nunca_passa_de_256(self):
        self.assertEqual(run_ios.limite_de_lote(300), 256)
        self.assertEqual(run_ios.limite_de_lote(256), 256)

    def test_nunca_abaixo_de_2(self):
        self.assertEqual(run_ios.limite_de_lote(1), 2)
        self.assertEqual(run_ios.limite_de_lote(5), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
