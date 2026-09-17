"""Piper (Rhasspy) — vozes treinadas em português brasileiro.

É o único motor do projeto cujas vozes foram gravadas por falantes brasileiros:
os outros leem português com fonemizador e entregam sotaque de fora. Medido em
16/09/2026, foi o primeiro aprovado de ouvido.

VITS + ONNX Runtime, sem PyTorch. Roda a **RTF ~0,05** nesta máquina — cerca de
oito vezes mais rápido que o Pocket. Não tem streaming interno: devolve a frase
inteira de uma vez, o que não pesa porque o consumidor já quebra o texto em
frases curtas.

Voz padrão: ``jeff``, escolhida de ouvido entre as pt-BR disponíveis.
Timbre e articulação são coisas diferentes: a ``cadu`` mede melhor (3% de erro
de palavra contra 18% da ``jeff``), mas a escolha de ouvido foi a ``jeff`` — e
quem decide o timbre é quem ouve. Todas ficam disponíveis na janela de ajustes.

A pronúncia é corrigida em dois pontos, ambos **medidos** (gera → Whisper →
compara): o léxico de fonemas (palavra → IPA escrito com o inventário pt-BR,
seção ``fonemas`` do léxico) e as trocas de fonema por voz
(:data:`SUBSTITUICOES_POR_VOZ`). O caminho en-US que existiu por um dia foi
desligado: 75 dos 99 termos usavam fonemas que a voz nunca viu no treino e o
inglês saía pior do que deixando o pt-BR ler.

Os pesos não vêm com o pacote (~63 MB por voz); baixe uma vez em
``~/.claudinho-voice/modelos/piper/``.
"""

from __future__ import annotations

import functools
import logging
import re
import time
import unicodedata
from collections.abc import Iterator

import numpy as np

from ..config import PASTA_USUARIO
from .base import MotorDeVoz, VozIndisponivel

log = logging.getLogger(__name__)

PASTA_MODELO = PASTA_USUARIO / "modelos" / "piper"

VOZES = {
    "jeff": "pt_BR-jeff-medium.onnx",
    "cadu": "pt_BR-cadu-medium.onnx",
    "faber": "pt_BR-faber-medium.onnx",
}
"""As vozes pt-BR que valem a pena, todas do catálogo oficial e masculinas.

Erro de palavra medido em 16/09/2026 (Whisper small, frases longas, com uma
frase cheia de /ɾ/ pós-consoante: "problema, prazo e brecha"):

* ``jeff``     18% — **o padrão**, escolhido de ouvido pelo timbre.
* ``cadu``      3% — a mais exata: acerta o erre que derruba as outras.
* ``faber``    23% — come o /ɾ/ depois de consoante: "freia"→"feia".

Fora daqui ficaram a ``edresson`` (31%, única em 16 kHz) e as de comunidade
``miro`` e ``dii`` (24% e 23%): são fine-tunes de voz **portuguesa** com áudio
sintético, o sotaque não convence e a licença é não comercial.

Todas rodam em RTF ~0,05."""

URL_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR"

CAMINHOS_REMOTOS = {
    "cadu": "cadu/medium/pt_BR-cadu-medium.onnx",
    "jeff": "jeff/medium/pt_BR-jeff-medium.onnx",
    "faber": "faber/medium/pt_BR-faber-medium.onnx",
}


PPM_NATURAL = 165.0
"""Ritmo natural da ``jeff`` com ``length_scale`` em 1,0, medido em 16/09/2026.

A ``cadu`` sai a 160 e a ``faber`` a 232. As duas primeiras já nascem em ritmo
de leitura confortável, então o teto raramente precisa agir; trocar de voz pede
remedir isto."""


