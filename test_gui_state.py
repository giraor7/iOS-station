"""Testes da logica da interface — rodam SEM janela, sem Appium, sem iPhone.

Cobrem as regras que, se quebrarem, quebram a operacao: validacao de DDD,
limite de 1 a 36 listas por rodada, quando o botao Iniciar pode ligar,
exclusividade entre arquivo e Scroll Livre, e o padrao de seguranca
(simulacao, sem --approve-create).

  python3 test_gui_state.py
"""

from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gui_state as st  # noqa: E402


class DDD(unittest.TestCase):

    def test_aceita_separadores_e_ignora_repetido(self):
        validos, invalidos = st.parse_ddds("21, 22;24 21")
        self.assertEqual(validos, ["21", "22", "24"])
        self.assertEqual(invalidos, [])

    def test_recusa_inexistente_e_lixo(self):
        validos, invalidos = st.parse_ddds("21,99,00,abc,1")
        self.assertEqual(validos, ["21", "99"])          # 99 existe (MA)
        self.assertEqual(invalidos, ["00", "abc", "1"])

    def test_vazio_significa_todos(self):
        self.assertEqual(st.parse_ddds(""), ([], []))
        self.assertEqual(st.formatar_ddds([]), "")
        self.assertEqual(st.descrever_ddds([]), "todos os DDDs")

    def test_argumento_para_a_linha_de_comando(self):
        self.assertEqual(st.formatar_ddds(["21", "22", "24"]), "21,22,24")

    def test_ddds_de_destaque_existem_na_tabela(self):
        for cod in st.DDDS_DESTAQUE:
            self.assertTrue(st.ddd_valido(cod), cod)


class LimiteDeListas(unittest.TestCase):

    def test_faixa_valida(self):
        for texto, esperado in (("1", 1), ("36", 36), ("  7 ", 7)):
            valor, erro = st.validar_listas(texto)
            self.assertEqual(valor, esperado)
            self.assertEqual(erro, "")

    def test_recusa_fora_da_faixa(self):
        for texto in ("0", "37", "9999", "-3"):
            valor, erro = st.validar_listas(texto)
            self.assertIsNone(valor, texto)
            self.assertTrue(erro)

    def test_recusa_nao_numero(self):
        for texto in ("", "  ", "abc", "3,5"):
            valor, erro = st.validar_listas(texto)
            self.assertIsNone(valor)
            self.assertTrue(erro)

    def test_clamp_nunca_sai_da_faixa(self):
        self.assertEqual(st.clamp_listas(0), 1)
        self.assertEqual(st.clamp_listas(9999), 36)
        self.assertEqual(st.clamp_listas(12), 12)


class Seguranca(unittest.TestCase):

    def test_simulacao_nao_aprova_criacao(self):
        self.assertFalse(st.aprova_criacao(st.Execucao.SIMULACAO))

    def test_so_o_modo_real_aprova(self):
        self.assertTrue(st.aprova_criacao(st.Execucao.REAL))

    def test_limites_do_produto_intactos(self):
        self.assertEqual(st.LIMITE_LISTA, 256)
        self.assertEqual(st.MIN_DESTINATARIOS, 2)
        self.assertEqual(st.MAX_LISTAS_RODADA, 36)


class Lotes(unittest.TestCase):

    def test_contagem_de_listas(self):
        self.assertEqual(st.contar_listas(0), 0)
        self.assertEqual(st.contar_listas(1), 1)
        self.assertEqual(st.contar_listas(256), 1)
        self.assertEqual(st.contar_listas(257), 2)
        self.assertEqual(st.contar_listas(9216), 36)

    def test_ultimo_lote_pequeno_demais(self):
        self.assertEqual(st.lotes_pequenos(257), 1)   # sobra 1: nao vira lista
        self.assertEqual(st.lotes_pequenos(258), 0)   # sobra 2: vira lista
        self.assertEqual(st.lotes_pequenos(512), 0)


