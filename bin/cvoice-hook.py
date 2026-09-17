"""Ponto de entrada dos hooks quando o projeto roda como plugin do Claude Code.

O Claude Code chama isto de um diretório qualquer, com o Python do sistema e
sem o ambiente do projeto montado. Três coisas precisam acontecer antes de
qualquer import nosso:

1. achar a raiz do plugin (é o pai desta pasta) e pô-la no caminho de busca;
2. usar os pacotes do ``.venv`` se houver um, para não exigir instalação global;
3. preparar o ambiente na primeira execução, se ainda não existir.

Regra de ouro herdada dos hooks: **nunca** falhar de forma barulhenta e nunca
demorar. Qualquer problema aqui vira saída silenciosa — um leitor de voz que
não fala é um aborrecimento; um hook que quebra atrapalha a sessão inteira.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _preparar_caminho() -> None:
    """Põe a raiz do plugin e o site-packages do venv no caminho de busca."""
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))

    venv = RAIZ / ".venv"
    if not (venv / "pyvenv.cfg").exists():
        return

    libs = venv / "Lib" / "site-packages"
    if not libs.exists():  # Linux/macOS
        candidatos = sorted((venv / "lib").glob("python*/site-packages"))
        libs = candidatos[0] if candidatos else libs
    if libs.exists() and str(libs) not in sys.path:
        sys.path.insert(0, str(libs))


MARCA_DE_PREPARO = RAIZ / ".preparando"


def _preparar_em_segundo_plano() -> None:
    """Dispara a preparação da instalação e devolve o controle na hora.

    Numa instalação nova não há ambiente virtual nem pesos de voz, e criar os
    dois leva minutos. O hook não pode esperar por isso — ele roda a cada
    ferramenta e precisa devolver em milissegundos. Então solta o preparo em
    segundo plano e sai: esta leitura se perde, as próximas funcionam.

    A marca no disco evita que cada hook do turno dispare um preparo novo.
    """
    if MARCA_DE_PREPARO.exists():
        return
    try:
        import subprocess
        import time

        MARCA_DE_PREPARO.write_text(str(time.time()), encoding="utf-8")
        criacao = 0
        if sys.platform == "win32":
            criacao = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        subprocess.Popen(
            [sys.executable, "-m", "claudinho_voice.preparar_ambiente"],
            cwd=str(RAIZ),
            creationflags=criacao,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception:
        pass


HOOKS = {
    "stop": "claudinho_voice.hook",
    "prompt": "claudinho_voice.hook_prompt",
    "trabalhando": "claudinho_voice.hook_trabalhando",
}


def main() -> int:
    qual = sys.argv[1] if len(sys.argv) > 1 else ""
    modulo = HOOKS.get(qual)
    if not modulo:
        return 0

    try:
        _preparar_caminho()

        # instalação nova: sem venv, nada do projeto importa. Prepara e sai.
        if not (RAIZ / ".venv" / "pyvenv.cfg").exists():
            _preparar_em_segundo_plano()
            return 0

        import importlib

        return importlib.import_module(modulo).main()
    except Exception:
        # ambiente ainda não preparado, dependência faltando, o que for:
        # o hook sai calado e a sessão do Claude Code segue normal
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
