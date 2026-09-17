"""Velocidade da fala, silêncio nas bordas e respiro entre parágrafos."""

from __future__ import annotations

import numpy as np
import pytest

from claudinho_voice.config import Config
from claudinho_voice.preparar import MARCA_PARAGRAFO, dividir_em_frases, preparar
from claudinho_voice.ritmo import (
    PALAVRAS_POR_MINUTO_MODELO,
    aparar_silencio,
    esticar,
    fator_para_velocidade,
)

SR = 24000


def _voz(segundos: float, freq: float = 120.0) -> np.ndarray:
    """Onda periódica com harmônicos: imita voz o bastante para medir tom."""
    t = np.linspace(0, segundos, int(SR * segundos), endpoint=False)
    onda = np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(2 * np.pi * freq * 2 * t)
    return (onda * 0.3).astype(np.float32)


def _tom(a: np.ndarray) -> float:
    a = a - a.mean()
    corr = np.correlate(a, a, mode="full")[len(a) - 1 :]
    lo, hi = SR // 400, SR // 70
    return SR / (lo + int(np.argmax(corr[lo:hi])))


# ------------------------------------------------------------- velocidade


def test_fator_para_velocidade():
    assert fator_para_velocidade(PALAVRAS_POR_MINUTO_MODELO) == pytest.approx(1.0)
    assert fator_para_velocidade(129) == pytest.approx(2.0, abs=0.01)
    assert fator_para_velocidade(0) == 1.0


def test_esticar_aumenta_a_duracao():
    a = _voz(1.0)
    esticado = esticar(a, 1.5, SR)
    assert len(esticado) / len(a) == pytest.approx(1.5, rel=0.12)


def test_esticar_preserva_o_tom():
    # é isso que separa WSOLA da reamostragem ingênua, que baixaria o tom junto
    a = _voz(1.5, freq=120.0)
    esticado = esticar(a, 1.7, SR)
    assert _tom(esticado) == pytest.approx(_tom(a), rel=0.12)


def test_reamostragem_ingenua_estragaria_o_tom():
    a = _voz(1.5, freq=120.0)
    n = int(len(a) * 1.7)
    ingenuo = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a)
    assert _tom(ingenuo) < _tom(a) * 0.8, "a reamostragem baixa o tom — por isso não a usamos"


def test_fator_um_devolve_o_mesmo_audio():
    a = _voz(1.0)
    assert esticar(a, 1.0, SR) is a


def test_audio_curto_demais_passa_intacto():
    a = _voz(0.05)
    assert esticar(a, 1.5, SR) is a


def test_esticado_nao_tem_estouro():
    a = _voz(1.0)
    assert np.max(np.abs(esticar(a, 1.7, SR))) <= 1.0


# ---------------------------------------------------------------- bordas


def test_apara_silencio_das_pontas():
    miolo = _voz(0.5)
    a = np.concatenate([np.zeros(SR // 2, np.float32), miolo, np.zeros(SR // 2, np.float32)])
    aparado = aparar_silencio(a, SR)
    assert len(aparado) < len(a)
    assert len(aparado) >= len(miolo)


def test_apara_deixa_margem():
    a = np.concatenate([np.zeros(SR // 2, np.float32), _voz(0.3)])
    aparado = aparar_silencio(a, SR, margem_s=0.04)
    assert len(aparado) > int(SR * 0.3), "a margem precisa sobreviver"


def test_audio_todo_silencioso_passa_intacto():
    a = np.zeros(SR, np.float32)
    assert len(aparar_silencio(a, SR)) == len(a)


def test_audio_vazio_nao_quebra():
    assert len(aparar_silencio(np.array([], np.float32), SR)) == 0


# ------------------------------------------------------------ parágrafos


def test_marca_a_ultima_frase_de_cada_paragrafo():
    frases = dividir_em_frases(
        "Primeira. Segunda.\n\nTerceira. Quarta.", marcar_paragrafos=True
    )
    assert frases[1].endswith(MARCA_PARAGRAFO)
    assert frases[3].endswith(MARCA_PARAGRAFO)
    assert not frases[0].endswith(MARCA_PARAGRAFO)


def test_sem_marcar_nao_ha_marca():
    frases = dividir_em_frases("Uma.\n\nOutra.", marcar_paragrafos=False)
    assert not any(MARCA_PARAGRAFO in f for f in frases)


def test_texto_de_um_paragrafo_so_marca_o_fim():
    frases = dividir_em_frases("Uma. Duas.", marcar_paragrafos=True)
    assert not any(MARCA_PARAGRAFO in f for f in frases)


def test_pipeline_marca_paragrafos():
    resultado = preparar("Primeiro parágrafo aqui.\n\nSegundo parágrafo aqui.", Config())
    assert any(f.endswith(MARCA_PARAGRAFO) for f in resultado.frases)
    assert MARCA_PARAGRAFO not in resultado.texto, "o texto exibido fica limpo"


# ------------------------------------------- teto de ritmo (normalização)


def test_fator_para_teto_freia_frase_rapida_demais():
    """Frase acima do teto é esticada só até o teto, não até um alvo fixo.

    Medido em 16/09/2026: a mesma frase sai entre 169 e 312 ppm no Pocket.
    Esticar tudo por um fator fixo arrastava as frases já lentas (foi por isso
    que 150 ppm soou câmera lenta); o teto só age em quem passou dele.
    """
    from claudinho_voice.ritmo import fator_para_teto

    # 312 ppm com teto de 230 → estica na razão 312/230
    assert fator_para_teto(312, 230) == pytest.approx(312 / 230, abs=0.01)


def test_fator_para_teto_nao_toca_frase_dentro_do_teto():
    from claudinho_voice.ritmo import fator_para_teto

    assert fator_para_teto(170, 230) == 1.0
    assert fator_para_teto(230, 230) == 1.0


def test_fator_para_teto_desligado_quando_teto_zero():
    from claudinho_voice.ritmo import fator_para_teto

    assert fator_para_teto(312, 0) == 1.0


def test_fator_para_teto_limita_o_esticamento_maximo():
    """Estimativa ruim não pode virar câmera lenta.

    Se a medida der um ppm absurdo (frase de uma palavra, silêncio mal aparado),
    o fator é limitado — melhor uma frase um pouco rápida do que uma arrastada.
    """
    from claudinho_voice.ritmo import FATOR_MAXIMO, fator_para_teto

    assert fator_para_teto(10_000, 230) == pytest.approx(FATOR_MAXIMO)


def test_ppm_medido_usa_palavras_e_duracao():
    from claudinho_voice.ritmo import ppm_medido

    # 10 palavras em 3 segundos = 200 ppm
    assert ppm_medido(10, 3.0) == pytest.approx(200.0)
    assert ppm_medido(10, 0.0) == 0.0
    assert ppm_medido(0, 3.0) == 0.0