class ArquivoDeContatos(unittest.TestCase):

    def _csv(self, linhas):
        caminho = os.path.join(tempfile.mkdtemp(), "contatos.csv")
        with open(caminho, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["name", "phone"])
            w.writerows(linhas)
        return caminho

    def test_conta_validos_invalidos_e_repetidos(self):
        caminho = self._csv([
            ["A", "+55 21 99999-0001"],
            ["B", "+55 21 99999-0002"],
            ["C", "+55 21 99999-0001"],   # repetido
            ["D", "123"],                 # invalido
            ["E", "nao e telefone"],      # invalido
        ])
        r = st.analisar_arquivo(caminho)
        self.assertEqual(r.tipo, "CSV")
        self.assertEqual(r.encontrados, 5)
        self.assertEqual(r.validos, 2)
        self.assertEqual(r.duplicados, 1)
        self.assertEqual(r.invalidos, 2)
        self.assertTrue(r.ok)

    def test_dependencia_ausente_diz_o_que_rodar(self):
        import builtins
        original = builtins.__import__

        def sem_phonenumbers(name, *a, **k):
            if name in ("batching", "phonenumbers"):
                raise ImportError(f"No module named '{name}'", name=name)
            return original(name, *a, **k)

        builtins.__import__ = sem_phonenumbers
        try:
            r = st.analisar_arquivo(self._csv([["A", "+55 21 99999-0001"]]))
        finally:
            builtins.__import__ = original
        self.assertFalse(r.ok)
        self.assertIn("pip install -r requirements.txt", r.erro)

    def test_arquivo_ilegivel_vira_erro_explicado(self):
        caminho = self._csv([["A", "+55 21 99999-0001"]])
        with open(caminho, "w", encoding="utf-8") as f:
            f.write("coluna_errada\nvalor\n")
        r = st.analisar_arquivo(caminho)
        self.assertFalse(r.ok)
        self.assertIn("phone", r.erro)

    def test_filtro_de_ddd_bate_com_o_runner(self):
        caminho = self._csv([
            ["A", "+55 21 99999-0001"],
            ["B", "+55 22 99999-0002"],
            ["C", "+55 11 99999-0003"],
        ])
        r = st.analisar_arquivo(caminho)
        self.assertEqual(len(st.aplicar_filtro_ddd(r.contatos, [])), 3)
        self.assertEqual(len(st.aplicar_filtro_ddd(r.contatos, ["21"])), 1)
        self.assertEqual(len(st.aplicar_filtro_ddd(r.contatos, ["21", "22"])), 2)


def _ambiente(iphone=1, appium=True, wda="", verificado=True) -> st.Ambiente:
    return st.Ambiente(verificado=verificado, appium_ok=appium,
                       iphone_count=iphone, wda_bundle=wda)


