"""Mede o tempo por contato no iPhone SEM criar nenhuma lista.

Abre o seletor de contatos da nova transmissao, pesquisa N contatos do CSV e
cronometra. Por padrao NAO toca em ninguem (--with-tap opcional marca e desmarca
para medir o ciclo completo). Nunca pressiona "Criar", nunca envia mensagem.

Uso:
  python3 bench_ios.py --csv contatos.csv --n 20
  python3 bench_ios.py --csv contatos.csv --n 20 --with-tap

Referencia do Android (medido): ~2,5 s/contato -> ~11-15 min por lista de 256.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

import batching
from ios_selectors import BASELINE, profile_for_version
from spike_ios import IosSpike, State, UiChanged, build_driver

log = logging.getLogger("bench_ios")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--wda-bundle", default="")
    ap.add_argument("--server", default="http://127.0.0.1:4723")
    ap.add_argument("--wa-version", default="")
    ap.add_argument("--region", default="BR")
    ap.add_argument("--n", type=int, default=20, help="quantos contatos medir")
    ap.add_argument("--with-tap", action="store_true",
                    help="marca e desmarca cada contato (mede o ciclo completo)")
    ap.add_argument("--trust-profile", action="store_true")
    ap.add_argument("--speed", type=float, default=0.4,
                    help="MESMO ritmo do runner (Turbo=0.4, Seguro=1.0). Sem isto a "
                         "medida nao e comparavel com a operacao real")
    ap.add_argument("--pace", type=float, default=0.1,
                    help="pausa entre contatos, igual a do runner")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    nums = batching.normalize(batching.load_csv(args.csv), args.region)[: args.n]
    if not nums:
        log.error("CSV sem numeros validos")
        return 2
    log.info("medindo %d contatos (sem criar lista)", len(nums))

    driver = build_driver(args.server, args.wda_bundle or None)
    times: list[float] = []
    found = 0
    try:
        profile = profile_for_version(args.wa_version)
        if profile is None:
            if not args.trust_profile:
                log.error("versao '%s' sem perfil validado; rode diag_ios.py --inventory "
                          "e preencha ios_selectors.py antes de medir", args.wa_version)
                return 3
            profile = BASELINE
            log.warning("perfil baseline NAO validado (--trust-profile)")

        spike = IosSpike(driver, profile, speed=args.speed)
        if args.trust_profile:
            spike.verify_selection = False      # igual ao runner
        log.info("medindo com speed=%.2f e pace=%.2fs (o mesmo do runner)",
                 args.speed, args.pace)
        t0 = time.monotonic()
        spike.transition(State.PREPARING)
        spike.open_new_broadcast()
        t_open = time.monotonic() - t0
        log.info("[tempo] abrir WhatsApp + nova transmissao: %.1fs", t_open)

        for i, nc in enumerate(nums, 1):
            t = time.monotonic()
            try:
                cell = spike.find_exact_cell(nc.e164, nc.name or None)
            except UiChanged as e:
                log.warning("[%d] interrompido: %s", i, e)
                break
            if cell is None:
                log.info("[%d] nao encontrado", i)
                continue
            if args.with_tap:
                cell.click()
                spike.settle(0.5)          # a mesma pausa do runner apos o toque
            if args.pace:
                time.sleep(args.pace)
            # O RELOGIO PARA AQUI: o que vem abaixo (desmarcar) so existe no
            # bench, para nao deixar contatos marcados no aparelho. Contar isso
            # dobrava o tempo por contato e inflava qualquer comparacao.
            dt = time.monotonic() - t
            if args.with_tap:
                again = spike.find_exact_cell(nc.e164, nc.name or None)
                if again is not None:
                    again.click()
                    spike.settle(0.5)
            times.append(dt)
            found += 1
            if i % 5 == 0:
                log.info("[%d/%d] media %.2fs/contato", i, len(nums), sum(times) / len(times))

        if not times:
            log.error("nenhum contato medido — confira o CSV e os seletores")
            return 4

        avg = sum(times) / len(times)
        print("\n============== BENCHMARK iOS ==============")
        print(f"contatos medidos: {found}  (modo: {'busca+toque' if args.with_tap else 'somente busca'})")
        print(f"tempo por contato: media {avg:.2f}s  min {min(times):.2f}s  max {max(times):.2f}s")
        print(f"abrir o fluxo: {t_open:.1f}s (uma vez por lista)")
        print("\n--- extrapolacao (lista cheia de 256) ---")
        ordenados = sorted(times)
        mediana = ordenados[len(ordenados) // 2]
        print(f"mediana: {mediana:.2f}s/contato (use esta para comparar rodadas)")
        per_list = t_open + 256 * mediana + 5
        print(f"-> {per_list/60:.1f} min por lista de 256 | "
              f"40 listas (10 mil): {40*per_list/3600:.1f} h/aparelho")
        print("frota em paralelo: o tempo total ~= o de UM aparelho.")
        if not args.with_tap:
            print("obs: modo somente-busca subestima; some ~0,3-0,5s/contato pelo toque.")
        print("NENHUMA lista foi criada e nenhuma mensagem foi enviada.")
        print("==========================================\n")
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    sys.exit(main())
