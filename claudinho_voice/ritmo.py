"""Ritmo da fala: velocidade e silêncio nas bordas.

Medido no Pocket/rafael: a voz sai a ~258 palavras por minuto, quase o dobro
do confortável (locutor de audiolivro fica em 150, conversa normal em 130), e
cada frase traz ~0,23 s de silêncio colado no fim.

Reamostrar o áudio para deixá-lo mais lento também baixa o tom, e a voz vira
gravação arrastada. A solução é esticar o tempo sem tocar no tom: WSOLA, que
sobrepõe janelas curtas alinhadas pela correlação. É rápido o bastante para
rodar entre a geração e o alto-falante — alguns milissegundos por frase.
"""

from __future__ import annotations

import numpy as np

PALAVRAS_POR_MINUTO_MODELO = 258.0
"""Velocidade natural do Pocket/rafael, medida em 16/09/2026."""


def esticar(audio: np.ndarray, fator: float, sample_rate: int) -> np.ndarray:
    """Estica (fator > 1) ou encolhe (fator < 1) o tempo, preservando o tom.

    ``fator`` 1.3 deixa a fala 30% mais longa, ou seja, mais devagar.
    Implementa WSOLA: janelas de ~40 ms com 50% de sobreposição, cada nova
    janela procurada numa vizinhança para casar a fase com a anterior. Sem essa
    busca (SOLA ingênuo) a voz ganha um tremido metálico.
    """
    if abs(fator - 1.0) < 0.01 or len(audio) < sample_rate // 10:
        return audio

    janela = int(sample_rate * 0.040)  # 40 ms
    salto_saida = janela // 2
    salto_entrada = int(salto_saida / fator)
    busca = int(sample_rate * 0.008)  # ±8 ms para alinhar a fase

    if salto_entrada < 1:
        return audio

    envelope = np.hanning(janela * 2).astype(np.float32)
    subida, descida = envelope[:janela], envelope[janela:]

    tamanho = int(len(audio) * fator) + janela * 2
    saida = np.zeros(tamanho, dtype=np.float32)
    normalizacao = np.zeros(tamanho, dtype=np.float32)

    pos_entrada = 0
    pos_saida = 0
    anterior: np.ndarray | None = None

    while pos_entrada + janela + busca < len(audio) and pos_saida + janela < tamanho:
        inicio = pos_entrada
        if anterior is not None and busca > 0:
            # procura, na vizinhança, o trecho que melhor continua o anterior
            lo = max(0, pos_entrada - busca)
            hi = min(len(audio) - janela, pos_entrada + busca)
            if hi > lo:
                candidatos = np.lib.stride_tricks.sliding_window_view(
                    audio[lo : hi + janela], janela
                )
                correlacao = candidatos @ anterior
                inicio = lo + int(np.argmax(correlacao))

        trecho = audio[inicio : inicio + janela].astype(np.float32)
        if len(trecho) < janela:
            break

        saida[pos_saida : pos_saida + janela] += trecho * subida
        normalizacao[pos_saida : pos_saida + janela] += subida
        if pos_saida + janela * 2 <= tamanho:
            saida[pos_saida + janela : pos_saida + janela * 2] += trecho * descida
            normalizacao[pos_saida + janela : pos_saida + janela * 2] += descida

        anterior = audio[inicio + salto_saida : inicio + salto_saida + janela].astype(
            np.float32
        )
        if len(anterior) < janela:
            break

        pos_entrada += salto_entrada
        pos_saida += salto_saida

    fim = pos_saida + janela
    saida = saida[:fim]
    normalizacao = normalizacao[:fim]
    normalizacao[normalizacao < 1e-6] = 1.0
    return (saida / normalizacao).astype(np.float32)


def fator_para_velocidade(palavras_por_minuto: float) -> float:
    """Converte a velocidade desejada no fator de esticamento."""
    if palavras_por_minuto <= 0:
        return 1.0
    return PALAVRAS_POR_MINUTO_MODELO / palavras_por_minuto


def aparar_silencio(
    audio: np.ndarray, sample_rate: int, limiar: float = 0.012, margem_s: float = 0.04
) -> np.ndarray:
    """Tira o silêncio das bordas, deixando uma margem curta.

    O silêncio que o modelo devolve no fim de cada frase soma com a pausa que a
    gente insere; aparando aqui, a pausa entre frases passa a ser só a nossa e
    fica previsível.
    """
    if len(audio) == 0:
        return audio
    forte = np.abs(audio) > limiar
    if not forte.any():
        return audio
    margem = int(sample_rate * margem_s)
    inicio = max(0, int(np.argmax(forte)) - margem)
    fim = min(len(audio), len(audio) - int(np.argmax(forte[::-1])) + margem)
    return audio[inicio:fim]


TETO_PADRAO_PPM = 180.0
"""Teto de ritmo. Acima disto a frase soa apressada.

Medido em 16/09/2026 sobre o Pocket/rafael: a mesma frase sai entre 169 e
312 palavras por minuto, 2,5x de variação de ponta a ponta. A média fica em
196, e o ritmo natural fica em torno de 250 — acima do confortável.

Calibrado em 180 sobre texto real: a variação cai de 1,56x para 1,04x e a
leitura fica 8% mais longa. Medido também que o tamanho da frase NÃO muda o
ritmo do Pocket (242 a 270 ppm de 60 a 216 caracteres), então quebrar frase
não resolveria — o teto resolve.
"""

FATOR_MAXIMO = 1.6
"""Limite de esticamento por frase.

A estimativa de ppm erra em frase de uma ou duas palavras (o ataque e a queda
dominam a duração). Sem limite, um ppm absurdo viraria câmera lenta — que foi
exatamente o defeito da velocidade fixa. Melhor uma frase rápida demais do que
uma arrastada.
"""


def ppm_medido(palavras: int, duracao_s: float) -> float:
    """Palavras por minuto de um trecho já gerado."""
    if palavras <= 0 or duracao_s <= 0:
        return 0.0
    return palavras / (duracao_s / 60.0)


def fator_para_teto(ppm: float, teto: float = TETO_PADRAO_PPM) -> float:
    """Fator de esticamento que traz ``ppm`` para o ``teto``, se passou dele.

    Diferente de :func:`fator_para_velocidade`, que mira todas as frases num
    alvo único, aqui só quem está acima do teto é freado — e apenas até o teto.
    Frase no ritmo normal volta com 1.0 e não é tocada.
    """
    if teto <= 0 or ppm <= 0 or ppm <= teto:
        return 1.0
    return min(ppm / teto, FATOR_MAXIMO)