class BotaoIniciar(unittest.TestCase):

    def _resumo_ok(self) -> st.ResumoArquivo:
        r = st.ResumoArquivo(caminho="/tmp/x.csv", tipo="CSV")
        r.encontrados = r.validos = 300
        return r

    def test_liga_com_tudo_pronto_no_modo_arquivo(self):
        itens = st.itens_prontidao(_ambiente(), st.Fonte.ARQUIVO, self._resumo_ok(), 2)
        pode, motivo = st.pode_iniciar(itens, executando=False)
        self.assertTrue(pode, motivo)

    def test_nao_liga_sem_arquivo(self):
        itens = st.itens_prontidao(_ambiente(), st.Fonte.ARQUIVO, None, 0)
        pode, motivo = st.pode_iniciar(itens, executando=False)
        self.assertFalse(pode)
        self.assertIn("fonte de contatos", motivo.lower())

    def test_nao_liga_sem_iphone_e_explica(self):
        itens = st.itens_prontidao(_ambiente(iphone=0), st.Fonte.ARQUIVO,
                                   self._resumo_ok(), 2)
        iphone = next(i for i in itens if i.chave == "iphone")
        self.assertEqual(iphone.estado, st.Estado.FALTA)
        self.assertIn("Conecte", iphone.orientacao)
        self.assertFalse(st.pode_iniciar(itens, executando=False)[0])

    def test_sem_idevice_id_explica_a_ferramenta_e_nao_o_cabo(self):
        amb = _ambiente(iphone=0)
        amb.idevice_ok = False
        itens = st.itens_prontidao(amb, st.Fonte.SCROLL, None, 2)
        iphone = next(i for i in itens if i.chave == "iphone")
        self.assertEqual(iphone.estado, st.Estado.FALTA)
        self.assertIn("idevice_id", iphone.detalhe)
        self.assertIn("libimobiledevice", iphone.orientacao)

    def test_sem_appium_no_path_explica_instalacao(self):
        amb = _ambiente(appium=False)
        amb.appium_bin_ok = False
        itens = st.itens_prontidao(amb, st.Fonte.SCROLL, None, 2)
        appium = next(i for i in itens if i.chave == "appium")
        self.assertIn("não foi encontrado", appium.detalhe)
        self.assertIn("npm install -g appium", appium.orientacao)

    def test_dois_iphones_barram(self):
        itens = st.itens_prontidao(_ambiente(iphone=2), st.Fonte.ARQUIVO,
                                   self._resumo_ok(), 2)
        self.assertFalse(st.pode_iniciar(itens, executando=False)[0])

    def test_nao_liga_sem_appium_e_explica(self):
        itens = st.itens_prontidao(_ambiente(appium=False), st.Fonte.ARQUIVO,
                                   self._resumo_ok(), 2)
        appium = next(i for i in itens if i.chave == "appium")
        self.assertEqual(appium.estado, st.Estado.FALTA)
        self.assertTrue(appium.orientacao)
        self.assertFalse(st.pode_iniciar(itens, executando=False)[0])

    def test_wda_sem_bundle_nao_impede(self):
        itens = st.itens_prontidao(_ambiente(wda=""), st.Fonte.ARQUIVO,
                                   self._resumo_ok(), 2)
        wda = next(i for i in itens if i.chave == "wda")
        self.assertEqual(wda.estado, st.Estado.ATENCAO)
        self.assertTrue(st.pode_iniciar(itens, executando=False)[0])

    def test_scroll_livre_dispensa_arquivo(self):
        itens = st.itens_prontidao(_ambiente(), st.Fonte.SCROLL, None, 5)
        self.assertTrue(st.pode_iniciar(itens, executando=False)[0])

    def test_arquivo_sem_contato_apos_filtro_barra(self):
        itens = st.itens_prontidao(_ambiente(), st.Fonte.ARQUIVO,
                                   self._resumo_ok(), 0)
        self.assertFalse(st.pode_iniciar(itens, executando=False)[0])

    def test_nao_liga_durante_execucao(self):
        itens = st.itens_prontidao(_ambiente(), st.Fonte.SCROLL, None, 3)
        pode, motivo = st.pode_iniciar(itens, executando=True)
        self.assertFalse(pode)
        self.assertIn("andamento", motivo)

    def test_ambiente_ainda_verificando_nao_libera(self):
        itens = st.itens_prontidao(_ambiente(verificado=False), st.Fonte.SCROLL,
                                   None, 3)
        self.assertFalse(st.pode_iniciar(itens, executando=False)[0])


class Progresso(unittest.TestCase):

    def test_le_transmissao_do_run_ios(self):
        self.assertEqual(
            st.extrair_progresso("INFO === Transmissão 003 (256 contatos) ==="),
            (3, None))

    def test_le_lista_de_do_scroll(self):
        self.assertEqual(st.extrair_progresso("Lista 2 de 5"), (2, 5))

    def test_ignora_linha_comum(self):
        self.assertIsNone(st.extrair_progresso("INFO estado: SEARCHING -> MATCHING"))

    def test_classifica_severidade(self):
        self.assertEqual(st.classificar_linha("ERROR falhou"), "ERRO")
        self.assertEqual(st.classificar_linha("WARNING cuidado"), "AVISO")
        self.assertEqual(st.classificar_linha("[FALHA] Xcode ausente"), "ERRO")
        self.assertEqual(st.classificar_linha("[AVISO] iPhone"), "AVISO")
        self.assertEqual(st.classificar_linha("[OK  ] macOS 14"), "OK")
        self.assertEqual(st.classificar_linha("=== RESUMO ==="), "TITULO")
        self.assertEqual(st.classificar_linha("INFO qualquer coisa"), "INFO")

    def test_traduz_etapa_para_frase_humana(self):
        self.assertIn("WhatsApp", st.etapa_humana("INFO estado: OPENING_WHATSAPP"))
        self.assertEqual(st.etapa_humana("linha sem etapa"), "")


