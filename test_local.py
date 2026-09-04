"""Testes que rodam SEM iPhone e SEM Mac — valide o pacote antes de ir ao aparelho.

  python3 test_local.py

Cobrem: regras de contatos/lotes, conversao de vCard, redacao de dados pessoais,
perfil de seletores (versao desconhecida = parada segura) e as travas de
seguranca do fluxo (nunca enviar mensagem).
"""

from __future__ import annotations

import os
import sys
import tempfile

import batching
import diag_ios
import ios_selectors
import regions
import vcf_to_csv

FAILS: list[str] = []


def check(cond: bool, nome: str, detalhe: str = "") -> None:
    if cond:
        print(f"ok   {nome}")
    else:
        FAILS.append(nome)
        print(f"FALHA {nome} {detalhe}")


# ---------------- contatos e lotes ----------------

def _fake(n: int) -> list[batching.Contact]:
    return [batching.Contact(f"C{i}", f"+5521985{(200000 + i):06d}") for i in range(n)]


def test_lotes() -> None:
    check(batching.normalize([]) == [], "zero contatos")
    check(len(batching.normalize(_fake(1))) == 1, "um contato")

    lotes = batching.batch(batching.normalize(_fake(256)))
    check(len(lotes) == 1 and len(lotes[0]) == 256, "exatamente 256 = 1 lote")

    lotes = batching.batch(batching.normalize(_fake(257)))
    check([len(x) for x in lotes] == [256, 1], "257 = 256 + 1")

    lotes = batching.batch(batching.normalize(_fake(1000)))
    check(len(lotes) == 4 and len(lotes[-1]) == 232, "1000 = 4 lotes")

    dup = batching.normalize([
        batching.Contact("A", "+5521985257371"),
        batching.Contact("B", "21 98525-7371"),
    ])
    check(len(dup) == 1 and dup[0].name == "A", "duplicados removidos (1a ocorrencia)")

    check(batching.normalize([batching.Contact("x", "abc")]) == [], "numero invalido descartado")
    check(batching.label_for(1) == "Transmissão 001", "rotulo 001")
    check(batching.label_for(40) == "Transmissão 040", "rotulo 040")

    intl = batching.normalize([batching.Contact("Intl", "+1 415 555 2671")])
    check(intl and intl[0].e164 == "+14155552671", "numero internacional")


# ---------------- vCard ----------------

VCF = """BEGIN:VCARD
VERSION:3.0
FN:Ana Silva
TEL;type=CELL:+55 21 98525-7371
END:VCARD
BEGIN:VCARD
VERSION:3.0
N:Costa;Bruno;;;
TEL;type=CELL:21 99999-0002
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Repetido
TEL:+5521985257371
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Ruim
TEL:123
END:VCARD
"""


def test_vcf() -> None:
    d = tempfile.mkdtemp()
    vcf = os.path.join(d, "c.vcf")
    out = os.path.join(d, "c.csv")
    with open(vcf, "w", encoding="utf-8") as f:
        f.write(VCF)

    pares = vcf_to_csv.parse_vcf(vcf)
    check(len(pares) == 4, "vcf: 4 telefones lidos", f"({len(pares)})")
    check(any(n == "Bruno Costa" for n, _ in pares), "vcf: nome montado a partir de N:")

    rows = []
    vistos: dict[str, tuple[str, str]] = {}
    for name, phone in pares:
        e = vcf_to_csv.to_e164(phone, "BR")
        if e:
            vistos.setdefault(e, (name, e))
    rows = list(vistos.values())
    check(len(rows) == 2, "vcf: dedupe + descarte de invalido", f"({len(rows)})")

    vcf_to_csv.write_csv(rows, out)
    lidos = batching.load_csv(out)
    check(len(lidos) == 2, "vcf: CSV gerado e legivel pelo batching")


# ---------------- privacidade ----------------

def test_redacao() -> None:
    check(diag_ios.redact("Pesquisar") == "Pesquisar", "redacao mantem rotulo de UI")
    check("REDIGIDO" in diag_ios.redact("Ana Silva"), "redacao esconde nome")
    check("REDIGIDO" in diag_ios.redact("+5521985257371"), "redacao esconde numero")

    import spike_ios
    m = spike_ios.mask("+5521985257371")
    check("985257371" not in m and m.endswith("71>"), "mask nao vaza numero completo")


# ---------------- seguranca / perfis ----------------

def test_perfil() -> None:
    check(ios_selectors.profile_for_version("24.1") is None,
          "versao desconhecida => sem perfil (parada segura)")
    check(ios_selectors.profile_for_version("") is None,
          "versao vazia => sem perfil")
    check(ios_selectors.BASELINE.version_prefixes == (),
          "baseline nao casa sozinho (exige validacao)")

    prof = ios_selectors.BASELINE
    for chave in ("search_field", "contact_cell", "create_button", "message_composer"):
        check(chave in prof.selectors, f"perfil tem seletor '{chave}'")

    # A trava anti-envio precisa existir e ser usada.
    fonte = open("spike_ios.py", encoding="utf-8").read()
    check("assert_no_composer" in fonte, "existe trava anti-compositor")
    check(fonte.count("assert_no_composer()") >= 3, "trava chamada em varios pontos")
    for proibido in ("send_message", "sendMessage", "enviar_mensagem"):
        check(proibido not in fonte, f"nao ha funcao de envio ({proibido})")
    check("MIN_RECIPIENTS = 2" in fonte, "minimo de destinatarios definido")
    check("approve_create" in fonte, "criacao exige aprovacao explicita")

    runner = open("run_ios.py", encoding="utf-8").read()
    check("approve-create" in runner, "runner exige --approve-create")
    check("num_hash" in runner and "e164" not in runner.split("def num_hash")[0][-200:],
          "progresso usa hash")


def test_regioes() -> None:
    check(len(regions.UF_REGIAO) == 27, "regioes: 27 UFs")
    # toda UF com DDD tem regiao
    check(all(uf in regions.UF_REGIAO for uf in regions.DDD_UF.values()),
          "regioes: toda UF com DDD tem regiao")
    a = regions.area_de("+5521985257371")
    check(a.uf == "RJ" and a.regiao == "Sudeste", "regioes: classifica RJ/Sudeste")
    d = regions.area_de("+5510912345678")  # DDD 10 nao existe
    check(d.desconhecido, "regioes: DDD inexistente nao e chutado")
    intl = regions.area_de("+14155552671")
    check(intl.internacional, "regioes: numero internacional")

    class N:  # pato: so precisa de .e164 e .name
        def __init__(self, e, nm="x"):
            self.e164 = e; self.name = nm
    nums = [N("+5521985257371"), N("+5511987654321"), N("+5531988887777")]
    rj = regions.filtrar(nums, uf="RJ")
    check(len(rj) == 1 and rj[0].e164 == "+5521985257371", "regioes: filtro por UF")
    sudeste = regions.filtrar(nums, regiao="Sudeste")
    check(len(sudeste) == 3, "regioes: filtro por regiao")
    sem_sp = regions.filtrar(nums, excluir_ddd="11")
    check(len(sem_sp) == 2, "regioes: excluir DDD")


def main() -> int:
    print("=== testes locais (sem iPhone) ===\n")
    test_lotes()
    test_vcf()
    test_redacao()
    test_perfil()
    test_regioes()
    print()
    if FAILS:
        print(f"{len(FAILS)} FALHA(S): {', '.join(FAILS)}")
        return 1
    print("todos os testes locais passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
