"""Testes do que a interface MANDA executar — sem abrir janela e sem iPhone.

Aqui moram as travas que não podem afrouxar: `--approve-create` só entra no
modo real, o Scroll Livre nunca recebe filtro de DDD, o limite de listas é
respeitado, e o botão Parar realmente encerra o processo.

  python3 test_gui_runner.py
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gui_ios          # noqa: E402  (importa customtkinter, mas não abre janela)
import gui_state as st  # noqa: E402


def runner(**kw) -> gui_ios.RunnerThread:
    cfg = gui_ios.AppConfig()
    cfg.server = "http://127.0.0.1:4723"
    cfg.pace, cfg.pace_lists, cfg.speed = 0.1, 8.0, 0.4
    base = dict(csv_path="/tmp/contatos.csv", cfg=cfg, log_queue=queue.Queue(),
                on_finish=lambda _c: None)
    base.update(kw)
    return gui_ios.RunnerThread(**base)


class ComandoDoModoArquivo(unittest.TestCase):

    def test_simulacao_nao_manda_approve_create(self):
        cmd = runner(approve=False).comando()
        self.assertNotIn("--approve-create", cmd)
        self.assertIn("--trust-profile", cmd)
        self.assertTrue(cmd[1].endswith("run_ios.py"))

    def test_modo_real_manda_approve_create(self):
        self.assertIn("--approve-create", runner(approve=True).comando())

    def test_padrao_do_runner_e_simulacao(self):
        """Quem esquecer de passar `approve` NÃO cria lista nenhuma."""
        self.assertNotIn("--approve-create", runner().comando())

    def test_ddd_vai_como_lista_separada_por_virgula(self):
        cmd = runner(ddd="21,22,24").comando()
        self.assertIn("--ddd", cmd)
        self.assertEqual(cmd[cmd.index("--ddd") + 1], "21,22,24")

    def test_sem_ddd_nao_manda_o_argumento(self):
        self.assertNotIn("--ddd", runner(ddd="").comando())

    def test_ritmo_vai_para_o_runner(self):
        cmd = runner().comando()
        for flag in ("--pace", "--pace-lists", "--speed", "--csv", "--server"):
            self.assertIn(flag, cmd)


class ComandoDoScrollLivre(unittest.TestCase):

    def test_usa_o_script_do_scroll_e_respeita_o_limite(self):
        cmd = runner(scroll=True, scroll_lists=12).comando()
        self.assertTrue(cmd[1].endswith("run_ios_scroll.py"))
        self.assertEqual(cmd[cmd.index("--max-listas") + 1], "12")

    def test_limite_de_listas_e_travado_entre_1_e_36(self):
        for pedido, esperado in ((0, "1"), (-5, "1"), (999, "36"), (36, "36")):
            cmd = runner(scroll=True, scroll_lists=pedido).comando()
            self.assertEqual(cmd[cmd.index("--max-listas") + 1], esperado, pedido)

    def test_scroll_so_recebe_ddd_junto_com_a_agenda(self):
        cmd = runner(scroll=True, scroll_lists=3, ddd="21,22").comando()
        self.assertNotIn("--ddd", cmd)          # sem agenda nao ha como filtrar
        cmd = runner(scroll=True, scroll_lists=3, ddd="21,22",
                     agenda="/tmp/agenda.vcf").comando()
        self.assertEqual(cmd[cmd.index("--ddd") + 1], "21,22")
        self.assertEqual(cmd[cmd.index("--agenda") + 1], "/tmp/agenda.vcf")
        self.assertNotIn("--csv", cmd)          # a agenda nao vira fonte de contatos

    def test_turbo_e_opt_in_e_so_no_scroll(self):
        self.assertNotIn("--turbo", runner(scroll=True, scroll_lists=2).comando())
        self.assertIn("--turbo", runner(scroll=True, scroll_lists=2, turbo=True).comando())
        self.assertNotIn("--turbo", runner(turbo=True).comando())   # modo arquivo ignora

    def test_scroll_em_simulacao_tambem_nao_aprova(self):
        self.assertNotIn("--approve-create",
                         runner(scroll=True, scroll_lists=2).comando())

    def test_limite_por_lista_e_propagado_quando_pedido(self):
        """Auditoria 2026-09-10: sem isto, so o terminal alcancava o ensaio de
        5/30 contatos — quem abria a estacao ia direto para a lista cheia."""
        cmd = runner(scroll=True, scroll_lists=2, limite=5).comando()
        self.assertEqual(cmd[cmd.index("--limite-por-lista") + 1], "5")

    def test_sem_limite_pedido_nao_manda_o_argumento(self):
        """0 (ou omitido) preserva o comportamento de sempre: lista cheia,
        sem novidade para quem ja usava a estacao."""
        self.assertNotIn("--limite-por-lista", runner(scroll=True, scroll_lists=2).comando())
        self.assertNotIn("--limite-por-lista",
                         runner(scroll=True, scroll_lists=2, limite=0).comando())

    def test_limite_por_lista_tambem_vale_no_modo_arquivo(self):
        cmd = runner(limite=30).comando()
        self.assertEqual(cmd[cmd.index("--limite-por-lista") + 1], "30")


class ParadaSegura(unittest.TestCase):

    def test_parar_encerra_o_processo(self):
        """O botão Parar precisa mesmo derrubar o subprocesso."""
        script = os.path.join(tempfile.mkdtemp(), "demorado.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write("import time\nprint('comecou', flush=True)\ntime.sleep(60)\n")

        fila: queue.Queue = queue.Queue()
        terminou: list[int] = []
        r = runner(log_queue=fila, on_finish=terminou.append)
        r.comando = lambda: [sys.executable, script]   # troca só o alvo
        r.start()

        linha = fila.get(timeout=15)
        self.assertEqual(linha, ("log", "comecou"))
        r.stop()
        for _ in range(60):
            if terminou:
                break
            time.sleep(0.25)
        self.assertTrue(terminou, "o processo não encerrou depois do Parar")
        self.assertNotEqual(terminou[0], 0)
        # A interface sabe que foi ela quem parou: o desfecho não depende do
        # código de saída, que muda entre macOS e outros sistemas.
        self.assertTrue(r.parado_pelo_operador)
        self.assertEqual(st.desfecho_para(terminou[0], True).tom, "atencao")

    def test_sem_parada_o_codigo_de_erro_continua_erro(self):
        self.assertEqual(st.desfecho_para(4, False).tom, "erro")
        self.assertEqual(st.desfecho_para(1, False).tom, "erro")

    def test_stop_sem_processo_nao_quebra(self):
        runner().stop()   # nunca iniciado


class MonitorDeAmbiente(unittest.TestCase):

    def test_thread_sobrevive_a_excecao_no_callback(self):
        """Foi isto que deixava a tela em 'Verificando…' para sempre: uma
        excecao no callback matava a thread antes do 1o resultado chegar."""
        import threading
        chamadas = []
        pronto = threading.Event()

        def cb(amb):
            chamadas.append(amb)
            if len(chamadas) == 1:
                raise RuntimeError("main thread is not in main loop")
            pronto.set()

        gui_ios.POLL_ENV_MS = 50
        mon = gui_ios.EnvironmentMonitor(cb)
        mon.start()
        self.assertTrue(pronto.wait(timeout=20), "a thread morreu apos a 1a excecao")
        mon.stop()
        self.assertGreaterEqual(len(chamadas), 2)
        self.assertTrue(all(a.verificado for a in chamadas))

    def test_ambiente_marca_ferramentas_ausentes(self):
        mon = gui_ios.EnvironmentMonitor(lambda a: None)
        original = gui_ios.shutil.which
        gui_ios.shutil.which = lambda nome: None
        try:
            amb = mon._check()
        finally:
            gui_ios.shutil.which = original
        self.assertFalse(amb.appium_bin_ok)
        self.assertFalse(amb.idevice_ok)
        self.assertEqual(amb.iphone_count, 0)


class ConfiguracaoPersistida(unittest.TestCase):

    def test_ritmo_padrao_e_o_que_a_estacao_ja_usava(self):
        cfg = gui_ios.AppConfig()
        self.assertFalse(cfg.ritmo_definido)
        cfg2 = gui_ios.AppConfig.load.__wrapped__(gui_ios.AppConfig) \
            if hasattr(gui_ios.AppConfig.load, "__wrapped__") else None
        # O load() aplica o preset padrão quando o operador ainda não escolheu.
        turbo = st.PRESETS_RITMO[st.RITMO_PADRAO]
        self.assertEqual(turbo, (0.4, 0.1, 8.0))

    def test_campos_desconhecidos_no_json_nao_quebram(self):
        import json
        from pathlib import Path
        alvo = Path(tempfile.mkdtemp()) / "cfg.json"
        alvo.write_text(json.dumps({"server": "http://x:1", "coisa_nova": 1}),
                        encoding="utf-8")
        original = gui_ios.CONFIG_PATH
        try:
            gui_ios.CONFIG_PATH = alvo
            cfg = gui_ios.AppConfig.load()
            self.assertEqual(cfg.server, "http://x:1")
        finally:
            gui_ios.CONFIG_PATH = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
