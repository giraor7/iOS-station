"""Listas em sequencia e sessao em varios dias, no modo lista de contatos (CSV)
— sem iPhone.

O que precisa valer, aconteca o que acontecer na tela:
  * depois de cada lista criada, a estacao volta para Conversas ANTES de
    abrir a proxima;
  * o progresso da lista e gravado antes da volta (se a volta falhar, a lista
    criada nao e refeita na retomada);
  * quem ja esta numa lista criada fica de fora da rodada seguinte (com o
    mesmo arquivo ou outro); registros anteriores nunca sao sobrescritos;
  * so conta como criada depois do toque em "Criar";
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
import sessao  # noqa: E402
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


class ListaCriadaSoDepoisDoCriar(unittest.TestCase):
    """finish() com menos de 2 selecionados termina COMPLETED sem criar nada:
    o runner nao pode gravar isso como lista criada."""

    def test_menos_de_dois_nao_marca_criada(self):
        sp = spike_ios.IosSpike(Driver(Tela()), BASELINE)
        sp.wait_for = lambda chave, timeout=0, required=True: None
        sp.results = [{"outcome": "selected"}, {"outcome": "not_found"}]
        sp.finish(approve_create=True)
        self.assertEqual(sp.state, spike_ios.State.COMPLETED)
        self.assertFalse(sp.lista_criada)

    def test_toque_em_criar_marca_criada(self):
        tela = Tela()
        tela.estado = "picker"
        sp = spike(tela)
        sp.wait_for = lambda chave, timeout=0, required=True: El(tela, chave) if chave == "create_button" else None
        sp.results = [{"outcome": "selected"}, {"outcome": "selected"}]
        sp.finish(approve_create=True)
        self.assertTrue(sp.lista_criada)
        sp2 = spike(Tela())
        sp2.results = [{"outcome": "selected"}, {"outcome": "selected"}]
        sp2.wait_for = lambda chave, timeout=0, required=True: El(Tela(), chave)
        sp2.finish(approve_create=False)          # simulacao: nao toca em Criar
        self.assertFalse(sp2.lista_criada)


# ---------------- parte 2: run_ios.main() com um IosSpike falso ----------------

CHAMADAS: list[tuple] = []


class SpikeFalso:
    """Registra a ordem das chamadas; nao toca em nada."""
    instancias = 0
    contador = 0                 # contatos procurados na rodada (global)
    nao_encontrados: set = set()  # posicoes (1-based, na rodada) que saem 'not_found'
    volta_falha = False

    def __init__(self, driver, profile, speed=1.0):
        SpikeFalso.instancias += 1
        self.n = SpikeFalso.instancias
        self.state = spike_ios.State.IDLE
        self.results = []
        self.verify_selection = True
        self.lista_criada = False

    def transition(self, s):
        self.state = s

    def open_new_broadcast(self):
        CHAMADAS.append(("abrir", self.n))

    def search_and_select(self, e164, name=None, label=""):
        SpikeFalso.contador += 1
        CHAMADAS.append(("selecionar", self.n))
        achou = SpikeFalso.contador not in SpikeFalso.nao_encontrados
        self.results.append({"outcome": "selected" if achou else "not_found"})

    def finish(self, approve_create):
        selecionados = sum(1 for r in self.results if r["outcome"] == "selected")
        criar = approve_create and selecionados >= 2
        CHAMADAS.append(("criar" if criar else "parar", self.n))
        self.lista_criada = criar
        self.state = spike_ios.State.COMPLETED

    def voltar_para_conversas(self):
        CHAMADAS.append(("voltar", self.n))
        if SpikeFalso.volta_falha:
            raise spike_ios.UiChanged("tela presa (simulado)")


class DriverFalso:
    def quit(self):
        pass


def csv_de(n, pasta, nome="contatos.csv"):
    p = os.path.join(pasta, nome)
    with open(p, "w", encoding="utf-8") as f:
        f.write("name,phone\n")
        for i in range(1, n + 1):
            f.write(f"Contato {i:02d},+55 21 99876-54{i:02d}\n")
    return p


def rodar(argv):
    CHAMADAS.clear()
    SpikeFalso.instancias = 0
    SpikeFalso.contador = 0
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
        SpikeFalso.nao_encontrados = set()

    def comuns(self, *extras, csv=None):
        return ["--csv", csv or self.csv, "--trust-profile", "--progress", self.prog,
                "--pace", "0", "--pace-lists", "0", "--limite-por-lista", "5", *extras]

    def test_duas_listas_volta_para_conversas_entre_elas(self):
        rc = rodar(self.comuns("--approve-create"))
        self.assertEqual(rc, 0)
        esperado = ([("abrir", 1)] + [("selecionar", 1)] * 5 + [("criar", 1), ("voltar", 1)]
                    + [("abrir", 2)] + [("selecionar", 2)] * 5 + [("criar", 2), ("voltar", 2)])
        self.assertEqual(CHAMADAS, esperado)
        listas = progresso(self.prog)
        self.assertEqual(len(listas), 2)
        self.assertTrue(all(e["completed"] for e in listas.values()))
        self.assertTrue(all(e["csv"] == "contatos.csv" and e["quando"] for e in listas.values()))

    def test_max_lists_para_depois_da_primeira(self):
        rc = rodar(self.comuns("--approve-create", "--max-lists", "1"))
        self.assertEqual(rc, 0)
        self.assertEqual(SpikeFalso.instancias, 1)
        self.assertIn(("voltar", 1), CHAMADAS)     # volta mesmo sendo a ultima
        listas = progresso(self.prog)
        self.assertEqual(len(listas), 1)
        self.assertTrue(listas["Transmissão 001"]["completed"])

    def test_dia_seguinte_so_os_restantes_viram_lista(self):
        """Dia 1: 5 de 10 entram. Dia 2, MESMO arquivo: so os outros 5 sao
        procurados, o registro do dia 1 continua la e ninguem e repetido."""
        rodar(self.comuns("--approve-create", "--max-lists", "1"))
        rc = rodar(self.comuns("--approve-create"))
        self.assertEqual(rc, 0)
        self.assertEqual(SpikeFalso.instancias, 1)          # so uma lista: os 5 restantes
        self.assertEqual(CHAMADAS.count(("selecionar", 1)), 5)
        listas = progresso(self.prog)
        self.assertEqual(len(listas), 2)                    # nada sobrescrito
        hashes = [r["hash"] for e in listas.values() for r in e["results"]]
        self.assertEqual(len(hashes), 10)
        self.assertEqual(len(set(hashes)), 10)              # ninguem em duas listas
        # terceiro dia: nao ha mais o que criar
        rc = rodar(self.comuns("--approve-create"))
        self.assertEqual(rc, 0)
        self.assertEqual(SpikeFalso.instancias, 0)

    def test_arquivo_novo_com_contatos_a_mais(self):
        """O CSV do dia 2 tem os 10 de antes mais 3 novos: so os 3 novos e os que
        faltavam sao procurados."""
        rodar(self.comuns("--approve-create", "--max-lists", "1"))     # 5 adicionados
        maior = csv_de(13, self.pasta, "contatos2.csv")
        rodar(self.comuns("--approve-create", csv=maior))
        self.assertEqual(CHAMADAS.count(("selecionar", 1)) + CHAMADAS.count(("selecionar", 2)), 8)

    def test_progresso_gravado_antes_da_volta(self):
        SpikeFalso.volta_falha = True
        rc = rodar(self.comuns("--approve-create"))
        self.assertEqual(rc, 4)                              # UI_CHANGED
        listas = progresso(self.prog)
        self.assertTrue(listas["Transmissão 001"]["completed"])   # criada: nao refazer
        self.assertEqual(len(listas), 1)
        self.assertNotIn(("abrir", 2), CHAMADAS)

    def test_sem_approve_nao_cria_nao_volta_e_nao_marca_ninguem(self):
        rc = rodar(self.comuns())
        self.assertEqual(rc, 0)
        self.assertNotIn(("criar", 1), CHAMADAS)
        self.assertNotIn(("voltar", 1), CHAMADAS)
        self.assertFalse(progresso(self.prog)["Transmissão 001"]["completed"])
        rodar(self.comuns())                                  # simulacao de novo: os 10 continuam la
        self.assertEqual(CHAMADAS.count(("selecionar", 1)) + CHAMADAS.count(("selecionar", 2)), 10)

    def test_menos_de_dois_selecionados_nao_e_lista_criada(self):
        """Lote 2 com 4 'nao encontrado': Criar nao e tocado, o registro fica
        completed=False, nao ha volta para Conversas, e no dia seguinte os 4
        ficam de fora (ou voltam com --repetir-nao-encontrados)."""
        SpikeFalso.nao_encontrados = {6, 7, 8, 9}
        rc = rodar(self.comuns("--approve-create"))
        self.assertEqual(rc, 0)
        self.assertIn(("parar", 2), CHAMADAS)
        self.assertNotIn(("voltar", 2), CHAMADAS)
        listas = progresso(self.prog)
        self.assertEqual([e["completed"] for e in listas.values()], [True, False])
        # dia seguinte: sobra 1 restante (o contato 10) -> lote pequeno, pulado
        rodar(self.comuns("--approve-create"))
        self.assertEqual(SpikeFalso.instancias, 0)
        # pedindo para repetir: os 4 + o 10 voltam a ser procurados
        SpikeFalso.nao_encontrados = set()
        rodar(self.comuns("--approve-create", "--repetir-nao-encontrados"))
        self.assertEqual(CHAMADAS.count(("selecionar", 1)), 5)
        self.assertIn(("criar", 1), CHAMADAS)

    def test_exportar_grava_csvs_e_nao_toca_no_iphone(self):
        SpikeFalso.nao_encontrados = {3}
        rodar(self.comuns("--approve-create", "--max-lists", "1"))     # 4 adicionados, 1 nao encontrado
        rc = rodar(self.comuns("--approve-create", "--exportar"))
        self.assertEqual(rc, 0)
        self.assertEqual(SpikeFalso.instancias, 0)
        base = os.path.join(self.pasta, "contatos")
        with open(base + ".restantes.csv", encoding="utf-8") as f:
            self.assertEqual(len(f.read().splitlines()), 1 + 5)
        with open(base + ".adicionados.csv", encoding="utf-8") as f:
            self.assertEqual(len(f.read().splitlines()), 1 + 4)
        with open(base + ".nao-adicionados.csv", encoding="utf-8") as f:
            linhas = f.read().splitlines()
        self.assertEqual(linhas[0], "name,phone,motivo")
        self.assertEqual(len(linhas), 2)
        self.assertTrue(linhas[1].endswith(",nao_encontrado"))
        # o CSV de restantes exportado, importado no dia seguinte, gera 1 lista com os 5
        rc = rodar(self.comuns("--approve-create", csv=base + ".restantes.csv"))
        self.assertEqual(rc, 0)
        self.assertEqual(CHAMADAS.count(("selecionar", 1)), 5)
        self.assertIn(("criar", 1), CHAMADAS)


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
