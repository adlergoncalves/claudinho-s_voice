# Claudinho's Voice

Leitor por voz para o Claude Code. Roda inteiro na máquina: sem nuvem, sem API,
sem custo por uso.

- **Motor:** [Piper](https://github.com/OHF-Voice/piper1-gpl) (Rhasspy) — VITS + ONNX, sem PyTorch
- **Voz:** `jeff`, uma das quatro pt-BR **gravadas por falantes brasileiros**
- **Velocidade:** gera ~20x mais rápido do que fala (RTF ~0,05 em 4 núcleos)
- **Uso:** ouvir documentos, relatórios e as respostas do Claude Code enquanto se faz outra coisa

O motor é trocável: Pocket TTS (Kyutai) e Kokoro também acompanham o projeto.
A escolha do Piper foi medida — ver `eval/comparar_motores.py`.

## Instalação

### Como plugin do Claude Code (recomendado)

```
/plugin marketplace add adlergoncalves/claudinho-s_voice
/plugin install claudinho-voice@claudinho
```

A skill e os três hooks ligam sozinhos. Abra uma janela nova do Claude Code e
diga "ativa a voz": na primeira vez a instalação se prepara inteira — acha ou
instala um Python, cria o ambiente, baixa as três vozes pt-BR e o modelo Kokoro
(~540 MB no total) e **toca uma frase de teste** — uma vez só, alguns minutos.
Nas seguintes, ligar é instantâneo, e o painel abre junto.

### Manualmente (clone)

```powershell
powershell -File install.ps1
```

É o mesmo preparo do plugin, do zero ao áudio tocando. Não cria atalho, não
registra nada no Claude Code nem no Windows; o executável fica em
`.venv\Scripts\cvoice.exe`.

## Uso

```bash
cvoice testar                       # fala uma frase de teste
cvoice ler docs/adr/0030.md         # lê um arquivo
cat resumo.md | cvoice ler          # lê o que vier por pipe
cvoice auto on                      # passa a ler as respostas do Claude Code
cvoice parar                        # cala agora
cvoice pausar / retomar / pular
cvoice estado                       # o que está sendo lido
cvoice avancar / voltar             # navega por parágrafo dentro do texto
cvoice painel                       # abre a janela de controle
cvoice dispositivos                 # saídas de áudio disponíveis
```

Dentro do Claude Code, a skill `/cvoice` cobre os mesmos casos em linguagem natural
("lê esse ADR pra mim", "ativa a voz", "para").

## Trocar o modelo de voz

O modelo é uma peça substituível, não o coração do projeto. Todo o resto —
preparação de texto, fila, ritmo, hooks, histórico — não sabe quem fala.

```bash
cvoice motor                          # mostra o atual e os disponíveis
cvoice motor piper --voz jeff         # troca de voz dentro do mesmo motor
cvoice motor kokoro --voz pf_dora --instalar
cvoice reiniciar
```

`--instalar` baixa os pesos quando o motor precisa. Depois é só reiniciar.

### Motores que vêm no projeto

| Motor | Quando usar |
|---|---|
| `pocket` | padrão: voz mais natural, streaming de verdade (primeiro som em 0,1 s) |
| `kokoro` | quando a exatidão importa mais que o timbre: 0% de erro de palavra medido |

### Plugar um motor novo

Qualquer classe que implemente `MotorDeVoz` serve — XTTS, MOSS, uma API, o que
for. Não é preciso mudar nada no projeto:

```python
from claudinho_voice.motores import MotorDeVoz

class MotorXTTS(MotorDeVoz):
    nome = "xtts"
    corta_frases = False          # True liga a regeração por corte

    def carregar(self, idioma, voz, threads): ...
    @property
    def sample_rate(self): return 24000
    def gerar(self, texto): return audio_float32_mono
    def vozes(self): return ["Ana Florence", "Damien Black"]

    # opcional: só quem tem streaming nativo
    def gerar_em_pedacos(self, texto): ...
```

Aponte o caminho na configuração e pronto:

```json
{ "motor": "meupacote.xtts:MotorXTTS", "voz": "Ana Florence" }
```

Um pacote instalado também pode se registrar sozinho, pelo entry point
`claudinho_voice.motores`.

## Como funciona

```
Claude Code ──hook Stop──┐
skill /cvoice ───────────┤
cvoice (CLI) ────────────┴──► serviço em 127.0.0.1:8765
                                │  fila de leitura
                                │  preparador de texto
                                │  Pocket TTS (carregado uma vez)
                                └─► alto-falante, frase a frase
```

O serviço fica residente com o modelo em memória. Sem ele, cada leitura pagaria
de novo o custo de subir o Python e carregar os pesos.

### Preparação do texto

Nada vai cru para o modelo. O preparador (`preparar.py`) resolve, nesta ordem:

| Entrada | Vira |
|---|---|
| `**negrito**`, `# título`, `[link](url)` | prosa limpa |
| bloco de código | "bloco de código em python, 12 linhas, pulado" |
| tabela markdown | "Tabela com 3 linhas, colunas: A, B. A: x; B: y." |
| `ADR-0030` | "ADR 30" |
| `2026-03-26`, `R$ 1.250,50`, `30%` | por extenso |
| `ApplicationUser`, `pessoa_id` | "Application User", "pessoa id" |
| `JWT`, `PKCE`, `API` | "jota dáblio tê", "pê cá cê ê", "a pê i" |
| `DACPAC`, `CRUD`, `pipeline`, `deploy` | **intactos** — o modelo já acerta |

As regras não são palpite: cada uma foi medida gerando com o Pocket e
transcrevendo de volta com o Whisper. Reescrever inglês foneticamente foi testado
e **piora** muito ("Aplicêixon" virou "PlayStation"), por isso não se faz.

### Léxico

`~/.claudinho-voice/lexico.json` acrescenta termos ao padrão do pacote. Siglas que
caíram na regra genérica são anotadas em `~/.claudinho-voice/termos-desconhecidos.txt`
para revisão.

### Corte prematuro

Em ~20% das gerações o Pocket encerra cedo e devolve ~0,3 s de áudio, engolindo a
frase. Como a fala tem duração previsível (~0,056 s por caractere), o motor detecta
o corte e gera de novo, até 3 vezes. A frase seguinte é preparada em paralelo
enquanto a atual toca, então a validação não custa latência.

## Configuração

`~/.claudinho-voice/config.json`:

```json
{
  "voz": "jeff",
  "idioma": "portuguese",
  "threads": 4,
  "dispositivo_saida": null,
  "volume": 1.0,
  "ler_blocos_de_codigo": false
}
```

`threads: 4` não é arbitrário: neste i7-13700T (8 núcleos P + 8 E), usar 16 threads
deixa a geração até 8x mais lenta.

Vozes alternativas (mesmo sotaque, timbre diferente): `charles`, `anna`, `vera`,
`mary`, `alba`, `jean`, `marius`, `michael`, `paul`, `cosette`, `eve`, `george`, `javert`.

## Testes

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
```

## Decisões

Por que Pocket TTS, e não os outros — todos medidos nesta máquina, em CPU:

| Modelo | Veredito |
|---|---|
| **Pocket TTS 6L** | escolhido: RTF 0,25, streaming de verdade, voz aprovada |
| Kokoro-82M | pronúncia exata (0% de erro), mas timbres recusados |
| XTTS-v2 | RTF ~2: só serve para gerar em lote |
| Qwen3-TTS 0.6B | RTF ~2 em CPU sem AVX-512 |
| MOSS-TTS-Nano | troca palavras em português (16–41% de erro) |
| Vozes do Windows | caixa fechada, sem controle |
