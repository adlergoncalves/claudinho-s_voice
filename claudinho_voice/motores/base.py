"""Contrato que todo motor de voz precisa cumprir."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

import numpy as np


class VozIndisponivel(RuntimeError):
    """Motor inexistente, voz desconhecida ou modelo que não carregou."""


class MotorDeVoz(ABC):
    """Fala um texto curto e devolve áudio mono em float32.

    O consumidor (``motor.py``) cuida de fila, cancelamento, ritmo e validação
    de corte. Aqui só interessa transformar frase em som.

    Para escrever um motor novo — XTTS, MOSS, uma API, o que for — basta herdar
    daqui e implementar os quatro métodos abstratos. Nada mais no projeto
    precisa mudar; o motor é escolhido por configuração::

        class MotorXTTS(MotorDeVoz):
            nome = "xtts"

            def carregar(self, idioma, voz, threads): ...
            @property
            def sample_rate(self): return 24000
            def gerar(self, texto): return audio_float32
            def vozes(self): return ["Ana Florence", ...]
    """

    nome: str = ""
    """Identificador usado na configuração."""

    corta_frases: bool = False
    """True quando o modelo às vezes encerra a geração cedo e engole o fim da
    frase. Liga a validação por duração esperada no consumidor — que custa
    regeração, então não se liga à toa."""

    ritmo_nativo: bool = False
    """True quando o motor sabe alongar a própria fala na geração.

    Nesses casos o consumidor **não** estica o áudio depois: esticar por WSOLA
    cancela fase e deixa a voz metálica (medido: pico cai de 1,00 para 0,67).
    O motor recebe ``teto_ppm`` em :meth:`definir_ritmo` e se vira."""

    def definir_ritmo(self, teto_ppm: float) -> None:
        """Informa o teto de palavras por minuto ao motor com ritmo nativo.

        O padrão ignora — só quem declara ``ritmo_nativo`` precisa disto."""

    @abstractmethod
    def carregar(self, idioma: str, voz: str, threads: int) -> None:
        """Carrega modelo e voz. Deve ser idempotente."""

    @property
    @abstractmethod
    def sample_rate(self) -> int: ...

    @abstractmethod
    def gerar(self, texto: str) -> np.ndarray:
        """Áudio completo da frase."""

    def gerar_em_pedacos(self, texto: str) -> Iterator[np.ndarray]:
        """Áudio em pedaços, para começar a falar antes do fim da geração.

        O padrão devolve tudo de uma vez; motores com streaming nativo
        sobrescrevem."""
        yield self.gerar(texto)

    @abstractmethod
    def vozes(self) -> list[str]:
        """Vozes disponíveis para o idioma carregado."""

    def descrever(self) -> str:
        return self.nome
