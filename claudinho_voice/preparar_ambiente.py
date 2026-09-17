"""Preparo da instalação: ambiente virtual, dependências e voz.

Existe porque um plugin do Claude Code chega como código, não como programa
pronto: quem instala não vai criar venv nem baixar modelo na mão. A primeira
execução precisa resolver isso sozinha e uma vez só.

É deliberadamente conservador: nunca apaga nada, nunca reinstala o que já está
lá, e cada etapa pode ser repetida sem efeito colateral. Se algo falhar, diz o
que falhou em uma linha e devolve o controle — um leitor de voz que não
instalou é um aborrecimento, não um incidente.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from . import ambiente

RAIZ = ambiente.RAIZ
VENV = RAIZ / ".venv"


def venv_pronto() -> bool:
    return (VENV / "pyvenv.cfg").exists()


def _python_do_venv() -> Path:
    return VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def criar_venv() -> bool:
    """Cria o ambiente virtual do projeto. Idempotente."""
    if venv_pronto():
        return True
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(VENV)],
            check=True,
            capture_output=True,
            timeout=300,
        )
        return venv_pronto()
    except Exception as erro:
        print(f"não consegui criar o ambiente virtual: {erro}", file=sys.stderr)
        return False


def instalar_dependencias() -> bool:
    """Instala o projeto no venv. Repetir não reinstala o que já está lá."""
    python = _python_do_venv()
    if not python.exists():
        return False
    try:
        subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
            capture_output=True,
            timeout=600,
        )
        subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", "-e", str(RAIZ)],
            check=True,
            capture_output=True,
            timeout=1800,
        )
        return True
    except Exception as erro:
        print(f"não consegui instalar as dependências: {erro}", file=sys.stderr)
        return False


def voz_pronta(voz: str = "") -> bool:
    from .config import Config
    from .motores.piper import MotorPiper

    return MotorPiper.instalado(voz or Config.carregar().voz)


def baixar_voz(voz: str = "") -> bool:
    """Baixa os pesos da voz (~63 MB). Só na primeira vez."""
    from .config import Config
    from .motores.piper import MotorPiper

    voz = voz or Config.carregar().voz
    if MotorPiper.instalado(voz):
        return True
    try:
        MotorPiper.baixar(voz)
        return MotorPiper.instalado(voz)
    except Exception as erro:
        print(f"não consegui baixar a voz '{voz}': {erro}", file=sys.stderr)
        return False


def preparar(verboso: bool = True) -> bool:
    """Deixa a instalação pronta para uso. Devolve se está tudo no lugar."""

    def diz(texto: str) -> None:
        if verboso:
            print(texto)

    if not venv_pronto():
        diz("criando o ambiente virtual...")
        if not criar_venv():
            return False

    diz("instalando as dependências (pode demorar na primeira vez)...")
    if not instalar_dependencias():
        return False

    if not voz_pronta():
        diz("baixando a voz (~63 MB, uma vez só)...")
        if not baixar_voz():
            return False

    diz("pronto. Diga 'ativa a voz' no Claude Code, ou rode: cvoice testar")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if preparar() else 1)
