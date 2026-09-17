# -*- coding: utf-8 -*-
"""Banca do léxico de fonemas: nenhum verbete entra sem medida.

Para cada termo, gera uma frase-veículo com cada grafia IPA candidata (e com o
texto puro, que é a linha de base do espeak), transcreve com o Whisper e conta
em quantas repetições o termo voltou reconhecível. Quem ganha da linha de base
merece entrar em ``lexico_padrao.json``; quem perde fica de fora — e o motivo
fica registrado no ``_comentario``.

Por que medir e não confiar no ouvido: o VITS é estocástico, a mesma grafia
sai diferente a cada geração. Duas ou três repetições separam o verbete bom do
golpe de sorte.

Uso::

    python eval/medir_fonemas.py candidatos.json
    python eval/medir_fonemas.py candidatos.json --voz cadu --repeticoes 3
    python eval/medir_fonemas.py --lexico          # revalida o que já está no léxico

``candidatos.json``::

    {"frontend": ["fɾõtʃˈẽdʒɪ", "fɾˈõtʃẽdʒ"], "release": ["ɾilˈis", "xilˈis"]}

O IPA precisa usar só símbolos do inventário pt-BR da voz; símbolo estranho é
apontado antes de gerar. O inventário sai de ``eval/inventario_fonemas.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claudinho_voice.motores.piper import MotorPiper  # noqa: E402
from claudinho_voice.preparar import carregar_lexico  # noqa: E402

VEICULOS = [
    "Rodei o {t} ontem e o {t} passou sem erro.",
    "Depois do {t}, o {t} novo ficou pronto.",
]
"""Frases-veículo: o termo aparece duas vezes, no meio e no fim, porque a
posição muda a articulação do VITS."""


def _chave(texto: str) -> str:
    """Compara sem acento, caixa, hífen ou espaço: "front-end" casa "frontend"."""
    base = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in base if c.isalnum())


def _reconheceu(termo: str, ouvido: str) -> int:
    return _chave(ouvido).count(_chave(termo))


def medir(
    motor: MotorPiper, whisper, termo: str, candidatos: list[str], repeticoes: int, saida: Path
) -> None:
    conhecidos = set(motor._voz.config.phoneme_id_map)
    linhas = [("(texto puro)", None)] + [(ipa, ipa) for ipa in candidatos]
    print(f"\n{termo}")
    for rotulo, ipa in linhas:
        if ipa is not None:
            fora = sorted({s for s in unicodedata.normalize("NFD", ipa) if s not in conhecidos})
            if fora:
                print(f"  {rotulo:28} símbolo fora do inventário da voz: {fora}")
                continue
        motor._fonemas_validos = {termo.lower(): ipa} if ipa else {}
        acertos = 0
        total = 0
        ouvidos: list[str] = []
        for rep in range(repeticoes):
            for indice, veiculo in enumerate(VEICULOS):
                frase = veiculo.format(t=termo)
                audio = motor.gerar(frase)
                arquivo = saida / f"{_chave(termo)}_{_chave(rotulo)[:12]}_{rep}_{indice}.wav"
                sf.write(arquivo, audio, motor.sample_rate)
                segmentos, _ = whisper.transcribe(str(arquivo), language="pt", beam_size=5)
                ouvido = " ".join(s.text for s in segmentos).strip()
                acertos += min(2, _reconheceu(termo, ouvido))
                total += 2
                ouvidos.append(ouvido)
        exemplo = min(ouvidos, key=lambda o: _reconheceu(termo, o))
        print(f"  {rotulo:28} {acertos:2d}/{total}   pior: {exemplo}")
    motor._fonemas_validos = None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("candidatos", nargs="?", help="JSON {termo: [ipa, ...]}")
    parser.add_argument("--lexico", action="store_true", help="revalida os verbetes do léxico")
    parser.add_argument("--voz", default="cadu")
    parser.add_argument("--repeticoes", type=int, default=2)
    parser.add_argument("--saida", default="eval/audio/fonemas")
    args = parser.parse_args()

    if args.lexico:
        candidatos = {t: [ipa] for t, ipa in carregar_lexico()["fonemas"].items()}
    elif args.candidatos:
        candidatos = json.loads(Path(args.candidatos).read_text(encoding="utf-8"))
    else:
        parser.error("informe o JSON de candidatos ou --lexico")

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)

    motor = MotorPiper()
    motor.carregar("pt", args.voz, 4)
    from faster_whisper import WhisperModel

    whisper = WhisperModel("small", device="cpu", compute_type="int8")

    print(f"voz: {args.voz} · {args.repeticoes} repetições × {len(VEICULOS)} veículos × 2 ocorrências")
    for termo, ipas in candidatos.items():
        medir(motor, whisper, termo, list(ipas), args.repeticoes, saida)


if __name__ == "__main__":
    main()
