"""Logica pura da interface da Estacao iOS — sem Tk, sem Appium, sem iPhone.

Tudo que a interface precisa DECIDIR mora aqui: validacao de DDD, limite de
listas do Modo Scroll Livre, quando o botao Iniciar pode ser habilitado, o
resumo de um arquivo de contatos e a traducao de codigos de erro para
orientacoes em portugues.

Por que separado: a janela (gui_ios.py) nao pode ser testada sem tela; estas
regras podem — e sao justamente as que, se quebrarem, quebram a operacao.

Este modulo NAO toca no iPhone, no Appium, nos seletores do WhatsApp nem nos
arquivos de progresso. Ele so le arquivos de contatos que o operador escolheu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

# Regras do produto (espelham o backend; nao inventar valores aqui).
LIMITE_LISTA = 256          # limite do WhatsApp por lista de transmissao
MIN_DESTINATARIOS = 2       # o WhatsApp nao cria lista com menos que isso
MAX_LISTAS_RODADA = 36      # teto por rodada no Modo Scroll Livre
MIN_LISTAS_RODADA = 1

# Escada de ensaio do Modo Scroll Livre (auditoria 2026-09-10): 0 = lista
# cheia (nao manda --limite-por-lista; e o padrao de sempre, ninguem que ja
# usava a estacao e afetado). Antes disto so o terminal alcancava o ensaio de
# 5 contatos — quem abria a estacao ia direto para a lista cheia, o caminho
# que nunca tinha rodado num iPhone.
PRESETS_ENSAIO_SCROLL: dict[str, int] = {
    "Ensaio (5 contatos)": 5,
    "Ensaio (30 contatos)": 30,
    f"Lista cheia ({LIMITE_LISTA} contatos)": 0,
}
ENSAIO_SCROLL_PADRAO = f"Lista cheia ({LIMITE_LISTA} contatos)"


# ── DDDs ─────────────────────────────────────────────────────────────────────
# Tabela usada so para rotular a interface. O filtro de verdade e o
# regions.filtrar(), o mesmo que o run_ios.py aplica.

DDDS_BR: dict[str, str] = {
    "11": "SP · Capital",            "12": "SP · Vale do Paraíba",
    "13": "SP · Baixada Santista",   "14": "SP · Bauru",
    "15": "SP · Sorocaba",           "16": "SP · Ribeirão Preto",
    "17": "SP · S. J. Rio Preto",    "18": "SP · Pres. Prudente",
    "19": "SP · Campinas",
    "21": "RJ · Capital e Grande Rio", "22": "RJ · Norte Fluminense",
    "24": "RJ · Sul Fluminense",
    "27": "ES · Vitória",            "28": "ES · Cachoeiro",
    "31": "MG · Belo Horizonte",     "32": "MG · Juiz de Fora",
    "33": "MG · Gov. Valadares",     "34": "MG · Uberlândia",
    "35": "MG · Poços de Caldas",    "37": "MG · Divinópolis",
    "38": "MG · Montes Claros",
    "41": "PR · Curitiba",           "42": "PR · Ponta Grossa",
    "43": "PR · Londrina",           "44": "PR · Maringá",
    "45": "PR · Cascavel",           "46": "PR · Pato Branco",
    "47": "SC · Joinville",          "48": "SC · Florianópolis",
    "49": "SC · Chapecó",
    "51": "RS · Porto Alegre",       "53": "RS · Pelotas",
    "54": "RS · Caxias do Sul",      "55": "RS · Santa Maria",
    "61": "DF · Brasília",
    "62": "GO · Goiânia",            "64": "GO · Rio Verde",
    "63": "TO · Palmas",
    "65": "MT · Cuiabá",             "66": "MT · Rondonópolis",
    "67": "MS · Campo Grande",
    "68": "AC · Rio Branco",         "69": "RO · Porto Velho",
    "71": "BA · Salvador",           "73": "BA · Ilhéus",
    "74": "BA · Juazeiro",           "75": "BA · Feira de Santana",
    "77": "BA · Vitória da Conquista",
    "79": "SE · Aracaju",
    "81": "PE · Recife",             "87": "PE · Caruaru",
    "82": "AL · Maceió",
    "83": "PB · João Pessoa",
    "84": "RN · Natal",
    "85": "CE · Fortaleza",          "88": "CE · Juazeiro do Norte",
    "86": "PI · Teresina",           "89": "PI · Picos",
    "91": "PA · Belém",              "93": "PA · Santarém",
    "94": "PA · Marabá",
    "92": "AM · Manaus",             "97": "AM · Tefé",
    "95": "RR · Boa Vista",
    "96": "AP · Macapá",
    "98": "MA · São Luís",           "99": "MA · Imperatriz",
}

DDDS_DESTAQUE = ("21", "22", "24")  # os tres do dia a dia da operacao


def ddd_valido(codigo: str) -> bool:
    return codigo.strip() in DDDS_BR


def rotulo_ddd(codigo: str) -> str:
    codigo = codigo.strip()
    desc = DDDS_BR.get(codigo)
    return f"{codigo} — {desc}" if desc else codigo


def parse_ddds(texto: str) -> tuple[list[str], list[str]]:
    """Le "21, 22;24" e devolve (validos_em_ordem_sem_repetir, invalidos).

    Aceita virgula, ponto-e-virgula ou espaco como separador — o operador
    digita do jeito que lembrar.
    """
    validos: list[str] = []
    invalidos: list[str] = []
    for bruto in re.split(r"[,;\s]+", (texto or "").strip()):
        if not bruto:
            continue
        item = bruto.strip()
        if ddd_valido(item):
            if item not in validos:
                validos.append(item)
        elif item not in invalidos:
            invalidos.append(item)
    return validos, invalidos


def formatar_ddds(codigos: list[str]) -> str:
    """Monta o valor do argumento --ddd: "21,22,24" (vazio = todos)."""
    return ",".join(codigos)


def descrever_ddds(codigos: list[str]) -> str:
    if not codigos:
        return "todos os DDDs"
    if len(codigos) == 1:
        return f"DDD {codigos[0]}"
    return "DDDs " + ", ".join(codigos)


# ── Listas por rodada (Modo Scroll Livre) ────────────────────────────────────

def clamp_listas(valor: int) -> int:
    return max(MIN_LISTAS_RODADA, min(int(valor), MAX_LISTAS_RODADA))


def validar_listas(texto: str) -> tuple[int | None, str]:
    """Devolve (valor, erro). Valor None quando o texto nao serve."""
    bruto = (texto or "").strip()
    if not bruto:
        return None, f"Informe de {MIN_LISTAS_RODADA} a {MAX_LISTAS_RODADA} listas."
    if not bruto.isdigit():
        return None, "Use apenas números."
    valor = int(bruto)
    if valor < MIN_LISTAS_RODADA or valor > MAX_LISTAS_RODADA:
        return None, f"Entre {MIN_LISTAS_RODADA} e {MAX_LISTAS_RODADA} listas por rodada."
    return valor, ""


# ── Fonte dos contatos e tipo de execucao ────────────────────────────────────

class Fonte(str, Enum):
    ARQUIVO = "arquivo"     # CSV ou VCF
    SCROLL = "scroll"       # Modo Scroll Livre


class Execucao(str, Enum):
    SIMULACAO = "simulacao"   # sem --approve-create: seleciona e cancela
    REAL = "real"             # com --approve-create: cria as listas


def aprova_criacao(execucao: Execucao) -> bool:
    """Unica funcao que decide passar --approve-create. Padrao e NAO passar."""
    return execucao == Execucao.REAL


# ── Resumo de um arquivo de contatos ─────────────────────────────────────────

@dataclass
class ResumoArquivo:
    caminho: str = ""
    tipo: str = ""              # "CSV" ou "VCF"
    encontrados: int = 0        # linhas/entradas lidas do arquivo
    validos: int = 0            # numeros validos e unicos
    invalidos: int = 0          # nao viraram numero valido
    duplicados: int = 0         # numero repetido, contado uma vez so
    erro: str = ""
    contatos: list = field(default_factory=list, repr=False)  # NormalizedContact

    @property
    def ok(self) -> bool:
        return not self.erro and self.validos > 0

    @property
    def nome_arquivo(self) -> str:
        return self.caminho.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def analisar_arquivo(caminho: str) -> ResumoArquivo:
    """Le um CSV ou VCF e conta encontrados, validos, invalidos e duplicados.

    Usa as MESMAS regras do runner (batching.to_e164, dedupe por numero), so
    que contando separadamente o que foi descartado — o operador quer saber
    por que 10.000 contatos viraram 9.870.
    """
    resumo = ResumoArquivo(caminho=caminho)
    ehvcf = caminho.lower().endswith(".vcf")
    resumo.tipo = "VCF" if ehvcf else "CSV"
    try:
        import batching
    except ImportError as exc:
        # Dependencia ausente no .venv (acontece em .venv recem-criado): dizer o
        # que rodar vale mais que o nome do modulo.
        resumo.erro = (f"Falta a biblioteca '{exc.name}' no ambiente Python. Na pasta "
                       f"ios-station, rode: .venv/bin/pip install -r requirements.txt")
        return resumo
    try:
        if ehvcf:
            import vcf_to_csv
            pares = vcf_to_csv.parse_vcf(caminho)
            brutos = [batching.Contact(name=nome, raw_phone=fone) for nome, fone in pares]
        else:
            brutos = batching.load_csv(caminho)
    except Exception as exc:                     # arquivo ilegivel / sem coluna
        resumo.erro = str(exc)
        return resumo

    resumo.encontrados = len(brutos)
    vistos: dict[str, object] = {}
    for c in brutos:
        e164 = batching.to_e164(c.raw_phone)
        if e164 is None:
            resumo.invalidos += 1
            continue
        if e164 in vistos:
            resumo.duplicados += 1
            continue
        vistos[e164] = batching.NormalizedContact(e164, c.name)
    resumo.contatos = list(vistos.values())
    resumo.validos = len(resumo.contatos)
    if resumo.encontrados and not resumo.validos:
        resumo.erro = "Nenhum número válido no arquivo."
    return resumo


def aplicar_filtro_ddd(contatos: list, ddds: list[str]) -> list:
    """Filtro identico ao do run_ios.py (regions.filtrar), para o resumo da tela
    bater exatamente com o que a execucao vai fazer."""
    if not ddds:
        return list(contatos)
    import regions
    return regions.filtrar(contatos, ddd=formatar_ddds(ddds))


def contar_listas(quantidade: int) -> int:
    """Quantas listas de ate 256 saem de N contatos."""
    if quantidade <= 0:
        return 0
    return (quantidade + LIMITE_LISTA - 1) // LIMITE_LISTA


def lotes_pequenos(quantidade: int) -> int:
    """Quantos contatos ficariam num ultimo lote pequeno demais para virar lista."""
    resto = quantidade % LIMITE_LISTA
    return resto if 0 < resto < MIN_DESTINATARIOS else 0


PROGRESSO_PADRAO = "progress.ios.local.json"   # o mesmo que o run_ios.py usa


def descontar_sessao(contatos: list, progresso_path: str):
    """Separa os contatos (ja filtrados) em adicionados / restantes / nao
    adicionados, lendo o progresso do run_ios.py. Nunca escreve. E o que faz a
    tela mostrar 'ja em listas' e planejar so os restantes — a mesma conta que
    o runner faz (sessao.resumir)."""
    import sessao
    return sessao.resumir(contatos, sessao.carregar_progresso(progresso_path))


# ── Prontidao da estacao ─────────────────────────────────────────────────────

class Estado(str, Enum):
    PRONTO = "pronto"
    ATENCAO = "atencao"
    FALTA = "falta"
    VERIFICANDO = "verificando"


@dataclass(frozen=True)
class ItemProntidao:
    chave: str
    titulo: str
    estado: Estado
    detalhe: str
    orientacao: str = ""

    @property
    def ok(self) -> bool:
        return self.estado in (Estado.PRONTO, Estado.ATENCAO)


@dataclass
class Ambiente:
    """O que o monitor de ambiente conseguiu observar."""
    verificado: bool = False
    appium_ok: bool = False
    appium_versao: str = ""
    appium_bin_ok: bool = True     # o executavel `appium` existe no PATH?
    iphone_count: int = 0
    idevice_ok: bool = True        # a ferramenta `idevice_id` existe no PATH?
    wda_bundle: str = ""


def itens_prontidao(amb: Ambiente, fonte: Fonte, resumo: ResumoArquivo | None,
                    listas_previstas: int, ja_adicionados: int = 0) -> list[ItemProntidao]:
    """Checklist da Etapa 1. Nunca esconde o motivo: cada item que falta diz o
    que fazer para resolver."""
    itens: list[ItemProntidao] = []

    if not amb.verificado:
        itens.append(ItemProntidao("iphone", "iPhone conectado", Estado.VERIFICANDO,
                                   "Procurando o aparelho…"))
    elif amb.iphone_count == 1:
        itens.append(ItemProntidao("iphone", "iPhone conectado", Estado.PRONTO,
                                   "Um iPhone conectado por cabo."))
    elif not amb.idevice_ok:
        itens.append(ItemProntidao(
            "iphone", "iPhone conectado", Estado.FALTA,
            "Não consigo enxergar o cabo: a ferramenta idevice_id não foi encontrada.",
            "Instale com 'brew install libimobiledevice'. Se já está instalada, abra "
            "a estação pelo Terminal (o Finder não enxerga as pastas do Homebrew)."))
    elif amb.iphone_count == 0:
        itens.append(ItemProntidao(
            "iphone", "iPhone conectado", Estado.FALTA,
            "Nenhum iPhone detectado.",
            "Conecte um iPhone desbloqueado ao Mac e toque em Confiar."))
    else:
        itens.append(ItemProntidao(
            "iphone", "iPhone conectado", Estado.FALTA,
            f"{amb.iphone_count} iPhones conectados.",
            "Deixe apenas um aparelho ligado: a estação opera um por vez."))

    if not amb.verificado:
        itens.append(ItemProntidao("appium", "Appium funcionando", Estado.VERIFICANDO,
                                   "Consultando o servidor…"))
    elif amb.appium_ok:
        versao = f" (versão {amb.appium_versao})" if amb.appium_versao else ""
        itens.append(ItemProntidao("appium", "Appium funcionando", Estado.PRONTO,
                                   f"Servidor respondendo{versao}."))
    elif not amb.appium_bin_ok:
        itens.append(ItemProntidao(
            "appium", "Appium funcionando", Estado.FALTA,
            "O servidor não respondeu e o programa 'appium' não foi encontrado.",
            "Instale com 'npm install -g appium'. Se já está instalado, abra a "
            "estação pelo Terminal ou rode 'appium' num terminal à parte."))
    else:
        itens.append(ItemProntidao(
            "appium", "Appium funcionando", Estado.FALTA,
            "O servidor não respondeu.",
            "Ligue 'Iniciar Appium automaticamente' em Configurações, ou rode "
            "'appium' num terminal."))

    if amb.wda_bundle:
        itens.append(ItemProntidao("wda", "WebDriverAgent", Estado.PRONTO,
                                   "Identificador salvo nas configurações."))
    else:
        itens.append(ItemProntidao(
            "wda", "WebDriverAgent", Estado.ATENCAO,
            "Sem identificador salvo.",
            "Funciona assim mesmo: o Appium instala na primeira execução. "
            "Em Diagnóstico você pode instalar ou reparar antes."))

    if fonte == Fonte.SCROLL:
        itens.append(ItemProntidao(
            "fonte", "Fonte de contatos", Estado.PRONTO,
            f"Modo Scroll Livre: {listas_previstas} "
            f"{'lista' if listas_previstas == 1 else 'listas'} nesta rodada."))
    elif resumo is None or not resumo.caminho:
        itens.append(ItemProntidao(
            "fonte", "Fonte de contatos", Estado.FALTA,
            "Nenhum arquivo escolhido.",
            "Escolha um arquivo CSV ou VCF exportado da agenda do iPhone."))
    elif resumo.erro:
        itens.append(ItemProntidao(
            "fonte", "Fonte de contatos", Estado.FALTA,
            f"Não consegui ler {resumo.nome_arquivo}.", resumo.erro))
    elif listas_previstas == 0 and ja_adicionados:
        itens.append(ItemProntidao(
            "fonte", "Fonte de contatos", Estado.FALTA,
            f"Todos os {ja_adicionados} contatos deste arquivo (no filtro atual) já "
            "estão em listas criadas.",
            "Escolha outro arquivo ou outros DDDs. Para recomeçar do zero, apague "
            f"{PROGRESSO_PADRAO} na pasta da estação."))
    elif listas_previstas == 0:
        itens.append(ItemProntidao(
            "fonte", "Fonte de contatos", Estado.FALTA,
            "Nenhum contato depois do filtro.",
            "Escolha outros DDDs ou use todos."))
    else:
        itens.append(ItemProntidao(
            "fonte", "Fonte de contatos", Estado.PRONTO,
            f"{resumo.nome_arquivo}: {listas_previstas} "
            f"{'lista' if listas_previstas == 1 else 'listas'} planejadas."))
    return itens


def pode_iniciar(itens: list[ItemProntidao], executando: bool) -> tuple[bool, str]:
    """Regra unica do botao Iniciar. Devolve (habilitado, motivo_quando_nao)."""
    if executando:
        return False, "Uma operação já está em andamento."
    faltando = [i for i in itens if not i.ok]
    if not faltando:
        return True, ""
    if len(faltando) == 1:
        return False, f"Falta: {faltando[0].titulo.lower()}."
    return False, "Falta: " + ", ".join(i.titulo.lower() for i in faltando) + "."


# ── Confirmacao da operacao real ─────────────────────────────────────────────

def resumo_confirmacao(fonte: Fonte, execucao: Execucao, resumo: ResumoArquivo | None,
                       ddds: list[str], contatos_filtrados: int,
                       listas: int, ja_adicionados: int = 0) -> list[tuple[str, str]]:
    """Linhas (rotulo, valor) da caixa de confirmacao. So dados reais: o que a
    estacao nao sabe aparece como '—', nunca como numero inventado."""
    linhas: list[tuple[str, str]] = []
    linhas.append(("Tipo de execução",
                   "Criar listas de verdade" if execucao == Execucao.REAL
                   else "Simulação segura"))
    if fonte == Fonte.ARQUIVO:
        linhas.append(("Fonte", f"Arquivo {resumo.tipo} · {resumo.nome_arquivo}"
                       if resumo and resumo.caminho else "Arquivo"))
        linhas.append(("Filtro de DDD", descrever_ddds(ddds)))
        linhas.append(("Contatos", f"{contatos_filtrados:,}".replace(",", ".")
                       + (" restantes" if ja_adicionados else "")))
        if ja_adicionados:
            linhas.append(("Já em listas anteriores",
                           f"{ja_adicionados:,}".replace(",", ".") + " (ficam de fora)"))
    elif ddds:
        linhas.append(("Fonte", "Modo Scroll Livre, filtrado pela agenda"
                       + (f" ({resumo.nome_arquivo})" if resumo and resumo.caminho else "")))
        linhas.append(("Filtro de DDD", descrever_ddds(ddds) + ", decidido pelo nome"))
        linhas.append(("Contatos", f"{contatos_filtrados:,}".replace(",", ".")
                       + " da agenda nos DDDs; entram na ordem do WhatsApp"))
    else:
        linhas.append(("Fonte", "Modo Scroll Livre (sem arquivo)"))
        linhas.append(("Filtro de DDD", "não se aplica"))
        linhas.append(("Contatos", "definidos pela ordem da agenda no WhatsApp"))
    linhas.append(("Listas", f"{listas} de até {LIMITE_LISTA} contatos"))
    return linhas


# ── Leitura do que o runner imprime ──────────────────────────────────────────

_RE_TRANSMISSAO = re.compile(r"===\s+Transmiss[aã]o\s+(\d+)", re.IGNORECASE)
_RE_LISTA_DE = re.compile(r"^\s*Lista\s+(\d+)\s+de\s+(\d+)\s*$", re.IGNORECASE)


def extrair_progresso(linha: str) -> tuple[int, int | None] | None:
    """Le as duas linhas de progresso que os runners imprimem.

    run_ios.py     -> "=== Transmissão 003 (256 contatos) ==="  (total ja conhecido)
    run_ios_scroll -> "Lista 2 de 5"                            (total vem na linha)
    """
    m = _RE_LISTA_DE.match(linha)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _RE_TRANSMISSAO.search(linha)
    if m:
        return int(m.group(1)), None
    return None


def classificar_linha(linha: str) -> str:
    """Tag de cor do log tecnico. So classifica; nunca altera o texto."""
    up = linha.upper().lstrip()
    if up.startswith(("ERROR", "ERRO", "[FALHA]", "CRITICAL")):
        return "ERRO"
    if up.startswith(("WARNING", "AVISO", "[AVISO]")):
        return "AVISO"
    if up.startswith("==="):
        return "TITULO"
    if up.startswith("[OK") or "SELECIONADO" in up or "CRIADA" in up:
        return "OK"
    return "INFO"


def etapa_humana(linha: str) -> str:
    """Traduz a linha tecnica corrente para uma frase que o operador entende.
    Devolve '' quando a linha nao descreve uma etapa reconhecida."""
    baixa = linha.lower()
    tabela = (
        ("estado: idle", "Preparando a sessão…"),
        ("preparing", "Preparando a sessão…"),
        ("opening_whatsapp", "Abrindo o WhatsApp no iPhone…"),
        ("opening_new_broadcast", "Abrindo a tela de nova transmissão…"),
        ("searching", "Procurando o contato…"),
        ("matching", "Conferindo o contato encontrado…"),
        ("selecting", "Marcando contatos…"),
        ("verifying", "Conferindo a seleção…"),
        ("waiting_confirmation", "Aguardando confirmação…"),
        ("saving", "Criando a lista…"),
        ("completed", "Etapa concluída."),
        ("retomando", "Retomando de onde parou…"),
        ("ponto de retomada", "Ponto de retomada encontrado."),
        ("fim da lista de contatos", "Fim da agenda."),
        ("lista criada", "Lista criada."),
        ("filtro de area", "Aplicando o filtro de DDD…"),
        # Auditoria 2026-09-10: desfechos que NAO sao "fim da agenda" — sem
        # isto o operador leria esses avisos como se a agenda tivesse acabado,
        # quando na verdade a estação parou por segurança no meio dela.
        ("leitura vazia lenta", "A tela demorou para responder; conferindo com "
                                "segurança antes de continuar…"),
        ("teto de telas atingido", "Chegou ao limite de telas desta lista sem "
                                   "esgotar a agenda; salvando o que foi confirmado…"),
        ("rajada interrompida", "O toque em lote foi interrompido; conferindo "
                                "o que foi confirmado…"),
        ("criada parcial", "Lista criada com os contatos confirmados até aqui."),
    )
    for chave, frase in tabela:
        if chave in baixa:
            return frase
    return ""


# ── Fim da execucao ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Desfecho:
    titulo: str
    orientacao: str
    tom: str            # "ok" | "atencao" | "erro"


# Codigos de saida dos dois runners (run_ios.py e run_ios_scroll.py).
_DESFECHOS: dict[int, Desfecho] = {
    0: Desfecho("Concluído", "A operação terminou sem erros.", "ok"),
    2: Desfecho("Arquivo ou opção inválida",
                "Confira o arquivo de contatos e a quantidade de listas.", "erro"),
    3: Desfecho("Versão do WhatsApp não validada",
                "A estação parou por segurança em vez de tocar numa tela que não "
                "reconhece. Fale com o suporte técnico antes de continuar.", "erro"),
    4: Desfecho("A tela do WhatsApp mudou",
                "A estação parou sem tocar em nada e salvou o que viu em "
                "inventory-erro.json. Feche o seletor no iPhone e tente de novo; "
                "se repetir, envie esse arquivo ao suporte.", "erro"),
    5: Desfecho("Parada de segurança",
                "Algo fora do previsto apareceu na tela (uma conversa aberta, por "
                "exemplo) e a estação parou por segurança. Volte o WhatsApp para "
                "Conversas e tente de novo.", "erro"),
    6: Desfecho("Lista parcial criada",
                "A seleção foi interrompida no meio (rede lenta ou toque perdido), "
                "mas a lista foi criada com os contatos já confirmados. A próxima "
                "rodada continua automaticamente do contato seguinte.", "atencao"),
}

_INTERROMPIDO = Desfecho(
    "Interrompido pelo operador",
    "Nada foi criado depois do ponto em que você parou. As listas já criadas "
    "continuam salvas e a próxima rodada retoma daí.", "atencao")


# Erros que o Appium/WDA imprimem e que a operadora nao tem como interpretar.
# (padroes em minusculas, procurados no log inteiro) -> explicacao + o que fazer.
_ERROS_CONHECIDOS: list[tuple[tuple[str, ...], Desfecho]] = [
    (("socket hang up", "unable to start webdriveragent session",
      "could not proxy command to the remote server"),
     Desfecho("O WebDriverAgent não respondeu no iPhone",
              "Faça nesta ordem e tente de novo: 1) iPhone desbloqueado, com Bloqueio "
              "Automático em Nunca e confiando neste Mac. 2) Se o Xcode estiver aberto "
              "rodando o WebDriverAgent (⌘U), feche-o. 3) Feche e abra a estação (isso "
              "reinicia o Appium). 4) Em Diagnóstico, use 'Instalar ou reparar WDA'. "
              "5) Se repetir, no Terminal: appium driver update xcuitest.", "erro")),
    (("xcodebuild failed with code 65",),
     Desfecho("O Xcode não conseguiu compilar o WebDriverAgent",
              "Abra o Xcode uma vez e aceite a licença; confira a conta de desenvolvedor "
              "do WebDriverAgent. O passo a passo completo está em ERRO-xcodebuild-65.md.",
              "erro")),
    (("code=41", "not authorized"),
     Desfecho("O iPhone não autorizou a automação",
              "Desbloqueie o aparelho e toque em Confiar. Depois: Ajustes › Geral › VPN "
              "e Gestão do Dispositivo › confie no perfil do desenvolvedor.", "erro")),
    (("could not connect to server", "connection refused", "urlopen error",
      "max retries exceeded"),
     Desfecho("O Appium não está rodando",
              "Ligue 'Iniciar Appium automaticamente' em Configurações e reabra a "
              "estação, ou rode 'appium' num terminal à parte.", "erro")),
    (("no module named",),
     Desfecho("Falta uma biblioteca no ambiente Python",
              "Na pasta ios-station, rode: .venv/bin/pip install -r requirements.txt",
              "erro")),
]


def diagnosticar_log(texto: str) -> Desfecho | None:
    """Reconhece, no log tecnico, um erro conhecido e devolve a explicacao
    humana. None quando nao reconhece (o desfecho generico continua valendo)."""
    baixa = (texto or "").lower()
    for padroes, desfecho in _ERROS_CONHECIDOS:
        if any(p in baixa for p in padroes):
            return desfecho
    return None


def desfecho_para(codigo: int, interrompido: bool = False) -> Desfecho:
    """Traduz o codigo de saida do runner.

    `interrompido` vem da propria interface: quando o operador aperta Parar,
    ela SABE que parou, e nao precisa adivinhar pelo codigo — que varia de
    sistema para sistema (macOS devolve -15; outros devolvem 1).
    """
    if interrompido or codigo in (-2, -15, 130, 143):
        return _INTERROMPIDO
    conhecido = _DESFECHOS.get(codigo)
    if conhecido:
        return conhecido
    return Desfecho(
        "Encerrado com erro",
        "Abra 'Ver detalhes técnicos' e envie as últimas linhas ao suporte.",
        "erro")


# ── Ritmo da automacao ───────────────────────────────────────────────────────
# Presets equivalentes aos que a versao anterior aplicava. O Turbo continua
# sendo o padrao (era o que a estacao ja usava na pratica); a diferenca e que
# agora ele fica visivel e o operador pode mudar.

PRESETS_RITMO: dict[str, tuple[float, float, float]] = {
    # nome: (speed, pace entre contatos, pace entre listas)
    "Seguro": (1.0, 1.0, 30.0),
    "Rápido": (0.6, 0.3, 15.0),
    "Turbo": (0.4, 0.1, 8.0),
    # Pausas no piso que o runner aceita (0,375 s apos digitar). Use so depois
    # de medir no aparelho: se aparecerem "nao encontrado" que o Turbo achava,
    # a lista foi lida antes de o filtro aplicar — volte ao Turbo.
    "Máximo": (0.25, 0.05, 5.0),
}
RITMO_PADRAO = "Turbo"


def preset_de(speed: float, pace: float, pace_lists: float) -> str:
    """Nome do preset correspondente, ou 'Personalizado'."""
    for nome, (sp, pc, pl) in PRESETS_RITMO.items():
        if abs(sp - speed) < 0.01 and abs(pc - pace) < 0.01 and abs(pl - pace_lists) < 0.5:
            return nome
    return "Personalizado"


# Ida-e-volta ao aparelho por contato selecionado, medido no log do Appium
# (2026-09-04/2026-09-10, iPhone da operacao): limpar 0,42 + digitar 0,68 +
# achar as celulas 0,25 + ler o rotulo 0,05 + tocar 0,45, mais ~0,13 s de
# overhead de rede. Nao depende do ritmo escolhido — so as pausas dependem.
SEGUNDOS_DE_CHAMADAS = 1.98
SEGUNDOS_POR_LISTA = 17.0      # abrir a nova transmissao e criar, uma vez por lista


def estimativa_minutos(pace: float, speed: float) -> int:
    """Minutos aproximados para uma lista cheia (256 contatos), no modo arquivo.

    Conta as chamadas MEDIDAS mais as pausas calculadas do codigo (settle()
    escala por speed e tem piso). Continua sendo estimativa: o aparelho, o cabo
    e o WhatsApp mandam. A formula anterior so somava pausas e dava ~8 min
    quando a medicao dizia 16.
    """
    apos_digitar = max(1.5 * speed, 0.375)      # settle() em find_exact_cell
    apos_tocar = max(0.5 * speed, 0.25)         # settle(0.5) apos o clique
    por_contato = SEGUNDOS_DE_CHAMADAS + apos_digitar + apos_tocar + pace
    return max(1, round((SEGUNDOS_POR_LISTA + LIMITE_LISTA * por_contato) / 60))
