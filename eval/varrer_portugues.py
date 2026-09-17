# -*- coding: utf-8 -*-
"""Varredura do PORTUGUÊS: em que fenômeno da língua a voz tropeça.

O léxico nasceu para estrangeirismo e sigla; isto aqui é a outra metade — as
particularidades do português brasileiro que derrubam o modelo: LH, NH, QU/GU,
os cinco sons do X, timbre aberto/fechado de E e O, nasais, os erres, tônica em
proparoxítona, hiatos, homógrafos sem acento, S/Z, L final, e o vocabulário da
feira. O corpus está em ``eval/corpus_portugues.json``, agrupado por fenômeno.

Para cada palavra faz duas coisas:

1. mostra a **fonemização do espeak** (IPA) — erro aqui é erro de dicionário do
   espeak, e se conserta com IPA na seção ``fonemas`` do léxico;
2. gera em frase realista, transcreve com o Whisper e vê se a palavra volta —
   erro aqui com fonema certo é o **modelo** articulando mal, e se conserta com
   regra de fonema por voz (``SUBSTITUICOES_POR_VOZ``) ou se aceita como teto.

Sai um placar por fenômeno (quantas palavras do grupo voltaram) e a lista das
que falharam, com IPA e o que foi ouvido, em ``eval/resultados/``.

Uso::

    python eval/varrer_portugues.py                 # todos os grupos, voz da config
    python eval/varrer_portugues.py --grupo lh nh   # só estes
    python eval/varrer_portugues.py --so-fonemas    # só o IPA, sem áudio (instantâneo)
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claudinho_voice.config import Config  # noqa: E402
from claudinho_voice.motores.piper import MotorPiper  # noqa: E402

CORPUS = Path(__file__).resolve().parent / "corpus_portugues.json"
MOLDE = "Ontem eu falei {t} para ela e ela entendeu."
"""Frase curta e comum; a palavra no meio, com prosa dos dois lados."""


def _chave(texto: str) -> str:
    base = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in base if c.isalnum())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--voz", default=None)
    parser.add_argument("--grupo", nargs="*", help="nomes de grupo do corpus")
    parser.add_argument("--so-fonemas", action="store_true", help="não gera áudio")
    parser.add_argument("--saida", default="eval/resultados")
    parser.add_argument("--audio", default="eval/audio/portugues")
    args = parser.parse_args()

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    corpus.pop("_comentario", None)
    grupos = args.grupo or list(corpus)
    voz = args.voz or Config.carregar().voz or "cadu"

    motor = MotorPiper()
    motor.carregar("pt", voz, 4)
    piper = motor._voz

    whisper = None
    if not args.so_fonemas:
        import soundfile as sf
        from faster_whisper import WhisperModel

        whisper = WhisperModel("small", device="cpu", compute_type="int8")
        pasta = Path(args.audio)
        pasta.mkdir(parents=True, exist_ok=True)

    resultado = {"voz": voz, "data": date.today().isoformat(), "grupos": {}}
    for grupo in grupos:
        palavras = list(dict.fromkeys(corpus[grupo]))  # sem repetição, na ordem
        falhas = {}
        print(f"\n### {grupo}  ({len(palavras)} palavras)", flush=True)
        for palavra in palavras:
            ipa = "".join(p for s in piper.phonemize(palavra) for p in s)
            if whisper is None:
                print(f"  {palavra:16} {ipa}", flush=True)
                continue
            audio = motor.gerar(MOLDE.format(t=palavra))
            arquivo = pasta / f"{grupo}_{_chave(palavra)}.wav"
            sf.write(arquivo, audio, motor.sample_rate)
            segmentos, _ = whisper.transcribe(str(arquivo), language="pt", beam_size=5)
            ouvido = " ".join(s.text for s in segmentos).strip()
            ok = _chave(palavra) in _chave(ouvido)
            marca = "ok  " if ok else "ERRO"
            print(f"  {marca} {palavra:16} {ipa:22} {'' if ok else ouvido[:60]}", flush=True)
            if not ok:
                falhas[palavra] = {"ipa": ipa, "ouvido": ouvido}
        if whisper is not None:
            acertos = len(palavras) - len(falhas)
            resultado["grupos"][grupo] = {
                "acertos": acertos,
                "total": len(palavras),
                "falhas": falhas,
            }
            print(f"  → {grupo}: {acertos}/{len(palavras)}", flush=True)

    if whisper is not None:
        Path(args.saida).mkdir(parents=True, exist_ok=True)
        destino = Path(args.saida) / f"portugues-{voz}-{date.today().isoformat()}.json"
        destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\nPLACAR POR FENÔMENO")
        for grupo, r in sorted(resultado["grupos"].items(), key=lambda x: x[1]["acertos"] / x[1]["total"]):
            pct = 100 * r["acertos"] / r["total"]
            print(f"  {grupo:22} {r['acertos']:3d}/{r['total']:<3d} {pct:3.0f}%")
        print(f"→ {destino}")


if __name__ == "__main__":
    main()