class Desfechos(unittest.TestCase):

    def test_sucesso(self):
        self.assertEqual(st.desfecho_para(0).tom, "ok")

    def test_interrupcao_do_operador(self):
        for codigo in (-15, -2, 130, 143):
            d = st.desfecho_para(codigo)
            self.assertEqual(d.tom, "atencao", codigo)
            self.assertIn("Interrompido", d.titulo)

    def test_codigos_de_parada_segura_tem_orientacao(self):
        for codigo in (2, 3, 4, 5):
            d = st.desfecho_para(codigo)
            self.assertEqual(d.tom, "erro")
            self.assertTrue(d.orientacao)

    def test_reconhece_socket_hang_up_do_wda(self):
        log = ("selenium.common.exceptions.WebDriverException: Message: Unable to start "
               "WebDriverAgent session. Original error: Could not proxy command to the "
               "remote server. Original error: socket hang up")
        d = st.diagnosticar_log(log)
        self.assertIsNotNone(d)
        self.assertIn("WebDriverAgent", d.titulo)
        self.assertIn("Instalar ou reparar WDA", d.orientacao)

    def test_reconhece_outros_erros_conhecidos(self):
        self.assertIn("Xcode", st.diagnosticar_log("xcodebuild failed with code 65").titulo)
        self.assertIn("autorizou", st.diagnosticar_log("XCTDaemonErrorDomain Code=41").titulo)
        self.assertIn("Appium", st.diagnosticar_log("Connection refused").titulo)

    def test_log_sem_erro_conhecido_devolve_none(self):
        self.assertIsNone(st.diagnosticar_log("INFO estado: SEARCHING -> MATCHING"))

    def test_codigo_desconhecido_nao_quebra(self):
        d = st.desfecho_para(77)
        self.assertEqual(d.tom, "erro")
        self.assertTrue(d.orientacao)


class Ritmo(unittest.TestCase):

    def test_presets_reconhecidos(self):
        for nome, (sp, pace, listas) in st.PRESETS_RITMO.items():
            self.assertEqual(st.preset_de(sp, pace, listas), nome)

    def test_valor_fora_dos_presets_e_personalizado(self):
        self.assertEqual(st.preset_de(0.9, 2.2, 47), "Personalizado")

    def test_padrao_e_o_ritmo_que_a_estacao_ja_usava(self):
        self.assertEqual(st.PRESETS_RITMO[st.RITMO_PADRAO], (0.4, 0.1, 8.0))


class Confirmacao(unittest.TestCase):

    def test_mostra_modo_fonte_ddd_e_listas(self):
        r = st.ResumoArquivo(caminho="/tmp/agenda.csv", tipo="CSV")
        r.validos = 600
        linhas = st.resumo_confirmacao(st.Fonte.ARQUIVO, st.Execucao.REAL, r,
                                       ["21", "22"], 600, 3)
        texto = " | ".join(f"{k}: {v}" for k, v in linhas)
        self.assertIn("Criar listas de verdade", texto)
        self.assertIn("agenda.csv", texto)
        self.assertIn("21, 22", texto)
        self.assertIn("600", texto)
        self.assertIn("3 de até 256", texto)

    def test_scroll_nao_promete_contagem_que_nao_tem(self):
        linhas = dict(st.resumo_confirmacao(st.Fonte.SCROLL, st.Execucao.REAL,
                                            None, [], 0, 5))
        self.assertIn("Scroll Livre", linhas["Fonte"])
        self.assertEqual(linhas["Filtro de DDD"], "não se aplica")
        self.assertNotIn("0", linhas["Contatos"])


