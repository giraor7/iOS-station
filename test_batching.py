"""Testes puros das regras de contatos/lotes (rodam sem aparelho)."""
import batching as b


def _mk(n, prefix="+5521985"):
    # gera numeros BR validos e distintos
    return [b.Contact(f"C{i}", f"{prefix}{(200000 + i):06d}") for i in range(n)]


def test_zero():
    assert b.normalize([]) == []
    assert b.batch([]) == []


def test_um():
    nums = b.normalize([b.Contact("A", "21 98525-7371")])
    assert [x.e164 for x in nums] == ["+5521985257371"]


def test_dedupe_preserva_ordem():
    nums = b.normalize([
        b.Contact("A", "+5521985257371"),
        b.Contact("B", "21 98525-7371"),
    ])
    assert len(nums) == 1
    assert nums[0].name == "A"


def test_invalido_descartado():
    assert b.normalize([b.Contact("x", "abc"), b.Contact("y", "12")]) == []


def test_256_um_lote():
    nums = b.normalize(_mk(256))
    lotes = b.batch(nums)
    assert len(lotes) == 1 and len(lotes[0]) == 256


def test_257_dois_lotes():
    lotes = b.batch(b.normalize(_mk(257)))
    assert [len(x) for x in lotes] == [256, 1]


def test_mais_de_mil():
    lotes = b.batch(b.normalize(_mk(1000)))
    assert len(lotes) == 4 and len(lotes[-1]) == 232


def test_label():
    assert b.label_for(1) == "Transmissão 001"
    assert b.label_for(40) == "Transmissão 040"


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        try:
            fn()
            print(f"ok  {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {fn.__name__}: {e}")
    sys.exit(1 if fails else 0)
