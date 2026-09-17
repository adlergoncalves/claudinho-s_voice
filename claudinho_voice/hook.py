"""Hook ``Stop`` do Claude Code: lê em voz alta a resposta que acabou de sair.

O Claude Code chama este script quando termina uma resposta, passando um JSON na
entrada padrão com ``session_id`` e o caminho do *transcript* da sessão. Se a
leitura automática estiver ligada **para essa sessão**, tiramos do transcript o
último bloco de texto do assistente e mandamos para o serviço.

Regras de ouro deste script:

* **nunca** falhar de forma barulhenta — um hook que quebra atrapalha a sessão;
* **nunca** demorar — se o serviço não estiver no ar, sobe-o em segundo plano e
  desiste desta leitura; a próxima resposta já sai falada;
* **custo zero** quando a sessão não tem leitura ligada: um ``stat`` e sai.

O formato do transcript não é contrato público da Anthropic. Toda a leitura dele
está isolada em :func:`ultima_resposta` para que uma mudança de formato só afete
um ponto.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def ultima_resposta(caminho_transcript: str) -> str:
    """Devolve o texto do último turno do assistente no transcript (JSONL).

    Cada linha é um evento. Interessam as do tipo ``assistant``, cujo conteúdo é
    uma lista de blocos; queremos apenas os blocos de texto, ignorando chamadas
    de ferramenta e raciocínio.
    """
    caminho = Path(caminho_transcript)
    if not caminho.exists():
        return ""

    ultima = ""
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
                if evento.get("type") != "assistant":
                    continue
                if evento.get("isSidechain"):
                    continue  # subagentes não são a resposta principal
                mensagem = evento.get("message") or {}
                conteudo = mensagem.get("content")
                if isinstance(conteudo, str):
                    texto = conteudo
                elif isinstance(conteudo, list):
                    texto = "\n\n".join(
                        bloco.get("text", "")
                        for bloco in conteudo
                        if isinstance(bloco, dict) and bloco.get("type") == "text"
                    )
                else:
                    texto = ""
                texto = texto.strip()
                if texto:
                    ultima = texto
    except OSError:
        return ""
    return ultima


def _registrar(etapa: str, detalhe: str = "") -> None:
    """Rastro do hook num arquivo próprio.

    O hook é silencioso por design, o que torna impossível saber se ele sequer
    foi chamado quando a voz some. Este rastro responde isso em uma linha.
    """
    try:
        import time

        from .config import PASTA_USUARIO

        caminho = PASTA_USUARIO / "hook.log"
        with caminho.open("a", encoding="utf-8") as arquivo:
            arquivo.write(f"{time.strftime('%H:%M:%S')} stop {etapa} {detalhe}\n")
    except Exception:
        pass


def main() -> int:
    try:
        _registrar("chamado")
        entrada = json.loads(sys.stdin.read() or "{}")
        session_id = str(entrada.get("session_id") or "")
        if not session_id:
            transcript = str(entrada.get("transcript_path") or "")
            session_id = Path(transcript).stem if transcript else ""

        from .config import sessao_ligada

        if not sessao_ligada(session_id):
            _registrar("saiu", f"sessao {session_id[:8]} sem auto")
            return 0  # desligado para esta sessão: sai antes de qualquer custo

        if entrada.get("stop_hook_active"):
            _registrar("saiu", "reentrada")
            return 0  # evita reentrada

        texto = ultima_resposta(entrada.get("transcript_path", ""))
        if not texto:
            _registrar("saiu", "sem texto no transcript")
            return 0

        # o hook PreToolUse já narra o que o Claude escreve antes de usar uma
        # ferramenta. Quando esse texto acaba sendo a resposta final, ele seria
        # falado duas vezes — a mesma frase, seguida. Aqui se pergunta o que já
        # foi narrado nesta sessão e, se bate, o turno sai calado.
        try:
            from .hook_trabalhando import _ultimo_falado, texto_novo_do_assistente

            _, uuid_atual = texto_novo_do_assistente(
                str(entrada.get("transcript_path") or ""), ""
            )
            if uuid_atual and uuid_atual == _ultimo_falado(session_id):
                _registrar("saiu", "ja narrado durante o turno")
                return 0
        except Exception:
            pass  # na dúvida, fala: repetir é melhor que emudecer

        from .config import Config

        cfg = Config.carregar()
        if len(texto) > cfg.max_caracteres_resposta:
            texto = texto[: cfg.max_caracteres_resposta] + "\n\nResposta truncada para leitura."

        from .cli import garantir_servico_silencioso

        if not garantir_servico_silencioso():
            _registrar("saiu", "servico fora do ar")
            return 0

        import httpx

        _registrar("enfileirando", f"{len(texto)} chars")
        httpx.post(
            f"http://{cfg.host}:{cfg.porta}/ler",
            json={
                "texto": texto,
                "titulo": "resposta",
                # sem prioridade: a resposta ESPERA a vez. Com prioridade, cada
                # texto novo do Claude cortava o anterior pela metade — e num
                # turno com várias mensagens isso é a fala inteira picotada.
                # Quem interrompe é o Adler, digitando (barge-in), não o Claude.
                "prioridade": False,
                "sessao": session_id,
            },
            timeout=3.0,
        )
    except Exception as erro:
        # silêncio proposital para a sessão, mas o rastro fica no arquivo
        _registrar("ERRO", f"{type(erro).__name__}: {erro}")
        return 0
    _registrar("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
