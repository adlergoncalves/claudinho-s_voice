"""Ponto de entrada dos hooks quando o projeto roda como plugin do Claude Code.

O Claude Code chama isto de um diretório qualquer, com o Python do sistema e
sem o ambiente do projeto montado. Três coisas precisam acontecer antes de
qualquer import nosso:

1. achar a raiz do plugin (é o pai desta pasta) e pô-la no caminho de busca;
2. usar os pacotes do ``.venv`` se houver um, para não exigir instalação global;
3. sair calado se o ambiente ainda não existir — quem prepara é o ``cvoice
   ativar``, síncrono e falante; um hook mudo instalando coisas em segundo
   plano concorreria com ele no mesmo ``.venv`` e falharia sem deixar rastro.

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


HOOKS = {
    "stop": "claudinho_voice.hook",
    "prompt": "claudinho_voice.hook_prompt",
    "trabalhando": "claudinho_voice.hook_trabalhando",
}


def _preparar_agora() -> int:
    """Prepara a instalação aqui e agora, mostrando o progresso.

    É o único ponto de entrada que funciona antes de existir um venv: o
    ``cvoice`` só nasce depois do preparo, e quem instala o plugin precisa de
    alguma porta para bater na primeira vez.
    """
    # acento na saída, mesmo por pipe: sem isto o progresso sai "depend?ncias"
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    _preparar_caminho()
    from claudinho_voice.preparar_ambiente import preparar

    return 0 if preparar() else 1


def main() -> int:
    qual = sys.argv[1] if len(sys.argv) > 1 else ""

    # preparo explícito: síncrono e falante, ao contrário dos hooks
    if qual == "preparar":
        return _preparar_agora()

    modulo = HOOKS.get(qual)
    if not modulo:
        return 0

    try:
        _preparar_caminho()

        # instalação nova: sem venv, nada do projeto importa. Sai calado — o
        # preparo é do `cvoice ativar`, nunca daqui (ver docstring do módulo).
        if not (RAIZ / ".venv" / "pyvenv.cfg").exists():
            return 0

        import importlib

        return importlib.import_module(modulo).main()
    except Exception:
        # ambiente ainda não preparado, dependência faltando, o que for:
        # o hook sai calado e a sessão do Claude Code segue normal
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
