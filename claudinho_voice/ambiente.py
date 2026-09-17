"""Descoberta do ambiente: onde o projeto está e qual Python usar.

Nada aqui pode assumir um caminho de instalação. O leitor precisa funcionar
igual quando é clonado numa pasta qualquer, instalado como pacote (``pip
install``) ou distribuído como plugin do Claude Code — e os hooks são lançados
pelo Claude Code, de um diretório que não é o do projeto.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACOTE = Path(__file__).resolve().parent
RAIZ = PACOTE.parent
"""Raiz do projeto. Num clone é a pasta com o ``pyproject.toml``; instalado
como pacote é o ``site-packages``, e aí nada de venv será encontrado — o
caminho de reserva assume."""


def _venv_do_projeto() -> Path | None:
    """O ``.venv`` ao lado do projeto, se existir.

    Procura na raiz e um nível acima: o plugin do Claude Code instala o pacote
    dentro de uma pasta própria, com o ambiente virtual do lado.
    """
    for base in (RAIZ, RAIZ.parent):
        venv = base / ".venv"
        if (venv / "pyvenv.cfg").exists():
            return venv
    return None


def _python_base_do_venv(venv: Path, nome: str) -> Path | None:
    """O interpretador real por trás de um venv, lido do ``pyvenv.cfg``.

    Num venv gerido pelo ``uv``, o ``pythonw.exe`` do ``Scripts/`` **não é um
    Python**: é um lançador que chama o ``python.exe`` base — com console, que
    aparece na barra de tarefas. O ``home`` do ``pyvenv.cfg`` aponta para o
    interpretador de verdade.
    """
    try:
        texto = (venv / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for linha in texto.splitlines():
        if linha.lower().startswith("home"):
            candidato = Path(linha.split("=", 1)[1].strip()) / nome
            return candidato if candidato.exists() else None
    return None


def executavel(sem_console: bool = False) -> str:
    """Python a usar para lançar um processo nosso.

    Com ``sem_console``, devolve o interpretador que não abre janela preta —
    necessário no Windows para o serviço e para o painel. Fora do Windows a
    distinção não existe e os dois caminhos coincidem.
    """
    nome = "pythonw.exe" if (sem_console and sys.platform == "win32") else None

    if nome:
        venv = _venv_do_projeto()
        if venv:
            base = _python_base_do_venv(venv, nome)
            if base:
                return str(base)
            do_venv = venv / "Scripts" / nome
            if do_venv.exists():
                return str(do_venv)
        ao_lado = Path(sys.executable).with_name(nome)
        if ao_lado.exists():
            return str(ao_lado)

    return sys.executable


def diretorio_de_trabalho() -> str:
    """Onde lançar os processos do projeto.

    Precisa ser um diretório de onde ``claudinho_voice`` seja importável. Num
    clone é a raiz; instalado como pacote, o ``site-packages`` já está no
    caminho de busca e a raiz serve do mesmo jeito.
    """
    return str(RAIZ)


def opcoes_de_processo() -> dict:
    """Argumentos de ``subprocess.Popen`` para um processo de fundo e calado.

    ``CREATE_NO_WINDOW`` sozinho não basta quando o Windows Terminal é o
    terminal padrão do sistema: ele intercepta o console e mostra uma janela
    preta vazia. ``SW_HIDE`` fecha essa porta.
    """
    import subprocess

    # o pythonw base (fora do venv) não enxerga os pacotes instalados: sem
    # VIRTUAL_ENV e PYTHONPATH, o serviço morre no primeiro import
    env = dict(os.environ)
    venv = _venv_do_projeto()
    if venv:
        env["VIRTUAL_ENV"] = str(venv)
        libs = venv / "Lib" / "site-packages"
        if not libs.exists():  # Linux/macOS
            candidatos = sorted((venv / "lib").glob("python*/site-packages"))
            libs = candidatos[0] if candidatos else libs
        if libs.exists():
            anterior = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(libs) + (os.pathsep + anterior if anterior else "")

    opcoes: dict = {
        "cwd": diretorio_de_trabalho(),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        opcoes["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        )
        inicio = subprocess.STARTUPINFO()
        inicio.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        inicio.wShowWindow = subprocess.SW_HIDE
        opcoes["startupinfo"] = inicio
    return opcoes


def pasta_de_dados() -> Path:
    """Onde ficam config, modelos, histórico e logs.

    Fora do projeto de propósito: atualizar ou reinstalar o código não pode
    apagar as vozes baixadas nem a configuração. Como plugin do Claude Code,
    ``CLAUDE_PLUGIN_DATA`` aponta para a pasta persistente do próprio plugin.
    """
    do_plugin = os.environ.get("CLAUDE_PLUGIN_DATA")
    if do_plugin:
        return Path(do_plugin)
    return Path.home() / ".claudinho-voice"
