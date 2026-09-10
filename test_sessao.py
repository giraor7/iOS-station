"""Sessao (dividir a criacao em dias) — sem iPhone.

  python3 test_sessao.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import batching  # noqa: E402
import sessao  # noqa: E402


def contatos(n):
    return [batching.NormalizedContact(f"+55219987654{i:02d}", f"Contato {i}") for i in range(1, n + 1)]


def h(c):
    return sessao.hash_numero(c.e164)


def entrada(hashes, outcome="selected", completed=True, quando=None):
    e = {"completed": completed, "results": [{"hash": x, "outcome": outcome} for x in hashes]}
    if quando:
        e["quando"] = quando
    return e


class Resumir(unittest.TestCase):

    def test_sem_progresso_tudo_e_restante(self):
        cs = contatos(4)
        ses = sessao.resumir(cs, {"lists": {}})
        self.assertEqual(ses.restantes, cs)
        self.assertEqual((ses.adicionados, ses.nao_adicionados, ses.listas_criadas), ([], [], 0))

    def test_registro_antigo_sem_quando_conta_como_adicionado(self):
        cs = contatos(3)
        prog = {"lists": {"Transmissão 001": entrada([h(cs[0]), h(cs[1])])}}
        ses = sessao.resumir(cs, prog)
        self.assertEqual(ses.adicionados, cs[:2])
        self.assertEqual(ses.restantes, cs[2:])
        self.assertEqual(ses.listas_criadas, 1)

    def test_simulacao_ou_lista_nao_criada_nao_conta(self):
        cs = contatos(2)
        prog = {"lists": {"Transmissão 001": entrada([h(cs[0])], completed=False)}}
        ses = sessao.resumir(cs, prog)
        self.assertEqual(ses.adicionados, [])
        self.assertEqual(ses.restantes, cs)
        self.assertEqual(ses.listas_criadas, 0)

    def test_nao_encontrado_fica_de_fora_por_padrao(self):
        cs = contatos(3)
        prog = {"lists": {"Transmissão 001": {"completed": True, "results": [
            {"hash": h(cs[0]), "outcome": "selected"},
            {"hash": h(cs[1]), "outcome": "not_found"},
            {"hash": h(cs[2]), "outcome": "ambiguous"}]}}}
        ses = sessao.resumir(cs, prog)
        self.assertEqual(ses.adicionados, cs[:1])
        self.assertEqual(ses.restantes, [])
        self.assertEqual([m for _, m in ses.nao_adicionados], ["nao_encontrado", "ambiguo"])
        de_novo = sessao.resumir(cs, prog, repetir_nao_encontrados=True)
        self.assertEqual(de_novo.restantes, cs[1:])
        self.assertEqual(de_novo.nao_adicionados, [])

    def test_nao_encontrado_num_dia_e_adicionado_no_outro(self):
        cs = contatos(1)
        prog = {"lists": {
            "Transmissão 001": entrada([h(cs[0])], outcome="not_found", quando="2026-09-08T10:00"),
            "Transmissão 001 @ 2026-09-09T09:00": entrada([h(cs[0])], quando="2026-09-09T09:00"),
        }}
        ses = sessao.resumir(cs, prog)
        self.assertEqual(ses.adicionados, cs)
        self.assertEqual(ses.nao_adicionados, [])
        self.assertEqual(ses.ultima, "2026-09-09T09:00")

    def test_hash_bate_com_o_do_runner(self):
        import run_ios
        self.assertEqual(run_ios.num_hash("+5521999999999"), sessao.hash_numero("+5521999999999"))
        self.assertEqual(len(sessao.hash_numero("+5521999999999")), 16)

    def test_progresso_corrompido_ou_ausente_vira_vazio(self):
        pasta = tempfile.mkdtemp()
        self.assertEqual(sessao.carregar_progresso(os.path.join(pasta, "nada.json")), {"lists": {}})
        ruim = os.path.join(pasta, "ruim.json")
        with open(ruim, "w", encoding="utf-8") as f:
            f.write("{isto nao e json")
        self.assertEqual(sessao.carregar_progresso(ruim), {"lists": {}})
        with open(ruim, "w", encoding="utf-8") as f:
            json.dump(["lista", "errada"], f)
        self.assertEqual(sessao.carregar_progresso(ruim), {"lists": {}})

    def test_descrever_so_contagens(self):
        cs = contatos(3)
        prog = {"lists": {"Transmissão 001": {"completed": True, "quando": "2026-09-09T14:03", "results": [
            {"hash": h(cs[0]), "outcome": "selected"}, {"hash": h(cs[1]), "outcome": "not_found"}]}}}
        texto = sessao.descrever(sessao.resumir(cs, prog))
        self.assertIn("1 ja adicionado(s) em 1 lista(s)", texto)
        self.assertIn("2026-09-09 14:03", texto)
        self.assertIn("1 nao encontrado(s)", texto)
        self.assertIn("1 restante(s)", texto)
        for c in cs:
            self.assertNotIn(c.e164, texto)
            self.assertNotIn(c.name, texto)


class Exportar(unittest.TestCase):

    def setUp(self):
        self.pasta = tempfile.mkdtemp()
        self.origem = os.path.join(self.pasta, "contatos.csv")
        with open(self.origem, "w", encoding="utf-8") as f:
            f.write("name,phone\n")

    def _ler(self, caminho):
        with open(caminho, encoding="utf-8", newline="") as f:
            return list(csv.reader(f))

    def test_grava_tres_arquivos_ao_lado_do_csv(self):
        cs = contatos(5)
        ses = sessao.Sessao(adicionados=cs[:2], restantes=cs[2:4],
                            nao_adicionados=[(cs[4], "nao_encontrado")])
        saidas = sessao.exportar(self.origem, ses)
        self.assertEqual(set(saidas), {"restantes", "adicionados", "nao-adicionados"})
        for caminho in saidas.values():
            self.assertEqual(os.path.dirname(caminho), self.pasta)
        self.assertEqual(self._ler(saidas["restantes"]),
                         [["name", "phone"], ["Contato 3", cs[2].e164], ["Contato 4", cs[3].e164]])
        self.assertEqual(self._ler(saidas["adicionados"])[1:],
                         [["Contato 1", cs[0].e164], ["Contato 2", cs[1].e164]])
        self.assertEqual(self._ler(saidas["nao-adicionados"]),
                         [["name", "phone", "motivo"], ["Contato 5", cs[4].e164, "nao_encontrado"]])

    def test_sem_nao_adicionados_nao_cria_o_terceiro(self):
        cs = contatos(2)
        saidas = sessao.exportar(self.origem, sessao.Sessao(restantes=cs))
        self.assertEqual(set(saidas), {"restantes", "adicionados"})
        self.assertEqual(self._ler(saidas["adicionados"]), [["name", "phone"]])

    def test_restantes_e_importavel_pelo_runner(self):
        cs = contatos(3)
        saidas = sessao.exportar(self.origem, sessao.Sessao(restantes=cs))
        lidos = batching.normalize(batching.load_csv(saidas["restantes"]), "BR")
        self.assertEqual([c.e164 for c in lidos], [c.e164 for c in cs])

    def test_nome_vazio_nao_quebra(self):
        c = batching.NormalizedContact("+5521998765401", "")
        saidas = sessao.exportar(self.origem, sessao.Sessao(restantes=[c]))
        self.assertEqual(self._ler(saidas["restantes"])[1], ["", c.e164])


if __name__ == "__main__":
    unittest.main(verbosity=2)
