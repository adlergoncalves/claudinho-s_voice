# -*- coding: utf-8 -*-
"""Varredura: quais termos técnicos a voz atual lê errado.

Primeiro passo do conserto de pronúncia. A banca (``medir_fonemas.py``) compara
candidatos para **um** termo que você já sabe estar quebrado; esta varredura
descobre **quais** estão quebrados, passando o vocabulário inteiro pela voz e
transcrevendo de volta com o Whisper.

Rode ao trocar de voz: o inventário treinado muda de modelo para modelo, e o
que a ``cadu`` acerta a ``jeff`` pode errar. O que sair como ``RUIM`` vira
candidato para a seção ``pronuncia`` do léxico (grafia aportuguesada — a que
costuma ganhar) ou, se a grafia não resolver, para a seção ``fonemas`` (IPA).

Uso::

    python eval/varrer_termos.py                    # vocabulário padrão, voz da config
    python eval/varrer_termos.py --voz jeff
    python eval/varrer_termos.py --termos meus.txt  # um termo por linha

O veredito é ``acertos/4``: duas gerações, cada uma com o termo repetido duas
vezes na frase-veículo. ``OK`` = 3 ou 4; ``~`` = 1 ou 2 (instável, olhar);
``RUIM`` = 0.

⚠️ O Whisper erra em nome próprio: já transcreveu "time" para uma fala correta
de "tims". Em nome de produto, confirme o wav de ouvido antes de condenar.
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claudinho_voice.config import Config  # noqa: E402
from claudinho_voice.motores.piper import MotorPiper  # noqa: E402

VOCABULARIO = """
branch merge commit rebase checkout push pull deploy release rollback build
frontend backend fullstack endpoint payload worktree scratchpad pipeline
hotfix workaround bug debug log sprint backlog board card issue review
request response timeout retry worker queue trigger webhook middleware
handler provider container cluster runtime streaming chunk thread lock mock
stub fixture seed schema migration bundle lint coverage storage upload
download login logout hash token cache template layout loading toast drawer
modal tooltip placeholder skeleton hook props state store teams outlook
sharepoint azure slack zoom react docker python github javascript typescript
figma node npm dotnet blazor kubernetes redis kafka nginx linux windows
""".split()
"""Jargão que aparece na rotina: git, web, .NET, nuvem e as ferramentas do dia."""

VEICULO = "Rodei o {t} ontem e o {t} passou sem erro."
"""O termo duas vezes, no meio e no fim: a posição muda a articulação do VITS."""


def _chave(texto: str) -> str:
    """Compara sem acento, caixa ou pontuação: "Git-Hub" casa "github"."""
    base = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in base if c.isalnum())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--voz", default=None, help="padrão: a voz da config")
    parser.add_argument("--termos", help="arquivo com um termo por linha")
    parser.add_argument("--repeticoes", type=int, default=2)
    parser.add_argument("--saida", default="eval/audio/varredura")
    args = parser.parse_args()

    termos = (
        Path(args.termos).read_text(encoding="utf-8").split()
        if args.termos
        else VOCABULARIO
    )
    voz = args.voz or Config.carregar().voz or "cadu"
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)

    motor = MotorPiper()
    motor.carregar("pt", voz, 4)
    # sem o léxico: a varredura mede o texto CRU, que é o que se quer diagnosticar
    motor._fonemas_validos = {}

    from faster_whisper import WhisperModel

    whisper = WhisperModel("small", device="cpu", compute_type="int8")

    maximo = args.repeticoes * 2
    print(f"voz: {voz} · {len(termos)} termos · veredito em acertos/{maximo}\n")
    print(f"{'termo':16} {'ok':>5}  ouvido")
    ruins: list[str] = []
    instaveis: list[str] = []
    for termo in termos:
        acertos = 0
        ouvidos: list[str] = []
        for rep in range(args.repeticoes):
            audio = motor.gerar(VEICULO.format(t=termo))
            arquivo = saida / f"{_chave(termo)}_{rep}.wav"
            sf.write(arquivo, audio, motor.sample_rate)
            segmentos, _ = whisper.transcribe(str(arquivo), language="pt", beam_size=5)
            ouvido = " ".join(s.text for s in segmentos).strip()
            ouvidos.append(ouvido)
            acertos += min(2, _chave(ouvido).count(_chave(termo)))
        if acertos >= maximo - 1:
            marca = "OK  "
        elif acertos >= 1:
            marca = "~   "
            instaveis.append(termo)
        else:
            marca = "RUIM"
            ruins.append(termo)
        print(f"{termo:16} {acertos}/{maximo} {marca} {ouvidos[0][:70]}", flush=True)

    print(f"\nRUIM ({len(ruins)}): {' '.join(ruins)}")
    print(f"INSTÁVEL ({len(instaveis)}): {' '.join(instaveis)}")
    print("\nPróximo passo: escreva a grafia aportuguesada de cada um na seção")
    print("`pronuncia` do léxico e confirme com `python eval/medir_fonemas.py`.")


if __name__ == "__main__":
    main()
