"""Estação iOS — interface da criação assistida de listas de transmissão.

Abre o Appium, acompanha o iPhone e executa run_ios.py / run_ios_scroll.py sem
que o operador precise tocar no terminal.

A camada de execução (Appium, subprocessos, seletores, travas de segurança) é
a mesma versão já validada em aparelho: esta interface só decide O QUE pedir e
mostra o que está acontecendo. As regras que ela usa para decidir ficam em
gui_state.py; os componentes visuais, em ui_kit.py.

Uso:
    python3 gui_ios.py
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
import tkinter as _tk

# No macOS, o Python 3.9 da Apple usa Tk 8.5, incompatível com o CustomTkinter
# (janela cinza e 100% de CPU). Se for o caso, reabre no .venv (Tk 8.6+).
if getattr(_tk, "TkVersion", 0) < 8.6:
    candidates = [
        Path(__file__).resolve().parent / ".venv" / "bin" / "python",
        Path("/opt/homebrew/bin/python3.12"),
        Path("/usr/local/bin/python3.12"),
    ]
    for cand in candidates:
        if cand.exists():
            os.execv(str(cand), [str(cand)] + sys.argv)
    print("ERRO: este Python tem Tcl/Tk abaixo de 8.6 (incompatível com a interface).")
    print("Rode pelo ambiente virtual: .venv/bin/python gui_ios.py")
    sys.exit(1)

from tkinter import filedialog
import customtkinter as ctk

import gui_state as st
import ui_kit as ui
from ui_kit import C, S

TITULO = "Estação iOS"
SUBTITULO = "Criação assistida de listas de transmissão"
CONFIG_PATH = Path.home() / ".lista_local_config.json"
APPIUM_URL = "http://127.0.0.1:4723"
POLL_ENV_MS = 5000
POLL_LOG_MS = 100

ctk.set_appearance_mode("system")     # acompanha o tema do macOS
ctk.set_default_color_theme("blue")


def _ampliar_path() -> None:
    """Aberta pelo Finder (dois cliques), a estação recebe um PATH mínimo, sem
    Homebrew nem npm — e `appium` e `idevice_id` "desaparecem". Acrescenta as
    pastas onde essas ferramentas costumam estar no macOS."""
    candidatos = ["/opt/homebrew/bin", "/opt/homebrew/opt/node/bin",
                  "/usr/local/bin", "/usr/local/opt/node/bin",
                  str(Path.home() / ".npm-global" / "bin")]
    for versao in sorted((Path.home() / ".nvm" / "versions" / "node").glob("*/bin"),
                         reverse=True):
        candidatos.append(str(versao))
    atual = os.environ.get("PATH", "").split(os.pathsep)
    novos = [c for c in candidatos if os.path.isdir(c) and c not in atual]
    if novos:
        os.environ["PATH"] = os.pathsep.join(novos + atual)


_ampliar_path()


# ── Configuração persistente ─────────────────────────────────────────────────

@dataclass
class AppConfig:
    wda_bundle: str      = ""
    server: str          = APPIUM_URL
    pace: float          = 1.0
    pace_lists: float    = 30.0
    auto_appium: bool    = True
    approve_create: bool = False   # mantido por compatibilidade; não decide nada
    scroll_mode: bool    = False
    scroll_lists: int    = 1
    speed: float         = 1.0
    ddds: str            = ""      # "21,22,24" — vazio = todos
    ritmo_definido: bool = False   # o operador já escolheu um ritmo?

    @classmethod
    def load(cls) -> "AppConfig":
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            campos = set(cls.__dataclass_fields__)
            cfg = cls(**{k: v for k, v in raw.items() if k in campos})
        except Exception:
            cfg = cls()
        if not cfg.ritmo_definido:
            # A versão anterior aplicava o ritmo Turbo em toda abertura, por
            # baixo dos panos. Mantemos o mesmo comportamento como PADRÃO, mas
            # agora ele fica visível em Configurações e o operador pode mudar.
            cfg.speed, cfg.pace, cfg.pace_lists = st.PRESETS_RITMO[st.RITMO_PADRAO]
        return cfg

    def save(self) -> None:
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8")


# ── Appium ───────────────────────────────────────────────────────────────────

class AppiumManager:
    def __init__(self):
        self._proc: subprocess.Popen | None = None

    def is_running(self) -> bool:
        try:
            with urllib.request.urlopen(f"{APPIUM_URL}/status", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def start(self) -> bool:
        if self.is_running():
            return True
        appium_bin = shutil.which("appium")
        if not appium_bin:
            return False
        self._proc = subprocess.Popen([appium_bin], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
        for _ in range(20):
            time.sleep(0.5)
            if self.is_running():
                return True
        return False

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def managed(self) -> bool:
        return self._proc is not None


class EnvironmentMonitor:
    """Consulta o Appium e o cabo do iPhone a cada 5 s, numa thread separada."""

    def __init__(self, callback):
        self._cb = callback
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._t.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._cb(self._check())
            except Exception as exc:   # a thread nunca pode morrer em silêncio
                print(f"[monitor] {exc!r}", file=sys.stderr, flush=True)
            self._stop.wait(timeout=POLL_ENV_MS / 1000)

    def _check(self) -> st.Ambiente:
        amb = st.Ambiente(verificado=True)
        amb.appium_bin_ok = shutil.which("appium") is not None
        try:
            with urllib.request.urlopen(f"{APPIUM_URL}/status", timeout=2) as r:
                data = json.loads(r.read().decode())
            amb.appium_ok = True
            amb.appium_versao = data.get("value", {}).get("build", {}).get("version", "")
        except Exception:
            amb.appium_ok = False

        idevice = shutil.which("idevice_id")
        amb.idevice_ok = idevice is not None
        if idevice:
            try:
                p = subprocess.run([idevice, "-l"], capture_output=True,
                                   text=True, timeout=5)
                linhas = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
                amb.iphone_count = len(linhas)
            except Exception:
                pass
        return amb


# ── Execução dos runners ─────────────────────────────────────────────────────

class RunnerThread:
    """Roda run_ios.py ou run_ios_scroll.py e entrega a saída linha a linha.

    A montagem do comando é a mesma da versão validada. `--approve-create` só
    entra quando `approve=True`, e isso só acontece depois da confirmação.
    """

    def __init__(self, csv_path: str, cfg: AppConfig, log_queue: queue.Queue,
                 on_finish, ddd: str = "", scroll: bool = False,
                 scroll_lists: int = 1, approve: bool = False,
                 turbo: bool = False, agenda: str = "", limite: int = 0):
        self._turbo = bool(turbo)
        self._agenda = agenda or ""
        self._csv = csv_path
        self._cfg = cfg
        self._q = log_queue
        self._on_finish = on_finish
        self._ddd = ddd
        self._scroll = scroll
        self._scroll_lists = st.clamp_listas(scroll_lists)
        self._approve = bool(approve)
        # Contatos por lista. 0 = nao manda a flag (usa o padrao do runner,
        # a lista cheia). Existe para permitir o ensaio em escada (5 -> 30 ->
        # 256) SEM precisar cair no terminal — antes so o terminal alcancava
        # o teste de 5 contatos; quem abria a estacao ia direto para a lista
        # cheia, o caminho que nunca tinha rodado (auditoria 2026-09-10).
        self._limite = int(limite) if limite else 0
        self._proc: subprocess.Popen | None = None
        self.parado_pelo_operador = False
        self._t = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._t.start()

    def stop(self):
        self.parado_pelo_operador = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def comando(self) -> list[str]:
        base = Path(__file__).parent
        if self._scroll:
            cmd = [sys.executable, str(base / "run_ios_scroll.py"),
                   "--server", self._cfg.server,
                   "--max-listas", str(self._scroll_lists),
                   "--trust-profile"]
            if self._turbo:
                cmd.append("--turbo")
            # DDD no Scroll Livre so existe com a agenda (o runner exige as duas).
            if self._ddd and self._agenda:
                cmd += ["--ddd", self._ddd, "--agenda", self._agenda]
        else:
            cmd = [sys.executable, str(base / "run_ios.py"),
                   "--csv", self._csv,
                   "--server", self._cfg.server,
                   "--pace", str(self._cfg.pace),
                   "--pace-lists", str(self._cfg.pace_lists),
                   "--speed", str(self._cfg.speed),
                   "--trust-profile"]
        if self._cfg.wda_bundle:
            cmd += ["--wda-bundle", self._cfg.wda_bundle]
        if self._approve:
            cmd.append("--approve-create")
        if self._ddd and not self._scroll:
            cmd += ["--ddd", self._ddd]
        if self._limite:
            cmd += ["--limite-por-lista", str(self._limite)]
        return cmd

    def _run(self):
        env = os.environ.copy()
        # Silencia o aviso do macOS sobre fork em processos com CoreFoundation.
        env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        self._proc = subprocess.Popen(
            self.comando(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, cwd=str(Path(__file__).parent), env=env)
        for linha in self._proc.stdout:
            self._q.put(("log", linha.rstrip()))
        self._proc.wait()
        self._on_finish(self._proc.returncode)


# ── Aba: Operação ────────────────────────────────────────────────────────────

class OperationView(ctk.CTkScrollableFrame):

    def __init__(self, master, app: "StationApp"):
        super().__init__(master, fg_color="transparent")
        self._app = app
        self.grid_columnconfigure(0, weight=1)

        self._resumo: st.ResumoArquivo | None = None
        self._sessao = None          # sessao.Sessao do arquivo atual (ja em listas / restantes)
        self._executando = False
        self._itens_prontidao: list[st.ItemProntidao] = []

        self._fonte_var = ctk.StringVar(
            value=st.Fonte.SCROLL.value if app.cfg.scroll_mode else st.Fonte.ARQUIVO.value)
        # Segurança: a execução SEMPRE começa em simulação, mesmo que a última
        # rodada tenha sido real. Escolha consciente, toda vez.
        self._exec_var = ctk.StringVar(value=st.Execucao.SIMULACAO.value)
        self._arquivo_var = ctk.StringVar()
        self._ddd_modo_var = ctk.StringVar(value="todos" if not app.cfg.ddds else "selecao")
        self._ddd_extra_var = ctk.StringVar()
        self._listas_var = ctk.StringVar(value=str(st.clamp_listas(app.cfg.scroll_lists)))
        # Ensaio em escada (5 -> 30 -> lista cheia): nunca persiste — a
        # estação sempre reabre no "Lista cheia" (o padrão de sempre) para
        # que ligar "Real" sem pensar nunca dispare menos que o esperado nem
        # mais; escolher um ensaio menor é decisão consciente a cada abertura.
        self._ensaio_var = ctk.StringVar(value=st.ENSAIO_SCROLL_PADRAO)
        self._ddd_checks: dict[str, ctk.BooleanVar] = {}

        salvos, _ = st.parse_ddds(app.cfg.ddds)
        for cod in st.DDDS_DESTAQUE:
            self._ddd_checks[cod] = ctk.BooleanVar(value=cod in salvos)
        extras = [c for c in salvos if c not in st.DDDS_DESTAQUE]
        if extras:
            self._ddd_extra_var.set(",".join(extras))

        self._montar()
        self._ao_trocar_fonte()

    # ---------- construção ----------

    def _montar(self):
        self._card_estado()
        self._card_fonte()
        self._card_ddd()
        self._card_execucao()
        self._card_andamento()

    def _card_estado(self):
        card = ui.SectionCard(
            self, "Estado da estação",
            "O que precisa estar pronto antes de começar.", numero=1)
        card.grid(row=0, column=0, sticky="ew", pady=(0, S.MD))
        self._card_estado_ref = card

        self._prontidao: dict[str, ui.ReadinessItem] = {}
        for i, (chave, titulo) in enumerate((
                ("iphone", "iPhone conectado"),
                ("appium", "Appium funcionando"),
                ("wda", "WebDriverAgent"),
                ("fonte", "Fonte de contatos"))):
            item = ui.ReadinessItem(card.body, titulo)
            item.grid(row=i, column=0, sticky="ew", pady=(0 if i == 0 else S.MD, 0))
            item.set("verificando", "Verificando…")
            self._prontidao[chave] = item

    def _card_fonte(self):
        card = ui.SectionCard(
            self, "De onde vêm os contatos",
            "Escolha um jeito. Os dois não funcionam ao mesmo tempo.", numero=2)
        card.grid(row=1, column=0, sticky="ew", pady=(0, S.MD))
        self._card_fonte_ref = card
        card.body.grid_columnconfigure((0, 1), weight=1, uniform="fonte")

        self._modo_arquivo = ui.ModeSelectorCard(
            card.body, "Importar CSV ou VCF",
            "Você escolhe o arquivo exportado da agenda. Dá para filtrar por DDD "
            "e conferir quantas listas vão sair antes de começar.",
            self._fonte_var, st.Fonte.ARQUIVO.value, self._ao_trocar_fonte)
        self._modo_arquivo.grid(row=0, column=0, sticky="nsew", padx=(0, S.SM))

        self._modo_scroll = ui.ModeSelectorCard(
            card.body, "Usar Scroll Livre",
            "Sem arquivo: a estação marca os contatos na ordem em que o WhatsApp "
            "os lista e retoma de onde parou na rodada anterior.",
            self._fonte_var, st.Fonte.SCROLL.value, self._ao_trocar_fonte)
        self._modo_scroll.grid(row=0, column=1, sticky="nsew", padx=(S.SM, 0))

        # ---- painel do modo arquivo ----
        self._painel_arquivo = ctk.CTkFrame(card.body, fg_color="transparent")
        self._painel_arquivo.grid_columnconfigure(0, weight=1)

        campo = ui.FormField(self._painel_arquivo, "Arquivo de contatos",
                             "Exporte no iPhone: Contatos › Listas › Todos os Contatos › "
                             "Exportar › AirDrop para o Mac.")
        campo.grid(row=0, column=0, sticky="ew")
        campo.body.grid_columnconfigure(0, weight=1)
        self._entrada_arquivo = ctk.CTkEntry(
            campo.body, textvariable=self._arquivo_var, height=ui.ALTURA_CONTROLE,
            placeholder_text="Nenhum arquivo escolhido", font=ui.f_corpo(),
            corner_radius=ui.RAIO_PEQ, border_color=C.BORDA)
        self._entrada_arquivo.grid(row=0, column=0, sticky="ew", padx=(0, S.SM))
        ui.SecondaryButton(campo.body, "Escolher…", self._escolher_arquivo,
                           width=120).grid(row=0, column=1)
        ui.SecondaryButton(campo.body, "Exportar restantes…", self._exportar_restantes,
                           width=170).grid(row=0, column=2, padx=(S.SM, 0))

        self._resumo_frame = ctk.CTkFrame(self._painel_arquivo, fg_color=C.SUPERFICIE_2,
                                          corner_radius=ui.RAIO_PEQ)
        self._resumo_frame.grid(row=1, column=0, sticky="ew", pady=(S.MD, 0))
        self._tiles: dict[str, ctk.CTkLabel] = {}
        self._tiles_frames: list[ctk.CTkFrame] = []
        for i, (chave, rotulo) in enumerate((
                ("encontrados", "No arquivo"),
                ("validos", "Números válidos"),
                ("descartados", "Inválidos ou repetidos"),
                ("filtrados", "Depois do filtro"),
                ("adicionados", "Já em listas"),
                ("listas", "Listas planejadas"))):
            bloco = ctk.CTkFrame(self._resumo_frame, fg_color="transparent")
            self._tiles_frames.append(bloco)
            ctk.CTkLabel(bloco, text="—", font=ui.f_numero(), text_color=C.TEXTO,
                         anchor="w").grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(bloco, text=rotulo, font=ui.f_legenda(),
                         text_color=C.TEXTO_3, anchor="w").grid(row=1, column=0,
                                                                sticky="w")
            self._tiles[chave] = bloco.winfo_children()[0]
        self._nota_resumo = ctk.CTkLabel(
            self._resumo_frame, text="Escolha um arquivo para ver o resumo.",
            font=ui.f_apoio(), text_color=C.TEXTO_3, anchor="w", justify="left",
            wraplength=620)
        self._grid_tiles(3)

        # ---- painel do modo scroll ----
        self._painel_scroll = ctk.CTkFrame(card.body, fg_color="transparent")
        self._painel_scroll.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self._painel_scroll,
            text=("Neste modo a estação não usa arquivo nem filtro de DDD. Ela abre "
                  "a tela de destinatários e marca os contatos na ordem alfabética "
                  "em que o WhatsApp os mostra, até completar a lista."),
            font=ui.f_apoio(), text_color=C.TEXTO_2, anchor="w", justify="left",
            wraplength=620).grid(row=0, column=0, sticky="ew")

        linha = ctk.CTkFrame(self._painel_scroll, fg_color="transparent")
        linha.grid(row=1, column=0, sticky="ew", pady=(S.MD, 0))
        linha.grid_columnconfigure(2, weight=1)

        self._campo_listas = ui.FormField(
            linha, "Listas nesta rodada",
            f"De {st.MIN_LISTAS_RODADA} a {st.MAX_LISTAS_RODADA} listas de até "
            f"{st.LIMITE_LISTA} contatos.")
        self._campo_listas.grid(row=0, column=0, sticky="w")
        self._entrada_listas = ctk.CTkEntry(
            self._campo_listas.body, textvariable=self._listas_var, width=88,
            height=ui.ALTURA_CONTROLE, justify="center", font=ui.f_corpo(),
            corner_radius=ui.RAIO_PEQ, border_color=C.BORDA)
        self._entrada_listas.grid(row=0, column=0, sticky="w")
        self._listas_var.trace_add("write", lambda *_: self._ao_mudar_listas())

        ui.SecondaryButton(linha, "Consultar progresso", self._consultar_progresso,
                           width=180).grid(row=0, column=1, sticky="w",
                                           padx=(S.MD, 0), pady=(20, 0))

        self._progresso_scroll = ctk.CTkLabel(
            self._painel_scroll, text="Progresso ainda não consultado.",
            font=ui.f_apoio(), text_color=C.TEXTO_3, anchor="w", justify="left",
            wraplength=620)
        self._progresso_scroll.grid(row=2, column=0, sticky="ew", pady=(S.MD, 0))

        # Agenda opcional: so para o filtro de DDD. A tela do WhatsApp não mostra
        # o número de contato salvo, então o DDD é decidido pelo nome, cruzando
        # com a agenda exportada.
        agenda = ui.FormField(
            self._painel_scroll, "Agenda para filtrar por DDD (opcional)",
            "Só é necessária se você marcar DDDs abaixo. O mesmo arquivo VCF ou CSV "
            "exportado do iPhone.")
        agenda.grid(row=5, column=0, sticky="ew", pady=(S.LG, 0))
        agenda.body.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(agenda.body, textvariable=self._arquivo_var,
                     height=ui.ALTURA_CONTROLE, placeholder_text="Nenhum arquivo",
                     font=ui.f_corpo(), corner_radius=ui.RAIO_PEQ,
                     border_color=C.BORDA).grid(row=0, column=0, sticky="ew",
                                                padx=(0, S.SM))
        ui.SecondaryButton(agenda.body, "Escolher…", self._escolher_arquivo,
                           width=120).grid(row=0, column=1)

        # Tamanho do ensaio: o caminho para 5 -> 30 -> lista cheia sem precisar
        # do terminal (auditoria 2026-09-10 — antes só o terminal alcançava o
        # teste de 5 contatos, e quem abria a estação ia direto para 256).
        ensaio = ui.FormField(
            self._painel_scroll, "Tamanho do ensaio",
            "Comece pequeno num iPhone novo: 5, depois 30, só depois a lista cheia.")
        ensaio.grid(row=6, column=0, sticky="w", pady=(S.LG, 0))
        ctk.CTkSegmentedButton(
            ensaio.body, values=list(st.PRESETS_ENSAIO_SCROLL.keys()),
            variable=self._ensaio_var, font=ui.f_corpo(),
            selected_color=C.AZUL, selected_hover_color=C.AZUL_HOVER,
        ).grid(row=0, column=0, sticky="w")

        # Turbo: nunca persiste — é escolha consciente a cada abertura.
        self._turbo_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self._painel_scroll, text="Turbo: tocar todos os contatos da tela de uma vez",
            variable=self._turbo_var, font=ui.f_corpo(), checkbox_width=18,
            checkbox_height=18, fg_color=C.AMBAR, hover_color=C.AMBAR,
            corner_radius=4).grid(row=3, column=0, sticky="w", pady=(S.LG, 0))
        ctk.CTkLabel(
            self._painel_scroll,
            text=("Cerca de 3 vezes mais rápido. Ligue só depois de o teste de 5 "
                  "contatos ter passado neste iPhone: no turbo, um aviso que apareça "
                  "no meio da tela interrompe a lista por segurança."),
            font=ui.f_legenda(), text_color=C.TEXTO_3, anchor="w", justify="left",
            wraplength=620).grid(row=4, column=0, sticky="ew", pady=(S.XS, 0))

    def _grid_tiles(self, colunas: int):
        for i in range(6):
            self._resumo_frame.grid_columnconfigure(i, weight=0)
        for i in range(colunas):
            self._resumo_frame.grid_columnconfigure(i, weight=1, uniform="tile")
        for i, bloco in enumerate(self._tiles_frames):
            bloco.grid(row=i // colunas, column=i % colunas, sticky="ew",
                       padx=S.LG, pady=(S.MD, S.SM))
        linhas = (len(self._tiles_frames) + colunas - 1) // colunas
        self._nota_resumo.grid(row=linhas, column=0, columnspan=colunas,
                               sticky="ew", padx=S.LG, pady=(0, S.MD))

    def _card_ddd(self):
        card = ui.SectionCard(
            self, "Filtrar por DDD",
            "Vale combinar mais de um. Sem seleção, entram todos.", numero=3)
        card.grid(row=2, column=0, sticky="ew", pady=(0, S.MD))
        self._card_ddd_ref = card

        opcoes = ctk.CTkFrame(card.body, fg_color="transparent")
        opcoes.grid(row=0, column=0, sticky="ew")
        ctk.CTkRadioButton(opcoes, text="Todos os DDDs", variable=self._ddd_modo_var,
                           value="todos", command=self._ao_mudar_ddd,
                           font=ui.f_corpo(), radiobutton_width=18,
                           radiobutton_height=18, fg_color=C.AZUL,
                           hover_color=C.AZUL_HOVER).grid(row=0, column=0, sticky="w")
        ctk.CTkRadioButton(opcoes, text="Selecionar DDDs", variable=self._ddd_modo_var,
                           value="selecao", command=self._ao_mudar_ddd,
                           font=ui.f_corpo(), radiobutton_width=18,
                           radiobutton_height=18, fg_color=C.AZUL,
                           hover_color=C.AZUL_HOVER).grid(row=0, column=1, sticky="w",
                                                          padx=(S.XL, 0))

        self._painel_ddd = ctk.CTkFrame(card.body, fg_color="transparent")
        self._painel_ddd.grid(row=1, column=0, sticky="ew", pady=(S.MD, 0))
        self._painel_ddd.grid_columnconfigure(0, weight=1)

        chips = ctk.CTkFrame(self._painel_ddd, fg_color="transparent")
        chips.grid(row=0, column=0, sticky="ew")
        self._chips_ddd = []
        for i, cod in enumerate(st.DDDS_DESTAQUE):
            chk = ctk.CTkCheckBox(
                chips, text=st.rotulo_ddd(cod), variable=self._ddd_checks[cod],
                command=self._ao_mudar_ddd, font=ui.f_corpo(),
                checkbox_width=18, checkbox_height=18, fg_color=C.AZUL,
                hover_color=C.AZUL_HOVER, corner_radius=4)
            chk.grid(row=0, column=i, sticky="w", padx=(0 if i == 0 else S.LG, 0))
            self._chips_ddd.append(chk)

        self._campo_extra = ui.FormField(
            self._painel_ddd, "Outros DDDs",
            "Separe por vírgula. Exemplo: 11,31,71")
        self._campo_extra.grid(row=1, column=0, sticky="ew", pady=(S.MD, 0))
        self._entrada_extra = ctk.CTkEntry(
            self._campo_extra.body, textvariable=self._ddd_extra_var, width=220,
            height=ui.ALTURA_CONTROLE, font=ui.f_corpo(), corner_radius=ui.RAIO_PEQ,
            placeholder_text="opcional", border_color=C.BORDA)
        self._entrada_extra.grid(row=0, column=0, sticky="w")
        self._ddd_extra_var.trace_add("write", lambda *_: self._ao_mudar_ddd())

    def _card_execucao(self):
        card = ui.SectionCard(
            self, "Tipo de execução",
            "A simulação percorre tudo e cancela no fim, sem criar nada.", numero=4)
        card.grid(row=3, column=0, sticky="ew", pady=(0, S.MD))
        self._card_exec_ref = card
        card.body.grid_columnconfigure((0, 1), weight=1, uniform="exec")

        self._modo_simulacao = ui.ModeSelectorCard(
            card.body, "Simulação segura",
            "Abre o WhatsApp, marca os contatos e cancela antes de criar. "
            "Serve para conferir o que entraria na lista.",
            self._exec_var, st.Execucao.SIMULACAO.value, self._ao_trocar_execucao)
        self._modo_simulacao.grid(row=0, column=0, sticky="nsew", padx=(0, S.SM))

        self._modo_real = ui.ModeSelectorCard(
            card.body, "Criar listas de verdade",
            "Cria as listas no WhatsApp do iPhone. Pede confirmação antes de "
            "começar. Nenhuma mensagem é enviada.",
            self._exec_var, st.Execucao.REAL.value, self._ao_trocar_execucao,
            tom_selecionado="atencao")
        self._modo_real.grid(row=0, column=1, sticky="nsew", padx=(S.SM, 0))

    def _card_andamento(self):
        card = ui.SectionCard(self, "Execução",
                              "Acompanhe aqui. Dá para parar a qualquer momento.",
                              numero=5)
        card.grid(row=4, column=0, sticky="nsew", pady=(0, S.LG))
        self._card_exec_andamento = card
        self.grid_rowconfigure(4, weight=1)
        card.body.grid_columnconfigure(0, weight=1)

        self._selo_estado = ui.StatusBadge(card.acessorio(), "Parada", "neutro")
        self._selo_estado.pack()

        self._estado_lbl = ctk.CTkLabel(
            card.body, text="Pronta para começar.", font=ui.f_corpo_b(),
            text_color=C.TEXTO, anchor="w", justify="left", wraplength=620)
        self._estado_lbl.grid(row=0, column=0, sticky="ew")

        self._motivo_lbl = ctk.CTkLabel(
            card.body, text="", font=ui.f_apoio(), text_color=C.TEXTO_2,
            anchor="w", justify="left", wraplength=620)
        self._motivo_lbl.grid(row=1, column=0, sticky="ew", pady=(2, 0))

        barra = ctk.CTkFrame(card.body, fg_color="transparent")
        barra.grid(row=2, column=0, sticky="ew", pady=(S.MD, 0))
        barra.grid_columnconfigure(0, weight=1)
        self._barra = ctk.CTkProgressBar(barra, height=8, corner_radius=4,
                                         progress_color=C.AZUL, fg_color=C.NEUTRO_FUNDO)
        self._barra.set(0)
        self._barra.grid(row=0, column=0, sticky="ew", padx=(0, S.MD))
        self._contador_lbl = ctk.CTkLabel(barra, text="", font=ui.f_apoio(),
                                          text_color=C.TEXTO_2, anchor="e", width=170)
        self._contador_lbl.grid(row=0, column=1, sticky="e")

        botoes = ctk.CTkFrame(card.body, fg_color="transparent")
        botoes.grid(row=3, column=0, sticky="ew", pady=(S.LG, 0))
        self._btn_iniciar = ui.PrimaryButton(botoes, "Iniciar", self._iniciar, width=200)
        self._btn_iniciar.grid(row=0, column=0, sticky="w")
        self._btn_iniciar.configure(state="disabled")
        self._btn_parar = ui.DangerButton(botoes, "Parar com segurança", self._parar,
                                          width=190)
        self._btn_parar.grid(row=0, column=1, sticky="w", padx=(S.SM, 0))
        self._btn_parar.configure(state="disabled")

        self._detalhes = ui.Collapsible(card.body, "Ver detalhes técnicos")
        self._detalhes.grid(row=4, column=0, sticky="nsew", pady=(S.MD, 0))
        card.body.grid_rowconfigure(4, weight=1)
        self._log = ui.LogBox(self._detalhes.body, height=220)
        self._log.grid(row=0, column=0, sticky="nsew")

    # ---------- reações da interface ----------

    def _ao_trocar_fonte(self):
        arquivo = self._fonte_var.get() == st.Fonte.ARQUIVO.value
        self._painel_arquivo.grid(row=1, column=0, columnspan=2, sticky="ew",
                                  pady=(S.LG, 0)) if arquivo else self._painel_arquivo.grid_forget()
        self._painel_scroll.grid_forget() if arquivo else self._painel_scroll.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(S.LG, 0))
        # O filtro de DDD vale nos dois modos. No Scroll Livre ele depende da
        # agenda (o subtítulo do cartão explica).
        self._card_ddd_ref.grid(row=2, column=0, sticky="ew", pady=(0, S.MD))
        self._app.cfg.scroll_mode = not arquivo
        self._app.cfg.save()
        self._atualizar()

    def _ao_trocar_execucao(self):
        self._atualizar()

    def _ao_mudar_ddd(self):
        selecao = self._ddd_modo_var.get() == "selecao"
        estado = "normal" if selecao else "disabled"
        for chk in self._chips_ddd:
            chk.configure(state=estado)
        self._entrada_extra.configure(state=estado)
        if selecao:
            self._painel_ddd.grid(row=1, column=0, sticky="ew", pady=(S.MD, 0))
        else:
            self._painel_ddd.grid_forget()
        self._atualizar()

    def _ao_mudar_listas(self):
        valor, erro = st.validar_listas(self._listas_var.get())
        self._campo_listas.erro(erro)
        if valor is not None:
            self._app.cfg.scroll_lists = valor
            self._app.cfg.save()
        self._atualizar()

    def _escolher_arquivo(self):
        caminho = filedialog.askopenfilename(
            title="Escolher arquivo de contatos",
            filetypes=[("Contatos (CSV ou VCF)", "*.csv *.vcf"),
                       ("CSV", "*.csv"), ("vCard", "*.vcf"),
                       ("Todos os arquivos", "*.*")])
        if not caminho:
            return
        self._arquivo_var.set(caminho)
        self._resumo = st.analisar_arquivo(caminho)
        self._atualizar()

    def _consultar_progresso(self):
        """Pergunta ao próprio run_ios_scroll.py onde a rodada anterior parou.
        Não lê nem escreve o arquivo de progresso por conta própria."""
        self._progresso_scroll.configure(text="Consultando…", text_color=C.TEXTO_3)

        def trabalho():
            script = Path(__file__).parent / "run_ios_scroll.py"
            try:
                saida = subprocess.run(
                    [sys.executable, str(script), "--progresso"],
                    capture_output=True, text=True, timeout=60,
                    cwd=str(Path(__file__).parent))
                texto = (saida.stdout or saida.stderr or "").strip()
                texto = texto.splitlines()[-1] if texto else "Sem informação."
                cor = C.TEXTO_2
            except Exception as exc:
                texto = f"Não consegui consultar o progresso: {exc}"
                cor = C.VERMELHO
            self._app.after(0, lambda: self._progresso_scroll.configure(
                text=texto, text_color=cor))

        threading.Thread(target=trabalho, daemon=True).start()

    # ---------- estado derivado ----------

    def _ddds_escolhidos(self) -> tuple[list[str], list[str]]:
        if self._ddd_modo_var.get() != "selecao":
            return [], []
        escolhidos = [c for c in st.DDDS_DESTAQUE if self._ddd_checks[c].get()]
        extras, invalidos = st.parse_ddds(self._ddd_extra_var.get())
        for c in extras:
            if c not in escolhidos:
                escolhidos.append(c)
        return escolhidos, invalidos

    def _contagem(self) -> tuple[int, int]:
        """(contatos depois do filtro, listas previstas)."""
        if self._fonte_var.get() == st.Fonte.SCROLL.value:
            valor, _ = st.validar_listas(self._listas_var.get())
            ddds, _ = self._ddds_escolhidos()
            na_agenda = 0
            if ddds and self._resumo and self._resumo.ok:
                na_agenda = len(st.aplicar_filtro_ddd(self._resumo.contatos, ddds))
            return na_agenda, valor or 0
        if not self._resumo or not self._resumo.ok:
            return 0, 0
        ddds, _ = self._ddds_escolhidos()
        filtrados = st.aplicar_filtro_ddd(self._resumo.contatos, ddds)
        # Quem ja esta numa lista criada fica de fora — a mesma conta do runner.
        self._sessao = st.descontar_sessao(filtrados, self._progresso_path())
        restantes = len(self._sessao.restantes)
        return restantes, st.contar_listas(restantes)

    def _progresso_path(self) -> str:
        return str(Path(__file__).parent / st.PROGRESSO_PADRAO)

    def _ja_adicionados(self) -> int:
        if self._fonte_var.get() != st.Fonte.ARQUIVO.value or self._sessao is None:
            return 0
        return len(self._sessao.adicionados)

    def _exportar_restantes(self):
        """Grava, ao lado do arquivo importado, os CSVs de restantes, adicionados e
        nao adicionados desta sessao (respeitando o filtro de DDD). Nao toca no
        iPhone nem no progresso."""
        if not self._resumo or not self._resumo.ok:
            self._nota_resumo.configure(text="Escolha um arquivo primeiro.",
                                        text_color=C.AMBAR)
            return
        ddds, _ = self._ddds_escolhidos()
        filtrados = st.aplicar_filtro_ddd(self._resumo.contatos, ddds)
        ses = st.descontar_sessao(filtrados, self._progresso_path())
        try:
            import sessao
            saidas = sessao.exportar(self._resumo.caminho, ses)
        except Exception as exc:
            self._nota_resumo.configure(text=f"Não consegui exportar: {exc}",
                                        text_color=C.VERMELHO)
            return
        nomes = ", ".join(Path(p).name for p in saidas.values())
        self._nota_resumo.configure(
            text=(f"Exportado na pasta do arquivo: {nomes} — {len(ses.restantes)} "
                  f"restantes, {len(ses.adicionados)} já em listas, "
                  f"{len(ses.nao_adicionados)} não adicionados."),
            text_color=C.TEXTO_2)

    def _atualizar(self):
        fonte = st.Fonte(self._fonte_var.get())
        ddds, invalidos = self._ddds_escolhidos()
        self._campo_extra.erro(
            "DDD inexistente: " + ", ".join(invalidos) if invalidos else "")
        filtrados, listas = self._contagem()

        if fonte == st.Fonte.ARQUIVO:
            self._atualizar_resumo(filtrados, listas, ddds)
            self._app.cfg.ddds = st.formatar_ddds(ddds)
            self._app.cfg.save()

        amb = self._app.ambiente
        amb.wda_bundle = self._app.cfg.wda_bundle
        self._itens_prontidao = st.itens_prontidao(amb, fonte, self._resumo, listas,
                                                   ja_adicionados=self._ja_adicionados())
        for item in self._itens_prontidao:
            alvo = self._prontidao.get(item.chave)
            if alvo:
                alvo.set(item.estado.value, item.detalhe, item.orientacao)

        pode, motivo = st.pode_iniciar(self._itens_prontidao, self._executando)
        if invalidos:
            pode, motivo = False, "Corrija os DDDs digitados."
        elif fonte == st.Fonte.SCROLL and ddds and not (self._resumo and self._resumo.ok):
            pode, motivo = False, ("Para filtrar por DDD no Scroll Livre, escolha o "
                                   "arquivo da agenda: a tela do WhatsApp não mostra "
                                   "o número.")
        real = self._exec_var.get() == st.Execucao.REAL.value
        self._btn_iniciar.configure(
            state="normal" if pode else "disabled",
            text="Criar listas de verdade" if real else "Iniciar simulação",
            fg_color=C.AMBAR if real else C.AZUL,
            hover_color=("#6E4700", "#D98A1F") if real else C.AZUL_HOVER)
        if not self._executando:
            self._motivo_lbl.configure(text=motivo, text_color=C.TEXTO_2)
        self._app.atualizar_indicadores()

    def _atualizar_resumo(self, filtrados: int, listas: int, ddds: list[str]):
        fmt = lambda n: f"{n:,}".replace(",", ".")
        r = self._resumo
        if r is None or not r.caminho:
            for lbl in self._tiles.values():
                lbl.configure(text="—", text_color=C.TEXTO_3)
            self._nota_resumo.configure(
                text="Escolha um arquivo para ver o resumo.", text_color=C.TEXTO_3)
            return
        if r.erro:
            for lbl in self._tiles.values():
                lbl.configure(text="—", text_color=C.TEXTO_3)
            self._nota_resumo.configure(
                text=f"Não consegui ler {r.nome_arquivo}: {r.erro}",
                text_color=C.VERMELHO)
            return
        self._tiles["encontrados"].configure(text=fmt(r.encontrados), text_color=C.TEXTO)
        self._tiles["validos"].configure(text=fmt(r.validos), text_color=C.TEXTO)
        self._tiles["descartados"].configure(
            text=fmt(r.invalidos + r.duplicados),
            text_color=C.AMBAR if (r.invalidos + r.duplicados) else C.TEXTO)
        # `filtrados` aqui sao os RESTANTES (depois do filtro e da sessao).
        ses = self._sessao
        adicionados = len(ses.adicionados) if ses else 0
        nao_adic = len(ses.nao_adicionados) if ses else 0
        apos_filtro = filtrados + adicionados + nao_adic
        self._tiles["filtrados"].configure(
            text=fmt(apos_filtro), text_color=C.TEXTO if apos_filtro else C.AMBAR)
        self._tiles["adicionados"].configure(
            text=fmt(adicionados), text_color=C.TEXTO if adicionados else C.TEXTO_3)
        self._tiles["listas"].configure(
            text=str(listas), text_color=C.TEXTO if listas else C.AMBAR)
        pequeno = st.lotes_pequenos(filtrados)
        nota = (f"{r.tipo} · {r.nome_arquivo} · {st.descrever_ddds(ddds)} · "
                f"{r.invalidos} inválido(s) e {r.duplicados} repetido(s) descartados.")
        if adicionados or nao_adic:
            nota += (f" Sessão: {fmt(adicionados)} já em listas criadas e "
                     f"{fmt(filtrados)} restantes")
            if nao_adic:
                nota += f"; {fmt(nao_adic)} não encontrado(s) antes ficam de fora"
            nota += "."
        if pequeno:
            nota += (f" A última lista ficaria com {pequeno} contato e o WhatsApp "
                     f"exige {st.MIN_DESTINATARIOS}: ela será pulada.")
        self._nota_resumo.configure(text=nota, text_color=C.TEXTO_3)

    # ---------- execução ----------

    def _iniciar(self):
        fonte = st.Fonte(self._fonte_var.get())
        execucao = st.Execucao(self._exec_var.get())
        ddds, _ = self._ddds_escolhidos()
        filtrados, listas = self._contagem()

        turbo = fonte == st.Fonte.SCROLL and bool(self._turbo_var.get())
        ensaio_txt = self._ensaio_var.get() if fonte == st.Fonte.SCROLL else st.ENSAIO_SCROLL_PADRAO
        limite_ensaio = (st.PRESETS_ENSAIO_SCROLL.get(ensaio_txt, 0)
                         if fonte == st.Fonte.SCROLL else 0)
        if execucao == st.Execucao.REAL:
            # O limite do ensaio vai JUNTO: sem ele a linha "Listas" dizia
            # "de ate 256 contatos" com o ensaio de 5 escolhido logo abaixo.
            linhas = st.resumo_confirmacao(fonte, execucao, self._resumo, ddds,
                                           filtrados, listas,
                                           ja_adicionados=self._ja_adicionados(),
                                           limite=limite_ensaio)
            if turbo:
                linhas.append(("Toques", "Turbo: rajada por tela"))
            if fonte == st.Fonte.SCROLL and ensaio_txt != st.ENSAIO_SCROLL_PADRAO:
                linhas.append(("Tamanho do ensaio", ensaio_txt))
            dialogo = ui.ConfirmDialog(
                self._app, "Confirmar criação das listas", linhas,
                "Durante a execução a estação controla o WhatsApp no iPhone. "
                "Deixe o aparelho desbloqueado e não mexa nele. Nenhuma mensagem "
                "é enviada.", texto_confirmar="Criar listas")
            if not dialogo.perguntar():
                return

        aprova = st.aprova_criacao(execucao)
        self._executando = True
        self._log.limpar()
        self._detalhes.abrir()
        self._barra.set(0)
        self._selo_estado.set("Executando", "ativo")
        self._estado_lbl.configure(text="Preparando a sessão…", text_color=C.TEXTO)
        self._motivo_lbl.configure(
            text=("Criando listas de verdade no iPhone." if aprova
                  else "Simulação: nada será criado."),
            text_color=C.AMBAR if aprova else C.TEXTO_2)
        self._contador_lbl.configure(text="")
        self._btn_iniciar.configure(state="disabled")
        self._btn_parar.configure(state="normal")
        self._rolar_para_execucao()

        if fonte == st.Fonte.SCROLL:
            self._app.total_listas = listas
            agenda = self._arquivo_var.get() if ddds else ""
            limite = st.PRESETS_ENSAIO_SCROLL.get(self._ensaio_var.get(), 0)
            self._app.iniciar_execucao("", ddd=st.formatar_ddds(ddds) if agenda else "",
                                       scroll=True, scroll_lists=listas,
                                       approve=aprova, turbo=turbo, agenda=agenda,
                                       limite=limite)
            return

        caminho = self._arquivo_var.get()
        if caminho.lower().endswith(".vcf"):
            convertido = self._converter_vcf(caminho)
            if convertido is None:
                self._encerrar_ui(2)
                return
            caminho = convertido
        self._app.total_listas = listas
        self._app.iniciar_execucao(caminho, ddd=st.formatar_ddds(ddds),
                                   approve=aprova)

    def _converter_vcf(self, caminho: str) -> str | None:
        """O runner só lê CSV: converte o VCF antes, com as mesmas regras do
        resumo que a tela mostrou."""
        try:
            import csv as _csv
            destino = caminho[:-4] + "_estacao.csv"
            with open(destino, "w", encoding="utf-8", newline="") as f:
                escritor = _csv.writer(f)
                escritor.writerow(["name", "phone"])
                for c in (self._resumo.contatos if self._resumo else []):
                    escritor.writerow([c.name, c.e164])
            self._log.escrever(
                f"INFO  VCF convertido para CSV: {len(self._resumo.contatos)} "
                f"números.", "INFO")
            return destino
        except Exception as exc:
            self._log.escrever(f"ERRO  Falha ao converter o VCF: {exc}", "ERRO")
            self._detalhes.abrir()
            return None

    def _rolar_para_execucao(self):
        """Leva a tela até o cartão de execução: quem apertou Iniciar precisa
        ver o andamento, não a configuração."""
        def _rolar():
            try:
                self.update_idletasks()
                self._parent_canvas.yview_moveto(1.0)
            except Exception:
                pass
        # duas passadas: a primeira depois de a área recalcular a altura com o
        # log aberto, a segunda quando as primeiras linhas já entraram.
        self.after(80, _rolar)
        self.after(400, _rolar)

    def _parar(self):
        self._btn_parar.configure(state="disabled", text="Parando…")
        self._estado_lbl.configure(text="Encerrando com segurança…")
        self._app.parar_execucao()

    def registrar_log(self, linha: str):
        self._log.escrever(linha, st.classificar_linha(linha))
        frase = st.etapa_humana(linha)
        if frase and self._executando:
            self._estado_lbl.configure(text=frase, text_color=C.TEXTO)

    def atualizar_progresso(self, atual: int, total: int):
        if total > 0:
            fracao = min(1.0, atual / total)
            self._barra.set(fracao)
            self._contador_lbl.configure(
                text=f"Lista {atual} de {total}  ·  {round(fracao * 100)}%")
        else:
            self._contador_lbl.configure(text=f"Lista {atual}")

    def _encerrar_ui(self, codigo: int, interrompido: bool = False):
        self._executando = False
        self._btn_parar.configure(state="disabled", text="Parar com segurança")
        desfecho = st.desfecho_para(codigo, interrompido)
        if desfecho.tom == "erro":
            # Erro conhecido no log (WDA, Xcode, autorizacao, Appium)? Explica
            # em portugues o que fazer, em vez de "veja os detalhes".
            conhecido = st.diagnosticar_log(self._log.texto())
            if conhecido is not None:
                desfecho = conhecido
        tom = {"ok": "ok", "atencao": "atencao", "erro": "erro"}[desfecho.tom]
        self._selo_estado.set(desfecho.titulo, tom)
        self._estado_lbl.configure(
            text=desfecho.titulo,
            text_color={"ok": C.VERDE, "atencao": C.AMBAR, "erro": C.VERMELHO}[desfecho.tom])
        self._motivo_lbl.configure(text=desfecho.orientacao, text_color=C.TEXTO_2)
        if desfecho.tom == "ok":
            self._barra.set(1)
        else:
            self._detalhes.abrir()
        if desfecho.tom == "erro":
            self._log.escrever(f"INFO  código técnico de saída: {codigo}", "INFO")
        self._atualizar()

    def ao_terminar(self, codigo: int, interrompido: bool = False):
        self._encerrar_ui(codigo, interrompido)

    def atualizar_ambiente(self):
        self._atualizar()

    def ajustar(self, largura: int):
        colunas = (5 if largura >= 1000 else 4 if largura >= 820
                   else 3 if largura >= 620 else 2)
        self._grid_tiles(colunas)
        texto = max(280, largura - 120)
        for item in self._prontidao.values():
            item.ajustar_texto(texto)
        for cartao in (self._modo_arquivo, self._modo_scroll,
                       self._modo_simulacao, self._modo_real):
            cartao.ajustar_texto(max(180, largura // 2 - 90))
        for lbl in (self._estado_lbl, self._motivo_lbl, self._nota_resumo,
                    self._progresso_scroll):
            lbl.configure(wraplength=texto)
        # Cartões de escolha lado a lado só quando cabem.
        empilhar = largura < 760
        for card, filhos in ((self._card_fonte_ref, (self._modo_arquivo, self._modo_scroll)),
                             (self._card_exec_ref, (self._modo_simulacao, self._modo_real))):
            if empilhar:
                card.body.grid_columnconfigure(1, weight=0)
                filhos[0].grid(row=0, column=0, columnspan=2, sticky="ew",
                               padx=0, pady=(0, S.SM))
                filhos[1].grid(row=1, column=0, columnspan=2, sticky="ew", padx=0)
            else:
                card.body.grid_columnconfigure((0, 1), weight=1, uniform="par")
                filhos[0].grid(row=0, column=0, columnspan=1, sticky="nsew",
                               padx=(0, S.SM), pady=0)
                filhos[1].grid(row=0, column=1, columnspan=1, sticky="nsew",
                               padx=(S.SM, 0), pady=0)
        linha_painel = 2 if empilhar else 1
        if self._fonte_var.get() == st.Fonte.ARQUIVO.value:
            self._painel_arquivo.grid(row=linha_painel, column=0, columnspan=2,
                                      sticky="ew", pady=(S.LG, 0))
        else:
            self._painel_scroll.grid(row=linha_painel, column=0, columnspan=2,
                                     sticky="ew", pady=(S.LG, 0))


# ── Aba: Diagnóstico ─────────────────────────────────────────────────────────

# Cada cartão é alimentado pelas linhas que o doctor_ios.py imprime. A ordem
# importa: a primeira palavra-chave que casar leva a linha.
_CARTOES_DIAG = [
    ("macos", "macOS", ("macos", "sistema:")),
    ("xcode", "Xcode", ("xcode",)),
    # "Dependencias Python (appium, ...)" cita o Appium: precisa vir antes dele.
    ("ferramentas", "Ferramentas e bibliotecas",
     ("node", "python3", "idevice_id", "dependencias", "dependências",
      "ideviceinstaller", "libimobiledevice")),
    ("xcuitest", "Driver XCUITest", ("xcuitest",)),
    ("appium", "Appium", ("appium",)),
    # "iOS 16+ exige Modo de Desenvolvedor" cita o iOS: precisa vir antes do iPhone.
    ("devmode", "Modo de Desenvolvedor", ("modo de desenvolvedor",)),
    ("whatsapp", "WhatsApp", ("whatsapp",)),
    ("iphone", "iPhone", ("iphone", "ios ", "aparelho")),
]


class DiagnosticsView(ctk.CTkScrollableFrame):

    def __init__(self, master, app: "StationApp"):
        super().__init__(master, fg_color="transparent")
        self._app = app
        self._ocupado = False
        self.grid_columnconfigure(0, weight=1)
        self._montar()

    def _montar(self):
        card = ui.SectionCard(
            self, "Verificação do ambiente",
            "Confere o que a estação precisa no Mac e no iPhone. "
            "Não toca no WhatsApp.")
        card.grid(row=0, column=0, sticky="ew", pady=(0, S.MD))
        self._card_check = card
        acessorio = card.acessorio()
        self._btn_verificar = ui.SecondaryButton(
            acessorio, "Verificar novamente", self._verificar, width=190)
        self._btn_verificar.pack()

        self._itens: dict[str, ui.ReadinessItem] = {}
        self._grade = card.body
        for i, (chave, titulo, _) in enumerate(_CARTOES_DIAG):
            item = ui.ReadinessItem(self._grade, titulo)
            item.set("verificando", "Ainda não verificado.")
            self._itens[chave] = item
        self._item_wda = ui.ReadinessItem(self._grade, "WebDriverAgent")
        self._itens["wda"] = self._item_wda
        self._grid_itens(2)

        card_wda = ui.SectionCard(
            self, "WebDriverAgent",
            "Componente que o Appium instala no iPhone para conseguir tocar na "
            "tela. Precisa disso na primeira configuração e depois de falhas de "
            "conexão. Leva de 3 a 7 minutos e usa o Xcode.")
        card_wda.grid(row=1, column=0, sticky="ew", pady=(0, S.MD))
        self._btn_wda = ui.SecondaryButton(
            card_wda.body, "Instalar ou reparar WDA", self._instalar_wda, width=230)
        self._btn_wda.grid(row=0, column=0, sticky="w")
        self._wda_estado = ctk.CTkLabel(
            card_wda.body, text="", font=ui.f_apoio(), text_color=C.TEXTO_2,
            anchor="w", justify="left", wraplength=620)
        self._wda_estado.grid(row=1, column=0, sticky="ew", pady=(S.SM, 0))

        card_log = ui.SectionCard(self, "Saída técnica",
                                  "O texto completo das ferramentas, sem filtro.")
        card_log.grid(row=2, column=0, sticky="nsew", pady=(0, S.LG))
        self.grid_rowconfigure(2, weight=1)
        card_log.body.grid_rowconfigure(0, weight=1)
        self._log = ui.LogBox(card_log.body, height=240)
        self._log.grid(row=0, column=0, sticky="nsew")
        self._atualizar_wda()

    def _grid_itens(self, colunas: int):
        chaves = [c for c, _, _ in _CARTOES_DIAG] + ["wda"]
        for i in range(4):
            self._grade.grid_columnconfigure(i, weight=0)
        for i in range(colunas):
            self._grade.grid_columnconfigure(i, weight=1, uniform="diag")
        for i, chave in enumerate(chaves):
            self._itens[chave].grid(row=i // colunas, column=i % colunas,
                                    sticky="ew", padx=(0, S.LG), pady=(0, S.MD))

    def _atualizar_wda(self):
        bundle = self._app.cfg.wda_bundle
        if bundle:
            self._item_wda.set("pronto", "Identificador salvo.", "")
            self._wda_estado.configure(
                text=f"Identificador atual: {bundle}", text_color=C.TEXTO_2)
        else:
            self._item_wda.set(
                "atencao", "Sem identificador salvo.",
                "Não impede a operação: o Appium instala na primeira execução.")
            self._wda_estado.configure(
                text="Nenhum identificador salvo. A estação funciona assim mesmo.",
                text_color=C.TEXTO_3)

    # ---------- ações ----------

    def _travar(self, ocupado: bool, texto_wda: str = "Instalar ou reparar WDA"):
        self._ocupado = ocupado
        estado = "disabled" if ocupado else "normal"
        self._btn_verificar.configure(
            state=estado, text="Verificando…" if ocupado else "Verificar novamente")
        self._btn_wda.configure(state=estado, text=texto_wda)

    def _verificar(self):
        if self._ocupado:
            return
        self._travar(True)
        self._log.limpar()
        for chave, _, _ in _CARTOES_DIAG:
            self._itens[chave].set("verificando", "Verificando…")
        threading.Thread(target=self._rodar_doctor, daemon=True).start()

    def _rodar_doctor(self):
        script = Path(__file__).parent / "doctor_ios.py"
        pendente: str | None = None
        try:
            proc = subprocess.Popen(
                [sys.executable, str(script)], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                cwd=str(Path(__file__).parent))
            for bruta in proc.stdout:
                linha = bruta.rstrip()
                if not linha:
                    continue
                self._app.after(0, self._log.escrever, linha,
                                st.classificar_linha(linha))
                pendente = self._app_processar(linha, pendente)
            proc.wait()
        except Exception as exc:
            self._app.after(0, self._log.escrever, f"ERRO  {exc}", "ERRO")
        self._app.after(0, self._fim_doctor)

    def _app_processar(self, linha: str, pendente: str | None) -> str | None:
        """Encaixa a linha do doctor no cartão certo. Devolve a chave do cartão
        que ainda pode receber a dica da linha seguinte ('-> faça isso')."""
        despido = linha.strip()
        if despido.startswith("->") and pendente:
            self._app.after(0, self._completar_item, pendente, despido[2:].strip())
            return pendente
        if not despido.startswith("["):
            return None
        estado = ("pronto" if despido.startswith("[OK") else
                  "atencao" if despido.startswith("[AVISO") else "falta")
        texto = despido.split("]", 1)[1].strip() if "]" in despido else despido
        baixa = texto.lower()
        for chave, _, palavras in _CARTOES_DIAG:
            if any(p in baixa for p in palavras):
                self._app.after(0, self._preencher_item, chave, estado, texto)
                return chave
        return None

    def _preencher_item(self, chave: str, estado: str, texto: str):
        item = self._itens.get(chave)
        if item:
            item.set(estado, texto)

    def _completar_item(self, chave: str, dica: str):
        """A dica vem na linha seguinte ('-> faça isso'): mantém o estado que já
        foi decidido e só acrescenta a orientação."""
        item = self._itens.get(chave)
        if item:
            item.set(item.estado, item.detalhe_atual(), dica)

    def _fim_doctor(self):
        self._travar(False)
        for chave, _titulo, _ in _CARTOES_DIAG:
            item = self._itens[chave]
            if item.estado == "verificando":
                item.set("atencao", "O diagnóstico não informou este item.",
                         "Veja a saída técnica abaixo.")
        self._atualizar_wda()

    def _instalar_wda(self):
        if self._ocupado:
            return
        self._travar(True, "Instalando…")
        self._log.limpar()
        self._log.escrever("=== Instalação do WebDriverAgent ===", "TITULO")
        self._log.escrever("INFO  Pode levar de 3 a 7 minutos. Não desconecte o "
                           "iPhone e mantenha a tela desbloqueada.", "INFO")
        self._item_wda.set("verificando", "Instalando…")
        threading.Thread(target=self._rodar_install_wda, daemon=True).start()

    def _rodar_install_wda(self):
        script = Path(__file__).parent / "install_wda.py"
        env = os.environ.copy()
        env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        bundle = ""
        codigo = 1
        try:
            proc = subprocess.Popen(
                [sys.executable, str(script)], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                cwd=str(Path(__file__).parent), env=env)
            for bruta in proc.stdout:
                linha = bruta.rstrip()
                if not linha:
                    continue
                if linha.startswith("WDA_BUNDLE:"):
                    bundle = linha.split(":", 1)[1].strip()
                    continue
                if linha.startswith("WDA_ERROR:"):
                    self._app.after(0, self._log.escrever,
                                    "ERRO  " + linha.split(":", 1)[1].strip(), "ERRO")
                    continue
                self._app.after(0, self._log.escrever, linha,
                                st.classificar_linha(linha))
            proc.wait()
            codigo = proc.returncode
        except Exception as exc:
            self._app.after(0, self._log.escrever, f"ERRO  {exc}", "ERRO")
        self._app.after(0, self._fim_install_wda, codigo, bundle)

    def _fim_install_wda(self, codigo: int, bundle: str):
        self._travar(False)
        if codigo == 0:
            if bundle:
                self._app.cfg.wda_bundle = bundle
                self._app.cfg.save()
                self._log.escrever(
                    f"OK  WebDriverAgent instalado. Identificador salvo: {bundle}", "OK")
            else:
                self._log.escrever(
                    "OK  WebDriverAgent instalado. O Appium vai reaproveitá-lo.", "OK")
            self._log.escrever("Volte para Operação e comece pela simulação.", "INFO")
        else:
            self._item_wda.set("falta", "A instalação falhou.",
                               "Veja o erro na saída técnica acima.")
            self._log.escrever(
                "ERRO  A instalação não terminou. Confira se o Xcode está instalado "
                "e se o iPhone confia neste Mac (Ajustes › Geral › VPN e Gestão do "
                "Dispositivo).", "ERRO")
            return
        self._atualizar_wda()

    def ajustar(self, largura: int):
        self._grid_itens(2 if largura >= 720 else 1)
        for item in self._itens.values():
            item.ajustar_texto(max(240, (largura // 2) - 80))
        self._wda_estado.configure(wraplength=max(280, largura - 120))


# ── Aba: Configurações ───────────────────────────────────────────────────────

class SettingsView(ctk.CTkScrollableFrame):

    def __init__(self, master, app: "StationApp"):
        super().__init__(master, fg_color="transparent")
        self._app = app
        self.grid_columnconfigure(0, weight=1)
        cfg = app.cfg
        self._server_var = ctk.StringVar(value=cfg.server)
        self._wda_var = ctk.StringVar(value=cfg.wda_bundle)
        self._auto_var = ctk.BooleanVar(value=cfg.auto_appium)
        self._pace_var = ctk.DoubleVar(value=cfg.pace)
        self._pace_listas_var = ctk.DoubleVar(value=cfg.pace_lists)
        self._ritmo_var = ctk.StringVar(
            value=st.preset_de(cfg.speed, cfg.pace, cfg.pace_lists))
        self._speed = cfg.speed
        self._montar()

    def _montar(self):
        # Conexão
        card = ui.SectionCard(self, "Conexão",
                              "Onde a estação fala com o Appium.")
        card.grid(row=0, column=0, sticky="ew", pady=(0, S.MD))
        campo = ui.FormField(card.body, "Endereço do servidor Appium",
                             "Padrão: http://127.0.0.1:4723 (o próprio Mac).")
        campo.grid(row=0, column=0, sticky="ew")
        ctk.CTkEntry(campo.body, textvariable=self._server_var, width=320,
                     height=ui.ALTURA_CONTROLE, font=ui.f_corpo(),
                     corner_radius=ui.RAIO_PEQ, border_color=C.BORDA).grid(
            row=0, column=0, sticky="w")

        # WebDriverAgent
        card = ui.SectionCard(self, "WebDriverAgent",
                              "Identificador do componente instalado no iPhone.")
        card.grid(row=1, column=0, sticky="ew", pady=(0, S.MD))
        campo = ui.FormField(
            card.body, "Identificador (Bundle ID)",
            "Deixe vazio se o padrão funciona. A aba Diagnóstico preenche "
            "sozinha depois de instalar.")
        campo.grid(row=0, column=0, sticky="ew")
        ctk.CTkEntry(campo.body, textvariable=self._wda_var, width=420,
                     height=ui.ALTURA_CONTROLE, font=ui.f_corpo(),
                     corner_radius=ui.RAIO_PEQ, border_color=C.BORDA,
                     placeholder_text="opcional").grid(row=0, column=0, sticky="w")

        # Ritmo
        card = ui.SectionCard(
            self, "Ritmo da automação",
            "Pausas entre um contato e outro. Ritmo mais lento parece mais com "
            "uso humano; mais rápido termina antes.")
        card.grid(row=2, column=0, sticky="ew", pady=(0, S.MD))
        self._card_ritmo = card

        presets = ctk.CTkSegmentedButton(
            card.body, values=list(st.PRESETS_RITMO.keys()) + ["Personalizado"],
            variable=self._ritmo_var, command=self._aplicar_preset,
            font=ui.f_corpo(), height=32, selected_color=C.AZUL,
            selected_hover_color=C.AZUL_HOVER)
        presets.grid(row=0, column=0, sticky="w")

        self._campo_pace = ui.FormField(card.body, "Pausa entre contatos")
        self._campo_pace.grid(row=1, column=0, sticky="ew", pady=(S.LG, 0))
        linha = self._campo_pace.body
        self._pace_lbl = ctk.CTkLabel(linha, text="", font=ui.f_corpo_b(),
                                      text_color=C.TEXTO, width=70, anchor="w")
        self._pace_lbl.grid(row=0, column=1, sticky="w", padx=(S.MD, 0))
        ctk.CTkSlider(linha, from_=0.05, to=3.0, number_of_steps=59, width=260,
                      variable=self._pace_var, command=self._ao_mover_pace,
                      button_color=C.AZUL, progress_color=C.AZUL).grid(
            row=0, column=0, sticky="w")

        self._campo_pace_listas = ui.FormField(card.body, "Pausa entre listas")
        self._campo_pace_listas.grid(row=2, column=0, sticky="ew", pady=(S.MD, 0))
        linha2 = self._campo_pace_listas.body
        self._pace_listas_lbl = ctk.CTkLabel(linha2, text="", font=ui.f_corpo_b(),
                                             text_color=C.TEXTO, width=70, anchor="w")
        self._pace_listas_lbl.grid(row=0, column=1, sticky="w", padx=(S.MD, 0))
        ctk.CTkSlider(linha2, from_=5, to=120, number_of_steps=115, width=260,
                      variable=self._pace_listas_var,
                      command=self._ao_mover_pace_listas,
                      button_color=C.AZUL, progress_color=C.AZUL).grid(
            row=0, column=0, sticky="w")

        self._estimativa = ctk.CTkLabel(
            card.body, text="", font=ui.f_apoio(), text_color=C.TEXTO_3,
            anchor="w", justify="left", wraplength=620)
        self._estimativa.grid(row=3, column=0, sticky="ew", pady=(S.MD, 0))

        # Inicialização
        card = ui.SectionCard(self, "Inicialização",
                              "O que acontece quando a estação abre.")
        card.grid(row=3, column=0, sticky="ew", pady=(0, S.MD))
        ctk.CTkSwitch(card.body, text="Iniciar o Appium automaticamente",
                      variable=self._auto_var, font=ui.f_corpo(),
                      progress_color=C.AZUL).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(card.body,
                     text="Desligue se você prefere rodar o Appium à mão no terminal.",
                     font=ui.f_legenda(), text_color=C.TEXTO_3, anchor="w").grid(
            row=1, column=0, sticky="w", pady=(S.XS, 0))

        # Salvar
        rodape = ctk.CTkFrame(self, fg_color="transparent")
        rodape.grid(row=4, column=0, sticky="ew", pady=(0, S.LG))
        ui.PrimaryButton(rodape, "Salvar configurações", self._salvar,
                         width=220).grid(row=0, column=0, sticky="w")
        self._aviso_salvo = ui.StatusBadge(rodape, "", "ok")
        self._aviso_salvo.grid(row=0, column=1, sticky="w", padx=(S.MD, 0))
        self._aviso_salvo.grid_remove()

        self._ao_mover_pace(self._pace_var.get())
        self._ao_mover_pace_listas(self._pace_listas_var.get())

    def _aplicar_preset(self, nome: str):
        if nome not in st.PRESETS_RITMO:
            return
        speed, pace, pace_listas = st.PRESETS_RITMO[nome]
        self._speed = speed
        self._pace_var.set(pace)
        self._pace_listas_var.set(pace_listas)
        self._ao_mover_pace(pace)
        self._ao_mover_pace_listas(pace_listas)
        self._ritmo_var.set(nome)

    def _ao_mover_pace(self, valor):
        self._pace_lbl.configure(text=f"{float(valor):.2f} s")
        self._sincronizar_preset()

    def _ao_mover_pace_listas(self, valor):
        self._pace_listas_lbl.configure(text=f"{float(valor):.0f} s")
        self._sincronizar_preset()

    def _sincronizar_preset(self):
        nome = st.preset_de(self._speed, self._pace_var.get(),
                            self._pace_listas_var.get())
        self._ritmo_var.set(nome)
        minutos = st.estimativa_minutos(self._pace_var.get(), self._speed)
        self._estimativa.configure(
            text=f"Estimativa: cerca de {minutos} min por lista cheia de "
                 f"{st.LIMITE_LISTA} contatos, no modo arquivo. É estimativa, "
                 f"não medição.")

    def _salvar(self):
        cfg = self._app.cfg
        cfg.server = self._server_var.get().strip() or APPIUM_URL
        cfg.wda_bundle = self._wda_var.get().strip()
        cfg.auto_appium = self._auto_var.get()
        cfg.pace = round(self._pace_var.get(), 2)
        # Preset "Máximo" só existe se speed for 0,25 — o piso que o runner aceita.
        cfg.pace_lists = round(self._pace_listas_var.get(), 0)
        cfg.speed = self._speed
        cfg.ritmo_definido = True
        cfg.save()
        self._aviso_salvo.grid()
        self._aviso_salvo.set("Salvo", "ok")
        self.after(2500, self._aviso_salvo.grid_remove)
        self._app.ao_salvar_config()

    def ajustar(self, largura: int):
        self._estimativa.configure(wraplength=max(280, largura - 120))


# ── Janela principal ─────────────────────────────────────────────────────────

class StationApp(ctk.CTk):

    ABAS = (("operacao", "Operação"), ("diagnostico", "Diagnóstico"),
            ("config", "Configurações"))

    def __init__(self):
        super().__init__()
        self.cfg = AppConfig.load()
        self.ambiente = st.Ambiente()
        self.total_listas = 0
        self._lista_atual = 0
        self._runner: RunnerThread | None = None
        self._appium = AppiumManager()
        self._fila: queue.Queue = queue.Queue()
        self._aba_atual = "operacao"
        self._largura_anterior = 0
        self._redimensionar_id = None

        self.title(f"{TITULO} — Lista Local")
        self.geometry("1080x820")
        self.minsize(ui.LARGURA_MINIMA, 640)
        self.configure(fg_color=C.JANELA)

        self._montar()
        self._iniciar_appium()

        # O monitor roda numa thread e NÃO toca no Tk: entrega o resultado pela
        # mesma fila que o log usa, consumida no laço principal. (Chamar after()
        # de outra thread antes do mainloop matava a thread em silêncio, e a
        # tela ficava em "Verificando…" para sempre.)
        self._monitor = EnvironmentMonitor(self._ao_observar_ambiente)
        self.after(300, self._monitor.start)
        self._consumir_fila()
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self.bind("<Configure>", self._ao_redimensionar)
        self.update_idletasks()
        self.after(150, self.update_idletasks)   # evita janela cinza no macOS

    # ---------- layout ----------

    def _montar(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        lateral = ctk.CTkFrame(self, fg_color=C.LATERAL, corner_radius=0, width=228)
        lateral.grid(row=0, column=0, sticky="nsw")
        lateral.grid_propagate(False)
        lateral.grid_rowconfigure(2, weight=1)
        lateral.grid_columnconfigure(0, weight=1)

        marca = ctk.CTkFrame(lateral, fg_color="transparent")
        marca.grid(row=0, column=0, sticky="ew", padx=S.LG, pady=(S.XL, S.LG))
        marca.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(marca, text=TITULO, font=ui.fonte(17, negrito=True),
                     text_color=C.TEXTO, anchor="w").grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(marca, text=SUBTITULO, font=ui.f_legenda(),
                     text_color=C.TEXTO_3, anchor="w", justify="left",
                     wraplength=190).grid(row=1, column=0, sticky="ew", pady=(2, 0))

        navegacao = ctk.CTkFrame(lateral, fg_color="transparent")
        navegacao.grid(row=1, column=0, sticky="ew", padx=S.MD)
        navegacao.grid_columnconfigure(0, weight=1)
        self._botoes_aba: dict[str, ctk.CTkButton] = {}
        for i, (chave, rotulo) in enumerate(self.ABAS):
            b = ctk.CTkButton(
                navegacao, text=rotulo, anchor="w", height=38,
                corner_radius=ui.RAIO_PEQ, font=ui.f_corpo(),
                fg_color="transparent", text_color=C.TEXTO_2,
                hover_color=C.NEUTRO_FUNDO,
                command=lambda c=chave: self.mostrar_aba(c))
            b.grid(row=i, column=0, sticky="ew", pady=2)
            self._botoes_aba[chave] = b

        indicadores = ctk.CTkFrame(lateral, fg_color=C.SUPERFICIE_2,
                                   corner_radius=ui.RAIO_PEQ)
        indicadores.grid(row=3, column=0, sticky="ew", padx=S.MD, pady=(S.LG, S.LG))
        indicadores.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(indicadores, text="ESTAÇÃO", font=ui.fonte(10, negrito=True),
                     text_color=C.TEXTO_3, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=S.MD, pady=(S.MD, S.XS))
        self._indicadores = ui.StatusStrip(indicadores, [
            ("iphone", "iPhone"), ("appium", "Appium"),
            ("ambiente", "Ambiente"), ("operacao", "Operação")])
        self._indicadores.grid(row=1, column=0, sticky="ew", padx=S.MD,
                               pady=(0, S.MD))

        # área principal
        principal = ctk.CTkFrame(self, fg_color="transparent")
        principal.grid(row=0, column=1, sticky="nsew")
        principal.grid_rowconfigure(1, weight=1)
        principal.grid_columnconfigure(0, weight=1)

        cabecalho = ctk.CTkFrame(principal, fg_color="transparent", height=64)
        cabecalho.grid(row=0, column=0, sticky="ew", padx=S.XL, pady=(S.XL, S.MD))
        cabecalho.grid_columnconfigure(0, weight=1)
        self._titulo_pagina = ctk.CTkLabel(cabecalho, text="Operação",
                                           font=ui.f_pagina(), text_color=C.TEXTO,
                                           anchor="w")
        self._titulo_pagina.grid(row=0, column=0, sticky="ew")
        self._subtitulo_pagina = ctk.CTkLabel(
            cabecalho, text="", font=ui.f_apoio(), text_color=C.TEXTO_3,
            anchor="w", justify="left")
        self._subtitulo_pagina.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self._selo_topo = ui.StatusBadge(cabecalho, "Verificando", "neutro")
        self._selo_topo.grid(row=0, column=1, rowspan=2, sticky="e")

        self._container = ctk.CTkFrame(principal, fg_color="transparent")
        self._container.grid(row=1, column=0, sticky="nsew", padx=S.XL,
                             pady=(0, S.LG))
        self._container.grid_rowconfigure(0, weight=1)
        self._container.grid_columnconfigure(0, weight=1)

        self._views = {
            "operacao": OperationView(self._container, self),
            "diagnostico": DiagnosticsView(self._container, self),
            "config": SettingsView(self._container, self),
        }
        self.mostrar_aba("operacao")

    def mostrar_aba(self, chave: str):
        self._aba_atual = chave
        for c, view in self._views.items():
            if c == chave:
                view.grid(row=0, column=0, sticky="nsew")
            else:
                view.grid_forget()
        for c, botao in self._botoes_aba.items():
            ativo = c == chave
            botao.configure(fg_color=C.AZUL_FUNDO if ativo else "transparent",
                            text_color=C.AZUL if ativo else C.TEXTO_2,
                            font=ui.f_corpo_b() if ativo else ui.f_corpo())
        titulos = {
            "operacao": ("Operação", "Prepare, confira e execute."),
            "diagnostico": ("Diagnóstico", "O que está pronto no Mac e no iPhone."),
            "config": ("Configurações", "Ajustes que valem para todas as rodadas."),
        }
        titulo, sub = titulos[chave]
        self._titulo_pagina.configure(text=titulo)
        self._subtitulo_pagina.configure(text=sub)
        self.after(30, lambda: self._aplicar_largura(force=True))

    # ---------- responsividade ----------

    def _ao_redimensionar(self, evento):
        if evento.widget is not self:
            return
        if self._redimensionar_id:
            self.after_cancel(self._redimensionar_id)
        self._redimensionar_id = self.after(120, self._aplicar_largura)

    def _aplicar_largura(self, force: bool = False):
        self._redimensionar_id = None
        largura = max(320, self._container.winfo_width() - 40)
        if not force and abs(largura - self._largura_anterior) < 40:
            return
        self._largura_anterior = largura
        view = self._views.get(self._aba_atual)
        if view and hasattr(view, "ajustar"):
            try:
                view.ajustar(largura)
            except Exception:
                pass

    # ---------- ambiente e indicadores ----------

    def _iniciar_appium(self):
        if not self.cfg.auto_appium:
            return
        threading.Thread(target=self._appium.start, daemon=True).start()

    def _ao_observar_ambiente(self, ambiente: st.Ambiente):
        """Chamado NA THREAD do monitor: só enfileira. Nada de Tk aqui."""
        self._fila.put(("ambiente", ambiente))

    def _aplicar_ambiente(self, ambiente: st.Ambiente):
        ambiente.wda_bundle = self.cfg.wda_bundle
        self.ambiente = ambiente
        self._views["operacao"].atualizar_ambiente()

    def atualizar_indicadores(self):
        amb = self.ambiente
        if not amb.verificado:
            self._indicadores.set("iphone", "Verificando…", "verificando")
            self._indicadores.set("appium", "Verificando…", "verificando")
        else:
            if amb.iphone_count == 1:
                self._indicadores.set("iphone", "iPhone conectado", "pronto")
            elif amb.iphone_count == 0:
                self._indicadores.set("iphone", "iPhone não detectado", "falta")
            else:
                self._indicadores.set("iphone", f"{amb.iphone_count} iPhones", "falta")
            self._indicadores.set(
                "appium", "Appium ativo" if amb.appium_ok else "Appium parado",
                "pronto" if amb.appium_ok else "falta")

        executando = self._runner is not None and self._em_execucao()
        pronto = amb.verificado and amb.appium_ok and amb.iphone_count == 1
        self._indicadores.set("ambiente", "Pronto" if pronto else "Incompleto",
                              "pronto" if pronto else "atencao")
        self._indicadores.set(
            "operacao", "Em andamento" if executando else "Parada",
            "verificando" if executando else "pronto")
        if executando:
            self._selo_topo.set("Executando", "ativo")
        elif pronto:
            self._selo_topo.set("Pronta", "ok")
        elif amb.verificado:
            self._selo_topo.set("Requisitos incompletos", "atencao")
        else:
            self._selo_topo.set("Verificando", "neutro")

    def _em_execucao(self) -> bool:
        proc = getattr(self._runner, "_proc", None)
        return bool(self._runner) and (proc is None or proc.poll() is None)

    def ao_salvar_config(self):
        self._views["diagnostico"]._atualizar_wda()
        self._views["operacao"].atualizar_ambiente()

    # ---------- execução ----------

    def iniciar_execucao(self, csv_path: str, ddd: str = "", scroll: bool = False,
                         scroll_lists: int = 1, approve: bool = False,
                         turbo: bool = False, agenda: str = "", limite: int = 0):
        self._lista_atual = 0
        self._runner = RunnerThread(
            csv_path=csv_path, cfg=self.cfg, log_queue=self._fila,
            on_finish=lambda codigo: self.after(0, self._ao_terminar, codigo),
            ddd=ddd, scroll=scroll, scroll_lists=scroll_lists, approve=approve,
            turbo=turbo, agenda=agenda, limite=limite)
        self._runner.start()
        self.atualizar_indicadores()

    def parar_execucao(self):
        if self._runner:
            self._runner.stop()

    def _ao_terminar(self, codigo: int):
        interrompido = bool(self._runner and self._runner.parado_pelo_operador)
        self._views["operacao"].ao_terminar(codigo, interrompido)
        self._runner = None
        self.atualizar_indicadores()

    def _consumir_fila(self):
        try:
            while True:
                tipo, dado = self._fila.get_nowait()
                if tipo == "log":
                    self._processar_linha(dado)
                elif tipo == "ambiente":
                    self._aplicar_ambiente(dado)
        except queue.Empty:
            pass
        self.after(POLL_LOG_MS, self._consumir_fila)

    def _processar_linha(self, linha: str):
        self._views["operacao"].registrar_log(linha)
        progresso = st.extrair_progresso(linha)
        if progresso:
            atual, total = progresso
            self._lista_atual = atual
            if total:
                self.total_listas = total
            self._views["operacao"].atualizar_progresso(atual, self.total_listas)

    def _ao_fechar(self):
        if self._runner:
            self._runner.stop()
        if self._appium.managed():
            self._appium.stop()
        self._monitor.stop()
        self.destroy()


if __name__ == "__main__":
    StationApp().mainloop()
