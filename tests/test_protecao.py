"""Leitura protegida: o que foi pedido de propósito não morre com o barge-in.

O bug que motivou isto: pediu-se "repete", a repetição começou, e
mandou "cade?" e a própria pergunta matou a fala que ele estava esperando.
"""

from __future__ import annotations

import numpy as np
import pytest

from claudinho_voice.config import Config
from claudinho_voice.motor import Motor


@pytest.fixture
def motor() -> Motor:
    m = Motor(
        Config(
            aquecimento="",
            pausa_entre_itens_s=0,
            palavras_por_minuto=0,
            aparar_silencio_das_bordas=False,
        )
    )
    m._modelo = object()
    m._voz = object()
    type(m).sample_rate = property(lambda self: 24000)
    m._tocar = lambda audio, geracao: None
    return m


def _preparar_leitura(m: Motor, protegido: bool) -> None:
    """Coloca o motor no estado de quem está lendo, sem depender do modelo."""
    with m._trava_estado:
        m._estado.lendo = True
        m._estado.protegido = protegido
    m._geracao = 5


def test_barge_in_para_leitura_comum(motor: Motor):
    _preparar_leitura(motor, protegido=False)
    motor.parar(respeitar_protegido=True)
    assert motor._cancelado(5) is True


def test_barge_in_nao_para_leitura_protegida(motor: Motor):
    _preparar_leitura(motor, protegido=True)
    motor.parar(respeitar_protegido=True)
    assert motor._cancelado(5) is False, (
        "quem pediu para repetir quer ouvir até o fim, mesmo digitando depois"
    )


def test_parar_explicito_para_ate_o_protegido(motor: Motor):
    _preparar_leitura(motor, protegido=True)
    motor.parar()  # sem respeitar_protegido: é o "para" que a pessoa pediu
    assert motor._cancelado(5) is True


def test_estado_expoe_protegido(motor: Motor):
    _preparar_leitura(motor, protegido=True)
    assert motor.estado().protegido is True


def test_protegido_volta_a_falso_no_fim(motor: Motor):
    from claudinho_voice.motor import Item

    motor._gerar_frase = lambda frase, geracao: iter([np.zeros(240, np.float32)])
    motor._falar_item(Item(texto="Oi.", frases=["Oi."], geracao=1, protegido=True))
    assert motor.estado().protegido is False
    assert motor.estado().lendo is False


def _capturar_item(motor: Motor, **kwargs):
    """Chama ler() sem deixar a thread de reprodução consumir a fila."""
    motor.iniciar = lambda: None  # type: ignore[method-assign]
    motor.ler("Um texto qualquer para ler agora.", **kwargs)
    return motor._fila.get_nowait()


def test_ler_marca_o_item_como_protegido(motor: Motor):
    assert _capturar_item(motor, protegido=True).protegido is True


def test_ler_sem_protecao_por_padrao(motor: Motor):
    assert _capturar_item(motor).protegido is False


def test_prioridade_nao_derruba_leitura_protegida(motor: Motor):
    """A resposta do Claude não pode matar a leitura que foi pedida.

    O artefato de 263 frases morreu na primeira resposta que chegou depois:
    `ler(prioridade=True)` parava tudo, inclusive o protegido. Quem pediu para
    ouvir um documento quer ouvi-lo até o fim — só "parar" explícito o cala.
    """
    from claudinho_voice.motor import Item

    protegido = Item(texto="o documento", frases=["o documento"], protegido=True)
    motor._fila.put(protegido)
    with motor._trava_estado:
        motor._estado.lendo = True
        motor._estado.protegido = True

    motor.ler("a resposta do Claude.", prioridade=True)

    assert motor._geracao_valida == 0, "a leitura protegida foi invalidada"
