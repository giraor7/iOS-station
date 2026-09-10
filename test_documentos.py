"""Suite de coerencia entre os documentos, os textos da GUI e o codigo.

Nao roda Tk, nem Appium, nem iPhone. Todo teste aqui verifica um FATO textual
que precisa continuar batendo com o codigo real — se um numero, um comando ou
uma afirmacao dos documentos envelhecer, um teste aqui fica vermelho.

  python3 test_documentos.py
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import sys
import unittest

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import gui_state as st          # noqa: E402
import run_ios                  # noqa: E402
import run_ios_scroll as rs     # noqa: E402
import test_scroll_local as tsl  # noqa: E402


def _ler(nome: str) -> str:
    with open(os.path.join(BASE, nome), encoding="utf-8") as f:
        return f.read()


def _paradas_nomeadas() -> list[str]:
    """A lista COMPLETA de paradas nomeadas que o operador pode encontrar no
    log de run_ios_scroll.py.

    Duas fontes, unidas de proposito (auditoria 2026-09-10, 4a rodada):

    1. AST: toda string literal atribuida a `self.parada`.
    2. Toda constante de modulo `PARADA_*` de run_ios_scroll.

    So a fonte (1) existia, e ela e CEGA a `self.parada = self._corte_motivo or
    PARADA_SEM_ROTULO` — um ast.BoolOp, nao um ast.Constant. As duas paradas
    criadas com essa forma passaram pelos dois testes desta classe sem nunca
    serem olhadas, e chegaram a producao sem traducao humana na GUI (a tela
    continuava exibindo "Marcando contatos…" depois de a selecao ter parado).
    """
    arvore = ast.parse(_ler("run_ios_scroll.py"))
    achadas: list[str] = []
    for node in ast.walk(arvore):
        if not isinstance(node, ast.Assign):
            continue
        alvo_ok = any(
            isinstance(t, ast.Attribute) and t.attr == "parada" for t in node.targets)
        if alvo_ok and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            achadas.append(node.value.value)
    for nome in dir(rs):
        if nome.startswith("PARADA_"):
            valor = getattr(rs, nome)
            if isinstance(valor, str) and valor not in achadas:
                achadas.append(valor)
    return achadas


class TestParadasTraduzidas(unittest.TestCase):
    """Toda parada nomeada de run_ios_scroll.py precisa ter uma traducao em
    gui_state.etapa_humana — senao o operador le a linha tecnica crua."""

    def test_toda_parada_tem_traducao_humana(self):
        paradas = _paradas_nomeadas()
        self.assertGreater(len(paradas), 5, "a extracao por AST nao achou nada")
        sem_traducao = []
        for motivo in paradas:
            linha = f"WARNING selecao desta lista foi interrompida: {motivo}"
            frase = st.etapa_humana(linha)
            if not frase or frase == "Fim da agenda.":
                sem_traducao.append(motivo)
        self.assertEqual(sem_traducao, [],
                         f"parada(s) sem traducao em gui_state.etapa_humana: {sem_traducao}")


class TestCodigosDeSaida(unittest.TestCase):
    """Todo codigo de saida que main() pode devolver precisa estar em
    gui_state._DESFECHOS, com o tom certo."""

    @staticmethod
    def _codigos_de_retorno(caminho: str) -> set[int]:
        arvore = ast.parse(_ler(caminho))
        main_fn = next(n for n in ast.walk(arvore)
                       if isinstance(n, ast.FunctionDef) and n.name == "main")
        codigos = set()
        for node in ast.walk(main_fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, int):
                codigos.add(node.value.value)
        return codigos

    def test_codigos_do_scroll_estao_todos_traduzidos(self):
        codigos = self._codigos_de_retorno("run_ios_scroll.py")
        self.assertIn(6, codigos)
        self.assertIn(7, codigos)
        for codigo in codigos:
            self.assertIn(codigo, st._DESFECHOS, f"codigo {codigo} sem desfecho traduzido")

    def test_codigo_6_e_atencao_nao_erro(self):
        self.assertEqual(st.desfecho_para(6).tom, "atencao")

    def test_codigo_7_e_atencao_nao_erro(self):
        self.assertEqual(st.desfecho_para(7).tom, "atencao")


class TestNumerosQueOsDocumentosPrometem(unittest.TestCase):
    """README/MODO-SCROLL-LIVRE/DEVICE-TEST-IOS/SETUP-MAC precisam citar o
    numero que o CODIGO hoje sustenta, nunca o aposentado."""

    DOCS = ("README.md", "MODO-SCROLL-LIVRE.md", "DEVICE-TEST-IOS.md", "SETUP-MAC.md")

    def test_numero_aposentado_nao_aparece_em_nenhum_doc(self):
        for nome in self.DOCS:
            texto = _ler(nome)
            self.assertNotIn("2,5 s", texto, nome)
            self.assertNotIn("2.5 s", texto, nome)

    def test_readme_cita_a_estimativa_real_do_modo_csv(self):
        minutos_turbo = st.estimativa_minutos(0.1, 0.4)
        self.assertIn(f"{minutos_turbo} min", _ler("README.md"))

    def test_device_test_cita_a_mesma_estimativa_da_tela(self):
        minutos_turbo = st.estimativa_minutos(0.1, 0.4)
        self.assertIn(f"~{minutos_turbo} min", _ler("DEVICE-TEST-IOS.md"))

    def test_setup_mac_cita_a_mesma_estimativa(self):
        minutos_turbo = st.estimativa_minutos(0.1, 0.4)
        self.assertIn(f"~{minutos_turbo} min", _ler("SETUP-MAC.md"))


class TestContagemDeTestes(unittest.TestCase):
    """O numero de casos de test_scroll_local.py citado nos documentos precisa
    bater com o numero real (contado, nao rodado)."""

    def _quantidade_real(self) -> int:
        return unittest.TestLoader().loadTestsFromModule(tsl).countTestCases()

    def test_readme_cita_o_numero_real_de_casos(self):
        n = self._quantidade_real()
        self.assertGreaterEqual(n, 80)
        texto = _ler("README.md")
        self.assertIn(f"{n} testes", texto)

    def test_modo_scroll_livre_cita_o_numero_real_de_casos(self):
        n = self._quantidade_real()
        texto = _ler("MODO-SCROLL-LIVRE.md")
        self.assertIn(f"{n} casos", texto)


class TestGuiaDoOperador(unittest.TestCase):
    """COMO-OPERAR.md precisa existir, cobrir as 9 secoes e citar toda parada
    nomeada que o operador pode encontrar."""

    def setUp(self):
        self.texto = _ler("COMO-OPERAR.md")

    def test_arquivo_existe_e_tem_as_secoes(self):
        for titulo in ("O que a estação faz", "Antes de começar",
                       "modo lista de contatos", "Scroll Livre",
                       "escada de ensaio", "observar no log",
                       "parada nomeada", "nunca saem do Mac",
                       "Perguntas rápidas"):
            self.assertIn(titulo, self.texto, titulo)

    def test_cobre_toda_parada_nomeada(self):
        for motivo in _paradas_nomeadas():
            # casa pelo trecho antes do primeiro parenteses (paradas com
            # detalhe parametrico, como "orcamento de tempo da lista
            # (durante a retomada)", tem o texto fixo citado inteiro).
            trecho = motivo.split(" (")[0]
            self.assertIn(trecho, self.texto, f"parada nao documentada: {motivo}")

    def test_cita_a_escada_de_ensaio(self):
        for comando in ("--limite-por-lista 5", "--limite-por-lista 30",
                        "--limite-por-lista 100", "--max-listas 1"):
            self.assertIn(comando, self.texto, comando)

    def test_diz_que_nunca_envia_mensagem_e_nao_renomeia(self):
        self.assertIn("nunca envia mensagem", self.texto)
        self.assertIn("nome padrão do WhatsApp", self.texto)


class TestTextosDaGuiSaoHonestos(unittest.TestCase):

    def test_painel_scroll_nao_nega_o_filtro_de_ddd(self):
        self.assertNotIn("nem filtro de DDD", st.TEXTO_PAINEL_SCROLL)
        self.assertIn("agenda", st.TEXTO_PAINEL_SCROLL.lower())

    def test_turbo_nao_promete_multiplicador(self):
        self.assertIsNone(re.search(r"\d+\s*vezes", st.TEXTO_TURBO))
        self.assertIn("medido", st.TEXTO_TURBO.lower())

    def test_confirmacao_traz_o_nome_das_listas(self):
        linhas = st.resumo_confirmacao(st.Fonte.ARQUIVO, st.Execucao.REAL, None,
                                       [], 10, 1)
        self.assertIn(("Nome das listas", "o padrão do WhatsApp (a estação não renomeia)"),
                      linhas)


class TestAfirmacoesRetiradas(unittest.TestCase):
    """Frases que o codigo parou de sustentar nao podem sobreviver nos docs."""

    def test_modo_scroll_livre_nao_promete_limite_fixo_na_gui(self):
        texto = _ler("MODO-SCROLL-LIVRE.md")
        self.assertNotIn("Pela GUI o limite é sempre 256", texto)
        self.assertNotIn('botão **"Onde parou?"**', texto)

    def test_readme_nao_diz_que_o_fluxo_nunca_foi_confirmado(self):
        self.assertNotIn("ainda não confirmado num iPhone", _ler("README.md"))

    def test_setup_mac_nao_diz_que_o_fluxo_nunca_foi_confirmado(self):
        self.assertNotIn("ainda não foi\n> confirmado num iPhone", _ler("SETUP-MAC.md"))
        self.assertNotIn("ainda não foi confirmado num iPhone", _ler("SETUP-MAC.md"))

    def test_como_abrir_nao_cita_pasta_com_numero_de_versao_fantasma(self):
        self.assertNotIn("V-15.5-ios-station", _ler("COMO-ABRIR-NO-MAC.txt"))

    def test_como_abrir_fala_de_atualizar_antes_de_falar_de_zip(self):
        texto = _ler("COMO-ABRIR-NO-MAC.txt").lower()
        self.assertLess(texto.index("atualizar.command"), texto.index("zip"),
                        "o fluxo do dia a dia (git) precisa vir antes do caso excepcional (zip)")


class TestEstimativaDoRunIosBateComATela(unittest.TestCase):
    """run_ios.py (--dry-run) e gui_state.py (a tela) precisam concordar no
    numero mostrado ao operador — sao a MESMA conta, duas fontes de codigo."""

    def test_constantes_batem(self):
        self.assertEqual(run_ios.SEGUNDOS_DE_CHAMADAS, st.SEGUNDOS_DE_CHAMADAS)
        self.assertEqual(run_ios.SEGUNDOS_POR_LISTA, st.SEGUNDOS_POR_LISTA)

    def test_estimativa_em_minutos_bate_para_todos_os_presets(self):
        for nome, (speed, pace, _pl) in st.PRESETS_RITMO.items():
            da_tela = st.estimativa_minutos(pace, speed)
            do_terminal = round(run_ios.estimativa_segundos(pace, speed) / 60)
            self.assertEqual(da_tela, do_terminal, nome)

    def test_docstring_do_run_ios_nao_promete_nome_de_lista_errado(self):
        fonte = inspect.getsource(run_ios)
        self.assertNotIn("2.5", fonte.split('"""')[1])
        self.assertIn("nome padrao do WhatsApp", fonte)


