"""Hook ``PreToolUse``: fala uma frase de espera enquanto o Claude trabalha.

Numa conversa por voz, ficar mudo por trinta segundos parece travamento. Este
hook roda antes de cada ferramenta e, se a sessão está em modo voz e já passou
tempo suficiente desde a última mensagem, pede ao serviço uma frase curta.

Quem decide se vale falar é o serviço (ele sabe se algo está tocando e quando
falou por último); aqui só medimos há quanto tempo o turno começou.

O relógio do turno é um arquivo por sessão, tocado pelo hook de prompt quando
a mensagem chega. Precisa ser barato: este hook roda antes de *toda* chamada
de ferramenta.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from .config import PASTA_USUARIO

PASTA_TURNOS = PASTA_USUARIO / "turnos"


def marcar_inicio_do_turno(session_id: str) -> None:
    """Chamado pelo hook de prompt: zera o relógio desta sessão."""
    if not session_id:
        return
    try:
        PASTA_TURNOS.mkdir(parents=True, exist_ok=True)
        (PASTA_TURNOS / _seguro(session_id)).write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def segundos_no_turno(session_id: str) -> float:
    try:
        bruto = (PASTA_TURNOS / _seguro(session_id)).read_text(encoding="utf-8")
        return time.time() - float(bruto)
    except (OSError, ValueError):
        return 0.0


def _seguro(session_id: str) -> str:
    return "".join(c for c in session_id if c.isalnum() or c in "-_")


# ------------------------------------------------- narração do que está sendo feito


def texto_novo_do_assistente(caminho_transcript: str, ja_falado: str) -> tuple[str, str]:
    """Último texto que o assistente escreveu, se ainda não tiver sido falado.

    O hook roda **antes** da ferramenta, então o que está no fim do transcript é
    a frase que o Claude acabou de escrever para anunciar o que vai fazer. É
    isso que interessa ouvir — bem mais útil que "deixa eu ver aqui".

    Devolve ``("", "")`` quando não há texto novo: várias ferramentas seguidas
    sem nada escrito no meio não devem virar repetição.
    """
    caminho = Path(caminho_transcript)
    if not caminho.exists():
        return "", ""

    ultimo_texto = ""
    ultimo_uuid = ""
    try:
        with caminho.open(encoding="utf-8", errors="replace") as arquivo:
            for linha in arquivo:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    evento = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                if evento.get("type") != "assistant" or evento.get("isSidechain"):
                    continue
                blocos = (evento.get("message") or {}).get("content")
                if not isinstance(blocos, list):
                    continue
                texto = " ".join(
                    b.get("text", "")
                    for b in blocos
                    if isinstance(b, dict) and b.get("type") == "text"
                ).strip()
                if texto:
                    ultimo_texto = texto
                    ultimo_uuid = str(evento.get("uuid") or "")
    except OSError:
        return "", ""

    if not ultimo_texto or ultimo_uuid == ja_falado:
        return "", ""
    return ultimo_texto, ultimo_uuid


def _ultimo_falado(session_id: str) -> str:
    try:
        return (PASTA_TURNOS / (_seguro(session_id) + ".falado")).read_text(encoding="utf-8")
    except OSError:
        return ""


def _marcar_falado(session_id: str, uuid: str) -> None:
    try:
        PASTA_TURNOS.mkdir(parents=True, exist_ok=True)
        (PASTA_TURNOS / (_seguro(session_id) + ".falado")).write_text(uuid, encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    try:
        entrada = json.loads(sys.stdin.read() or "{}")
        session_id = str(entrada.get("session_id") or "")
        if not session_id:
            transcript = str(entrada.get("transcript_path") or "")
            session_id = Path(transcript).stem if transcript else ""

        from .config import sessao_ligada

        if not sessao_ligada(session_id):
            return 0

        esperando = segundos_no_turno(session_id)
        if esperando <= 0:
            return 0

        import httpx

        from .config import Config

        cfg = Config.carregar()

        # o que o Claude acabou de escrever vale mais que "deixa eu ver aqui"
        texto, uuid = texto_novo_do_assistente(
            str(entrada.get("transcript_path") or ""), _ultimo_falado(session_id)
        )
        if texto:
            _marcar_falado(session_id, uuid)
            httpx.post(
                f"http://{cfg.host}:{cfg.porta}/narrar",
                json={"texto": texto},
                timeout=1.5,
            )
            return 0

        httpx.post(
            f"http://{cfg.host}:{cfg.porta}/preencher",
            json={"segundos_esperando": esperando},
            timeout=1.5,
        )
    except Exception:
        return 0  # nunca atrapalhar a execução da ferramenta
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