SUBSTITUICOES_POR_VOZ: dict[str, dict[str, list[str]]] = {
    "cadu": {"ʎ": ["l", "j"], "ɲ": ["ɲ", "ʲ"]},
    "jeff": {"ʎ": ["l", "j"]},
}
"""Trocas de fonema medidas por voz: o que o modelo articula mal vira o que ele sabe.

O /ʎ/ é engolido pelas vozes pt-BR do Piper: na ``cadu`` ``filho`` sai "fio",
``velha`` sai "vela", ``brilho`` sai "brio"; na ``jeff`` ``milho`` sai "mil" e
``galho`` sai "gado". É a pronúncia "fíliu" que muito brasileiro já usa.

Medido em 16/09/2026 com o Whisper como juiz, contando **só as palavras com
LH** (3 rodadas × 15 palavras): ``cadu`` 38% → **84%** de acerto, ``jeff``
29% → **62%**.

⚠️ No WER da frase inteira o ganho da ``jeff`` desaparece (44% → 46%): ela
erra tanto fora do LH que o total encobre a melhora. Foi o que quase me fez
descartar a regra para ela. Medida de regra de fonema se faz na palavra que a
regra toca; o WER da frase mede a voz, não a regra.

O NH também é engolido, mas a troca certa é outra — e achar isso exigiu voltar
atrás. Em 16/09 testei só ɲ→n+j, que PIORA (``manhã``→"mania"), e concluí que o
NH não tinha conserto. Com corpus maior (25 palavras × 3 gerações, 17/09) e mais
variantes: cru 50/75 (67%) · n+j 13/24 (pior) · j+til 54/75 (72%) ·
**ɲ+ʲ 58/75 (77%)**. A palatal seguida da semivogal ʲ conserta ``caminho``,
``tamanho``, ``desenho``, ``ninho`` e ``minha``. Lição: variante ruim não prova
que o fenômeno não tem solução.

Para o R nada ajudou (ɾ pré-consoante→x, x inicial alongado, ``noise``/``length``
do VITS): é o teto do modelo, não do texto.

A tabela é por voz porque o inventário treinado muda de modelo para modelo —
mas o defeito do /ʎ/ apareceu nas duas medidas até agora, então é do Piper em
pt-BR, não de uma voz. Voz nova entra aqui só depois de medida."""


def aplicar_substituicoes(fonemas: list[str], voz: str) -> list[str]:
    """Aplica as trocas medidas para a voz; voz sem medição passa intacta."""
    trocas = SUBSTITUICOES_POR_VOZ.get(voz)
    if not trocas:
        return list(fonemas)
    saida: list[str] = []
    for fonema in fonemas:
        saida.extend(trocas.get(fonema, [fonema]))
    return saida


@functools.lru_cache(maxsize=8)
def _regex_dos_verbetes(chaves: tuple[str, ...]) -> re.Pattern:
    # \b nas bordas para não casar dentro de palavra ("logo" não é "log");
    # o mais longo primeiro para "pull request" vencer "pull"
    alternativas = "|".join(re.escape(c) for c in sorted(chaves, key=len, reverse=True))
    return re.compile(rf"\b(?:{alternativas})\b", re.IGNORECASE)


def segmentar_por_lexico(texto: str, fonemas: dict[str, str]) -> list[tuple[str, str]]:
    """Quebra o texto em trechos ``texto`` (vão ao fonemizador) e ``ipa`` (já são fonemas).

    ``fonemas`` é a seção homônima do léxico, chave em caixa baixa. Lista
    **fechada**, palavra inteira, sem heurística: "comida" nunca vira "commit".
    O IPA de cada verbete tem de ser escrito com o inventário que a voz viu no
    treino — ver :func:`MotorPiper._lexico_de_fonemas`.
    """
    texto = texto.strip()
    if not texto:
        return []
    if not fonemas:
        return [(texto, "texto")]
    segmentos: list[tuple[str, str]] = []
    fim = 0
    for achado in _regex_dos_verbetes(tuple(fonemas)).finditer(texto):
        antes = texto[fim : achado.start()].strip()
        if antes:
            segmentos.append((antes, "texto"))
        segmentos.append((fonemas[achado.group(0).lower()], "ipa"))
        fim = achado.end()
    resto = texto[fim:].strip()
    if resto:
        segmentos.append((resto, "texto"))
    return segmentos


