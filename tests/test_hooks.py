"""Testes dos dois hooks do Claude Code.

Ambos precisam ser silenciosos e baratos quando a sessão não está em modo voz:
um hook que fala fora de hora, ou que demora, atrapalha a sessão inteira.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from claudinho_voice import config, hook_prompt
from claudinho_voice.hook import ultima_resposta

RAIZ = Path(__file__).resolve().parent.parent


def _rodar(modulo: str, entrada: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", modulo],
        input=json.dumps(entrada),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=RAIZ,
        timeout=60,
    )


@pytest.fixture
def sessoes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PASTA_SESSOES", tmp_path / "sessoes")
    return tmp_path


# ------------------------------------------------- hook do prompt (modo voz)


def test_injeta_contrato_quando_a_sessao_esta_ligada(sessoes, capsys):
    config.definir_sessao("s1", True)
    hook_prompt.main_com_entrada({"session_id": "s1"})
    saida = capsys.readouterr().out
    assert "MODO VOZ LIGADO" in saida
    assert "como quem fala" in saida


def test_nao_injeta_nada_quando_desligada(sessoes, capsys):
    hook_prompt.main_com_entrada({"session_id": "s1"})
    assert capsys.readouterr().out == ""


def test_nao_vaza_para_outra_sessao(sessoes, capsys):
    config.definir_sessao("s1", True)
    hook_prompt.main_com_entrada({"session_id": "s2"})
    assert capsys.readouterr().out == ""


def test_usa_o_transcript_quando_falta_session_id(sessoes, capsys):
    config.definir_sessao("abc123", True)
    hook_prompt.main_com_entrada({"transcript_path": "/x/y/abc123.jsonl"})
    assert "MODO VOZ" in capsys.readouterr().out


def test_entrada_invalida_nao_quebra(sessoes):
    resultado = _rodar("claudinho_voice.hook_prompt", {})
    assert resultado.returncode == 0


def test_contrato_proibe_o_que_nao_se_fala():
    texto = hook_prompt.CONTRATO
    for proibido in ("títulos", "listas", "tabelas", "negrito", "emojis"):
        assert proibido in texto
    assert "```" in texto, "precisa explicar o escape por bloco de código"
    assert "uma por vez" in texto, "perguntas em série não funcionam por voz"


# --------------------------------------------------- hook da resposta (Stop)


def test_stop_nao_le_quando_a_sessao_esta_desligada(sessoes):
    resultado = _rodar("claudinho_voice.hook", {"session_id": "nao-ligada"})
    assert resultado.returncode == 0
    assert resultado.stdout == ""


def test_stop_ignora_reentrada(sessoes):
    resultado = _rodar(
        "claudinho_voice.hook", {"session_id": "x", "stop_hook_active": True}
    )
    assert resultado.returncode == 0


def test_ultima_resposta_pega_o_ultimo_texto(tmp_path):
    t = tmp_path / "s.jsonl"
    eventos = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "primeira"}]}},
        {"type": "user", "message": {"content": "pergunta"}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "última"}]}},
    ]
    t.write_text("\n".join(json.dumps(e) for e in eventos), encoding="utf-8")
    assert ultima_resposta(str(t)) == "última"


def test_ultima_resposta_ignora_subagente(tmp_path):
    t = tmp_path / "s.jsonl"
    eventos = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "principal"}]}},
        {
            "type": "assistant",
            "isSidechain": True,
            "message": {"content": [{"type": "text", "text": "do subagente"}]},
        },
    ]
    t.write_text("\n".join(json.dumps(e) for e in eventos), encoding="utf-8")
    assert ultima_resposta(str(t)) == "principal"


def test_ultima_resposta_com_arquivo_inexistente():
    assert ultima_resposta("/caminho/que/nao/existe.jsonl") == ""


def test_ultima_resposta_tolera_linha_corrompida(tmp_path):
    t = tmp_path / "s.jsonl"
    t.write_text(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"ok"}]}}\n'
        "{lixo que não é json\n",
        encoding="utf-8",
    )
    assert ultima_resposta(str(t)) == "ok"


# ------------------------------------------- narração: texto do transcript


def _linha_assistente(texto: str, uuid: str = "u1") -> str:
    import json as _json

    return _json.dumps(
        {
            "type": "assistant",
            "uuid": uuid,
            "message": {"content": [{"type": "text", "text": texto}]},
        }
    )


def test_texto_novo_do_assistente(tmp_path):
    """Pega o último texto que o assistente escreveu antes de chamar a ferramenta."""
    from claudinho_voice.hook_trabalhando import texto_novo_do_assistente

    t = tmp_path / "t.jsonl"
    t.write_text(
        _linha_assistente("primeiro", "a") + "\n" + _linha_assistente("Olhando o hook.", "b"),
        encoding="utf-8",
    )

    texto, uuid = texto_novo_do_assistente(str(t), ja_falado="a")

    assert texto == "Olhando o hook."
    assert uuid == "b"


def test_texto_ja_falado_nao_repete(tmp_path):
    """Várias ferramentas seguidas sem texto novo: não fala de novo."""
    from claudinho_voice.hook_trabalhando import texto_novo_do_assistente

    t = tmp_path / "t.jsonl"
    t.write_text(_linha_assistente("Olhando o hook.", "b"), encoding="utf-8")

    texto, uuid = texto_novo_do_assistente(str(t), ja_falado="b")

    assert texto == ""


def test_transcript_ausente_nao_quebra():
    from claudinho_voice.hook_trabalhando import texto_novo_do_assistente

    assert texto_novo_do_assistente("nao-existe.jsonl", ja_falado="") == ("", "")
