"""DDD -> UF -> regiao do Brasil, e filtros de contatos por area.

Usado para segmentar a base antes de criar as listas: por exemplo, criar
"Transmissao RJ 001" so com contatos do Rio, ou separar por DDD.

Funciona sobre numeros ja normalizados em E.164 (+55DD9XXXXXXXX). Numeros de
fora do Brasil ficam com uf=None e sao tratados pelo filtro "internacional".
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Tabela de DDDs. Codigos que nao existem simplesmente nao estao aqui — um
# numero com DDD desconhecido e sinalizado, nunca "chutado" para um estado.
# ---------------------------------------------------------------------------
DDD_UF: dict[str, str] = {
    # Sudeste
    "11": "SP", "12": "SP", "13": "SP", "14": "SP", "15": "SP",
    "16": "SP", "17": "SP", "18": "SP", "19": "SP",
    "21": "RJ", "22": "RJ", "24": "RJ",
    "27": "ES", "28": "ES",
    "31": "MG", "32": "MG", "33": "MG", "34": "MG", "35": "MG",
    "37": "MG", "38": "MG",
    # Sul
    "41": "PR", "42": "PR", "43": "PR", "44": "PR", "45": "PR", "46": "PR",
    "47": "SC", "48": "SC", "49": "SC",
    "51": "RS", "53": "RS", "54": "RS", "55": "RS",
    # Centro-Oeste
    "61": "DF",
    "62": "GO", "64": "GO",
    "65": "MT", "66": "MT",
    "67": "MS",
    # Norte
    "63": "TO",
    "68": "AC",
    "69": "RO",
    "91": "PA", "93": "PA", "94": "PA",
    "92": "AM", "97": "AM",
    "95": "RR",
    "96": "AP",
    # Nordeste
    "71": "BA", "73": "BA", "74": "BA", "75": "BA", "77": "BA",
    "79": "SE",
    "81": "PE", "87": "PE",
    "82": "AL",
    "83": "PB",
    "84": "RN",
    "85": "CE", "88": "CE",
    "86": "PI", "89": "PI",
    "98": "MA", "99": "MA",
}

UF_REGIAO: dict[str, str] = {
    # Norte
    "AC": "Norte", "AP": "Norte", "AM": "Norte", "PA": "Norte",
    "RO": "Norte", "RR": "Norte", "TO": "Norte",
    # Nordeste
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste",
    "PB": "Nordeste", "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste",
    "SE": "Nordeste",
    # Centro-Oeste
    "DF": "Centro-Oeste", "GO": "Centro-Oeste", "MT": "Centro-Oeste",
    "MS": "Centro-Oeste",
    # Sudeste
    "ES": "Sudeste", "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    # Sul
    "PR": "Sul", "RS": "Sul", "SC": "Sul",
}

# Areas principais por DDD (informativo, usado no relatorio).
DDD_AREA: dict[str, str] = {
    "11": "Sao Paulo (capital e regiao metropolitana)",
    "12": "Vale do Paraiba / Sao Jose dos Campos",
    "13": "Baixada Santista",
    "14": "Bauru / Marilia",
    "15": "Sorocaba",
    "16": "Ribeirao Preto / Sao Carlos",
    "17": "Sao Jose do Rio Preto",
    "18": "Presidente Prudente / Aracatuba",
    "19": "Campinas / Piracicaba",
    "21": "Rio de Janeiro (capital e regiao metropolitana)",
    "22": "Norte e Regiao dos Lagos (Campos, Macae, Cabo Frio)",
    "24": "Sul Fluminense e Serrana (Volta Redonda, Petropolis)",
    "27": "Vitoria / Grande Vitoria",
    "28": "Sul do ES (Cachoeiro de Itapemirim)",
    "31": "Belo Horizonte", "32": "Juiz de Fora",
    "33": "Governador Valadares / Teofilo Otoni",
    "34": "Uberlandia / Triangulo Mineiro",
    "35": "Sul de Minas (Pocos de Caldas, Varginha)",
    "37": "Divinopolis / Centro-Oeste mineiro",
    "38": "Montes Claros / Norte de Minas",
    "41": "Curitiba", "42": "Ponta Grossa / Guarapuava",
    "43": "Londrina", "44": "Maringa",
    "45": "Cascavel / Foz do Iguacu",
    "46": "Pato Branco / Francisco Beltrao",
    "47": "Joinville / Blumenau / Itajai",
    "48": "Florianopolis / Criciuma",
    "49": "Chapeco / Lages",
    "51": "Porto Alegre", "53": "Pelotas / Rio Grande",
    "54": "Caxias do Sul / Serra gaucha",
    "55": "Santa Maria / Uruguaiana",
    "61": "Brasilia e entorno",
    "62": "Goiania", "64": "Rio Verde / Sul de Goias",
    "65": "Cuiaba", "66": "Rondonopolis / Sinop",
    "67": "Campo Grande",
    "63": "Palmas / Tocantins",
    "68": "Rio Branco / Acre",
    "69": "Porto Velho / Rondonia",
    "71": "Salvador", "73": "Ilheus / Itabuna / Porto Seguro",
    "74": "Juazeiro / Irece", "75": "Feira de Santana / Alagoinhas",
    "77": "Barreiras / Vitoria da Conquista",
    "79": "Aracaju / Sergipe",
    "81": "Recife", "87": "Petrolina / Serra Talhada",
    "82": "Maceio / Alagoas",
    "83": "Joao Pessoa / Campina Grande",
    "84": "Natal / Mossoro",
    "85": "Fortaleza", "88": "Juazeiro do Norte / Sobral",
    "86": "Teresina", "89": "Picos / Floriano",
    "91": "Belem", "93": "Santarem", "94": "Maraba",
    "92": "Manaus", "97": "Tefe / Coari",
    "95": "Boa Vista / Roraima",
    "96": "Macapa / Amapa",
    "98": "Sao Luis", "99": "Imperatriz / Sul do Maranhao",
}

REGIOES = ("Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul")


@dataclass(frozen=True)
class Area:
    ddd: str | None
    uf: str | None
    regiao: str | None
    area: str | None
    internacional: bool = False

    @property
    def desconhecido(self) -> bool:
        return not self.internacional and self.uf is None


def area_de(e164: str) -> Area:
    """Extrai DDD/UF/regiao de um numero E.164."""
    if not e164.startswith("+55"):
        return Area(None, None, None, None, internacional=True)
    resto = e164[3:]
    ddd = resto[:2]
    uf = DDD_UF.get(ddd)
    if uf is None:
        return Area(ddd, None, None, None)
    return Area(ddd, uf, UF_REGIAO.get(uf), DDD_AREA.get(ddd))


def _norm_lista(valor: str | None) -> set[str]:
    if not valor:
        return set()
    return {p.strip().upper() for p in valor.replace(";", ",").split(",") if p.strip()}


def filtrar(numeros, *, ddd: str | None = None, uf: str | None = None,
            regiao: str | None = None, excluir_ddd: str | None = None,
            excluir_uf: str | None = None, incluir_internacional: bool = False,
            incluir_desconhecido: bool = False):
    """Filtra uma lista de NormalizedContact por area.

    Todos os criterios sao opcionais e combinam com E logico. Sem criterio
    nenhum, devolve tudo (exceto o que for barrado pelas flags de inclusao).
    """
    inc_ddd = _norm_lista(ddd)
    inc_uf = _norm_lista(uf)
    inc_reg = {r.title() for r in _norm_lista(regiao)}
    exc_ddd = _norm_lista(excluir_ddd)
    exc_uf = _norm_lista(excluir_uf)

    out = []
    for n in numeros:
        a = area_de(n.e164)
        if a.internacional:
            if incluir_internacional:
                out.append(n)
            continue
        if a.desconhecido:
            if incluir_desconhecido:
                out.append(n)
            continue
        if a.ddd in exc_ddd or (a.uf or "") in exc_uf:
            continue
        if inc_ddd and a.ddd not in inc_ddd:
            continue
        if inc_uf and a.uf not in inc_uf:
            continue
        if inc_reg and (a.regiao or "") not in inc_reg:
            continue
        out.append(n)
    return out


def agrupar(numeros, por: str) -> dict[str, list]:
    """Agrupa por 'ddd', 'uf' ou 'regiao'. Chave 'OUTROS' para o que nao casar."""
    if por not in ("ddd", "uf", "regiao"):
        raise ValueError("por deve ser ddd, uf ou regiao")
    grupos: dict[str, list] = {}
    for n in numeros:
        a = area_de(n.e164)
        if a.internacional:
            chave = "INTL"
        elif a.desconhecido:
            chave = "OUTROS"
        else:
            chave = {"ddd": a.ddd, "uf": a.uf, "regiao": a.regiao}[por] or "OUTROS"
        grupos.setdefault(chave, []).append(n)
    return dict(sorted(grupos.items(), key=lambda kv: (-len(kv[1]), kv[0])))


def distribuicao(numeros) -> list[tuple[str, str, str, int]]:
    """Relatorio: (ddd, uf, area, quantidade), do maior para o menor."""
    cont: dict[str, int] = {}
    for n in numeros:
        a = area_de(n.e164)
        chave = "INTL" if a.internacional else (a.ddd or "??")
        cont[chave] = cont.get(chave, 0) + 1
    linhas = []
    for ddd, qtd in sorted(cont.items(), key=lambda kv: (-kv[1], kv[0])):
        if ddd == "INTL":
            linhas.append(("INTL", "-", "internacional", qtd))
        else:
            linhas.append((ddd, DDD_UF.get(ddd, "??"),
                           DDD_AREA.get(ddd, "DDD desconhecido"), qtd))
    return linhas
