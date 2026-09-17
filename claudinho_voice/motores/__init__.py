"""Motores de voz intercambiáveis.

O resto do projeto — preparação de texto, fila, hooks, histórico, ritmo — não
sabe qual modelo fala. Tudo que ele precisa está em :class:`MotorDeVoz`:
carregar, dizer o sample rate, gerar uma frase (de preferência em pedaços) e
listar as vozes disponíveis.

**Qualquer** classe que cumpra esse contrato serve, venha de onde vier. Os
motores que acompanham o projeto são só os que já foram testados aqui; um
motor novo não exige mudança neste arquivo. Para usar um, aponte o caminho
completo na configuração:

    {"motor": "meupacote.meumotor:MotorXTTS", "voz": "Ana Florence"}

Os nomes curtos abaixo são atalhos para os motores que vêm junto. A resolução
tenta, em ordem: atalho conhecido → ``pacote.modulo:Classe`` → um motor
registrado por outro pacote no entry point ``claudinho_voice.motores``.
"""

from __future__ import annotations

import importlib
import logging

from .base import MotorDeVoz, VozIndisponivel

log = logging.getLogger(__name__)

ATALHOS: dict[str, str] = {
    "pocket": "claudinho_voice.motores.pocket:MotorPocket",
    "kokoro": "claudinho_voice.motores.kokoro:MotorKokoro",
    "piper": "claudinho_voice.motores.piper:MotorPiper",
}
"""Apelidos para os motores que acompanham o projeto. Não é uma lista fechada:
qualquer caminho ``modulo:Classe`` é aceito diretamente."""

GRUPO_ENTRY_POINT = "claudinho_voice.motores"
"""Um pacote instalado pode registrar motores próprios aqui, sem tocar neste
arquivo. No pyproject dele:

    [project.entry-points."claudinho_voice.motores"]
    xtts = "meupacote.xtts:MotorXTTS"
"""


def _de_entry_points() -> dict[str, str]:
    try:
        from importlib.metadata import entry_points

        return {
            ep.name: ep.value for ep in entry_points(group=GRUPO_ENTRY_POINT)
        }
    except Exception:  # ambiente sem metadados não pode derrubar o leitor
        return {}


def motores_disponiveis() -> dict[str, str]:
    """Nome curto → caminho, juntando os embutidos e os registrados por terceiros."""
    return {**ATALHOS, **_de_entry_points()}


def resolver(nome: str) -> type[MotorDeVoz]:
    """Devolve a classe do motor a partir de um atalho ou de ``modulo:Classe``."""
    caminho = motores_disponiveis().get(nome, nome)
    if ":" not in caminho:
        raise VozIndisponivel(
            f"motor '{nome}' desconhecido. Use um atalho ({', '.join(motores_disponiveis())}) "
            "ou o caminho completo, como 'meupacote.motor:MinhaClasse'."
        )
    modulo, _, classe = caminho.partition(":")
    try:
        alvo = getattr(importlib.import_module(modulo), classe)
    except (ImportError, AttributeError) as erro:
        raise VozIndisponivel(f"não consegui carregar o motor '{nome}': {erro}") from erro
    if not issubclass(alvo, MotorDeVoz):
        raise VozIndisponivel(
            f"'{caminho}' não implementa MotorDeVoz — falta herdar da classe base"
        )
    return alvo


def criar(nome: str, **opcoes) -> MotorDeVoz:
    """Instancia um motor pelo nome ou caminho, importando só o que for usado."""
    return resolver(nome)(**opcoes)


__all__ = [
    "ATALHOS",
    "MotorDeVoz",
    "VozIndisponivel",
    "criar",
    "motores_disponiveis",
    "resolver",
]
