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


def _tem_pip(python: Path) -> bool:
    try:
        pronto = subprocess.run(
            [str(python), "-m", "pip", "--version"], capture_output=True, timeout=60
        )
        return pronto.returncode == 0
    except Exception:
        return False


def instalar_dependencias() -> bool:
    """Instala o projeto no venv. Repetir não reinstala o que já está lá."""
    python = _python_do_venv()
    if not python.exists():
        return False
    try:
        # Um venv feito pelo ``uv venv`` não traz pip, e aí todo o resto falha
        # com "No module named pip" — mensagem que não diz nada a quem instalou.
        # ``ensurepip`` resolve e não custa nada quando o pip já está lá.
        if not _tem_pip(python):
            subprocess.run(
                [str(python), "-m", "ensurepip", "--upgrade"],
                capture_output=True,
                timeout=300,
            )
            if not _tem_pip(python):
                print(
                    "o ambiente virtual não tem pip e não consegui instalá-lo; "
                    "apague a pasta .venv e rode o preparo de novo",
                    file=sys.stderr,
                )
                return False

        subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
            capture_output=True,
            timeout=600,
        )
        # O extra "painel" entra junto, e não por capricho: o painel é a única
        # interface do leitor, e o lançador dele roda com janela escondida —
        # sem pywebview o import falha calado, nada abre e nenhum erro aparece.
        subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", "-e", f"{RAIZ}[painel]"],
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


def tudo_pronto() -> bool:
    """A instalação já está inteira? Barato o bastante para chamar sempre.

    Checa disco, não importa módulos: é chamado do processo que ainda pode não
    conseguir importar nada do projeto.
    """
    if not venv_pronto():
        return False
    try:
        from .config import Config
        from .motores.piper import MotorPiper

        return MotorPiper.instalado(Config.carregar().voz)
    except Exception:
        return False


def preparar(verboso: bool = True, ao_andar=None) -> bool:
    """Deixa a instalação pronta para uso. Devolve se está tudo no lugar.

    ``ao_andar`` recebe cada etapa em uma linha, para quem quiser mostrar o
    progresso em outro lugar que não a saída padrão.
    """

    def diz(texto: str) -> None:
        if verboso:
            print(texto)
        if ao_andar:
            try:
                ao_andar(texto)
            except Exception:
                pass

    if not venv_pronto():
        diz("criando o ambiente virtual...")
        if not criar_venv():
            return False

    diz("instalando as dependências (pode demorar na primeira vez)...")
    if not instalar_dependencias():
        return False

    # A voz é baixada DENTRO do venv recém-criado, não aqui: este processo
    # roda no Python do sistema, que não tem httpx nem o resto — ele acabou de
    # instalar as dependências, mas não consegue usá-las sem reiniciar. Sem
    # isto o preparo terminava "com sucesso" e a voz nunca chegava.
    diz("baixando a voz (~63 MB, uma vez só)...")
    try:
        pronto = subprocess.run(
            [
                str(_python_do_venv()),
                "-c",
                "from claudinho_voice.preparar_ambiente import baixar_voz;"
                " raise SystemExit(0 if baixar_voz() else 1)",
            ],
            cwd=str(RAIZ),
            capture_output=True,
            timeout=1800,
        )
        if pronto.returncode != 0:
            print(pronto.stderr.decode("utf-8", "replace")[-400:], file=sys.stderr)
            return False
    except Exception as erro:
        print(f"não consegui baixar a voz: {erro}", file=sys.stderr)
        return False

    diz("pronto. Diga 'ativa a voz' no Claude Code, ou rode: cvoice testar")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if preparar() else 1)
