"""Detecção da sessão atual e conversão de HTML."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from claudinho_voice import config, sessao
from claudinho_voice.html_para_texto import html_para_markdown, parece_html
from claudinho_voice.preparar import preparar


# ------------------------------------------------------------- sessão


def _transcript(pasta: Path, session_id: str, comando: str | None, idade_s: float = 0) -> Path:
    projeto = pasta / "c--projeto"
    projeto.mkdir(parents=True, exist_ok=True)
    caminho = projeto / f"{session_id}.jsonl"
    eventos = [{"type": "user", "message": {"role": "user", "content": "oi"}}]
    if comando:
        eventos.append(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "name": "Bash", "input": {"command": comando}}],
                },
            }
        )
    caminho.write_text("\n".join(json.dumps(e) for e in eventos) + "\n", encoding="utf-8")
    if idade_s:
        antigo = time.time() - idade_s
        import os

        os.utime(caminho, (antigo, antigo))
    return caminho


@pytest.fixture
def projetos(tmp_path, monkeypatch):
    monkeypatch.setattr(sessao, "PASTA_PROJETOS", tmp_path)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    return tmp_path


def test_escolhe_a_sessao_que_chamou_o_cvoice(projetos):
    _transcript(projetos, "outra-sessao", comando="git status")
    _transcript(projetos, "sessao-certa", comando='"C:/x/cvoice.exe" auto on')
    # a "outra" foi tocada por último, mas quem citou cvoice vence
    time.sleep(0.05)
    _transcript(projetos, "outra-sessao", comando="git status")
    assert sessao.sessao_atual() == "sessao-certa"


def test_sem_citacao_vale_a_mais_recente(projetos):
    _transcript(projetos, "velha", comando=None, idade_s=30)
    _transcript(projetos, "nova", comando=None)
    assert sessao.sessao_atual() == "nova"


def test_ignora_transcripts_fora_da_janela(projetos):
    _transcript(projetos, "muito-velha", comando=None, idade_s=3600)
    assert sessao.sessao_atual() is None


def test_variavel_de_ambiente_tem_prioridade(projetos, monkeypatch):
    _transcript(projetos, "qualquer", comando=None)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "explicita")
    assert sessao.sessao_atual() == "explicita"


def test_flag_por_sessao(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PASTA_SESSOES", tmp_path / "sessoes")
    config.definir_sessao("abc", True)
    assert config.sessao_ligada("abc") is True
    assert config.sessao_ligada("outra") is False, "ligar numa sessão não vaza para outra"
    config.definir_sessao("abc", False)
    assert config.sessao_ligada("abc") is False


def test_desligar_todas(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PASTA_SESSOES", tmp_path / "sessoes")
    config.definir_sessao("a", True)
    config.definir_sessao("b", True)
    assert config.desligar_todas_as_sessoes() == 2
    assert config.sessoes_ligadas() == []


def test_id_de_sessao_e_saneado(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PASTA_SESSOES", tmp_path / "sessoes")
    config.definir_sessao("../../fora", True)
    assert (tmp_path / "sessoes" / "fora").exists()


# --------------------------------------------------------------- HTML


HTML = """<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-width">
<link rel="stylesheet" href="x.css"><title>Plano de Voz</title>
<style>body{color:red}</style><script>alert(1)</script></head>
<body>
<h1>Plano</h1>
<p>Primeiro par&aacute;grafo com <b>negrito</b> e <a href="x">link</a>.</p>
<ul><li>Item um</li><li>Item dois</li></ul>
<ol><li>Passo A</li><li>Passo B</li></ol>
<table><tr><th>Motor</th><th>RTF</th></tr><tr><td>Pocket</td><td>0,25</td></tr></table>
<pre>x = 1
y = 2</pre>
<p>Fim.</p>
</body></html>"""


def test_html_vira_markdown_falavel():
    md, titulo = html_para_markdown(HTML)
    assert titulo == "Plano de Voz"
    assert "alert" not in md and "color:red" not in md
    assert "# Plano" in md
    assert "Primeiro parágrafo com negrito e link." in md
    assert "- Item um" in md and "- Item dois" in md
    assert "1. Passo A" in md and "2. Passo B" in md
    assert "| Motor | RTF |" in md and "| Pocket | 0,25 |" in md
    assert "```" in md and "x = 1" in md


def test_html_passa_pelo_preparador_inteiro():
    md, _ = html_para_markdown(HTML)
    texto = preparar(md, config.Config()).texto
    assert "Tabela com uma linha" in texto
    assert "bloco de código" in texto and "x = 1" not in texto
    assert "<" not in texto and "|" not in texto


def test_detecta_html():
    assert parece_html(HTML)
    assert parece_html("  <div><p>oi</p></div>")
    assert not parece_html("# Título\n\nTexto normal em markdown.")


def test_volume_fica_entre_zero_e_um():
    """O painel manda volume de um controle deslizante: precisa ser limitado."""
    from claudinho_voice.servico import limitar_volume

    assert limitar_volume(0.5) == 0.5
    assert limitar_volume(1.8) == 1.0
    assert limitar_volume(-0.3) == 0.0


def test_ajustes_aceita_so_o_que_conhece():
    """O painel manda só os campos que mexeu; o resto fica como está."""
    from claudinho_voice.servico import campos_ajustaveis

    assert "motor" in campos_ajustaveis()
    assert "voz" in campos_ajustaveis()
    assert "ler_codigo" in campos_ajustaveis()
    assert "host" not in campos_ajustaveis(), "endereço não se muda pela janela"


def test_troca_de_voz_pede_reinicio():
    """Voz é carregada uma vez: trocar exige recarregar o modelo."""
    from claudinho_voice.servico import exige_reinicio

    assert exige_reinicio({"voz": "jeff"})
    assert not exige_reinicio({"velocidade": 150})
