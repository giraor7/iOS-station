"""Runner operacional iOS — cria listas de transmissao em lote a partir de um CSV,
via Appium XCUITest no Mac. Espelho do run_android.py (que ja rodou de verdade).

Fluxo: CSV -> E.164 (libphonenumber) -> dedupe -> lotes de ate 256 ->
"Transmissão 001, 002, ..." com ritmo configuravel e RETOMADA.
Listas em sequencia: depois de cada "Criar" a estacao volta para Conversas
antes de abrir a proxima (o progresso da lista e gravado antes da volta).
Sessao em varios dias: quem ja esta numa lista criada (hash no progresso)
fica de fora automaticamente; so os restantes viram listas novas.

Seguranca: nunca envia mensagem, nunca abre conversa, nunca toca no compositor;
para em UI desconhecida; cria listas SOMENTE com --approve-create; o progresso
guarda apenas HASH do numero (nunca o numero em claro).

SO opere de verdade depois que spike_ios.py passar no dry-run dos casos de teste
no iPhone (ver DEVICE-TEST-IOS.md).

Uso:
  python3 run_ios.py --csv contatos.csv --dry-run
  python3 run_ios.py --csv contatos.csv --wa-version <v> \
      --approve-create --max-lists 1
  python3 run_ios.py --csv contatos.csv --exportar     # CSVs de restantes/adicionados
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

import batching
import regions
import sessao
from ios_selectors import BASELINE, profile_for_version
from spike_ios import exigir_appium
from spike_ios import (BROADCAST_LIMIT, MIN_RECIPIENTS, IosSpike, State,
                       UiChanged, UnsafeState, build_driver)

log = logging.getLogger("run_ios")


import signal as _signal


def _encerrar_com_seguranca(*_):
    """SIGTERM (botao 'Parar' da estacao) vira KeyboardInterrupt: os blocos
    `finally` rodam e driver.quit() encerra a sessao do Appium/WDA. Sem isso a
    sessao ficava presa no aparelho e a proxima abertura falhava com
    'socket hang up'."""
    raise KeyboardInterrupt


def pace_sleep(seconds: float, seed: int) -> None:
    """Pausa com pequena variacao (evita cadencia robotica perfeita)."""
    if seconds <= 0:
        return
    jitter = ((seed * 2654435761) % 1000) / 1000.0  # deterministico
    time.sleep(seconds * (0.75 + 0.5 * jitter))


num_hash = sessao.hash_numero   # uma unica definicao (progresso, relatorio, GUI)


def limite_de_lote(valor: int) -> int:
    """Tamanho do lote: nunca acima de 256 (regra do WhatsApp) nem abaixo de 2.
    Valores <= 0 significam "o padrao"."""
    if valor is None or valor <= 0:
        return BROADCAST_LIMIT
    return max(MIN_RECIPIENTS, min(valor, BROADCAST_LIMIT))


class Progress:
    """Historico das listas. Guarda apenas hash do numero + desfecho.
    A retomada e por CONTATO (sessao.resumir): quem ja esta numa lista criada
    fica de fora da proxima rodada, com o mesmo arquivo ou com outro.

    Escrita atomica: grava em .tmp e renomeia, para nao corromper o arquivo se a
    execucao for interrompida no meio.
    """

    def __init__(self, path: str):
        self.path = path
        self.data: dict = {"lists": {}}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, OSError):
                log.warning("progresso ilegivel em %s; comecando do zero", path)
                self.data = {"lists": {}}
        self.data.setdefault("lists", {})

    def mark(self, label: str, results: list[dict], completed: bool,
             csv: str = "") -> None:
        """Nunca sobrescreve um registro anterior: os rotulos recomecam em 001 a
        cada rodada (so os restantes sao divididos), entao um rotulo repetido
        ganha o horario na chave. Fica so o nome do arquivo, nunca o caminho."""
        agora = datetime.now().isoformat(timespec="minutes")
        chave = label if label not in self.data["lists"] else f"{label} @ {agora}"
        self.data["lists"][chave] = {"completed": completed, "results": results,
                                     "quando": agora, "csv": os.path.basename(csv)}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


def main() -> int:
    _signal.signal(_signal.SIGTERM, _encerrar_com_seguranca)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, help="CSV com colunas name,phone")
    ap.add_argument("--wda-bundle", default="")
    ap.add_argument("--server", default="http://127.0.0.1:4723")
    ap.add_argument("--wa-version", default="")
    ap.add_argument("--region", default="BR")
    ap.add_argument("--progress", default="progress.ios.local.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="so planeja os lotes; nao toca no iPhone")
    ap.add_argument("--approve-create", action="store_true",
                    help="cria as listas de fato (sem isto, para antes de criar)")
    ap.add_argument("--max-lists", type=int, default=0,
                    help="limita quantas listas criar nesta execucao (0 = todas)")
    ap.add_argument("--pace", type=float, default=1.0,
                    help="pausa media entre contatos, em segundos (reduz risco de bloqueio)")
    ap.add_argument("--pace-lists", type=float, default=30.0,
                    help="pausa media entre listas, em segundos")
    ap.add_argument("--trust-profile", action="store_true")
    ap.add_argument("--limite-por-lista", type=int, default=BROADCAST_LIMIT,
                    help="SO PARA TESTE: lotes menores (ex.: 5) para validar listas em "
                         "sequencia com um CSV pequeno. Nunca passa de 256 nem fica abaixo de 2")
    ap.add_argument("--exportar", action="store_true",
                    help="grava, ao lado do CSV, <nome>.restantes.csv, <nome>.adicionados.csv "
                         "e <nome>.nao-adicionados.csv desta sessao; nao toca no iPhone")
    ap.add_argument("--repetir-nao-encontrados", action="store_true",
                    help="tentar de novo os contatos que ja sairam como nao encontrado/ambiguo "
                         "(por padrao ficam de fora: ~3 s cada para falhar de novo)")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="velocidade das pausas internas: 1.0=seguro, 0.6=rapido, 0.4=turbo (experimental)")
    # filtros de area (opcionais) — mesmos do Android
    ap.add_argument("--ddd", help="incluir apenas estes DDDs (ex.: 21,22,24)")
    ap.add_argument("--uf", help="incluir apenas estas UFs (ex.: RJ,ES)")
    ap.add_argument("--regiao", help="incluir apenas estas regioes (ex.: Sudeste)")
    ap.add_argument("--excluir-ddd", help="remover estes DDDs")
    ap.add_argument("--excluir-uf", help="remover estas UFs")
    ap.add_argument("--incluir-internacional", action="store_true",
                    help="manter numeros de fora do Brasil (por padrao um filtro os remove)")
    ap.add_argument("--incluir-desconhecido", action="store_true",
                    help="manter numeros com DDD desconhecido")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    contatos = batching.load_csv(args.csv)
    nums = batching.normalize(contatos, args.region)
    if nums and all(n.e164.startswith("+552190000") for n in nums):
        log.error("o CSV contem apenas os numeros de EXEMPLO (+55 21 90000-000x); "
                  "eles nao existem. Use o CSV real de contatos do aparelho.")
        return 2
    filtro_ativo = any([args.ddd, args.uf, args.regiao, args.excluir_ddd, args.excluir_uf])
    if filtro_ativo:
        antes = len(nums)
        # Transparencia: quantos internacionais/desconhecidos serao afetados.
        intl = sum(1 for n in nums if regions.area_de(n.e164).internacional)
        desc = sum(1 for n in nums if regions.area_de(n.e164).desconhecido)
        nums = regions.filtrar(
            nums, ddd=args.ddd, uf=args.uf, regiao=args.regiao,
            excluir_ddd=args.excluir_ddd, excluir_uf=args.excluir_uf,
            incluir_internacional=args.incluir_internacional,
            incluir_desconhecido=args.incluir_desconhecido)
        log.info("filtro de area: %d -> %d contatos", antes, len(nums))
        if intl and not args.incluir_internacional:
            log.info("  (%d internacionais removidos; use --incluir-internacional p/ manter)", intl)
        if desc and not args.incluir_desconhecido:
            log.info("  (%d com DDD desconhecido removidos; use --incluir-desconhecido)", desc)
    limite = limite_de_lote(args.limite_por_lista)
    if limite != BROADCAST_LIMIT:
        log.warning("TESTE: lotes de %d contatos (--limite-por-lista); a operacao real usa %d",
                    limite, BROADCAST_LIMIT)
    # Sessao: quem ja esta numa lista CRIADA (hash no progresso) fica de fora;
    # so os restantes sao divididos. E o que permite parar num dia e seguir
    # no outro — com o mesmo arquivo ou com o CSV de restantes exportado.
    progress = Progress(args.progress)
    ses = sessao.resumir(nums, progress.data,
                         repetir_nao_encontrados=args.repetir_nao_encontrados)
    if ses.adicionados or ses.nao_adicionados:
        log.info("sessao (%s): %s", args.progress, sessao.descrever(ses))
    lotes = batching.batch(ses.restantes, limit=limite)
    log.info("CSV: %d linha(s) -> %d numero(s) validos/unicos -> %d lista(s) de ate %d",
             len(contatos), len(nums), len(lotes), limite)
    if args.exportar:
        for grupo, caminho in sessao.exportar(args.csv, ses).items():
            log.info("exportado (%s): %s", grupo, caminho)
        log.info("exportacao concluida; o iPhone nao foi tocado.")
        return 0
    for i, lote in enumerate(lotes, 1):
        log.info("  %s: %d contatos", batching.label_for(i), len(lote))

    pequenos = [i + 1 for i, l in enumerate(lotes) if len(l) < MIN_RECIPIENTS]
    if pequenos:
        log.warning("lote(s) com menos de %d contatos nao podem virar lista: %s",
                    MIN_RECIPIENTS, pequenos)

    if args.dry_run:
        est = 12 + 256 * (2.5 + args.pace) + 5
        log.info("estimativa: ~%.0f min por lista cheia com pace=%.1fs "
                 "(base medida no Android)", est / 60, args.pace)
        log.info("dry-run: o iPhone nao foi tocado.")
        return 0

    if not exigir_appium(args.server):
        return 2
    driver = build_driver(args.server, args.wda_bundle or None)
    criadas = 0
    try:
        profile = profile_for_version(args.wa_version)
        if profile is None:
            if not args.trust_profile:
                log.error("versao '%s' do WhatsApp sem perfil validado. Rode "
                          "diag_ios.py --inventory, preencha ios_selectors.py e "
                          "registre a versao antes de operar.", args.wa_version)
                return 3
            profile = BASELINE
            log.warning("perfil baseline NAO validado (--trust-profile): "
                        "rode antes o spike_ios.py em dry-run")

        for i, lote in enumerate(lotes, 1):
            label = batching.label_for(i)
            if len(lote) < MIN_RECIPIENTS:
                log.info("%s: pulada (menos de %d contatos)", label, MIN_RECIPIENTS)
                continue
            if args.max_lists and criadas >= args.max_lists:
                log.info("limite --max-lists=%d atingido; parando com seguranca.",
                         args.max_lists)
                break

            log.info("=== %s (%d contatos) ===", label, len(lote))
            spike = IosSpike(driver, profile, speed=args.speed)
            if args.trust_profile:
                # Com perfil nao validado, os seletores de verificacao de selecao
                # (selected_chip / selected_indicator) podem capturar elementos
                # errados e travar o WDA ao varrer 200+ celulas. O match exato
                # unico por E.164 ja e garantia suficiente de corretude.
                spike.verify_selection = False
            spike.transition(State.PREPARING)
            spike.open_new_broadcast()


            for j, nc in enumerate(lote):
                spike.search_and_select(nc.e164, nc.name or None, label=f"c{j}")
                pace_sleep(args.pace, j)

            spike.finish(args.approve_create)
            # So conta como criada depois do toque em "Criar" (nao o estado
            # COMPLETED, que tambem sai quando havia menos de 2 selecionados).
            concluida = bool(getattr(spike, "lista_criada", False))
            resultados = [
                {"hash": num_hash(lote[k].e164), **r}
                for k, r in enumerate(spike.results) if k < len(lote)
            ]
            progress.mark(label, resultados, concluida, csv=args.csv)
            if concluida:
                # Depois de "Criar" o WhatsApp fica DENTRO da conversa da lista:
                # sem voltar para Conversas, a proxima lista nao acha o "+".
                # (So depois de gravar o progresso: se a volta falhar, a lista
                # criada nao e refeita na retomada.)
                spike.voltar_para_conversas()

            sel = sum(1 for r in resultados if r["outcome"] == "selected")
            nf = sum(1 for r in resultados if r["outcome"] == "not_found")
            amb = sum(1 for r in resultados if r["outcome"] == "ambiguous")
            log.info("%s: %d selecionados, %d nao encontrados, %d ambiguos; criada=%s",
                     label, sel, nf, amb, concluida)
            if getattr(spike, "colisoes", 0):
                # Quantas vezes a tela ainda mostrava o contato anterior. E a
                # medicao que diz se a pausa apos digitar esta curta demais.
                log.info("%s: %d vez(es) a lista ainda nao tinha refiltrado "
                         "(se for recorrente, use um ritmo mais lento)",
                         label, spike.colisoes)
            if concluida:
                criadas += 1
            pace_sleep(args.pace_lists, i)

        log.info("fim. listas criadas nesta execucao: %d", criadas)
        return 0
    except UnsafeState as e:
        log.error("PARADA DE SEGURANCA: %s", e)
        return 5
    except UiChanged as e:
        log.error("UI_CHANGED: %s — progresso preservado; rode de novo para retomar.", e)
        return 4
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
