# -*- coding: utf-8 -*-
"""Banca de comparação entre motores de voz.

Serve para decidir troca de motor com número, não com impressão. Roda o mesmo
corpus em cada motor e mede o que importa para um leitor em streaming:

* **primeiro áudio** — quanto tempo até sair o primeiro som. É o que o ouvido
  sente como "demorou pra começar"; o Pocket fica em ~0,12 s.
* **RTF** — segundos de processamento por segundo de fala. Acima de 1 o motor
  não acompanha a leitura contínua em CPU.
* **ritmo (ppm)** — palavras por minuto e a variação entre gerações, que é o
  que faz a fala soar apressada.
* **carga** — tempo até o modelo ficar pronto, pago uma vez por serviço.

Gera também os wav de cada motor lado a lado, porque timbre não se decide por
métrica — a decisão final é de ouvido.

Uso::

    python eval/comparar_motores.py pocket kokoro
    python eval/comparar_motores.py pocket --voz rafael --repeticoes 3
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claudinho_voice.config import Config  # noqa: E402
from claudinho_voice.motores import criar  # noqa: E402
from claudinho_voice.ritmo import ppm_medido  # noqa: E402

CORPUS = [
    "O serviço está de pé.",
    "A leitura automática está ligada nesta sessão.",
    "O hook Stop enfileirou a resposta e o serviço começou a ler normalmente.",
    "A velocidade natural da voz foi medida em duzentas e cinquenta palavras "
    "por minuto, que é o ritmo cru do modelo.",
    "Quando o texto tem muitas frases curtas seguidas, a pausa entre elas "
    "domina o tempo total e a leitura parece apressada, mesmo que cada frase "
    "isolada esteja no mesmo ritmo de sempre.",
]
"""Frases de 21 a 181 caracteres: a faixa real de uma resposta falada."""


def medir(nome: str, voz: str, idioma: str, threads: int, repeticoes: int, saida: Path):
    print(f"\n{'=' * 70}\nMOTOR: {nome}  (voz={voz or 'padrão'})\n{'=' * 70}", flush=True)

    try:
        motor = criar(nome)
    except Exception as erro:
        print(f"  NÃO CARREGOU: {erro}")
        return None

    inicio = time.perf_counter()
    try:
        motor.carregar(idioma, voz, threads)
    except Exception as erro:
        print(f"  NÃO CARREGOU: {erro}")
        return None
    carga = time.perf_counter() - inicio
    sr = motor.sample_rate
    print(f"  carga: {carga:.1f}s · sample_rate: {sr} · {motor.descrever()}", flush=True)

    primeiros, rtfs, ppms = [], [], []
    saida.mkdir(parents=True, exist_ok=True)

    for indice, frase in enumerate(CORPUS):
        for repeticao in range(repeticoes):
            t0 = time.perf_counter()
            primeiro = None
            pedacos = []
            for pedaco in motor.gerar_em_pedacos(frase):
                if primeiro is None:
                    primeiro = time.perf_counter() - t0
                pedacos.append(np.asarray(pedaco, dtype=np.float32).squeeze())
            total = time.perf_counter() - t0

            audio = np.concatenate(pedacos) if pedacos else np.zeros(0, np.float32)
            duracao = len(audio) / sr
            if duracao <= 0:
                print(f"  [{indice}] geração vazia")
                continue

            primeiros.append(primeiro or total)
            rtfs.append(total / duracao)
            ppms.append(ppm_medido(len(frase.split()), duracao))

            if repeticao == 0:
                try:
                    import soundfile as sf

                    sf.write(saida / f"{nome}-{indice}.wav", audio, sr)
                except Exception:
                    pass

        print(
            f"  [{indice}] {len(frase):3}ch  1º áudio {primeiros[-1]:.2f}s  "
            f"RTF {rtfs[-1]:.2f}  {ppms[-1]:.0f} ppm",
            flush=True,
        )

    if not rtfs:
        return None

    variacao = max(ppms) / min(ppms)
    print(
        f"\n  RESUMO {nome}: 1º áudio {statistics.median(primeiros):.2f}s · "
        f"RTF {statistics.median(rtfs):.2f} · ppm {statistics.median(ppms):.0f} "
        f"(variação {variacao:.2f}x) · carga {carga:.0f}s"
    )
    print(f"  wavs em {saida}")
    return {
        "motor": nome,
        "primeiro_audio": statistics.median(primeiros),
        "rtf": statistics.median(rtfs),
        "ppm": statistics.median(ppms),
        "variacao": variacao,
        "carga": carga,
    }


def main() -> int:
    cfg = Config.carregar()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("motores", nargs="+", help="atalhos ou modulo:Classe")
    p.add_argument("--voz", default="")
    p.add_argument("--idioma", default=cfg.idioma)
    p.add_argument("--threads", type=int, default=cfg.threads)
    p.add_argument("--repeticoes", type=int, default=3)
    p.add_argument("--saida", type=Path, default=Path(__file__).parent / "audio")
    args = p.parse_args()

    resultados = []
    for nome in args.motores:
        voz = args.voz or (cfg.voz if nome == cfg.motor else "")
        r = medir(nome, voz, args.idioma, args.threads, args.repeticoes, args.saida / nome)
        if r:
            resultados.append(r)

    if len(resultados) > 1:
        print(f"\n{'=' * 70}\nCOMPARATIVO\n{'=' * 70}")
        print(f"{'motor':<14}{'1º áudio':>10}{'RTF':>8}{'ppm':>8}{'variação':>11}{'carga':>9}")
        for r in resultados:
            print(
                f"{r['motor']:<14}{r['primeiro_audio']:>9.2f}s{r['rtf']:>8.2f}"
                f"{r['ppm']:>8.0f}{r['variacao']:>10.2f}x{r['carga']:>8.0f}s"
            )
        print("\nRTF acima de 1,0 não acompanha leitura contínua em CPU.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
