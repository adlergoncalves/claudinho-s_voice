# Claudinho's Voice — roteiro da máquina limpa (v1.1.0)

Executar numa máquina onde o plugin **nunca** foi instalado. Cada passo tem o
resultado esperado; se divergir, anote o passo, o que apareceu e siga só se o
roteiro disser que pode.

## Pré-condições

- Windows 11, Claude Code CLI instalado e logado, VS Code com a extensão do Claude Code.
- Rede liberada para `github.com`, `huggingface.co`, `astral.sh` e `pypi.org`.
- Antivírus corporativo pode estar presente (Kaspersky). **Não** copie a pasta `certs/` de
  outra máquina: o plugin monta o bundle de CA sozinho a partir do repositório do Windows.
- Nenhum Python instalado é aceitável (o plugin instala). Se houver Python, precisa ser ≥ 3.12
  com `pip`/`ensurepip`; se for menor, o plugin também instala o dele.
- A pasta `%USERPROFILE%\.claudinho-voice` **não existe**. Se existir, renomeie antes.

## Passo 1 — instalar o plugin (Claude Code CLI)

Abra o Claude Code no terminal e rode os dois prompts, um por vez:

```
/plugin marketplace add adlergoncalves/claudinho-s_voice
/plugin install claudinho-voice@claudinho
```

**Esperado:** os dois terminam sem erro. A pasta
`%USERPROFILE%\.claude\plugins\cache\claudinho\claudinho-voice\1.1.0\` passa a existir, com
`hooks.json`, `bin\`, `skills\` e `claudinho_voice\`, e **sem** `.venv\` (ainda).

**Não é bug:** nenhuma voz sai nesta sessão do CLI, mesmo que você digite algo. A sessão que
instala o plugin não recebe os hooks; só a próxima recebe. Feche o CLI.

## Passo 2 — primeira ativação (VS Code)

Abra o VS Code, abra um chat do Claude Code e mande **uma** destas mensagens:

```
/claudinho-voice:cvoice
```
ou, em linguagem natural: `ativa a voz` · `cvoice` · `claudinho's voice: on`.

**Esperado — primeira execução (3 a 5 minutos com Python já instalado; ~540 MB de download; a
saída aparece passo a passo, em ordem e com acento):**

1. Diz qual Python vai usar. Se não houver nenhum utilizável, diz que vai instalar (`uv` +
   CPython 3.12) e instala. Se der erro de rede aqui, a mensagem nomeia o download que falhou.
2. Cria o ambiente (`.venv` dentro da pasta do plugin) e instala as dependências, **incluindo o
   painel** (`pywebview`) e o **Kokoro**.
3. Baixa as **três vozes** pt-BR do Piper (jeff, cadu, faber — ~63 MB cada) e o modelo
   **Kokoro** (~350 MB) para `%USERPROFILE%\.claudinho-voice\modelos\`. Se o Kokoro falhar,
   é aviso, não erro: o Piper funciona sem ele.
4. **Toca uma frase de teste** ("Claudinho's Voice pronto…") — se não ouvir, pare aqui: o
   problema é dispositivo de saída ou volume do sistema, não o plugin.
5. Sobe o serviço de voz e **abre o painel** (janela com o orbe, fica por cima).
6. Liga a leitura nesta sessão ("voz ligada nesta sessão"). Como esta sessão nasceu **depois**
   da instalação, **não deve aparecer aviso de hook** nem pedido de reinício — quando o hook
   está OK, o comando fica calado sobre ele.
7. O Claude responde uma linha curta de confirmação — e **essa resposta já sai falada**, sem
   comer as primeiras palavras.

**Não é bug:**
- Se o plugin instalou o Python: o `uv` grava um `python3.12.exe` em `%USERPROFILE%\.local\bin`
  e avisa que essa pasta não está no PATH. É esperado — o plugin não mexe no seu PATH e usa o
  Python pelo caminho gerenciado (`%APPDATA%\uv\python`), não por esse atalho.
- A primeira resposta falada pode demorar alguns segundos a mais (motor aquecendo).
- Uma frase curta de espera ("deixa eu ver aqui") quando o Claude usa ferramentas por mais de
  ~3,5 s.

**É bug (anote e pare):**
- Na etapa 1, `Get-ExecutionPolicy ... não foi possível carregar o módulo` (o lançador deve
  isolar o PowerShell 5.1 do pwsh 7) ou `invalid peer certificate: UnknownIssuer` no download do
  Python (o uv deve usar a loja de certificados do Windows — antivírus que intercepta TLS).
- Qualquer etapa sair em silêncio sem dizer o que fez.
- Terminar dizendo "voz ligada" e a resposta seguinte não ser lida.
- Pedir para reiniciar o Claude Code nesta sessão (ela nasceu depois da instalação).
- Painel não aparecer. Se acontecer, olhe `%USERPROFILE%\.claudinho-voice\painel.log`.
- Painel abrir com a onda de barras antiga em vez do orbe (HTML em cache — não deve mais ocorrer).
- Ícone do Python na barra de tarefas em vez do ícone do Claudinho.
- Serviço subir sem som com o deslizante de volume no zero (volume não é mais gravado).

## Passo 3 — usar

Peça algo que gere resposta de 2–3 parágrafos. **Esperado:** leitura completa, prosa (sem títulos
ou listas sendo soletrados). Digite qualquer coisa no meio da leitura: **esperado**, a fala corta
na hora (barge-in). Botões do painel: pausar, retomar, pular, repetir, parar — cada um age em
menos de 1 s.

## Passo 4 — segunda sessão (o "só ativar")

Feche o chat, abra **outro** chat do Claude Code no VS Code e mande `ativa a voz`.

**Esperado:** responde em menos de 2 s — "voz ligada nesta sessão" — sem baixar nem instalar
nada, e a resposta já sai falada. **É bug** se voltar a preparar ambiente ou baixar voz.

## Passo 5 — reinício do sistema

Reinicie o Windows, abra o VS Code, novo chat, `ativa a voz`. **Esperado:** aparece
"subindo o serviço..." e leva alguns segundos (3–5 s) — o serviço sobe sozinho, sem etapa
manual — e depois "voz ligada nesta sessão". **Não é bug** essa demora; **é bug** voltar a
instalar ou baixar algo.

## Evidências a coletar

- Saída completa do passo 2 (copiar do chat).
- `%USERPROFILE%\.claudinho-voice\hook.log` após o passo 3 — deve ter linhas
  `stop enfileirando N chars` seguidas de `stop ok`.
- `dir %USERPROFILE%\.claudinho-voice\modelos\piper` — as três vozes (`jeff`, `cadu`, `faber`) com
  seus `.json`; `modelos\kokoro` com `kokoro-v1.0.onnx` e `voices-v1.0.bin`.
- Se houver falha: `%USERPROFILE%\.claudinho-voice\claudinho-voice.log` e `painel.log`.

## O que este roteiro não prova

- Comportamento em Linux/macOS.
- Máquina com proxy que bloqueia download de executável (`astral.sh`): o esperado é a instalação
  **parar com mensagem clara** no passo 2.1; isso não foi testado.
- A interceptação TLS do antivírus é **intermitente**: um passo 2.1 verde não prova que a
  correção `UV_SYSTEM_CERTS` foi necessária. A evidência é a falha `UnknownIssuer` registrada
  na validação de 17/09/2026, antes da correção.
