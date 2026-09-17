"""Pocket TTS (Kyutai) — o motor padrão.

100M parâmetros, streaming nativo, voz natural em português. Roda a ~4x o
tempo real em 4 núcleos. Defeito conhecido: em cerca de 20% das gerações
encerra cedo e devolve ~0,3 s de áudio, por isso ``corta_frases``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator

import numpy as np

from .base import MotorDeVoz, VozIndisponivel

log = logging.getLogger(__name__)

VOZES = [
    "rafael", "charles", "anna", "vera", "mary", "alba", "jean", "marius",
    "michael", "paul", "cosette", "eve", "george", "javert",
]
"""As 14 vozes que falam português razoavelmente. O catálogo tem mais, mas o
sotaque das outras destoa."""


class MotorPocket(MotorDeVoz):
    nome = "pocket"
    corta_frases = True

    def __init__(self) -> None:
        self._modelo = None
        self._voz = None

    def carregar(self, idioma: str, voz: str, threads: int) -> None:
        if self._modelo is not None:
            return
        import torch
        from pocket_tts import TTSModel

        from ..config import preparar_ambiente_ssl

        preparar_ambiente_ssl()
        torch.set_num_threads(threads)
        inicio = time.perf_counter()
        try:
            self._modelo = TTSModel.load_model(language=idioma)
            self._voz = self._modelo.get_state_for_audio_prompt(voz)
        except Exception as erro:
            raise VozIndisponivel(f"Pocket não carregou ({idioma}/{voz}): {erro}") from erro
        log.info(
            "Pocket carregado: %s / %s em %.1fs", idioma, voz, time.perf_counter() - inicio
        )

    @property
    def sample_rate(self) -> int:
        return self._modelo.sample_rate

    def gerar(self, texto: str) -> np.ndarray:
        return self._modelo.generate_audio(self._voz, texto).numpy().squeeze().astype(np.float32)

    def gerar_em_pedacos(self, texto: str) -> Iterator[np.ndarray]:
        for pedaco in self._modelo.generate_audio_stream(self._voz, texto):
            yield pedaco.numpy().squeeze().astype(np.float32)

    def vozes(self) -> list[str]:
        return list(VOZES)

    def descrever(self) -> str:
        return "Pocket TTS (Kyutai), streaming nativo"
