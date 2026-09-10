"""Nomear a lista e voltar para Conversas — sem iPhone.

O que precisa valer, aconteca o que acontecer na tela:
  * nunca digitar com o compositor de mensagem visivel;
  * nunca abortar a rodada por causa do nome (a lista ja foi criada);
  * voltar para Conversas antes da proxima lista.

  python3 test_nomear.py
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import spike_ios  # noqa: E402
from ios_selectors import BASELINE  # noqa: E402

spike_ios.time.sleep = lambda s: None
spike_ios._dump_inventory_on_fail = lambda d, p: None   # nao escreve arquivo nos testes


class El:
    def __init__(self, tela, nome):
        self.tela, self.nome = tela, nome
        self.cliques = 0
        self.texto = ""

    def click(self):
        self.cliques += 1
        self.tela.tocou(self.nome)

    def clear(self):
        self.texto = ""

    def send_keys(self, t):
        self.tela.digitado.append((self.nome, t, self.tela.estado))
        self.texto += t

    def get_attribute(self, a):
        return "true" if a == "enabled" else None


class Tela:
    """Maquina de estados minima do WhatsApp depois de 'Criar'."""

    def __init__(self, tem_titulo=True, tem_campo=True, tem_salvar=True, titulo_abre_info=True):
        self.estado = "conversa"         # conversa -> info -> editando
        self.digitado = []
        self.tem_titulo, self.tem_campo, self.tem_salvar = tem_titulo, tem_campo, tem_salvar
        self.titulo_abre_info = titulo_abre_info
        self.backs = 0

    def composer_visivel(self):
        return self.estado == "conversa"

    def tocou(self, nome):
        if nome == "create_button":
            self.estado = "conversa"          # "Criar" abre a conversa da lista
        elif nome == "chat_title_button" and self.titulo_abre_info:
            self.estado = "info"
        elif nome == "list_name_row":
            self.estado = "editando"
        elif nome == "save_button":
            self.estado = "info"
        elif nome == "back_button":
            self.backs += 1
            self.estado = {"editando": "info", "info": "conversa", "conversa": "conversas"}[self.estado]

    def elemento(self, chave):
        e = self.estado
        disponiveis = {
            "picker": {"create_button": True},
            "conversa": {"chat_title_button": self.tem_titulo, "back_button": True},
            "info": {"list_name_row": self.tem_campo, "back_button": True},
            "editando": {"list_name_field": self.tem_campo, "save_button": self.tem_salvar,
                         "back_button": True},
            "conversas": {"chats_tab": True},
        }
        return El(self, chave) if disponiveis.get(e, {}).get(chave) else None


class Driver:
    def __init__(self, tela):
        self.tela = tela

    def find_elements(self, by, val):
        if "XCUIElementTypeTextView" in str(val):
            return [object()] if self.tela.composer_visivel() else []
        return []

    def back(self):
        self.tela.tocou("back_button")


def spike(tela):
    sp = spike_ios.IosSpike(Driver(tela), BASELINE)
    sp.wait_for = lambda chave, timeout=0, required=True: tela.elemento(chave)
    return sp


class Nomear(unittest.TestCase):

    def test_caminho_feliz_digita_so_fora_da_conversa(self):
        tela = Tela()
        sp = spike(tela)
        self.assertTrue(sp.nomear_lista("Lista de transmissão 01"))
        self.assertEqual(len(tela.digitado), 1)
        campo, texto, estado = tela.digitado[0]
        self.assertEqual((campo, texto), ("list_name_field", "Lista de transmissão 01"))
        self.assertNotEqual(estado, "conversa")      # nunca com o compositor na tela

    def test_sem_titulo_desiste_sem_digitar_e_sem_erro(self):
        tela = Tela(tem_titulo=False)
        sp = spike(tela)
        self.assertFalse(sp.nomear_lista("Lista de transmissão 01"))
        self.assertEqual(tela.digitado, [])

    def test_titulo_que_nao_sai_da_conversa_nao_digita(self):
        """Se o toque no titulo nao abrir as informacoes, o compositor continua
        visivel: digitar ali seria escrever uma mensagem. Proibido."""
        tela = Tela(titulo_abre_info=False)
        sp = spike(tela)
        self.assertFalse(sp.nomear_lista("Lista de transmissão 01"))
        self.assertEqual(tela.digitado, [])

    def test_sem_campo_desiste(self):
        tela = Tela(tem_campo=False)
        sp = spike(tela)
        self.assertFalse(sp.nomear_lista("Lista de transmissão 01"))
        self.assertEqual(tela.digitado, [])

    def test_sem_botao_salvar_usa_return(self):
        tela = Tela(tem_salvar=False)
        sp = spike(tela)
        self.assertTrue(sp.nomear_lista("Lista de transmissão 02"))
        textos = [t for _, t, _ in tela.digitado]
        self.assertEqual(textos, ["Lista de transmissão 02", "\n"])

    def test_finish_nomeia_e_nunca_aborta_por_causa_do_nome(self):
        tela = Tela(tem_titulo=False)
        tela.estado = "picker"                    # finish() e chamado no seletor
        sp = spike(tela)
        sp.nome_lista = "Lista de transmissão 01"
        sp.results = [{"outcome": "selected"}, {"outcome": "selected"}]
        sp.finish(approve_create=True)            # cria, tenta nomear, nao levanta
        self.assertEqual(sp.state, spike_ios.State.COMPLETED)
        self.assertEqual(tela.estado, "conversa")  # criou (Criar foi tocado)
        self.assertEqual(tela.digitado, [])        # e nao digitou nada na conversa


class VoltarParaConversas(unittest.TestCase):

    def test_da_conversa_ate_conversas(self):
        tela = Tela()
        sp = spike(tela)
        sp.voltar_para_conversas()
        self.assertEqual(tela.estado, "conversas")
        self.assertEqual(tela.backs, 1)

    def test_das_informacoes_ate_conversas(self):
        tela = Tela()
        tela.estado = "editando"
        sp = spike(tela)
        sp.voltar_para_conversas()
        self.assertEqual(tela.estado, "conversas")
        self.assertEqual(tela.backs, 3)

    def test_nomeia_e_volta_na_sequencia(self):
        tela = Tela()
        sp = spike(tela)
        self.assertTrue(sp.nomear_lista("Lista de transmissão 03"))
        sp.voltar_para_conversas()
        self.assertEqual(tela.estado, "conversas")


if __name__ == "__main__":
    unittest.main(verbosity=2)
