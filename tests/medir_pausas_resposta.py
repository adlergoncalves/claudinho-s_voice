"""Mede buracos e silêncio final usando a última resposta REAL desta sessão.

Uso: python tests/medir_pausas_resposta.py <transcript.jsonl>
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claudinho_voice.config import Config  # noqa: E402
from claudinho_voice.hook import ultima_resposta  # noqa: E402
from claudinho_voice.motor import Motor  # noqa: E402
from claudinho_voice.preparar import preparar  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logging.getLogger("pocket_tts").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


def silencio_final(audio: np.ndarray, sr: int, limiar: float = 0.01) -> float:
    idx = np.where(np.abs(audio) > limiar)[0]
    if len(idx) == 0:
        return len(audio) / sr
    return (len(audio) - idx[-1]) / sr


def resposta_mais_longa_recente(caminho: str, ultimas: int = 8) -> str:
    """A mais longa entre as últimas respostas: é a que expõe títulos curtos
    seguidos de parágrafos longos, o padrão que gera buraco."""
    import json

    textos: list[str] = []
    with open(caminho, encoding="utf-8", errors="replace") as arquivo:
        for linha in arquivo:
            try:
                evento = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if evento.get("type") != "assistant" or evento.get("isSidechain"):
                continue
            conteudo = (evento.get("message") or {}).get("content") or []
            texto = "\n\n".join(
                b.get("text", "") for b in conteudo if isinstance(b, dict) and b.get("type") == "text"
            ).strip()
            if texto:
                textos.append(texto)
    return max(textos[-ultimas:], key=len) if textos else ""


def main() -> None:
    texto = resposta_mais_longa_recente(sys.argv[1]) if len(sys.argv) > 2 else ultima_resposta(sys.argv[1])
    prep = preparar(texto, Config())
    print(f"frases: {len(prep.frases)} | tamanhos: {[len(f) for f in prep.frases]}")

    m = Motor(Config(pausa_entre_itens_s=0))
    m.carregar()

    estado = {"fim": 0.0, "inicio": 0.0, "audio": 0.0}
    buracos: list[tuple[int, float]] = []
    silencios: list[float] = []
    frase_atual = {"n": 0}
    acumulado: list[np.ndarray] = []

    def tocar_falso(audio: np.ndarray, geracao: int) -> None:
        agora = time.perf_counter()
        n = m.estado().frase_atual
        if n != frase_atual["n"]:
            if acumulado:
                silencios.append(silencio_final(np.concatenate(acumulado), m.sample_rate))
            acumulado.clear()
            frase_atual["n"] = n
        acumulado.append(audio)
        if estado["inicio"] == 0.0:
            estado["inicio"] = agora
            logging.info("PRIMEIRO SOM apos %.2fs", agora - t0)
        elif estado["fim"] and agora - estado["fim"] > 0.15:
            buraco = agora - estado["fim"]
            buracos.append((n, buraco))
            logging.info("  buraco de %.2fs antes da frase %d (%d chars)", buraco, n, len(prep.frases[n - 1]))
        dur = len(audio) / m.sample_rate
        estado["audio"] += dur
        time.sleep(dur)
        estado["fim"] = time.perf_counter()

    m._tocar = tocar_falso  # type: ignore[method-assign]
    t0 = time.perf_counter()
    m.ler(texto, titulo="resposta")
    time.sleep(0.5)
    while m.estado().lendo or m.estado().itens_na_fila:
        time.sleep(0.2)
    if acumulado:
        silencios.append(silencio_final(np.concatenate(acumulado), m.sample_rate))
    total = time.perf_counter() - t0

    print()
    print(f"audio: {estado['audio']:.1f}s | relogio: {total:.1f}s | primeiro som: {estado['inicio']-t0:.2f}s")
    print(f"buracos > 0,15s: {len(buracos)} | maior: {max((b for _, b in buracos), default=0):.2f}s | soma: {sum(b for _, b in buracos):.2f}s")
    print(f"silencio no fim das frases: mediana {np.median(silencios):.2f}s | max {max(silencios):.2f}s | soma {sum(silencios):.1f}s")
    m.desligar()


if __name__ == "__main__":
    main()
