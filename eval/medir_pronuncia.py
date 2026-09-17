# -*- coding: utf-8 -*-
"""Medição em lote da seção ``pronuncia``: centenas de termos de uma vez.

Substitui o rito artesanal (um termo, uma banca, um veredito) por uma esteira:
para cada termo de um arquivo de candidatos, gera o texto **cru** e cada grafia
aportuguesada em duas frases realistas — um termo por frase, prosa em volta, que
é o uso real — transcreve com o Whisper e decide:

* ``ja_certo``    — o cru acerta as duas frases: **não mexer**, grafia só piora.
* ``vencedores``  — a melhor grafia acerta mais que o cru: entra no léxico.
* ``sem_solucao`` — nada acerta: candidato a IPA (seção ``fonemas``) ou a
  julgamento de ouvido (o Whisper erra em nome próprio: "Tread" para ``thread``
  correto, "cocro" para ``kokoro``).

Grava o resultado em ``eval/resultados/`` com o que foi ouvido em cada caso, para
auditar de ouvido o que a métrica reprovou. ``--parte 1/2`` divide a lista para
rodar dois processos em paralelo.

Uso::

    python eval/medir_pronuncia.py eval/candidatos_pronuncia.json
    python eval/medir_pronuncia.py eval/candidatos_pronuncia.json --parte 1/2 &
    python eval/medir_pronuncia.py eval/candidatos_pronuncia.json --parte 2/2
    python eval/aplicar_pronuncia.py eval/resultados/pronuncia-*.json   # funde no léxico

Formato dos candidatos::

    {"cache": ["quéche", "quéchi"], "thread": ["thréd"]}

As grafias seguem o que foi medido em 17/09/2026: **o acento na sílaba tônica é
o que faz funcionar** ('quéche' devolve "cache", 'quéxe' vira "que é que se").
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import date
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claudinho_voice.config import Config  # noqa: E402
from claudinho_voice.motores.piper import MotorPiper  # noqa: E402

MOLDES = [
    "Ontem eu mexi no {t} e funcionou direitinho.",
    "Preciso revisar o {t} antes de terminar o dia.",
]
"""Um termo por frase, cercado de português comum. Frase-veículo com o termo
repetido ou cheia de jargão aprovava grafia que caía no uso real."""


def _chave(texto: str) -> str:
    base = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in base if c.isalnum())


def _fatia(itens: list, parte: str | None) -> list:
    if not parte:
        return itens
    i, n = (int(x) for x in parte.split("/"))
    return itens[i - 1 :: n]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("candidatos")
    parser.add_argument("--voz", default=None, help="padrão: a voz da config")
    parser.add_argument("--parte", default=None, help="ex.: 1/2 para metade da lista")
    parser.add_argument("--saida", default="eval/resultados")
    parser.add_argument("--audio", default="eval/audio/pronuncia")
    args = parser.parse_args()

    candidatos = json.loads(Path(args.candidatos).read_text(encoding="utf-8"))
    termos = _fatia(sorted(candidatos), args.parte)
    voz = args.voz or Config.carregar().voz or "cadu"
    pasta_audio = Path(args.audio)
    pasta_audio.mkdir(parents=True, exist_ok=True)
    Path(args.saida).mkdir(parents=True, exist_ok=True)
    sufixo = f"-{args.parte.replace('/', 'de')}" if args.parte else ""
    destino = Path(args.saida) / f"pronuncia-{voz}-{date.today().isoformat()}{sufixo}.json"

    motor = MotorPiper()
    motor.carregar("pt", voz, 4)
    motor._fonemas_validos = {}  # mede a grafia sozinha, sem o léxico IPA por cima

    from faster_whisper import WhisperModel

    whisper = WhisperModel("small", device="cpu", compute_type="int8")

    def medir(texto: str, termo: str, rotulo: str) -> tuple[int, list[str]]:
        acertos = 0
        ouvidos = []
        for i, molde in enumerate(MOLDES):
            audio = motor.gerar(molde.format(t=texto))
            arquivo = pasta_audio / f"{_chave(termo)}_{_chave(rotulo)[:14]}_{i}.wav"
            sf.write(arquivo, audio, motor.sample_rate)
            segmentos, _ = whisper.transcribe(str(arquivo), language="pt", beam_size=5)
            ouvido = " ".join(s.text for s in segmentos).strip()
            ouvidos.append(ouvido)
            if _chave(termo) in _chave(ouvido):
                acertos += 1
        return acertos, ouvidos

    resultado = {
        "voz": voz,
        "data": date.today().isoformat(),
        "ja_certo": {},
        "vencedores": {},
        "sem_solucao": {},
    }
    print(f"voz: {voz} · {len(termos)} termos · {len(MOLDES)} frases cada\n", flush=True)
    for n, termo in enumerate(termos, 1):
        cru, ouvido_cru = medir(termo, termo, "cru")
        if cru == len(MOLDES):
            resultado["ja_certo"][termo] = ouvido_cru[0]
            print(f"[{n}/{len(termos)}] {termo:16} cru {cru}/2  já certo", flush=True)
            continue
        melhor = None
        detalhe = {"cru": {"acertos": cru, "ouvido": ouvido_cru}}
        for grafia in candidatos[termo]:
            acertos, ouvidos = medir(grafia, termo, grafia)
            detalhe[grafia] = {"acertos": acertos, "ouvido": ouvidos}
            if acertos > cru and (melhor is None or acertos > melhor[0]):
                melhor = (acertos, grafia)
        if melhor:
            resultado["vencedores"][termo] = {"grafia": melhor[1], "acertos": melhor[0], "cru": cru}
            print(f"[{n}/{len(termos)}] {termo:16} cru {cru}/2  ENTRA {melhor[1]!r} {melhor[0]}/2", flush=True)
        else:
            resultado["sem_solucao"][termo] = detalhe
            print(f"[{n}/{len(termos)}] {termo:16} cru {cru}/2  sem solução — ouvido: {ouvido_cru[0][:50]}", flush=True)
        destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")

    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\njá certo {len(resultado['ja_certo'])} · vencedores {len(resultado['vencedores'])}"
        f" · sem solução {len(resultado['sem_solucao'])}\n→ {destino}"
    )


if __name__ == "__main__":
    main()
