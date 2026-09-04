"""Filtra e segmenta um CSV de contatos por DDD / UF / regiao ANTES de criar as
listas. Nao toca no aparelho — so prepara os arquivos.

Exemplos:
  # ver a distribuicao da base por DDD
  python filter_contacts.py contatos.csv --report

  # so RJ e ES, gravando um novo CSV
  python filter_contacts.py contatos.csv --uf RJ,ES -o sudeste-litoral.csv

  # so a regiao Nordeste, ja dividido em lotes de 256
  python filter_contacts.py contatos.csv --regiao Nordeste -o ne.csv --split 256

  # tudo, mas um arquivo por UF (gera contatos.RJ.csv, contatos.SP.csv, ...)
  python filter_contacts.py contatos.csv --split-by uf

  # excluir DDD 11 e numeros internacionais
  python filter_contacts.py contatos.csv --excluir-ddd 11 -o sem-sp-capital.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

import batching
import regions


def _write(rows, path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "phone"])
        for n in rows:
            w.writerow([n.name, n.e164])


def _split_files(rows, base: str, ext: str, size: int) -> int:
    n = 0
    for i in range(0, len(rows), size):
        n += 1
        _write(rows[i:i + size], f"{base}.lote{n:03d}{ext}")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="CSV de entrada (name,phone)")
    ap.add_argument("-o", "--out", default="", help="CSV de saida do resultado filtrado")
    ap.add_argument("--region-default", default="BR", help="regiao padrao p/ numeros sem DDI")

    ap.add_argument("--ddd", help="incluir apenas estes DDDs (ex.: 21,22,24)")
    ap.add_argument("--uf", help="incluir apenas estas UFs (ex.: RJ,ES)")
    ap.add_argument("--regiao", help="incluir apenas estas regioes (ex.: Sudeste,Sul)")
    ap.add_argument("--excluir-ddd", help="remover estes DDDs")
    ap.add_argument("--excluir-uf", help="remover estas UFs")
    ap.add_argument("--incluir-internacional", action="store_true",
                    help="manter numeros de fora do Brasil")
    ap.add_argument("--incluir-desconhecido", action="store_true",
                    help="manter numeros com DDD desconhecido")

    ap.add_argument("--report", action="store_true",
                    help="mostrar a distribuicao por DDD e nao gravar nada")
    ap.add_argument("--split", type=int, default=0,
                    help="gravar tambem em lotes de N (ex.: 256)")
    ap.add_argument("--split-by", choices=["ddd", "uf", "regiao"],
                    help="gerar um CSV por DDD/UF/regiao")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"arquivo nao encontrado: {args.csv}", file=sys.stderr)
        return 2

    contatos = batching.load_csv(args.csv)
    nums = batching.normalize(contatos, args.region_default)
    print(f"{len(contatos)} linha(s) -> {len(nums)} numero(s) validos/unicos")

    # --report: distribuicao da base inteira
    if args.report:
        print("\ndistribuicao por DDD (maior -> menor):")
        print(f"  {'DDD':<5} {'UF':<3} {'qtd':>7}  area")
        for ddd, uf, area, qtd in regions.distribuicao(nums):
            print(f"  {ddd:<5} {uf:<3} {qtd:>7}  {area}")
        por_uf = regions.agrupar(nums, "uf")
        print("\npor UF:", ", ".join(f"{k}={len(v)}" for k, v in por_uf.items()))
        por_reg = regions.agrupar(nums, "regiao")
        print("por regiao:", ", ".join(f"{k}={len(v)}" for k, v in por_reg.items()))
        return 0

    # aplica os filtros
    filtrados = regions.filtrar(
        nums, ddd=args.ddd, uf=args.uf, regiao=args.regiao,
        excluir_ddd=args.excluir_ddd, excluir_uf=args.excluir_uf,
        incluir_internacional=args.incluir_internacional,
        incluir_desconhecido=args.incluir_desconhecido,
    )
    print(f"apos filtro: {len(filtrados)} numero(s)")
    if filtrados:
        n_listas = (len(filtrados) + 255) // 256
        print(f"  daria {n_listas} lista(s) de ate 256")

    # --split-by: um arquivo por grupo
    if args.split_by:
        if args.split:
            print("aviso: --split e ignorado quando se usa --split-by")
        grupos = regions.agrupar(filtrados, args.split_by)
        base, ext = os.path.splitext(args.out or args.csv)
        total = 0
        for chave, rows in grupos.items():
            path = f"{base}.{chave}{ext or '.csv'}"
            _write(rows, path)
            print(f"  {path}: {len(rows)} contatos")
            total += 1
        print(f"{total} arquivo(s) por {args.split_by} gerados")
        return 0

    if not args.out:
        print("(nada gravado — use -o para salvar, --report para ver a base, "
              "ou --split-by para separar)")
        return 0

    _write(filtrados, args.out)
    print(f"CSV gravado: {args.out}")
    if args.split and filtrados:
        base, ext = os.path.splitext(args.out)
        n = _split_files(filtrados, base, ext, args.split)
        print(f"{n} arquivo(s) de lote gerados ({args.split} por lote)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
