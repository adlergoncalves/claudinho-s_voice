"""Hook ``UserPromptSubmit`` do Claude Code: injeta o contrato de fala.

Quando a leitura automática está ligada para a sessão, tudo que o Claude
escrever será ouvido, não lido. Um texto bom de ler (títulos, listas, tabelas,
negrito) é péssimo de ouvir. Este hook roda a cada prompt e, se a sessão estiver
em modo voz, devolve na saída padrão um bloco de contexto que o Claude Code
anexa ao prompt — o Claude passa a responder como quem fala.

Custo zero fora do modo voz: um ``stat`` e sai sem imprimir nada.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONTRATO = """\
[Claudinho's Voice — MODO VOZ LIGADO nesta sessão]
Sua resposta final será lida em voz alta, não lida na tela. Escreva como quem fala, \
no estilo de uma conversa por voz (como o Claude no CarPlay):

- Prosa corrida, em frases curtas. Sem títulos, listas, tabelas, negrito, emojis ou \
separadores. Nada de "1.", "2.", bullets ou dois-pontos de rótulo.
- Vá direto ao ponto na primeira frase. Uma resposta comum cabe em 2 a 5 frases \
(até uns 500 caracteres, meio minuto de fala). Se o assunto pedir mais, diga o \
essencial e ofereça o detalhe: "quer que eu entre no detalhe de X?".
- Tom de colega conversando, em português, tratando por "você". Sem formalidade, \
sem preâmbulo, sem repetir a pergunta.
- Comando, código, caminho longo ou tabela: coloque num bloco de código (```), que \
será pulado na leitura, e diga em uma frase o que deixou na tela: "deixei o comando \
na tela". Nunca soletre um caminho ou uma URL em prosa.
- Sigla e termo técnico em inglês podem ficar (JWT, pipeline, deploy); o leitor sabe \
falar. Números podem ficar em algarismos.
- Ao terminar trabalho que alterou algo, ainda diga o que mudou, o que foi \
verificado e o que ficou pendente — mas em frases faladas, não em seções.
- Perguntas ao usuário: uma por vez, curta, no fim.
- Enquanto estiver executando ferramentas, os textos intermediários podem ser \
mínimos; o que importa é a resposta final.
Isto vale só para o texto da resposta. Não muda o que você faz, só como conta.
"""


def _interromper_fala() -> None:
    """Barge-in: você digitou, então a fala em curso perde a vez.

    Sem microfone, o gesto de interromper é começar a escrever. O prompt chega
    aqui antes de o Claude pensar, então parar neste ponto é o mais próximo do
    barge-in de um assistente de voz. Falha em silêncio: se o serviço não está
    no ar, não há nada tocando.

    Exceção importante: uma leitura **pedida** ("lê esse arquivo", "repete") não
    pode ser cortada pela mensagem seguinte — quem pediu quer ouvir até o fim.
    O serviço marca essas leituras como protegidas e ignora a interrupção; só
    "parar" explícito as cala.
    """
    try:
        import httpx

        from .config import Config

        cfg = Config.carregar()
        httpx.post(
            f"http://{cfg.host}:{cfg.porta}/parar",
            json={"motivo": "barge-in"},
            timeout=1.0,
        )
    except Exception:
        pass


def main_com_entrada(entrada: dict) -> int:
    """Corpo do hook, separado da leitura da entrada padrão para poder testar."""
    session_id = str(entrada.get("session_id") or "")
    if not session_id:
        transcript = str(entrada.get("transcript_path") or "")
        session_id = Path(transcript).stem if transcript else ""

    from .config import sessao_ligada

    if not sessao_ligada(session_id):
        return 0

    from .hook import _registrar

    _registrar("prompt", f"sessao {session_id[:8]}")
    _interromper_fala()

    # zera o relógio do turno: o hook de ferramenta usa isto para saber há
    # quanto tempo a pessoa está esperando em silêncio
    from .hook_trabalhando import marcar_inicio_do_turno

    marcar_inicio_do_turno(session_id)

    sys.stdout.write(CONTRATO)
    return 0


def main() -> int:
    try:
        return main_com_entrada(json.loads(sys.stdin.read() or "{}"))
    except Exception:
        return 0  # nunca atrapalhar o prompt


if __name__ == "__main__":
    raise SystemExit(main())
