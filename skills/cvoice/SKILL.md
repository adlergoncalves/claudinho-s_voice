---
name: cvoice
description: Voz do Claude Code na máquina local. Três usos — (1) ativar a leitura em voz alta de todas as respostas desta janela de contexto; (2) ler um arquivo do disco; (3) ler um artefato do Claude pela URL. Use quando pedirem "ativa a voz", "lê suas respostas", "lê esse arquivo pra mim", "me lê o ADR X", "lê esse artefato", "para de ler", "desliga a voz", ou indicar que vai ouvir em vez de ler.
---

# Claudinho's Voice

Leitor por voz 100% local (Piper, vozes pt-BR). Você **não** precisa subir nem
gerenciar nada: o comando levanta o serviço sozinho na primeira chamada.

O `cvoice` **não está no PATH**: ele vive no plugin. O lançador em `bin/`
existe desde a instalação — antes mesmo de haver ambiente — então o caminho é
sempre o mesmo. Descubra uma vez por sessão e guarde:

```bash
# Ao atualizar o plugin, a pasta da versão antiga FICA no cache. Nunca pegue a
# primeira que o ls devolver: a mais recente que tenha o lançador é a instalada.
PL=$(ls -dt ~/.claude/plugins/cache/*/claudinho-voice/*/ 2>/dev/null | while read -r d; do [ -e "$d/bin/cvoice.cmd" ] && { echo "$d"; break; }; done)
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) CV="$PL/bin/cvoice.cmd" ;; *) CV="$PL/bin/cvoice" ;; esac
# clone manual, fora do plugin: PL é a raiz do projeto
```

Nos exemplos abaixo, `$CV` é esse caminho. Em Bash use aspas: `"$CV"`.

**Primeira vez:** não existe caminho especial. O mesmo `"$CV" ativar` do
Cenário 1 percebe que não há ambiente e faz tudo: acha um Python 3.12+ na
máquina (ou instala um, sem admin, se não houver), cria o ambiente, instala as
dependências, baixa a voz (~63 MB), sobe o serviço e abre o painel. Leva
alguns minutos e imprime cada etapa — repasse a saída, não a resuma. Se uma
etapa falhar, a saída diz qual e por quê: mostre isso e pare. Não tente
preparar nada por outro caminho.

## Cenário 1 — ler todas as minhas respostas nesta janela de contexto

Pedido típico: "ativa a voz", "passa a ler suas respostas", "modo voz".

```bash
"$CV" ativar
```

Um comando, sempre esse. Ele prepara o que faltar, sobe a voz e abre a janela de
controle **juntas** — nunca uma sem a outra — e liga a leitura **só aqui**:
outras janelas do Claude Code não são afetadas. A partir da próxima resposta,
tudo que eu escrever como resposta final é lido em voz alta.

Numa instalação nova ele demora alguns minutos e imprime o que está fazendo;
numa já pronta responde na hora. Use `"$CV" ativar --sem-painel` só se ele pedir
a voz sem a janela.

**Se a saída trouxer o aviso de que os hooks não estão carregados**, repasse-o:
o plugin foi instalado com esta janela já aberta, o Claude Code só lê o
`hooks.json` ao iniciar, e por isso as respostas não serão lidas até ele abrir
uma janela nova. Tudo o mais funciona — inclusive ler arquivo e artefato.

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

## Narração enquanto você trabalha

Com o modo voz ligado, o texto que você escreve **entre** chamadas de
ferramenta é narrado enquanto a ferramenta roda — se você passou mais de 3,5
segundos trabalhando. É automático, feito por hook; não chame nada. A narração
é perecível: se a fila atrasar, o serviço descarta o que envelheceu, então
escreva esses textos intermediários curtos e no presente ("abrindo o arquivo",
"rodando os testes"). Não existem frases de espera pré-gravadas.

## Interrupção

Com o modo voz ligado, **qualquer mensagem enviada já corta a fala em
curso** (barge-in por teclado, feito pelo hook de prompt). Não é preciso chamar
`parar` antes de responder; só chame quando ele pedir explicitamente para calar.

## Painel — a janela de controle

Pedido típico: "abre o painel", "abre o player", "quero os controles".

```bash
"$CV" painel
```

Janela sem moldura, sempre por cima: pausar, andar de parágrafo, repetir,
parar, volume e velocidade; na engrenagem, modelo, voz, pausas e leitura de
blocos de código, com botão de salvar. Fechar a janela encerra tudo — a leitura,
o modo voz e o serviço.

## Velocidade — "fala mais devagar"

Pedido típico: "fala mais devagar", "tá muito rápido", "acelera um pouco".

A velocidade é um multiplicador da **reprodução**, como no YouTube — vale no
áudio que já está saindo, não na geração:

```bash
curl -s -X POST http://127.0.0.1:8765/taxa -H "Content-Type: application/json" -d '{"taxa": 1.5}'
```

Entre 0,5 e 2,0; `1.0` é o normal. No painel isso é o botão ao lado do volume.

O resto da configuração (voz, modelo, pausas, ler blocos de código) fica na
janela de ajustes do painel, pela engrenagem — abra com "abre o painel". Mexer
no arquivo à mão não é preciso.

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
   Os logs ficam em `~/.claudinho-voice/`: `claudinho-voice.log` (o serviço),
   `hook.log` (por que uma resposta não foi lida) e `painel.log` (por que a
   janela não abriu). Para "não sai voz nenhuma", o `hook.log` é o que responde
   — se ele não tem entrada recente, os hooks não estão carregados na janela.
