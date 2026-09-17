---
name: cvoice
description: Voz do Claude Code na máquina local. Três usos — (1) ativar a leitura em voz alta de todas as respostas desta janela de contexto; (2) ler um arquivo do disco; (3) ler um artefato do Claude pela URL. Use quando pedirem "ativa a voz", "lê suas respostas", "lê esse arquivo pra mim", "me lê o ADR X", "lê esse artefato", "para de ler", "desliga a voz", ou indicar que vai ouvir em vez de ler.
---

# Claudinho's Voice

Leitor por voz 100% local (Pocket TTS, voz `rafael`). Você **não** precisa subir
nem gerenciar nada: o comando levanta o serviço sozinho na primeira chamada.

Comando (sempre pelo caminho absoluto, ele não está no PATH):

```
CV="cvoice"   # o instalador põe no PATH; fora dele, use o caminho do .venv
```

Nos exemplos abaixo, `$CV` é esse caminho. Em Bash use aspas: `"$CV"`.

## Cenário 1 — ler todas as minhas respostas nesta janela de contexto

Pedido típico: "ativa a voz", "passa a ler suas respostas", "modo voz".

```bash
"$CV" auto on
```

Só isso. O comando descobre sozinho qual é esta sessão e liga a leitura **só
aqui**: outras janelas do Claude Code não são afetadas. A partir da próxima
resposta, tudo que eu escrever como resposta final é lido em voz alta.

Com o modo voz ligado, um hook injeta em cada prompt o **contrato de fala**: as
respostas passam a ser conversa falada — prosa curta, sem títulos, listas,
tabelas ou negrito, com comandos dentro de bloco de código (que a leitura pula).
Isso é automático; não precisa ser pedido nem lembrado.

Para desligar: `"$CV" auto off`. Para calar no meio de uma leitura: `"$CV" parar`.

Depois de ligar, responda só: "Voz ligada nesta sessão." Não explique como funciona.

## Cenário 2 — ler um arquivo do disco

Pedido típico: "lê o ADR 30 pra mim", "me lê esse arquivo", "lê docs/x.md".

```bash
"$CV" ler "C:\caminho\completo\do\arquivo.md"
```

Resolva o caminho completo antes (Glob se precisar). Aceita `.md`, `.txt`,
`.html`. **Não** reescreva nem resuma o arquivo: o preparador cuida de markdown,
tabelas, números, datas, siglas e identificadores. Responda só com uma linha:
"Lendo <nome> (~N min)." — o comando já imprime a estimativa.

Se o alvo for **código-fonte**, não mande o código. Escreva uma narração curta
do que o arquivo faz e mande a narração por pipe:

```bash
printf '%s' "NARRAÇÃO" | "$CV" ler --titulo "nome do arquivo"
```

## Cenário 3 — ler um artefato do Claude pela URL

Pedido típico: "lê esse artefato pra mim: https://claude.ai/…".

1. Leia o artefato com a ferramenta **Artifact**, `action: "read"`, passando a URL.
   Vem o HTML da página.
2. Grave esse HTML, com a ferramenta **Write**, em
   `~/.claudinho-voice/tmp/artefato.html` (o comando `cvoice tmp` imprime o caminho)
   (a pasta existe; se não existir, `"$CV" tmp` a cria e imprime o caminho).
3. Mande ler:

```bash
"$CV" ler "$("$CV" tmp)/artefato.html" --titulo "nome do artefato"
```

O conversor tira scripts e estilos e transforma títulos, listas, tabelas e blocos
de código em algo falável. Responda só com a linha de confirmação.

## Continuidade — "repete"

Pedido típico: "repete", "repete a última parte", "o que você disse mesmo?",
"não ouvi o final".

```bash
"$CV" repetir            # a última leitura inteira
"$CV" repetir fim -n 3   # só as 3 últimas frases
```

Se ele pedir "o que você já leu?", use `"$CV" historico`.

Quando o pedido for claramente sobre o **conteúdo** ("me explica de novo aquilo
do KYC"), não use `repetir` — responda você, com suas palavras. `repetir` é para
ouvir de novo o mesmo áudio.

## Frases de espera

Com o modo voz ligado, a pessoa ouve uma frase curta ("deixa eu ver aqui", "ainda
estou nisso") quando você passa mais de 3,5 segundos usando ferramentas sem
falar. É automático, feito por hook, com áudio pré-gerado — não chame nada nem
escreva essas frases na resposta.

Se ele quiser trocá-las, elas estão em `claudinho_voice/preenchimentos.py` e
precisam ser regeradas depois: `"$CV" estado` sobe o serviço, e daí
`POST /gerar-preenchimentos?forcar=true`.

## Interrupção

Com o modo voz ligado, **qualquer mensagem enviada já corta a fala em
curso** (barge-in por teclado, feito pelo hook de prompt). Não é preciso chamar
`parar` antes de responder; só chame quando ele pedir explicitamente para calar.

## Ritmo — "fala mais devagar"

Pedido típico: "fala mais devagar", "tá muito rápido", "acelera um pouco".

```bash
"$CV" velocidade 150   # palavras por minuto; fala uma amostra depois
"$CV" velocidade       # mostra a atual
```

Referência: 130 é conversa calma, 150 audiolivro, 170 o padrão, 258 é a voz crua
do modelo (o ajuste desligado, com `0`). Se ele disser só "mais devagar", tire
20 do valor atual.

As pausas entre frases e entre parágrafos também são configuráveis, em
`~/.claudinho-voice/config.json` (`pausa_entre_frases_s` e
`pausa_entre_paragrafos_s`). Depois de editar, rode `"$CV" velocidade` para o
serviço reler — ou pergunte o valor e edite você.

## Controles

| Pedido | Comando |
|---|---|
| "para", "cala", "chega" | `"$CV" parar` |
| "pausa" / "continua" | `"$CV" pausar` / `"$CV" retomar` |
| "pula essa parte" | `"$CV" pular` |
| "repete" / "repete o final" | `"$CV" repetir` / `"$CV" repetir fim` |
| "o que você já leu?" | `"$CV" historico` |
| "o que está lendo?" | `"$CV" estado` |
| "testa a voz" | `"$CV" testar` |

## Regras

1. **Um comando por pedido.** Não encadeie leitura com outras ações.
2. **Confirmação de uma linha.** Nunca repita o conteúdo que foi enfileirado.
3. **Não mexa no léxico por conta própria.** Termos mal falados vão para
   `~/.claudinho-voice/termos-desconhecidos.txt`; proponha a inclusão em
   `~/.claudinho-voice/lexico.json` e só edite com o aval dele.
4. Se o comando falhar, mostre a mensagem de erro dele em uma linha e pare.
   O log fica em `~/.claudinho-voice/claudinho-voice.log`.
