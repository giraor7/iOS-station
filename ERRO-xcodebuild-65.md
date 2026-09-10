# `xcodebuild failed with code 65` — o WebDriverAgent não subiu

Isto NÃO é erro do script: o Appium não conseguiu compilar/lançar o
WebDriverAgent (WDA) no iPhone ao abrir a sessão. Acontece com frequência
depois de várias sessões seguidas, e quase sempre é um destes:

1. um `xcodebuild` ou WDA **antigo ainda rodando** e travando o build;
2. **DerivedData** do WDA corrompida;
3. **assinatura/perfil** (conta Apple grátis expira em 7 dias; o Xcode precisa
   "re-confiar" o perfil no aparelho);
4. WDA instalado no iPhone por uma sessão anterior com outro bundle id.

## Recuperação (na ordem — pare quando funcionar)

```bash
# 1) mata processos antigos que seguram o build
pkill -f xcodebuild; pkill -f WebDriverAgent; pkill -f appium

# 2) limpa a DerivedData do WDA (ele recompila do zero)
rm -rf ~/Library/Developer/Xcode/DerivedData/WebDriverAgent-*

# 3) sobe o Appium de novo (outro terminal, deixe rodando)
appium
```

4. No **Xcode**, abra o WDA (`appium driver run xcuitest open-wda`), selecione o
   iPhone e rode **Product → Test (⌘U)** até aparecer "Testing…" sem erro.
   Se pedir, no iPhone: **Ajustes → Geral → VPN e Gerenciamento de Dispositivos
   → (seu perfil) → Confiar**.
5. Rode o spike de novo.

## Depois do ⌘U: PARE o teste no Xcode antes de rodar o spike

O ⌘U serve para **compilar e instalar** o WDA. Se você deixar o teste rodando
no Xcode (barra "Testing…" ativa), **o Xcode fica dono do WDA no iPhone** e a
sessão do Appium colide com ele — o sintoma é:

```
Unable to start WebDriverAgent session ... socket hang up
```

Assim que o ⌘U terminar de instalar (ou aparecer "Testing…"), clique em
**■ (Stop)** no Xcode e só então rode o spike.

## Se ainda falhar: use o WDA que o Xcode já compilou

O passo 4 acima instala um WDA funcional no iPhone. Diga ao pacote para
reaproveitá-lo em vez de recompilar a cada sessão:

```bash
LL_PREBUILT_WDA=1 python3 spike_ios.py --contacts contacts.example.csv \
  --wda-bundle com.isabella.wda2026 --trust-profile
```

(Vale para `run_ios.py` e `bench_ios.py` também — é só prefixar `LL_PREBUILT_WDA=1`.)

## Para ver a causa exata

O pacote agora liga `showXcodeLog`: o **terminal do `appium`** (não o do script)
mostra o log do xcodebuild. Procure por `error:` — as linhas com
`Signing`, `provisioning profile`, `No profiles for` ou `Code Signing` apontam
para assinatura; `DerivedData` ou `Build input file cannot be found` para o item 2.
Copie essas linhas e envie.

## Prevenção

- Conta **Apple Developer** (paga) evita o vencimento semanal do perfil.
- Não deixe várias sessões abertas ao mesmo tempo no mesmo iPhone.
- Mantenha `appium driver update xcuitest` em dia (WDA velho para o iOS novo é
  a outra causa clássica do código 65).
