"""Kokoro-82M (ONNX) — alternativa com pronúncia pt-BR exata.

Medido no bake-off de 16/09/2026: 0% de erro de palavra contra 9% do Pocket,
RTF 0,35, nunca corta frase. O custo é o timbre, mais sintético, e a latência
do primeiro som (~3,7 s contra 0,1 s), porque não tem streaming de verdade.

Duas particularidades que valem código:

* O fonemizador é por idioma. Termo em inglês no meio do português sai errado
  ("ApplicationUser" vira "a pique ionosa"), então fonemizamos por segmento:
  português no fonemizador pt-BR, termo inglês no en-US, tudo concatenado.
* Vozes podem ser misturadas por média ponderada dos embeddings, o que cria
  timbres que não existem no catálogo ("pm_alex+am_puck" fica mais jovem).

Os pesos não vêm com o pacote: baixe-os uma vez em
``~/.claudinho-voice/modelos/kokoro/``.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import numpy as np

from ..config import PASTA_USUARIO
from .base import MotorDeVoz, VozIndisponivel

log = logging.getLogger(__name__)

PASTA_MODELO = PASTA_USUARIO / "modelos" / "kokoro"
ARQUIVO_MODELO = PASTA_MODELO / "kokoro-v1.0.onnx"
ARQUIVO_VOZES = PASTA_MODELO / "voices-v1.0.bin"
URL_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

VOZES_PT = ["pf_dora", "pm_alex", "pm_santa"]
"""As três vozes que o catálogo marca como português."""

VOZES_RECOMENDADAS = ["af_heart", "af_bella", "af_kore", "pf_dora"]
"""Vozes medidas lendo português em frase longa, 16/09/2026.

Todas com **0% de erro de palavra** (Whisper small) e RTF entre 0,36 e 0,40 —
contra 16% do Pocket/rafael no mesmo corpus. O prefixo `af_` diz onde a voz foi
gravada, não que idioma ela fala: quem define a pronúncia é o fonemizador, e
ele roda em pt-BR antes de a voz entrar.

A medição que importou foi a de **frase longa**. Num corpus de frases curtas
isoladas o Pocket parecia melhor, e foi assim que ele acabou escolhido de
manhã — em texto de verdade ele embola, e o número aparece."""

_RE_TERMO_INGLES = re.compile(r"\b(?:[a-z]+[A-Z]\w*|[A-Z][a-z]+(?:[A-Z]\w*)+)\b")
_RE_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class MotorKokoro(MotorDeVoz):
    nome = "kokoro"
    corta_frases = False

    def __init__(self) -> None:
        self._modelo = None
        self._voz_id = ""
        self._estilo = None

    # ------------------------------------------------------------ instalação

    @staticmethod
    def instalado() -> bool:
        return ARQUIVO_MODELO.exists() and ARQUIVO_VOZES.exists()

    @staticmethod
    def baixar() -> None:
        """Baixa os pesos (~350 MB). Roda uma vez."""
        import httpx

        from ..config import preparar_ambiente_ssl

        preparar_ambiente_ssl()
        PASTA_MODELO.mkdir(parents=True, exist_ok=True)
        for destino in (ARQUIVO_MODELO, ARQUIVO_VOZES):
            if destino.exists():
                continue
            url = f"{URL_BASE}/{destino.name}"
            log.info("baixando %s", url)
            with httpx.stream("GET", url, follow_redirects=True, timeout=600) as r:
                r.raise_for_status()
                with destino.open("wb") as arquivo:
                    for bloco in r.iter_bytes(1 << 20):
                        arquivo.write(bloco)

    # --------------------------------------------------------------- carga

    def carregar(self, idioma: str, voz: str, threads: int) -> None:
        if self._modelo is not None:
            return
        if not self.instalado():
            raise VozIndisponivel(
                f"pesos do Kokoro não encontrados em {PASTA_MODELO}. "
                "Rode: cvoice motor kokoro --instalar"
            )
        import os

        os.environ.setdefault("OMP_NUM_THREADS", str(threads))
        try:
            from kokoro_onnx import Kokoro
        except ImportError as erro:
            raise VozIndisponivel(
                "pacote kokoro-onnx não instalado. Rode: uv pip install kokoro-onnx"
            ) from erro

        inicio = time.perf_counter()
        self._modelo = Kokoro(str(ARQUIVO_MODELO), str(ARQUIVO_VOZES))
        self._voz_id = voz or VOZES_PT[0]
        self._estilo = self._resolver_voz(self._voz_id)
        log.info("Kokoro carregado: %s em %.1fs", self._voz_id, time.perf_counter() - inicio)

    def _resolver_voz(self, voz: str):
        """Aceita uma voz ou uma mistura: ``pm_alex+am_puck`` ou ``pm_alex:0.6+am_puck:0.4``."""
        if "+" not in voz:
            if voz not in self._modelo.get_voices():
                raise VozIndisponivel(f"voz '{voz}' não existe no Kokoro")
            return voz

        pesos: dict[str, float] = {}
        for parte in voz.split("+"):
            nome, _, peso = parte.partition(":")
            nome = nome.strip()
            if nome not in self._modelo.get_voices():
                raise VozIndisponivel(f"voz '{nome}' não existe no Kokoro")
            pesos[nome] = float(peso) if peso else 1.0
        total = sum(pesos.values()) or 1.0
        estilo = sum(self._modelo.get_voice_style(n) * p for n, p in pesos.items())
        return estilo / total

    # ---------------------------------------------------------------- fala

    @property
    def sample_rate(self) -> int:
        return 24000

    def _fonemizar(self, texto: str) -> str:
        """Fonemiza por segmento: inglês no en-US, o resto em pt-BR.

        Sem isto, ``ApplicationUser`` sai como "a pique ionosa".
        """
        partes: list[str] = []
        fim = 0
        for achado in _RE_TERMO_INGLES.finditer(texto):
            antes = texto[fim : achado.start()]
            if antes.strip():
                partes.append(self._modelo.tokenizer.phonemize(antes, lang="pt-br"))
            termo = _RE_CAMEL.sub(" ", achado.group(0))
            partes.append(self._modelo.tokenizer.phonemize(termo, lang="en-us"))
            fim = achado.end()
        resto = texto[fim:]
        if resto.strip():
            partes.append(self._modelo.tokenizer.phonemize(resto, lang="pt-br"))
        return " ".join(p.strip() for p in partes if p.strip())

    def gerar(self, texto: str) -> np.ndarray:
        fonemas = self._fonemizar(texto)
        amostras, _ = self._modelo.create(
            fonemas, voice=self._estilo, lang="pt-br", is_phonemes=True
        )
        return np.asarray(amostras, dtype=np.float32)

    def vozes(self) -> list[str]:
        if self._modelo is None:
            return list(VOZES_PT)
        return sorted(self._modelo.get_voices())

    def descrever(self) -> str:
        return "Kokoro-82M (ONNX), pronúncia pt-BR exata"
