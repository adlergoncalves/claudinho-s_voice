"""A troca de motor é por configuração, não por código.

O teste que importa aqui é o do motor de terceiro: uma classe escrita fora do
projeto, apontada por caminho na config, tem de funcionar sem tocar em nada.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator

import numpy as np
import pytest

from claudinho_voice import motores
from claudinho_voice.config import Config
from claudinho_voice.motores import MotorDeVoz, VozIndisponivel, criar, resolver


# ------------------------------------------------------- motor de terceiro


class MotorFalso(MotorDeVoz):
    """O que alguém de fora escreveria para plugar um modelo novo."""

    nome = "falso"
    corta_frases = False

    def __init__(self) -> None:
        self.carregado_com: tuple | None = None

    def carregar(self, idioma: str, voz: str, threads: int) -> None:
        self.carregado_com = (idioma, voz, threads)

    @property
    def sample_rate(self) -> int:
        return 24000

    def gerar(self, texto: str) -> np.ndarray:
        return np.zeros(int(24000 * 0.05 * len(texto.split())), dtype=np.float32)

    def vozes(self) -> list[str]:
        return ["voz-a", "voz-b"]


@pytest.fixture
def modulo_externo(monkeypatch):
    """Simula um pacote instalado que traz o próprio motor."""
    modulo = types.ModuleType("pacote_de_terceiro")
    modulo.MeuMotor = MotorFalso
    monkeypatch.setitem(sys.modules, "pacote_de_terceiro", modulo)
    return modulo


def test_resolve_motor_de_terceiro_por_caminho(modulo_externo):
    assert resolver("pacote_de_terceiro:MeuMotor") is MotorFalso


def test_cria_e_carrega_motor_de_terceiro(modulo_externo):
    motor = criar("pacote_de_terceiro:MeuMotor")
    motor.carregar("portuguese", "voz-a", 4)
    assert motor.carregado_com == ("portuguese", "voz-a", 4)
    assert motor.sample_rate == 24000


def test_motor_de_terceiro_gera_audio(modulo_externo):
    motor = criar("pacote_de_terceiro:MeuMotor")
    audio = motor.gerar("uma frase de teste")
    assert isinstance(audio, np.ndarray) and audio.dtype == np.float32


def test_gerar_em_pedacos_tem_padrao(modulo_externo):
    """Quem não tem streaming não precisa implementar nada."""
    motor = criar("pacote_de_terceiro:MeuMotor")
    pedacos = list(motor.gerar_em_pedacos("uma frase"))
    assert len(pedacos) == 1


# ----------------------------------------------------------------- atalhos


def test_atalhos_apontam_para_caminhos_validos():
    for nome, caminho in motores.ATALHOS.items():
        assert ":" in caminho, f"atalho {nome} mal formado"


def test_disponiveis_inclui_os_embutidos():
    disponiveis = motores.motores_disponiveis()
    assert "pocket" in disponiveis and "kokoro" in disponiveis


# ------------------------------------------------------------------- erros


def test_nome_desconhecido_explica_o_que_fazer():
    with pytest.raises(VozIndisponivel, match="caminho completo"):
        resolver("modelo-que-nao-existe")


def test_modulo_inexistente_da_erro_claro():
    with pytest.raises(VozIndisponivel, match="não consegui carregar"):
        resolver("modulo.que.nao.existe:Classe")


def test_classe_que_nao_implementa_a_interface_e_recusada(monkeypatch):
    modulo = types.ModuleType("pacote_errado")
    modulo.NaoEhMotor = object
    monkeypatch.setitem(sys.modules, "pacote_errado", modulo)
    with pytest.raises(VozIndisponivel, match="não implementa MotorDeVoz"):
        resolver("pacote_errado:NaoEhMotor")


# ------------------------------------------------------------ configuração


def test_config_traz_pocket_por_padrao():
    assert Config().motor == "pocket"


def test_config_aceita_qualquer_caminho():
    cfg = Config(motor="meupacote.xtts:MotorXTTS")
    assert cfg.motor == "meupacote.xtts:MotorXTTS"


def test_config_sobrevive_ao_ciclo_de_gravacao(tmp_path):
    caminho = tmp_path / "config.json"
    Config(motor="kokoro", voz="pm_alex").salvar(caminho)
    assert Config.carregar(caminho).motor == "kokoro"


# --------------------------------------------- contrato usado pelo consumidor


def test_corta_frases_e_declarado_por_motor():
    from claudinho_voice.motores.kokoro import MotorKokoro
    from claudinho_voice.motores.pocket import MotorPocket

    assert MotorPocket.corta_frases is True, "o Pocket corta ~20% das frases"
    assert MotorKokoro.corta_frases is False, "o Kokoro não corta; não gastar regeração"


def test_consumidor_trabalha_com_o_numpy_do_adaptador(modulo_externo, monkeypatch):
    """O bug de 16/09: o motor ainda chamava .numpy() no que já era ndarray.

    A refatoração moveu a conversão para o adaptador, mas o consumidor continuou
    convertendo — e a leitura morria na frase zero, calada, porque a exceção
    acontecia dentro da thread produtora.
    """
    from claudinho_voice.config import Config
    from claudinho_voice.motor import Motor

    m = Motor(Config(motor="pacote_de_terceiro:MeuMotor", aquecimento="", palavras_por_minuto=0))
    m.carregar()
    pedacos = list(m._gerar_frase("uma frase de teste com algumas palavras", geracao=1))
    assert pedacos, "a frase precisa produzir áudio"
    assert all(p.dtype == np.float32 for p in pedacos)


def test_marca_de_paragrafo_nao_chega_ao_modelo(modulo_externo):
    """A marca é nossa; o modelo receberia um caractere que não sabe falar."""
    from claudinho_voice.config import Config
    from claudinho_voice.motor import Motor
    from claudinho_voice.preparar import MARCA_PARAGRAFO

    recebidos: list[str] = []

    class Espiao(MotorFalso):
        def gerar(self, texto: str) -> np.ndarray:
            recebidos.append(texto)
            return super().gerar(texto)

    m = Motor(Config(aquecimento="Atenção.", palavras_por_minuto=0))
    m._modelo = Espiao()
    type(m).sample_rate = property(lambda self: 24000)
    list(m._gerar_frase("Fim do parágrafo." + MARCA_PARAGRAFO, geracao=1))
    assert recebidos, "o motor precisa ter sido chamado"
    assert all(MARCA_PARAGRAFO not in t for t in recebidos), recebidos


def test_motor_base_exige_os_quatro_metodos():
    faltando = {"carregar", "sample_rate", "gerar", "vozes"} - set(
        MotorDeVoz.__abstractmethods__
    )
    assert not faltando, f"deixou de ser obrigatório: {faltando}"


# ----------------------------------------- vozes pt-BR fora do catálogo "pt"


def test_voz_estrangeira_serve_para_portugues():
    """O fonemizador é pt-BR; a voz é só timbre.

    Medido em 16/09/2026: `af_heart`, `af_bella` e `af_kore` leem português com
    0% de erro de palavra (Whisper small), contra 16% do Pocket/rafael no mesmo
    corpus de frases longas. O prefixo `af_` é a origem da gravação, não o
    idioma que a voz consegue falar.
    """
    from claudinho_voice.motores.kokoro import VOZES_RECOMENDADAS

    assert "af_heart" in VOZES_RECOMENDADAS
    assert all(isinstance(v, str) for v in VOZES_RECOMENDADAS)


# ------------------------------------------------------------------- piper


def test_piper_esta_no_catalogo_de_atalhos():
    from claudinho_voice.motores import motores_disponiveis

    assert "piper" in motores_disponiveis()


def test_piper_declara_que_nao_corta_frases():
    """VITS gera a frase inteira de uma vez: não há corte prematuro a validar."""
    from claudinho_voice.motores.piper import MotorPiper

    assert MotorPiper.corta_frases is False


def test_piper_lista_as_vozes_ptbr():
    from claudinho_voice.motores.piper import VOZES

    assert "faber" in VOZES
    assert "cadu" in VOZES


def test_piper_aceita_ritmo_nativo():
    """O Piper alonga a fala na geração, sem esticar o áudio depois.

    Medido em 16/09/2026: esticar a saída por WSOLA derruba o pico de 1,00 para
    0,67 (cancelamento de fase) e é o que se ouve como "vira um robô" em
    algumas frases — só nas que passavam do teto, por isso alternava. Com
    `length_scale` o ritmo cai de 232 para 205 ppm e o pico fica intacto.
    """
    from claudinho_voice.motores.piper import MotorPiper

    assert MotorPiper.ritmo_nativo is True


# --------------------------------------------- pronúncia pelo léxico de fonemas


def test_piper_nao_manda_mais_termo_para_o_en_us():
    """O caminho en-US foi desligado: piorava o inglês em vez de melhorar.

    Medido em 16/09/2026 à tarde (cadu + Whisper): 7/14 erros com o en-US contra
    4/14 deixando o pt-br ler. Causa: 75 dos 99 termos usam fonemas que a voz
    nunca viu no treino (ɹ ə æ ʌ ɚ ᵻ h ɜ ɑ). Estar no `phoneme_id_map` não é ter
    sido treinado. A pronúncia agora vem do léxico de fonemas, em IPA escrito
    com o inventário pt-BR.
    """
    import claudinho_voice.motores.piper as piper

    assert not hasattr(piper, "segmentar_por_idioma")
    assert not hasattr(piper, "TERMOS_EM_INGLES")


def test_piper_segmenta_pelo_lexico_de_fonemas():
    from claudinho_voice.motores.piper import segmentar_por_lexico

    fonemas = {"endpoint": "ˈẽdpˌoɪntʃɪ"}
    assert segmentar_por_lexico("o endpoint devolveu", fonemas) == [
        ("o", "texto"),
        ("ˈẽdpˌoɪntʃɪ", "ipa"),
        ("devolveu", "texto"),
    ]


def test_piper_lexico_de_fonemas_casa_composto_e_ignora_caixa():
    from claudinho_voice.motores.piper import segmentar_por_lexico

    fonemas = {"pull request": "pˈuw ɾikwˈɛstʃɪ"}
    assert segmentar_por_lexico("abri o Pull Request", fonemas) == [
        ("abri o", "texto"),
        ("pˈuw ɾikwˈɛstʃɪ", "ipa"),
    ]


def test_piper_lexico_de_fonemas_nao_casa_dentro_de_palavra():
    """`logo` não é `log`: a lista é fechada e casa palavra inteira."""
    from claudinho_voice.motores.piper import segmentar_por_lexico

    fonemas = {"log": "lˈɔɡɪ"}
    assert segmentar_por_lexico("o logo e o log", fonemas) == [
        ("o logo e o", "texto"),
        ("lˈɔɡɪ", "ipa"),
    ]


def test_piper_texto_sem_verbete_fica_num_segmento_so():
    from claudinho_voice.motores.piper import segmentar_por_lexico

    assert segmentar_por_lexico("a fala ficou clara", {"x": "y"}) == [
        ("a fala ficou clara", "texto")
    ]


def test_piper_substitui_lh_por_lj_na_cadu():
    """A cadu engole o /ʎ/: `filho` sai "fio", `velha` sai "vela".

    Medido em 16/09/2026 (2 rodadas × 6 frases, Whisper): 10 erros de LH na
    base, zero trocando ʎ por l+j — a pronúncia "fíliu" que muito brasileiro
    já usa. A mesma troca para o NH (ɲ→n+j) PIORA (`manhã`→"mania"), então o
    ɲ fica. Regra por voz: outra voz pede outra medição.
    """
    from claudinho_voice.motores.piper import aplicar_substituicoes

    assert aplicar_substituicoes(list("fˈiʎʊ"), "cadu") == list("fˈiljʊ")


def test_piper_palataliza_o_nh_na_cadu():
    """O NH também é engolido; a troca certa é ɲ→ɲ+ʲ, não ɲ→n+j.

    Em 16/09 concluí que "NH não tem conserto" testando só ɲ→n+j, que de fato
    piora (`manhã`→"mania"). Com corpus maior (25 palavras × 3 gerações, 17/09):
    cru 50/75 (67%) · ɲ+j nasal 54/75 (72%) · **ɲ+ʲ 58/75 (77%)**. A palatal
    seguida do ʲ conserta caminho, tamanho, desenho, ninho e minha.
    """
    from claudinho_voice.motores.piper import aplicar_substituicoes

    assert aplicar_substituicoes(["m", "ɐ", "ɲ", "ˈ", "ɐ"], "cadu") == [
        "m", "ɐ", "ɲ", "ʲ", "ˈ", "ɐ",
    ]


def test_piper_substitui_lh_tambem_na_jeff():
    """A troca do LH não é manha de uma voz só.

    Medido na `jeff` em 16/09/2026 (2 rodadas × 3 frases): 46% de erro na base
    contra 28% com ʎ→l+j. `milho` saía "mil", `alho` saía "al", `galho` saía
    "gado". Cada voz ainda entra por medição própria, mas o defeito é do
    inventário pt-BR do Piper, não da cadu.
    """
    from claudinho_voice.motores.piper import aplicar_substituicoes

    assert aplicar_substituicoes(list("mˈiʎʊ"), "jeff") == list("mˈiljʊ")


def test_piper_nao_substitui_em_voz_nao_medida():
    from claudinho_voice.motores.piper import aplicar_substituicoes

    assert aplicar_substituicoes(list("fˈiʎʊ"), "faber") == list("fˈiʎʊ")