class TestOrcamentoDeTempoNaGui(unittest.TestCase):

    def test_constante_da_gui_bate_com_a_do_runner(self):
        self.assertEqual(st.MAX_MINUTOS_POR_LISTA * 60, rs.ORCAMENTO_PADRAO_S)

    def test_o_default_real_do_cli_e_o_mesmo_numero(self):
        """A trava acima comparava DUAS CONSTANTES — e ORCAMENTO_PADRAO_S nao
        era lida por codigo nenhum: o orcamento de uma rodada de terminal vinha
        de um literal solto no argparse. Trocar esse literal por 5 (ou 999)
        deixava as 10 suites verdes enquanto os documentos e a caixa de
        confirmacao da GUI continuavam prometendo 60 min. Agora o teste
        pergunta ao PARSER."""
        padrao = rs.construir_parser().get_default("max_minutos")
        self.assertEqual(padrao * 60, rs.ORCAMENTO_PADRAO_S)
        self.assertEqual(padrao, st.MAX_MINUTOS_POR_LISTA)

    def test_ajuda_do_cli_cita_o_padrao_de_verdade(self):
        acoes = [a for a in rs.construir_parser()._actions
                 if "--max-minutos" in (a.option_strings or [])]
        self.assertEqual(len(acoes), 1)
        self.assertIn(f"padrao {st.MAX_MINUTOS_POR_LISTA}", acoes[0].help)


