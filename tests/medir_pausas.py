"""Mede os buracos de silêncio entre frases numa leitura real.

Substitui o alto-falante por um sumidouro que "toca" o áudio dormindo pelo
tempo exato dele. Assim medimos, sem placa de som, quanto tempo a fala fica
parada esperando a próxima frase ser gerada. Uso:

    python tests/medir_pausas.py [arquivo.md]
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claudinho_voice.config import Config  # noqa: E402
from claudinho_voice.motor import Motor  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logging.getLogger("pocket_tts").setLevel(logging.WARNING)


def main() -> None:
    alvo = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if alvo:
        texto = alvo.read_text(encoding="utf-8", errors="replace")
    else:
        texto = (
            "Os três cenários estão fechados e commitados. E a leitura automática está ligada nesta sessão "
            "desde o teste, então esta resposta é o teste ao vivo do cenário um. Se você ouvir o rafael lendo "
            "este texto, o hook disparou sem reiniciar o Claude Code. Cenário um: auto on detectou esta sessão "
            "sem nenhum parâmetro. Cenário dois: leu o ADR trinta real, cento e cinquenta e uma frases, pausa e "
            "parada funcionando. Cenário três: artefato Homologador de Fluxos lido ponta a ponta, sessenta e "
            "quatro frases, título extraído, zero cortes. Setenta e três testes passando. Um bug real que o "
            "teste não pegou: meta e link não fecham, o contador nunca voltava a zero e a página inteira sumia. "
            "Para usar: diga ativa a voz, lê o ADR trinta pra mim, ou lê esse artefato. Só isso."
        )

    m = Motor(Config(pausa_entre_itens_s=0))
    m.carregar()

    fim_ultimo_audio: list[float] = [0.0]
    buracos: list[float] = []
    inicio_leitura: list[float] = [0.0]
    total_audio: list[float] = [0.0]

    def tocar_falso(audio: np.ndarray, geracao: int) -> None:
        agora = time.perf_counter()
        if inicio_leitura[0] == 0.0:
            inicio_leitura[0] = agora
            logging.info("PRIMEIRO SOM apos %.2fs", agora - t0)
        elif fim_ultimo_audio[0] and agora - fim_ultimo_audio[0] > 0.15:
            buraco = agora - fim_ultimo_audio[0]
            buracos.append(buraco)
            logging.info("  buraco de %.2fs antes da frase", buraco)
        dur = len(audio) / m.sample_rate
        total_audio[0] += dur
        time.sleep(dur)  # "toca" em tempo real
        fim_ultimo_audio[0] = time.perf_counter()

    m._tocar = tocar_falso  # type: ignore[method-assign]

    t0 = time.perf_counter()
    m.ler(texto, titulo="medicao")
    time.sleep(0.5)
    while m.estado().lendo or m.estado().itens_na_fila:
        time.sleep(0.2)
    total = time.perf_counter() - t0

    print()
    print(f"frases: {m.estado().total_frases} | audio: {total_audio[0]:.1f}s | relogio: {total:.1f}s")
    print(f"primeiro som: {inicio_leitura[0]-t0:.2f}s")
    print(f"buracos > 0,15s: {len(buracos)} | maior: {max(buracos) if buracos else 0:.2f}s | soma: {sum(buracos):.2f}s")
    m.desligar()


if __name__ == "__main__":
    main()
