"""Descobre qual sessão do Claude Code está chamando o ``cvoice``.

O Claude Code não expõe o id da sessão ao comando que ele executa. Mas cada
sessão escreve seu transcript em ``~/.claude/projects/<projeto>/<session_id>.jsonl``
e, no instante em que o Claude roda ``cvoice auto on``, esse arquivo acabou de
receber a chamada da ferramenta com esse mesmo comando. Então:

1. candidatos = transcripts modificados nos últimos segundos;
2. vence o que tem, nas últimas linhas, um ``tool_use`` cujo comando cita ``cvoice``;
3. sem confirmação, vale o mais recente (uma sessão só costuma estar ativa).

É heurística, mas cada passo é verificável e o pior caso (duas sessões falando
ao mesmo tempo no mesmo segundo) é raro o bastante para ser aceito.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

PASTA_PROJETOS = Path.home() / ".claude" / "projects"
JANELA_S = 120.0
LINHAS_FINAIS = 60


def _ultimas_linhas(caminho: Path, quantidade: int) -> list[str]:
    try:
        tamanho = caminho.stat().st_size
        with caminho.open("rb") as arquivo:
            arquivo.seek(max(0, tamanho - 200_000))
            bruto = arquivo.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return bruto.splitlines()[-quantidade:]


def _cita_cvoice(linhas: list[str]) -> bool:
    for linha in reversed(linhas):
        if "cvoice" not in linha:
            continue
        try:
            evento = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if evento.get("type") != "assistant":
            continue
        conteudo = (evento.get("message") or {}).get("content") or []
        for bloco in conteudo:
            if isinstance(bloco, dict) and bloco.get("type") == "tool_use":
                comando = json.dumps(bloco.get("input", {}), ensure_ascii=False)
                if "cvoice" in comando and "auto" in comando:
                    return True
    return False


def transcripts_recentes(janela_s: float = JANELA_S) -> list[Path]:
    agora = time.time()
    candidatos: list[tuple[float, Path]] = []
    if not PASTA_PROJETOS.exists():
        return []
    for caminho in PASTA_PROJETOS.glob("*/*.jsonl"):
        try:
            mtime = caminho.stat().st_mtime
        except OSError:
            continue
        if agora - mtime <= janela_s:
            candidatos.append((mtime, caminho))
    candidatos.sort(reverse=True)
    return [c for _, c in candidatos]


def sessao_atual() -> str | None:
    """Id da sessão do Claude Code que (muito provavelmente) está executando agora."""
    explicito = os.environ.get("CLAUDE_SESSION_ID")
    if explicito:
        return explicito
    recentes = transcripts_recentes()
    if not recentes:
        return None
    for caminho in recentes:
        if _cita_cvoice(_ultimas_linhas(caminho, LINHAS_FINAIS)):
            return caminho.stem
    return recentes[0].stem