# Um comando de terminal citado num documento: `<script>.py` seguido das flags
# (e do valor de cada uma, quando houver). Para na primeira quebra de linha, na
# crase que fecha o bloco e na barra de continuacao.
_PADRAO_COMANDO = (
    r"([a-z_]+\.py)"
    r"((?:[ \t]+(?:--[A-Za-z0-9\-]+|-[a-zA-Z])(?:[ \t]+[^\s`\\]+)?)*)"
)
_PADRAO_FLAG = r"(?<![\w\-])(--[A-Za-z0-9\-]+|-[a-zA-Z])(?![\w\-])"


class TestComandosDosDocumentosExistem(unittest.TestCase):
    """Todo comando de terminal que os documentos mandam copiar precisa existir
    de verdade: script presente na pasta e TODA flag reconhecida pelo argparse
    daquele script.

    Motivo (auditoria 2026-09-10, 4a rodada): README/SETUP-MAC/DEVICE-TEST
    mandavam rodar `run_ios.py --csv contatos.csv --udid <UDID> --dry-run` em
    15 lugares. `--udid` NUNCA existiu em nenhum script deste repositorio (o
    driver acha o aparelho sozinho, `opts.udid = "auto"`), entao o comando
    morria na hora com "unrecognized arguments: --udid".
    """

    DOCS = ("README.md", "COMO-OPERAR.md", "MODO-SCROLL-LIVRE.md", "SETUP-MAC.md",
            "DEVICE-TEST-IOS.md", "ERRO-page_source-timeout.md",
            "ERRO-xcodebuild-65.md", "TRAVOU-EM-OPENING-BROADCAST.md",
            "COMO-ABRIR-NO-MAC.txt")

    @staticmethod
    def _flags_do_script(nome: str) -> set[str]:
        """Toda option string declarada no argparse daquele script, por AST —
        sem importar o modulo (alguns abrem sessao/driver no import)."""
        arvore = ast.parse(_ler(nome))
        flags = {"-h", "--help"}
        for node in ast.walk(arvore):
            if not isinstance(node, ast.Call):
                continue
            alvo = node.func
            if not (isinstance(alvo, ast.Attribute) and alvo.attr == "add_argument"):
                continue
            for arg in node.args:
                if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                        and arg.value.startswith("-")):
                    flags.add(arg.value)
        return flags

    def test_toda_flag_citada_existe_no_script_citado(self):
        scripts = [f for f in os.listdir(BASE) if f.endswith(".py")]
        flags_por_script = {nome: self._flags_do_script(nome) for nome in scripts}
        problemas = []
        for doc in self.DOCS:
            texto = _ler(doc)
            for m in re.finditer(_PADRAO_COMANDO, texto):
                script, resto = m.group(1), m.group(2)
                if script not in flags_por_script:
                    problemas.append(f"{doc}: script inexistente {script}")
                    continue
                for flag in re.findall(_PADRAO_FLAG, resto):
                    if flag not in flags_por_script[script]:
                        problemas.append(f"{doc}: {script} nao aceita {flag}")
        self.assertEqual(sorted(set(problemas)), [],
                         "\n".join(sorted(set(problemas))))

    def test_nenhum_documento_promete_udid(self):
        for doc in self.DOCS:
            self.assertNotIn("--udid", _ler(doc),
                             f"{doc} ainda manda passar --udid, que nao existe")


class TestGuiaCitaAsSaidasQueOCodigoProduz(unittest.TestCase):
    """COMO-OPERAR precisa cobrir cada codigo de saida do Scroll Livre com um
    texto proprio — o operador le o guia, nao o dicionario da GUI."""

    def test_cada_codigo_de_saida_do_scroll_tem_secao_no_guia(self):
        texto = _ler("COMO-OPERAR.md")
        codigos = TestCodigosDeSaida._codigos_de_retorno("run_ios_scroll.py")
        for codigo in sorted(codigos):
            if codigo in (0, 2, 3, 5):
                continue      # entrada invalida / versao / parada de seguranca:
                              # cobertos por texto proprio, sem numero de codigo
            self.assertIn(f"código {codigo}", texto,
                          f"o guia nao explica o codigo de saida {codigo}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
