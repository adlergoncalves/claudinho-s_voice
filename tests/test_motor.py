"""Testes do motor que não dependem do modelo nem de placa de som.

O que interessa aqui é o controle: geração/cancelamento, pausa, pular e a
detecção de corte prematuro. A síntese em si é substituída por uma dublê.
"""

from __future__ import annotations

import numpy as np
import pytest

from claudinho_voice.config import Config
from claudinho_voice.motor import Motor


@pytest.fixture
def motor() -> Motor:
    """Motor com modelo e áudio substituídos por dublês.

    O ritmo (velocidade e aparo de silêncio) fica desligado: estes testes são
    sobre controle de fila e cancelamento, e o ritmo tem suíte própria.
    """
    m = Motor(
        Config(
            aquecimento="",
            pausa_entre_itens_s=0,
            palavras_por_minuto=0,
            aparar_silencio_das_bordas=False,
        )
    )
    m._modelo = object()  # impede carregar() de tentar baixar pesos
    m._voz = object()
    m.tocados: list[np.ndarray] = []

    # 24 kHz é o sample rate do Pocket; fixamos para não consultar o modelo
    type(m).sample_rate = property(lambda self: 24000)

    def tocar(audio, geracao):
        if not m._cancelado(geracao):
            m.tocados.append(audio)

    m._tocar = tocar
    return m


def _audio(segundos: float) -> np.ndarray:
    return np.zeros(int(24000 * segundos), dtype=np.float32)


# ------------------------------------------------- detecção de corte


def test_duracao_minima_cresce_com_o_texto(motor: Motor):
    curta = motor._duracao_minima_esperada("Oi.")
    longa = motor._duracao_minima_esperada("Uma frase bem mais longa do que a outra.")
    assert longa > curta > 0


def test_regenera_quando_a_frase_sai_cortada(motor: Motor):
    frase = "Uma organização pode ter múltiplos usuários com papéis distintos."
    tentativas = []

    def gerar(f, geracao):
        tentativas.append(f)
        # primeira tentativa sai cortada (0,3 s), a segunda vem completa
        yield _audio(0.3 if len(tentativas) == 1 else 4.0)

    motor._gerar_uma_vez = gerar
    pedacos = list(motor._gerar_frase(frase, geracao=1))

    assert len(tentativas) == 2, "deveria ter gerado de novo após o corte"
    assert sum(len(p) for p in pedacos) / 24000 == pytest.approx(4.0)


def test_desiste_apos_o_limite_de_tentativas(motor: Motor):
    frase = "Uma organização pode ter múltiplos usuários com papéis distintos."
    tentativas = []

    def gerar(f, geracao):
        tentativas.append(f)
        yield _audio(0.3)  # sempre cortada

    motor._gerar_uma_vez = gerar
    pedacos = list(motor._gerar_frase(frase, geracao=1))

    assert len(tentativas) == motor.TENTATIVAS
    assert pedacos, "na última tentativa fala o que tem, não descarta"


def test_nao_regenera_frase_que_veio_inteira(motor: Motor):
    tentativas = []

    def gerar(f, geracao):
        tentativas.append(f)
        yield _audio(4.0)

    motor._gerar_uma_vez = gerar
    list(motor._gerar_frase("Uma frase de tamanho normal para o teste.", geracao=1))
    assert len(tentativas) == 1


# ------------------------------------------------------- cancelamento


def test_geracao_antiga_e_cancelada_por_parar(motor: Motor):
    motor._geracao = 5
    motor.parar()
    assert motor._cancelado(5) is True
    assert motor._cancelado(6) is False, "o item novo precisa nascer válido"


def test_parar_limpa_o_estado_de_pausa(motor: Motor):
    motor.pausar()
    assert motor.estado().pausado is True
    motor.parar()
    assert motor.estado().pausado is False, (
        "sem isto uma leitura nova aparece como pausada sem estar"
    )


def test_pular_nao_invalida_a_geracao(motor: Motor):
    motor._geracao = 3
    motor.pular()
    assert motor._cancelado(3) is False, "pular abandona o item, não cancela a fila"


def test_retomar_desfaz_a_pausa(motor: Motor):
    motor.pausar()
    motor.retomar()
    assert motor.estado().pausado is False


# --------------------------------------------------------------- fila


def test_texto_sem_frase_nao_entra_na_fila(motor: Motor):
    assert motor.ler("   \n  ") == 0


def test_estado_inicial_e_ocioso(motor: Motor):
    e = motor.estado()
    assert e.lendo is False and e.itens_na_fila == 0


# ------------------------------------------------- teto de ritmo no motor