class Sessao(unittest.TestCase):
    """A tela desconta quem ja esta em listas criadas — a mesma conta do runner."""

    def _contatos(self, n):
        import batching
        return [batching.NormalizedContact(f"+55219987654{i:02d}", f"C{i}") for i in range(1, n + 1)]

    def _progresso(self, pasta, hashes_ok, hashes_nf=()):
        import json, os
        import sessao
        p = os.path.join(pasta, "progress.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"lists": {"Transmissão 001": {"completed": True, "results":
                       [{"hash": h, "outcome": "selected"} for h in hashes_ok]
                       + [{"hash": h, "outcome": "not_found"} for h in hashes_nf]}}}, f)
        return p

    def test_desconta_adicionados_e_nao_encontrados(self):
        import tempfile
        import sessao
        cs = self._contatos(6)
        p = self._progresso(tempfile.mkdtemp(),
                            [sessao.hash_numero(cs[0].e164), sessao.hash_numero(cs[1].e164)],
                            [sessao.hash_numero(cs[2].e164)])
        ses = st.descontar_sessao(cs, p)
        self.assertEqual(len(ses.adicionados), 2)
        self.assertEqual(len(ses.nao_adicionados), 1)
        self.assertEqual(len(ses.restantes), 3)
        self.assertEqual(st.contar_listas(len(ses.restantes)), 1)

    def test_sem_progresso_nada_e_descontado(self):
        cs = self._contatos(3)
        ses = st.descontar_sessao(cs, "/caminho/que/nao/existe.json")
        self.assertEqual(len(ses.restantes), 3)
        self.assertEqual(ses.adicionados, [])

    def test_confirmacao_mostra_ja_adicionados(self):
        r = st.ResumoArquivo(caminho="/x/contatos.csv", tipo="CSV", validos=10)
        linhas = dict(st.resumo_confirmacao(st.Fonte.ARQUIVO, st.Execucao.REAL, r, [],
                                            7, 1, ja_adicionados=3))
        self.assertEqual(linhas["Contatos"], "7 restantes")
        self.assertEqual(linhas["Já em listas anteriores"], "3 (ficam de fora)")
        sem = dict(st.resumo_confirmacao(st.Fonte.ARQUIVO, st.Execucao.REAL, r, [], 10, 1))
        self.assertEqual(sem["Contatos"], "10")
        self.assertNotIn("Já em listas anteriores", sem)

    def test_prontidao_avisa_quando_todos_ja_foram_adicionados(self):
        amb = st.Ambiente(verificado=True, iphone_count=1, idevice_ok=True, appium_ok=True)
        r = st.ResumoArquivo(caminho="/x/contatos.csv", tipo="CSV", validos=5)
        itens = {i.chave: i for i in st.itens_prontidao(amb, st.Fonte.ARQUIVO, r, 0,
                                                        ja_adicionados=5)}
        self.assertEqual(itens["fonte"].estado, st.Estado.FALTA)
        self.assertIn("já", itens["fonte"].detalhe)
        self.assertIn("listas criadas", itens["fonte"].detalhe)


class Estimativa(unittest.TestCase):
    """A tela dizia 8 min quando o aparelho levava 16. A formula agora parte das
    chamadas medidas, nao so das pausas."""

    def test_turbo_bate_com_a_medicao(self):
        speed, pace, _ = st.PRESETS_RITMO["Turbo"]
        self.assertEqual(st.estimativa_minutos(pace, speed), 13)

    def test_mais_devagar_nunca_estima_menos(self):
        anterior = 0
        for nome in ("Máximo", "Turbo", "Rápido", "Seguro"):
            speed, pace, _ = st.PRESETS_RITMO[nome]
            atual = st.estimativa_minutos(pace, speed)
            self.assertGreaterEqual(atual, anterior, nome)
            anterior = atual

    def test_o_piso_das_pausas_limita_o_ganho(self):
        """Abaixo do piso do runner, baixar o ritmo nao muda mais nada."""
        self.assertEqual(st.estimativa_minutos(0.05, 0.25),
                         st.estimativa_minutos(0.05, 0.1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
