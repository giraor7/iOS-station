"""Tokens visuais e componentes reaproveitados da Estacao iOS.

Um lugar so para cor, espacamento, tipografia e os blocos que se repetem —
para a janela (gui_ios.py) tratar de fluxo, nao de pixel.

Aparencia: sobria, proxima do macOS. Todas as cores sao pares
(claro, escuro) — o CustomTkinter escolhe conforme o tema do sistema.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk


# ── Cores ────────────────────────────────────────────────────────────────────
# (claro, escuro). Cinzas com leve viés frio, como as janelas do macOS.

class C:
    JANELA      = ("#ECECEE", "#1B1B1D")
    LATERAL     = ("#E3E3E7", "#161617")
    SUPERFICIE  = ("#FFFFFF", "#252528")
    SUPERFICIE_2 = ("#F4F4F6", "#2E2E32")
    BORDA       = ("#D6D6DB", "#3A3A3F")
    BORDA_FORTE = ("#B9B9C0", "#4C4C53")

    TEXTO       = ("#1D1D1F", "#F2F2F5")
    TEXTO_2     = ("#4E4E56", "#B6B6BE")
    TEXTO_3     = ("#77777F", "#8A8A93")

    AZUL        = ("#0A6FE0", "#0A84FF")
    AZUL_HOVER  = ("#0857B0", "#3D9BFF")
    AZUL_FUNDO  = ("#E4EFFD", "#132D4A")

    VERDE       = ("#1D7A3A", "#32D74B")
    VERDE_FUNDO = ("#E1F3E6", "#12301A")

    AMBAR       = ("#8A5A00", "#FFA928")
    AMBAR_FUNDO = ("#FBF0DC", "#33260A")

    VERMELHO    = ("#C00F0C", "#FF453A")
    VERMELHO_FUNDO = ("#FBE6E5", "#3A1512")
    VERMELHO_HOVER = ("#9A0B09", "#D63A31")

    NEUTRO_FUNDO = ("#EDEDF0", "#313136")


# ── Espacamento (multiplos de 4) ─────────────────────────────────────────────

class S:
    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 24
    XXL = 32


RAIO = 12
RAIO_PEQ = 8
ALTURA_CONTROLE = 40
ALTURA_PRINCIPAL = 44

LARGURA_MINIMA = 900          # abaixo disso, tudo vira uma coluna
QUEBRA_DUAS_COLUNAS = 1040    # a partir daqui, resumo e ajustes lado a lado


# ── Tipografia ───────────────────────────────────────────────────────────────

_FAMILIAS_TEXTO = ("SF Pro Text", "SF Pro Display", ".AppleSystemUIFont",
                   "Helvetica Neue", "Segoe UI", "Inter", "DejaVu Sans")
_FAMILIAS_MONO = ("Menlo", "SF Mono", "Consolas", "DejaVu Sans Mono", "Courier New")
_cache: dict[str, str] = {}


def _familia(preferencias: tuple[str, ...], chave: str) -> str:
    """Primeira fonte instalada da lista. Sem isso o Tk troca em silencio."""
    if chave in _cache:
        return _cache[chave]
    try:
        disponiveis = {f.lower() for f in tkfont.families()}
    except Exception:
        disponiveis = set()
    escolhida = next((f for f in preferencias if f.lower() in disponiveis),
                     preferencias[-1])
    _cache[chave] = escolhida
    return escolhida


def fonte(tamanho: int = 13, negrito: bool = False, mono: bool = False) -> ctk.CTkFont:
    familia = (_familia(_FAMILIAS_MONO, "mono") if mono
               else _familia(_FAMILIAS_TEXTO, "texto"))
    return ctk.CTkFont(family=familia, size=tamanho,
                       weight="bold" if negrito else "normal")


# Escala de tipos: titulo de pagina, titulo de secao, corpo, apoio, legenda.
def f_pagina():   return fonte(21, negrito=True)
def f_secao():    return fonte(15, negrito=True)
def f_corpo():    return fonte(13)
def f_corpo_b():  return fonte(13, negrito=True)
def f_apoio():    return fonte(12)
def f_legenda():  return fonte(11)
def f_numero():   return fonte(26, negrito=True)
def f_mono():     return fonte(11, mono=True)


# ── Componentes ──────────────────────────────────────────────────────────────

class SectionCard(ctk.CTkFrame):
    """Bloco de conteudo com titulo, subtitulo e numero de etapa opcional.

    O conteudo vai em `card.body` (um frame com grid ja configurado).
    """

    def __init__(self, master, titulo: str, subtitulo: str = "",
                 numero: int | None = None, **kw):
        kw.setdefault("fg_color", C.SUPERFICIE)
        kw.setdefault("corner_radius", RAIO)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", C.BORDA)
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)

        cabeca = ctk.CTkFrame(self, fg_color="transparent")
        cabeca.grid(row=0, column=0, sticky="ew", padx=S.LG, pady=(S.LG, 0))
        cabeca.grid_columnconfigure(1, weight=1)

        col_titulo = 0
        if numero is not None:
            selo = ctk.CTkLabel(cabeca, text=str(numero), width=24, height=24,
                                corner_radius=12, fg_color=C.AZUL,
                                text_color="#FFFFFF", font=fonte(12, negrito=True))
            selo.grid(row=0, column=0, sticky="w", padx=(0, S.MD))
            col_titulo = 1

        textos = ctk.CTkFrame(cabeca, fg_color="transparent")
        textos.grid(row=0, column=col_titulo, sticky="ew")
        textos.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(textos, text=titulo, font=f_secao(), text_color=C.TEXTO,
                     anchor="w", justify="left").grid(row=0, column=0, sticky="ew")
        if subtitulo:
            ctk.CTkLabel(textos, text=subtitulo, font=f_apoio(),
                         text_color=C.TEXTO_3, anchor="w", justify="left",
                         wraplength=680).grid(row=1, column=0, sticky="ew",
                                              pady=(2, 0))
        self.cabeca = cabeca
        self.acessorio_col = col_titulo + 1

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=S.LG, pady=(S.MD, S.LG))
        self.body.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

    def acessorio(self) -> ctk.CTkFrame:
        """Area a direita do titulo (botoes, selos)."""
        f = ctk.CTkFrame(self.cabeca, fg_color="transparent")
        f.grid(row=0, column=self.acessorio_col, sticky="e", padx=(S.MD, 0))
        self.cabeca.grid_columnconfigure(self.acessorio_col, weight=0)
        return f


_TONS = {
    "ok":      (C.VERDE, C.VERDE_FUNDO),
    "atencao": (C.AMBAR, C.AMBAR_FUNDO),
    "erro":    (C.VERMELHO, C.VERMELHO_FUNDO),
    "ativo":   (C.AZUL, C.AZUL_FUNDO),
    "neutro":  (C.TEXTO_3, C.NEUTRO_FUNDO),
}


class StatusBadge(ctk.CTkLabel):
    """Selo com texto. A cor reforca; quem informa e a palavra."""

    def __init__(self, master, texto: str = "", tom: str = "neutro", **kw):
        cor, fundo = _TONS.get(tom, _TONS["neutro"])
        kw.setdefault("font", fonte(11, negrito=True))
        super().__init__(master, text=texto, text_color=cor, fg_color=fundo,
                         corner_radius=RAIO_PEQ, padx=0, **kw)
        self.configure(width=0)
        self._pad()

    def _pad(self):
        # CTkLabel nao tem padding proprio: o espaco vem do texto com margem.
        texto = self.cget("text")
        if texto and not texto.startswith(" "):
            self.configure(text=f"  {texto}  ")

    def set(self, texto: str, tom: str = "neutro"):
        cor, fundo = _TONS.get(tom, _TONS["neutro"])
        self.configure(text=f"  {texto}  ", text_color=cor, fg_color=fundo)


_MARCAS = {"pronto": "✓", "atencao": "!", "falta": "✕", "verificando": "…"}
_MARCA_TOM = {"pronto": "ok", "atencao": "atencao", "falta": "erro",
              "verificando": "neutro"}


class ReadinessItem(ctk.CTkFrame):
    """Linha do checklist: marca + titulo + detalhe + orientacao.

    A marca (✓ ! ✕ …) diz o estado sem depender de cor.
    """

    def __init__(self, master, titulo: str, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self.grid_columnconfigure(1, weight=1)

        self._marca = ctk.CTkLabel(self, text="…", width=22, height=22,
                                   corner_radius=11, font=fonte(12, negrito=True),
                                   fg_color=C.NEUTRO_FUNDO, text_color=C.TEXTO_3)
        self._marca.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, S.MD),
                         pady=(2, 0))
        self._titulo = ctk.CTkLabel(self, text=titulo, font=f_corpo_b(),
                                    text_color=C.TEXTO, anchor="w")
        self._titulo.grid(row=0, column=1, sticky="ew")
        self._detalhe = ctk.CTkLabel(self, text="", font=f_apoio(),
                                     text_color=C.TEXTO_2, anchor="w",
                                     justify="left", wraplength=560)
        self._detalhe.grid(row=1, column=1, sticky="ew")
        self._orientacao = ctk.CTkLabel(self, text="", font=f_apoio(),
                                        text_color=C.AMBAR, anchor="w",
                                        justify="left", wraplength=560)
        self.estado = "verificando"

    def set(self, estado: str, detalhe: str, orientacao: str = ""):
        self.estado = estado
        tom = _MARCA_TOM.get(estado, "neutro")
        cor, fundo = _TONS[tom]
        self._marca.configure(text=_MARCAS.get(estado, "…"),
                              text_color=cor, fg_color=fundo)
        self._detalhe.configure(text=detalhe)
        if orientacao:
            self._orientacao.configure(text=orientacao)
            self._orientacao.grid(row=2, column=1, sticky="ew", pady=(2, 0))
        else:
            self._orientacao.grid_forget()

    def detalhe_atual(self) -> str:
        return self._detalhe.cget("text")

    def ajustar_texto(self, largura: int):
        self._detalhe.configure(wraplength=max(240, largura))
        self._orientacao.configure(wraplength=max(240, largura))


class ModeSelectorCard(ctk.CTkFrame):
    """Cartao que funciona como opcao de um grupo (radio grande e clicavel).

    Mantem um CTkRadioButton de verdade dentro, para teclado e leitor de tela.
    """

    def __init__(self, master, titulo: str, descricao: str,
                 variable: tk.StringVar, value: str, command=None,
                 tom_selecionado: str = "ativo", **kw):
        kw.setdefault("fg_color", C.SUPERFICIE_2)
        kw.setdefault("corner_radius", RAIO)
        kw.setdefault("border_width", 2)
        kw.setdefault("border_color", C.BORDA)
        super().__init__(master, **kw)
        self._var = variable
        self._value = value
        self._command = command
        self._tom = tom_selecionado
        self.grid_columnconfigure(0, weight=1)

        self._radio = ctk.CTkRadioButton(
            self, text=titulo, font=f_corpo_b(), variable=variable, value=value,
            command=self._escolher, radiobutton_width=18, radiobutton_height=18,
            fg_color=C.AZUL, hover_color=C.AZUL_HOVER, text_color=C.TEXTO)
        self._radio.grid(row=0, column=0, sticky="w", padx=S.LG, pady=(S.LG, S.XS))

        self._desc = ctk.CTkLabel(self, text=descricao, font=f_apoio(),
                                  text_color=C.TEXTO_2, anchor="w",
                                  justify="left", wraplength=330)
        self._desc.grid(row=1, column=0, sticky="ew", padx=(S.XL + S.MD, S.LG),
                        pady=(0, S.LG))

        for w in (self, self._desc):
            w.bind("<Button-1>", lambda _e: self._escolher())
        variable.trace_add("write", lambda *_: self.atualizar())
        self.atualizar()

    def _escolher(self):
        self._var.set(self._value)
        if self._command:
            self._command()

    def atualizar(self):
        ativo = self._var.get() == self._value
        cor = _TONS[self._tom][0] if ativo else C.BORDA
        self.configure(border_color=cor,
                       fg_color=_TONS[self._tom][1] if ativo else C.SUPERFICIE_2)

    def ajustar_texto(self, largura: int):
        self._desc.configure(wraplength=max(200, largura))


def PrimaryButton(master, texto: str, command=None, **kw) -> ctk.CTkButton:
    kw.setdefault("height", ALTURA_PRINCIPAL)
    kw.setdefault("corner_radius", RAIO_PEQ)
    return ctk.CTkButton(master, text=texto, command=command,
                         font=fonte(13, negrito=True), fg_color=C.AZUL,
                         hover_color=C.AZUL_HOVER, text_color="#FFFFFF", **kw)


def SecondaryButton(master, texto: str, command=None, **kw) -> ctk.CTkButton:
    kw.setdefault("height", ALTURA_CONTROLE)
    kw.setdefault("corner_radius", RAIO_PEQ)
    return ctk.CTkButton(master, text=texto, command=command, font=f_corpo(),
                         fg_color=C.SUPERFICIE_2, hover_color=C.NEUTRO_FUNDO,
                         text_color=C.TEXTO, border_width=1,
                         border_color=C.BORDA_FORTE, **kw)


def DangerButton(master, texto: str, command=None, **kw) -> ctk.CTkButton:
    kw.setdefault("height", ALTURA_CONTROLE)
    kw.setdefault("corner_radius", RAIO_PEQ)
    return ctk.CTkButton(master, text=texto, command=command,
                         font=fonte(13, negrito=True), fg_color=C.VERMELHO,
                         hover_color=C.VERMELHO_HOVER, text_color="#FFFFFF", **kw)


class FormField(ctk.CTkFrame):
    """Rotulo + campo + ajuda curta, empilhados."""

    def __init__(self, master, rotulo: str, ajuda: str = "", **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=rotulo, font=f_corpo_b(), text_color=C.TEXTO,
                     anchor="w").grid(row=0, column=0, sticky="ew")
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="ew", pady=(S.XS, 0))
        self.body.grid_columnconfigure(0, weight=1)
        self._ajuda = None
        if ajuda:
            self._ajuda = ctk.CTkLabel(self, text=ajuda, font=f_legenda(),
                                       text_color=C.TEXTO_3, anchor="w",
                                       justify="left", wraplength=520)
            self._ajuda.grid(row=2, column=0, sticky="ew", pady=(S.XS, 0))

    def erro(self, mensagem: str):
        if self._ajuda is None:
            return
        self._ajuda.configure(text=mensagem or "",
                              text_color=C.VERMELHO if mensagem else C.TEXTO_3)


class Collapsible(ctk.CTkFrame):
    """Bloco recolhivel — usado para o log tecnico não dominar a tela."""

    def __init__(self, master, titulo: str, aberto: bool = False, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)
        self._aberto = aberto
        self._titulo = titulo
        self._botao = ctk.CTkButton(
            self, text="", command=self.alternar, anchor="w", height=30,
            font=f_apoio(), fg_color="transparent", hover_color=C.NEUTRO_FUNDO,
            text_color=C.AZUL, corner_radius=RAIO_PEQ)
        self._botao.grid(row=0, column=0, sticky="w")
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)
        self._pintar()

    def _pintar(self):
        seta = "▾" if self._aberto else "▸"
        self._botao.configure(text=f"{seta}  {self._titulo}")
        if self._aberto:
            self.body.grid(row=1, column=0, sticky="nsew", pady=(S.SM, 0))
            self.grid_rowconfigure(1, weight=1)
        else:
            self.body.grid_forget()
            self.grid_rowconfigure(1, weight=0)

    def alternar(self):
        self._aberto = not self._aberto
        self._pintar()

    def abrir(self):
        if not self._aberto:
            self.alternar()


class LogBox(ctk.CTkTextbox):
    """Log tecnico com cores por severidade. Nunca edita o texto recebido."""

    TAGS = {
        "INFO":   C.TEXTO_2,
        "OK":     C.VERDE,
        "AVISO":  C.AMBAR,
        "ERRO":   C.VERMELHO,
        "TITULO": C.AZUL,
    }

    def __init__(self, master, **kw):
        kw.setdefault("font", f_mono())
        kw.setdefault("wrap", "word")
        kw.setdefault("fg_color", C.SUPERFICIE_2)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", C.BORDA)
        kw.setdefault("corner_radius", RAIO_PEQ)
        super().__init__(master, **kw)
        self.configure(state="disabled")
        self._configurar_tags()

    def _modo_escuro(self) -> bool:
        return ctk.get_appearance_mode().lower() == "dark"

    def _cor(self, par) -> str:
        return par[1] if self._modo_escuro() else par[0]

    def _configurar_tags(self):
        alvo = getattr(self, "_textbox", None)
        if alvo is None:      # versao futura do CustomTkinter sem atributo privado
            return
        for nome, par in self.TAGS.items():
            try:
                alvo.tag_configure(nome, foreground=self._cor(par))
            except Exception:
                pass

    def escrever(self, linha: str, tag: str = "INFO"):
        self.configure(state="normal")
        alvo = getattr(self, "_textbox", None)
        if alvo is not None:
            alvo.insert("end", linha + "\n", tag)
        else:
            self.insert("end", linha + "\n")
        self.see("end")
        self.configure(state="disabled")

    def limpar(self):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")

    def texto(self) -> str:
        return self.get("1.0", "end")


class StatusStrip(ctk.CTkFrame):
    """Indicadores persistentes da barra lateral (iPhone, Appium, ambiente,
    operação). Cada um mostra estado por palavra e por marca."""

    def __init__(self, master, chaves: list[tuple[str, str]], **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)
        self._linhas: dict[str, tuple[ctk.CTkLabel, ctk.CTkLabel]] = {}
        for i, (chave, rotulo) in enumerate(chaves):
            linha = ctk.CTkFrame(self, fg_color="transparent")
            linha.grid(row=i, column=0, sticky="ew", pady=2)
            linha.grid_columnconfigure(1, weight=1)
            marca = ctk.CTkLabel(linha, text="…", width=16, font=fonte(11, negrito=True),
                                 text_color=C.TEXTO_3)
            marca.grid(row=0, column=0, sticky="w")
            valor = ctk.CTkLabel(linha, text=rotulo, font=f_legenda(),
                                 text_color=C.TEXTO_3, anchor="w")
            valor.grid(row=0, column=1, sticky="ew", padx=(S.XS, 0))
            self._linhas[chave] = (marca, valor)

    def set(self, chave: str, texto: str, estado: str):
        par = self._linhas.get(chave)
        if not par:
            return
        marca, valor = par
        tom = _MARCA_TOM.get(estado, "neutro")
        marca.configure(text=_MARCAS.get(estado, "…"), text_color=_TONS[tom][0])
        valor.configure(text=texto,
                        text_color=C.TEXTO_2 if estado != "falta" else C.TEXTO_2)


class ConfirmDialog(ctk.CTkToplevel):
    """Confirmacao consciente antes de uma operacao real.

    Nao substitui trava nenhuma do backend: e uma etapa a mais.
    """

    def __init__(self, master, titulo: str, linhas: list[tuple[str, str]],
                 aviso: str, texto_confirmar: str = "Criar listas"):
        super().__init__(master)
        self.title(titulo)
        self.resizable(False, False)
        self.configure(fg_color=C.JANELA)
        self.resultado = False
        try:
            # janela filha: o macOS mantém a caixa acima da janela principal.
            self.transient(master)
        except Exception:
            pass

        quadro = ctk.CTkFrame(self, fg_color="transparent")
        quadro.pack(fill="both", expand=True, padx=S.XL, pady=S.XL)
        quadro.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(quadro, text=titulo, font=fonte(17, negrito=True),
                     text_color=C.TEXTO, anchor="w").grid(row=0, column=0,
                                                          sticky="ew")
        tabela = ctk.CTkFrame(quadro, fg_color=C.SUPERFICIE, corner_radius=RAIO,
                              border_width=1, border_color=C.BORDA)
        tabela.grid(row=1, column=0, sticky="ew", pady=(S.MD, S.MD))
        tabela.grid_columnconfigure(1, weight=1)
        for i, (rotulo, valor) in enumerate(linhas):
            ctk.CTkLabel(tabela, text=rotulo, font=f_apoio(), text_color=C.TEXTO_3,
                         anchor="w").grid(row=i, column=0, sticky="w",
                                          padx=(S.LG, S.MD),
                                          pady=(S.MD if i == 0 else 2, 2))
            ctk.CTkLabel(tabela, text=valor, font=f_corpo_b(), text_color=C.TEXTO,
                         anchor="w", justify="left", wraplength=360).grid(
                row=i, column=1, sticky="ew", padx=(0, S.LG),
                pady=(S.MD if i == 0 else 2, 2))
        ctk.CTkFrame(tabela, height=S.SM, fg_color="transparent").grid(
            row=len(linhas), column=0)

        ctk.CTkLabel(quadro, text=aviso, font=f_apoio(), text_color=C.AMBAR,
                     anchor="w", justify="left", wraplength=430).grid(
            row=2, column=0, sticky="ew", pady=(0, S.LG))

        botoes = ctk.CTkFrame(quadro, fg_color="transparent")
        botoes.grid(row=3, column=0, sticky="e")
        SecondaryButton(botoes, "Cancelar", self._cancelar, width=120).pack(
            side="left", padx=(0, S.SM))
        confirmar = PrimaryButton(botoes, texto_confirmar, self._confirmar, width=180)
        confirmar.pack(side="left")

        self.bind("<Escape>", lambda _e: self._cancelar())
        self.protocol("WM_DELETE_WINDOW", self._cancelar)
        self.after(50, lambda: (self._centralizar(master), confirmar.focus_set()))

    def _centralizar(self, master):
        try:
            self.update_idletasks()
            x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
            y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
            self.grab_set()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _confirmar(self):
        self.resultado = True
        self._fechar()

    def _cancelar(self):
        self.resultado = False
        self._fechar()

    def _fechar(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def perguntar(self) -> bool:
        self.wait_window()
        return self.resultado
