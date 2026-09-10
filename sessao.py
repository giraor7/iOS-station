"""Sessao de listas: quem ja foi adicionado, quem falta, quem nao deu.

Serve para dividir a criacao das listas em dias diferentes. O progresso do
run_ios.py guarda so o HASH de cada numero (nunca o numero em claro); este
modulo cruza esses hashes com o arquivo de contatos importado e devolve, em
memoria, tres grupos:

  * adicionados     — ja estao numa lista CRIADA (o runner os deixa de fora);
  * nao_adicionados — foram procurados e nao deram (nao encontrado / ambiguo);
                      ficam de fora por padrao para nao gastar ~3 s cada de novo;
  * restantes       — o que ainda falta; e o que o runner divide em listas.

`exportar` grava esses grupos como CSV ao lado do arquivo importado (mesma
sensibilidade do proprio arquivo: fica so no Mac; *.csv esta no .gitignore).
Nao ha Appium aqui — tudo e puro e testavel sem iPhone.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass, field

ADICIONADO = ("selected", "already_selected")
NAO_ADICIONADO = {"not_found": "nao_encontrado", "ambiguous": "ambiguo"}


def hash_numero(e164: str) -> str:
    """O mesmo hash que o progresso grava (16 hex do SHA-256 do E.164)."""
    return hashlib.sha256(e164.encode()).hexdigest()[:16]


def carregar_progresso(path: str | None) -> dict:
    """Le o progresso do run_ios.py; ausente ou ilegivel => vazio (nunca falha)."""
    vazio: dict = {"lists": {}}
    if not path or not os.path.exists(path):
        return vazio
    try:
        with open(path, encoding="utf-8") as f:
            dados = json.load(f)
    except (json.JSONDecodeError, OSError):
        return vazio
    if not isinstance(dados, dict) or not isinstance(dados.get("lists"), dict):
        return vazio
    return dados


@dataclass
class Sessao:
    adicionados: list = field(default_factory=list)       # NormalizedContact
    restantes: list = field(default_factory=list)         # NormalizedContact
    nao_adicionados: list = field(default_factory=list)   # (NormalizedContact, motivo)
    listas_criadas: int = 0
    ultima: str = ""                                      # quando da ultima lista criada

    @property
    def total(self) -> int:
        return len(self.adicionados) + len(self.restantes) + len(self.nao_adicionados)


def resumir(nums: list, progresso: dict, repetir_nao_encontrados: bool = False) -> Sessao:
    """Separa `nums` (NormalizedContact ja filtrados) pelos registros do progresso.

    Conta como adicionado so o que foi 'selected' numa lista com completed=True
    (simulacao e lista interrompida nao contam). Um contato nao encontrado num
    dia e adicionado no outro e adicionado. Registros antigos (sem 'quando')
    sao lidos do mesmo jeito."""
    adicionados_h: set[str] = set()
    motivos: dict[str, str] = {}
    ses = Sessao()
    for entrada in (progresso.get("lists") or {}).values():
        if not isinstance(entrada, dict):
            continue
        criada = bool(entrada.get("completed"))
        if criada:
            ses.listas_criadas += 1
            ses.ultima = max(ses.ultima, str(entrada.get("quando") or ""))
        for r in entrada.get("results") or []:
            if not isinstance(r, dict):
                continue
            h, desfecho = r.get("hash"), r.get("outcome")
            if not h:
                continue
            if criada and desfecho in ADICIONADO:
                adicionados_h.add(h)
            elif desfecho in NAO_ADICIONADO:
                motivos.setdefault(h, NAO_ADICIONADO[desfecho])
    for n in nums:
        h = hash_numero(n.e164)
        if h in adicionados_h:
            ses.adicionados.append(n)
        elif h in motivos and not repetir_nao_encontrados:
            ses.nao_adicionados.append((n, motivos[h]))
        else:
            ses.restantes.append(n)
    return ses


def descrever(ses: Sessao) -> str:
    """Uma frase, so contagens (nunca nome ou numero)."""
    partes = [f"{len(ses.adicionados)} ja adicionado(s) em {ses.listas_criadas} lista(s) criada(s)"]
    if ses.ultima:
        partes[0] += f" (ultima em {ses.ultima.replace('T', ' ')})"
    if ses.nao_adicionados:
        partes.append(f"{len(ses.nao_adicionados)} nao encontrado(s)/ambiguo(s) antes, "
                      "deixados de fora (--repetir-nao-encontrados para tentar de novo)")
    partes.append(f"{len(ses.restantes)} restante(s)")
    return "; ".join(partes)


def exportar(csv_origem: str, ses: Sessao, pasta: str | None = None) -> dict[str, str]:
    """Grava <nome>.restantes.csv, <nome>.adicionados.csv e, se houver,
    <nome>.nao-adicionados.csv (com a coluna motivo) na pasta do arquivo
    importado. Os tres sao importaveis de volta (name,phone; extras ignoradas).
    Devolve {grupo: caminho}."""
    base = os.path.splitext(os.path.basename(csv_origem))[0]
    pasta = pasta or os.path.dirname(os.path.abspath(csv_origem))
    saidas: dict[str, str] = {}

    def escrever(grupo: str, linhas: list) -> None:
        caminho = os.path.join(pasta, f"{base}.{grupo}.csv")
        with open(caminho, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["name", "phone"] + (["motivo"] if grupo == "nao-adicionados" else []))
            for linha in linhas:
                w.writerow(linha)
        saidas[grupo] = caminho

    escrever("restantes", [(n.name or "", n.e164) for n in ses.restantes])
    escrever("adicionados", [(n.name or "", n.e164) for n in ses.adicionados])
    if ses.nao_adicionados:
        escrever("nao-adicionados", [(n.name or "", n.e164, motivo)
                                     for n, motivo in ses.nao_adicionados])
    return saidas