class MotorPiper(MotorDeVoz):
    nome = "piper"
    corta_frases = False
    ritmo_nativo = True

    def __init__(self) -> None:
        self._voz = None
        self._nome_voz = ""
        self._sample_rate = 22050
        self._length_scale = 1.0
        self._fonemas_validos: dict[str, str] | None = None

    def definir_ritmo(self, teto_ppm: float) -> None:
        """Converte o teto em ``length_scale``, o alongamento nativo do VITS.

        Esticar o áudio depois (WSOLA) cancelava fase e deixava a voz metálica
        em algumas frases — justamente as que passavam do teto, o que fazia a
        fala alternar entre normal e robótica. Aqui o alongamento entra na
        geração e o pico do áudio fica intacto."""
        if teto_ppm <= 0 or teto_ppm >= PPM_NATURAL:
            self._length_scale = 1.0
            return
        # length_scale é multiplicador de duração: dobrar a duração = metade do ppm
        self._length_scale = min(PPM_NATURAL / teto_ppm, 1.6)

    # ------------------------------------------------------------ instalação

    @staticmethod
    def arquivo_da_voz(voz: str):
        nome = VOZES.get(voz, voz)
        return PASTA_MODELO / nome

    @classmethod
    def instalado(cls, voz: str = "jeff") -> bool:
        arquivo = cls.arquivo_da_voz(voz)
        return arquivo.exists() and arquivo.with_suffix(".onnx.json").exists()

    @classmethod
    def baixar(cls, voz: str = "jeff") -> None:
        """Baixa o modelo e o JSON de configuração da voz (~63 MB)."""
        import httpx

        from ..config import preparar_ambiente_ssl

        preparar_ambiente_ssl()
        PASTA_MODELO.mkdir(parents=True, exist_ok=True)

        if voz not in CAMINHOS_REMOTOS:
            raise VozIndisponivel(
                f"voz '{voz}' não está no catálogo pt-BR ({', '.join(VOZES)})"
            )
        remoto = CAMINHOS_REMOTOS[voz]
        for sufixo in ("", ".json"):
            destino = PASTA_MODELO / (VOZES[voz] + sufixo)
            if destino.exists():
                continue
            url = f"{URL_BASE}/{remoto}{sufixo}"
            log.info("baixando %s", url)
            with httpx.stream("GET", url, follow_redirects=True, timeout=600) as r:
                r.raise_for_status()
                with destino.open("wb") as arquivo:
                    for bloco in r.iter_bytes(1 << 20):
                        arquivo.write(bloco)

    # ---------------------------------------------------------------- carga

    def carregar(self, idioma: str, voz: str, threads: int) -> None:
        if self._voz is not None:
            return

        voz = voz or "jeff"
        self._nome_voz = voz
        self._fonemas_validos = None
        arquivo = self.arquivo_da_voz(voz)
        if not arquivo.exists():
            raise VozIndisponivel(
                f"voz '{voz}' não encontrada em {PASTA_MODELO}. "
                f"Rode: cvoice motor piper --voz {voz} --instalar"
            )

        import os

        # o 13700T tem 8P+8E: espalhar nos E-cores degrada em vez de acelerar
        os.environ.setdefault("OMP_NUM_THREADS", str(threads))
        try:
            from piper import PiperVoice
        except ImportError as erro:
            raise VozIndisponivel(
                "pacote piper-tts não instalado. Rode: uv pip install piper-tts"
            ) from erro

        inicio = time.perf_counter()
        try:
            self._voz = PiperVoice.load(str(arquivo))
        except Exception as erro:
            raise VozIndisponivel(f"Piper não carregou ({voz}): {erro}") from erro
        self._sample_rate = self._voz.config.sample_rate
        log.info(
            "Piper carregado: %s (%d Hz) em %.1fs",
            voz,
            self._sample_rate,
            time.perf_counter() - inicio,
        )

    # ----------------------------------------------------------------- fala

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def _config_de_sintese(self):
        from piper import SynthesisConfig

        return SynthesisConfig(length_scale=self._length_scale)

    def _lexico_de_fonemas(self) -> dict[str, str]:
        """Verbetes do léxico cuja grafia IPA a voz carregada conhece.

        Símbolo fora do ``phoneme_id_map`` seria descartado em silêncio pelo
        Piper e a palavra sairia mutilada; melhor avisar uma vez e deixar o
        fonemizador ler o texto daquele verbete.
        """
        if self._fonemas_validos is None:
            from ..preparar import carregar_lexico

            conhecidos = set(self._voz.config.phoneme_id_map)
            validos: dict[str, str] = {}
            for palavra, ipa in carregar_lexico()["fonemas"].items():
                fora = {s for s in unicodedata.normalize("NFD", ipa) if s not in conhecidos}
                if fora:
                    log.warning(
                        "léxico de fonemas: '%s' usa símbolo que a voz %s não conhece %s; ignorado",
                        palavra, self._nome_voz, sorted(fora),
                    )
                    continue
                validos[palavra] = ipa
            self._fonemas_validos = validos
        return self._fonemas_validos

    def _fonemas_por_frase(self, texto: str) -> list[list[str]]:
        """Fonemiza pelo espeak, injeta os verbetes do léxico e aplica as trocas da voz.

        Uma lista por frase, para o áudio sair em pedaços como o ``synthesize``
        fazia. O IPA vai em NFD porque é assim que o Piper decompõe o que o
        espeak devolve: o til nasal é um símbolo à parte no ``phoneme_id_map``.
        """
        frases: list[list[str]] = []
        atual: list[str] = []
        for trecho, tipo in segmentar_por_lexico(texto, self._lexico_de_fonemas()):
            if tipo == "ipa":
                atual.extend(unicodedata.normalize("NFD", trecho))
                atual.append(" ")
                continue
            sentencas = self._voz.phonemize(trecho)
            for indice, sentenca in enumerate(sentencas):
                atual.extend(sentenca)
                if indice < len(sentencas) - 1:
                    frases.append(atual)
                    atual = []
                else:
                    atual.append(" ")
        if atual:
            frases.append(atual)
        return [
            aplicar_substituicoes(frase, self._nome_voz)
            for frase in frases
            if any(fonema.strip() for fonema in frase)
        ]

    def _audio_dos_fonemas(self, fonemas: list[str]) -> np.ndarray:
        ids = self._voz.phonemes_to_ids(fonemas)
        # este caminho devolve o ndarray direto, não um AudioChunk
        dados = np.asarray(
            self._voz.phoneme_ids_to_audio(ids, syn_config=self._config_de_sintese())
        ).squeeze()
        if dados.dtype == np.int16:
            dados = dados.astype(np.float32) / 32768.0
        else:
            dados = dados.astype(np.float32)
        # `synthesize` normaliza por padrão e este caminho não: sem isto a frase
        # sai com menos da metade do volume
        pico = float(np.abs(dados).max())
        if pico > 0:
            dados = dados / pico
        return dados

    def gerar(self, texto: str) -> np.ndarray:
        partes = [self._audio_dos_fonemas(frase) for frase in self._fonemas_por_frase(texto)]
        if not partes:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(partes)

    def gerar_em_pedacos(self, texto: str) -> Iterator[np.ndarray]:
        for frase in self._fonemas_por_frase(texto):
            yield self._audio_dos_fonemas(frase)

    def vozes(self) -> list[str]:
        """Só as vozes com peso no disco.

        Oferecer o catálogo inteiro deixava escolher uma voz não baixada: a
        config gravava o nome, o serviço não carregava e a leitura continuava
        na voz antiga, sem explicação.
        """
        return [nome for nome in VOZES if self.instalado(nome)]

    def descrever(self) -> str:
        return "Piper (Rhasspy), vozes nativas pt-BR"
