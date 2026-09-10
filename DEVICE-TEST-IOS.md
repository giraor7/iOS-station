# Roteiro de teste iOS — no seu iPhone primeiro, depois nos outros

Ordem segura de validação. Cada fase protege contra dois riscos: **bloqueio da
conta** e **clicar na tela errada**. Não pule etapas.

---

## Fase 0 — pacote (sem iPhone, 2 minutos)

```bash
cd ios-station
python3 test_local.py     # regras de lote, vCard, redação, travas de segurança
python3 doctor_ios.py     # o que falta instalar no Mac
```
✅ Avance quando os testes passarem e o doctor não acusar FALHA.

---

## Fase 1 — seu próprio iPhone (aparelho de teste)

Esta fase já foi cumprida no iPhone da operação (WhatsApp com abas embaixo,
2026-09). Ela vale para um **aparelho novo** ou uma versão nova do WhatsApp; no
dia a dia, vá direto para `COMO-OPERAR.md`.

Objetivo: descobrir o fluxo real e validar 3 casos, sem risco.

1. **Cadastre 3 contatos de teste** no iPhone:
   - um número válido **com WhatsApp** → caso **exato**;
   - um número que não existe / sem WhatsApp → caso **inexistente**;
   - **dois contatos com o mesmo nome** → caso **ambíguo**.
2. Siga `SETUP-MAC.md` seções 1–5 (Xcode, WDA assinado, iPhone preparado, Appium).
3. **Seção 6 — descoberta**: rode `diag_ios.py --inventory` em cada tela e
   preencha `ios_selectors.py`. Sem isso, nada de clicar.
4. **Seção 7 — dry-run**: os 3 casos devem sair como
   `selected` / `not_found` / `ambiguous`, terminando **sem criar**.
   Ajuste os seletores até passar.
5. **Seção 9 — uma lista de teste** com `--approve-create`.
   Confirme no iPhone: a lista existe e **nada foi enviado**. Apague depois.
6. Preencha a matriz no fim deste arquivo.

⚠️ Se o passo 4 não passar de forma limpa, **pare**. Um seletor errado em escala
seleciona o contato errado 256 vezes.

✅ Só avance para a Fase 2 quando os 3 casos e a criação de 1 lista funcionarem.

---

## Fase 2 — primeiro aparelho de produção

1. Conecte o iPhone; pegue o UDID (`idevice_id -l`) e a versão do WhatsApp.
   - Mesma versão da Fase 1? O perfil já serve.
   - Versão diferente? Refaça a **seção 6** e registre o novo `version_prefixes`.
2. Prepare os contatos desse aparelho (`SETUP-MAC.md` seção 10):
   Contatos.app → Exportar vCard → `vcf_to_csv.py contatos.vcf -o contatos.csv --split 256`.
3. **Planeje** (não toca no aparelho):
   ```bash
   python3 run_ios.py --csv contatos.csv --dry-run
   ```
   Confira a contagem: 10 mil contatos ≈ **40 listas**.
4. **Crie só a primeira** e confira no aparelho:
   ```bash
   python3 run_ios.py --csv contatos.csv \
     --wda-bundle <seu.bundle> --wa-version <versao> --approve-create --max-lists 1
   ```
5. Se estiver certo, libere o resto (`--pace 1.0`, sem `--max-lists`).
   Se cair, rode de novo: **retoma de onde parou**.

---

## Fase 3 — demais iPhones

Repita a Fase 2 por aparelho. Cada iPhone precisa:
- Modo de Desenvolvedor ativado e ter confiado no Mac;
- WDA instalado/confiado (o Xcode faz na primeira vez em cada aparelho);
- seu **próprio CSV** de contatos;
- Bloqueio Automático em **Nunca** durante a operação.

Recomendação: **um aparelho por vez** por Mac. Rodar vários em paralelo no mesmo
Mac aumenta falha de sessão e dificulta perceber um problema.

---

## Tempo esperado

Números da mesma fórmula que a tela mostra (`gui_state.estimativa_minutos`), a
partir de 1,98 s de ida-e-volta ao aparelho por contato, medidos no log do
Appium em 2026-09-04/2026-09-10. Confirme no seu caso com `bench_ios.py`.

| Ritmo | speed / pace | Por lista (256) | 40 listas |
|---|---|---|---|
| Turbo (padrão da estação) | 0,4 / 0,1 | ~13 min | ~8,7 h |
| Rápido | 0,6 / 0,3 | ~15 min | ~10 h |
| Seguro (padrão da linha de comando) | 1,0 / 1,0 | ~22 min | ~14,7 h |

Aparelhos em paralelo (um por Mac/estação) ≈ o tempo de **um** aparelho.

---

## Cuidados anti-bloqueio

- Nunca crie as 40 listas em rajada — use `--pace` e `--pace-lists`.
- Comece sempre por `--max-lists 1`.
- **Pare no primeiro aviso do WhatsApp** e não retome no mesmo dia.
- Lista de transmissão **só entrega para quem tem o seu número salvo** —
  garanta que a base é dessas pessoas, senão o esforço não gera entrega.
- O pacote **nunca envia mensagem**: o envio é sempre manual, depois, por você.

---

## Matriz (preencher a cada aparelho)

| iPhone (modelo) | iOS | WhatsApp | idioma | 3 casos OK? | 1 lista OK? | seletores divergentes |
|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |

## Se algo travar

1. `python3 doctor_ios.py` — diz o que está fora do lugar.
2. Tabela "Problemas comuns" no fim do `SETUP-MAC.md`.
3. Se o script parar com `UI_CHANGED`: a tela mudou. Refaça a descoberta
   (`diag_ios.py --inventory`) nessa tela — **não force**. O progresso está salvo.
4. Se o script (Modo Scroll Livre) sair com código 6, não é falha: a lista foi
   criada parcial com os contatos já confirmados e a próxima rodada continua do
   seguinte. Confira o número de destinatários no iPhone. Código 7: a estação
   parou por uma regra dela e não criou lista nenhuma — nada foi perdido.
