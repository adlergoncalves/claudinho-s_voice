"""Histórico do que foi falado — a base do 'repete'."""

from __future__ import annotations

import time

import pytest

from claudinho_voice import historico


@pytest.fixture(autouse=True)
def arquivo_temporario(tmp_path, monkeypatch):
    monkeypatch.setattr(historico, "ARQUIVO", tmp_path / "historico.json")


def test_registra_e_recupera_o_ultimo():
    historico.registrar("primeiro texto", "t1", ["primeiro texto."])
    historico.registrar("segundo texto", "t2", ["segundo texto."])
    item = historico.ultimo()
    assert item is not None
    assert item.texto == "segundo texto"
    assert item.titulo == "t2"


def test_sem_nada_falado_devolve_none():
    assert historico.ultimo() is None


def test_filtra_por_sessao():
    historico.registrar("da sessao A", "a", [], sessao="A")
    historico.registrar("da sessao B", "b", [], sessao="B")
    assert historico.ultimo("A").texto == "da sessao A"
    assert historico.ultimo("B").texto == "da sessao B"


def test_sessao_sem_registro_cai_no_global():
    historico.registrar("qualquer", "x", [], sessao="A")
    assert historico.ultimo("sessao-que-nao-falou").texto == "qualquer"


def test_trecho_final_pega_as_ultimas_frases():
    frases = ["Uma.", "Duas.", "Três.", "Quatro.", "Cinco."]
    item = historico.ItemFalado(texto="tudo", titulo="t", frases=frases)
    assert historico.trecho_final(item, 2) == "Quatro. Cinco."
    assert historico.trecho_final(item, 3) == "Três. Quatro. Cinco."


def test_trecho_final_sem_frases_devolve_o_texto():
    item = historico.ItemFalado(texto="texto inteiro", titulo="t", frases=[])
    assert historico.trecho_final(item, 3) == "texto inteiro"


def test_trecho_final_com_menos_frases_do_que_o_pedido():
    item = historico.ItemFalado(texto="x", titulo="t", frases=["Só uma."])
    assert historico.trecho_final(item, 5) == "Só uma."


def test_limita_o_tamanho_do_arquivo():
    for i in range(historico.MAX_ITENS + 15):
        historico.registrar(f"texto {i}", f"t{i}", [])
    assert len(historico._carregar()) == historico.MAX_ITENS
    assert historico.ultimo().texto == f"texto {historico.MAX_ITENS + 14}"


def test_idade_em_minutos():
    item = historico.ItemFalado(texto="x", titulo="t", quando=time.time() - 120)
    assert 1.9 < item.idade_min < 2.1


def test_arquivo_corrompido_nao_quebra(tmp_path):
    historico.ARQUIVO.write_text("{isto não é json", encoding="utf-8")
    assert historico.ultimo() is None
    historico.registrar("depois do erro", "t", [])
    assert historico.ultimo().texto == "depois do erro"


def test_ultimos_respeita_a_quantidade():
    for i in range(6):
        historico.registrar(f"t{i}", f"titulo{i}", [])
    assert [i.texto for i in historico.ultimos(2)] == ["t4", "t5"]