def test_teto_de_ritmo_freia_frase_rapida(motor: Motor):
    """Frase gerada acima do teto sai mais longa do que entrou."""
    motor.cfg.teto_ppm = 230.0
    frase = "uma duas três quatro cinco seis sete oito nove dez"  # 10 palavras
    # 10 palavras em 1,2 s = 500 ppm, muito acima do teto
    audio = np.ones(int(24000 * 1.2), dtype=np.float32) * 0.5

    ajustado = motor._ajustar_ritmo([audio], frase)

    assert len(ajustado[0]) > len(audio)


def test_teto_de_ritmo_nao_toca_frase_normal(motor: Motor):
    motor.cfg.teto_ppm = 230.0
    frase = "uma duas três quatro cinco seis sete oito nove dez"
    # 10 palavras em 3 s = 200 ppm, abaixo do teto
    audio = np.ones(int(24000 * 3.0), dtype=np.float32) * 0.5

    ajustado = motor._ajustar_ritmo([audio], frase)

    assert len(ajustado[0]) == len(audio)


def test_teto_desligado_deixa_tudo_passar(motor: Motor):
    motor.cfg.teto_ppm = 0
    frase = "uma duas três quatro cinco seis sete oito nove dez"
    audio = np.ones(int(24000 * 1.2), dtype=np.float32) * 0.5

    ajustado = motor._ajustar_ritmo([audio], frase)

    assert len(ajustado[0]) == len(audio)


# --------------------------------------------------- narração do trabalho


def test_item_de_narracao_vence():
    """Narração de trabalho tem validade: falar o passo antigo é pior que calar.

    Quando várias ferramentas rápidas se emendam, os textos saem mais depressa
    do que a fala acompanha. Sem validade a fila acumula e se ouve o que
    já passou.
    """
    from claudinho_voice.motor import Item

    item = Item(texto="olhando o hook", validade_s=8.0)

    assert item.vencido(agora=item.criado_em + 9.0)
    assert not item.vencido(agora=item.criado_em + 3.0)


def test_item_sem_validade_nunca_vence():
    """A resposta final não é perecível: ela espera a vez."""
    from claudinho_voice.motor import Item

    item = Item(texto="a resposta")

    assert not item.vencido(agora=item.criado_em + 3600)


def test_ler_aceita_validade(motor: Motor):
    """`ler` propaga a validade para o item enfileirado."""
    enfileirados = []
    motor._falar_item = lambda item: enfileirados.append(item)

    motor.ler("Olhando o hook.", validade_s=8.0)
    motor.iniciar()
    motor._fila.join()
    motor.desligar()

    assert enfileirados[0].validade_s == 8.0


def test_item_vencido_e_descartado_sem_falar(motor: Motor):
    """O laço pula o item que venceu enquanto esperava a vez."""
    from claudinho_voice.motor import Item

    falados = []
    motor._falar_item = lambda item: falados.append(item.texto)

    vencido = Item(texto="passo antigo", frases=["passo antigo"], validade_s=1.0)
    vencido.criado_em -= 10.0
    motor._fila.put(vencido)
    motor._fila.put(Item(texto="passo atual", frases=["passo atual"]))

    motor.iniciar()
    motor._fila.join()
    motor.desligar()

    assert falados == ["passo atual"]


# ------------------------------------------- navegação dentro da leitura


def test_avancar_pula_para_o_proximo_paragrafo():
    """Num documento de 263 frases, avançar tem de ser por bloco, não por item.

    `pular` abandonava o documento inteiro — inútil para navegar dentro dele.
    """
    from claudinho_voice.motor import proximo_paragrafo

    frases = ["a1", "a2¶", "b1", "b2", "b3¶", "c1"]

    assert proximo_paragrafo(frases, atual=0) == 2
    assert proximo_paragrafo(frases, atual=3) == 5
    assert proximo_paragrafo(frases, atual=5) is None


def test_voltar_vai_para_o_inicio_do_paragrafo_atual():
    """Voltar no meio de um bloco recomeça o bloco — como um leitor faria."""
    from claudinho_voice.motor import paragrafo_anterior

    frases = ["a1", "a2¶", "b1", "b2", "b3¶", "c1"]

    assert paragrafo_anterior(frases, atual=3) == 2
    assert paragrafo_anterior(frases, atual=2) == 0
    assert paragrafo_anterior(frases, atual=0) == 0


def test_navegar_preserva_o_documento_inteiro(motor: Motor):
    """Saltar não pode encolher o documento.

    Reenfileirar só o trecho restante fazia o total cair a cada salto (263 →
    259 → 258) e impedia voltar para antes do ponto de partida.
    """
    from claudinho_voice.motor import Item

    frases = [f"f{i}¶" for i in range(10)]
    motor._item_atual = Item(texto="doc", frases=list(frases), protegido=True)
    with motor._trava_estado:
        motor._estado.frase_atual = 3
        motor._estado.total_frases = len(frases)

    motor.navegar(adiante=True)
    item = motor._fila.get(timeout=1)

    assert len(item.frases) == 10, "o documento encolheu"
    assert item.inicio == 3
