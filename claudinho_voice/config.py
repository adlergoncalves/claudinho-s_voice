"""Configuração do Claudinho's Voice.

Tudo que é ajustável vive aqui ou no arquivo de config do usuário
(``~/.claudinho-voice/config.json``), que sobrepõe estes padrões.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path

PASTA_USUARIO = Path.home() / ".claudinho-voice"
ARQUIVO_CONFIG = PASTA_USUARIO / "config.json"
ARQUIVO_LEXICO = PASTA_USUARIO / "lexico.json"
ARQUIVO_DESCONHECIDOS = PASTA_USUARIO / "termos-desconhecidos.txt"
ARQUIVO_LOG = PASTA_USUARIO / "claudinho-voice.log"
PASTA_SESSOES = PASTA_USUARIO / "sessoes"
"""Um arquivo vazio por sessão do Claude Code com leitura automática ligada.
A leitura é **por janela de contexto**: ligar numa sessão não afeta as outras."""
PASTA_TMP = PASTA_USUARIO / "tmp"
"""Onde a skill deposita conteúdo transitório (ex.: HTML de um artefato) para leitura."""


@dataclass
class Config:
    # --- motor de voz ---
    motor: str = "pocket"
    """Qual modelo fala. Aceita um atalho dos motores que vêm no projeto
    ("pocket", "kokoro") ou o caminho completo de qualquer classe que implemente
    MotorDeVoz, como "meupacote.xtts:MotorXTTS". Trocar aqui não exige mudar
    mais nada."""

    # --- modelo ---
    idioma: str = "portuguese"
    """Variante do Pocket TTS. 'portuguese' (6 camadas, RTF 0.25) é o padrão;
    'portuguese_24l' é o preview de 24 camadas (RTF 0.73, ainda não destilado)."""

    voz: str = "rafael"
    """Voz padrão do português no Pocket TTS."""

    threads: int = 4
    """Núcleos usados pelo torch. Medido no i7-13700T (8P+8E): 4 threads é o ponto
    ótimo; 16 threads chega a ficar 8x mais lento por causa dos núcleos E."""

    # --- áudio ---
    dispositivo_saida: str | None = None
    """Nome (ou parte do nome) do dispositivo de saída. None = padrão do sistema."""

    volume: float = 1.0

    # --- serviço ---
    host: str = "127.0.0.1"
    porta: int = 8765

    # --- ritmo ---
    palavras_por_minuto: int = 170
    """Velocidade da fala. O Pocket/rafael sai a ~258, quase o dobro do
    confortável (audiolivro fica em 150, conversa normal em 130). O ajuste
    estica o tempo sem mexer no tom (WSOLA), custa ~0,1 s por frase.
    Use 0 para desligar e ouvir a voz como o modelo entrega."""

    taxa: float = 1.0
    """Multiplicador de velocidade da reprodução, como no YouTube: 1,0 é normal,
    1,5 acelera, 0,75 desacelera.

    Age no áudio já gerado (WSOLA, que preserva o tom), então vale na frase em
    curso — diferente de ``teto_ppm``, que entra na geração e só aparece na
    frase seguinte."""

    teto_ppm: float = 180.0
    """Teto de ritmo por frase, em palavras por minuto. 0 desliga.

    Diferente de ``palavras_por_minuto``, que mira todas as frases num alvo
    único (e por isso arrastava as lentas), o teto só freia a frase que passou
    dele. Medido em 16/09/2026: a mesma frase sai entre 169 e 312 ppm no
    Pocket/rafael — 2,5x de variação, que o ouvido lê como pressa.

    Calibrado em 180 sobre um texto real de 17 s: a variação cai de 1,56x para
    1,04x (leitura praticamente constante) e o texto fica 1,4 s mais longo. O
    teto não arrasta a voz como o alvo fixo de 150 ppm arrastava — ele só freia
    a frase que passou, e a maioria passa perto."""

    aparar_silencio_das_bordas: bool = True
    """Tira o silêncio que vem colado nas pontas de cada frase (~0,23 s no fim),
    para a pausa entre frases ser só a nossa, previsível."""

    pausa_entre_frases_s: float = 0.12
    """Respiro entre frases da mesma leitura."""

    pausa_entre_paragrafos_s: float = 0.45
    """Respiro maior quando muda de parágrafo — dá o contorno do texto ao ouvido."""

    # --- leitura ---
    pausa_entre_itens_s: float = 0.35
    """Silêncio inserido entre um item da fila e o próximo."""

    aquecimento: str = "Atenção."
    """Prefixo curto falado antes de cada item. O Pocket mastiga as duas primeiras
    palavras de cada geração; o prefixo absorve esse defeito e é descartado do áudio
    quando ``descartar_aquecimento`` está ligado."""

    descartar_aquecimento: bool = True

    ler_blocos_de_codigo: bool = False
    """Bloco de código é anunciado ('bloco de código C#, 12 linhas') e pulado."""

    max_caracteres_por_frase: int = 240
    """Frases maiores são quebradas em orações para não estourar a geração."""

    max_caracteres_resposta: int = 8000
    """Resposta do Claude acima disto é lida só até aqui (~7 min de fala)."""

    def salvar(self, caminho: Path = ARQUIVO_CONFIG) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def carregar(cls, caminho: Path = ARQUIVO_CONFIG) -> "Config":
        cfg = cls()
        if caminho.exists():
            try:
                dados = json.loads(caminho.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return cfg
            for chave, valor in dados.items():
                if hasattr(cfg, chave):
                    setattr(cfg, chave, valor)
        return cfg


def preparar_ambiente_ssl() -> None:
    """Aponta o Python para o bundle de CA que inclui o certificado do antivírus.

    O Kaspersky Endpoint Security intercepta TLS nesta máquina, então o ``certifi``
    puro falha ao baixar os pesos do Hugging Face. ``certs/ca-bundle.pem`` é gerado
    pelo ``install.ps1``; sem ele seguimos com o padrão do sistema.
    """
    bundle = Path(__file__).resolve().parent.parent / "certs" / "ca-bundle.pem"
    if bundle.exists():
        os.environ.setdefault("SSL_CERT_FILE", str(bundle))
        os.environ.setdefault("REQUESTS_CA_BUNDLE", str(bundle))


# ------------------------------------------------ leitura automática por sessão


def _arquivo_sessao(session_id: str) -> Path:
    seguro = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return PASTA_SESSOES / seguro


def sessao_ligada(session_id: str) -> bool:
    """A leitura automática está ligada para esta sessão do Claude Code?"""
    return bool(session_id) and _arquivo_sessao(session_id).exists()


def definir_sessao(session_id: str, ligado: bool) -> None:
    PASTA_SESSOES.mkdir(parents=True, exist_ok=True)
    arquivo = _arquivo_sessao(session_id)
    if ligado:
        arquivo.touch()
        _limpar_sessoes_antigas()
    elif arquivo.exists():
        arquivo.unlink()


def sessoes_ligadas() -> list[str]:
    if not PASTA_SESSOES.exists():
        return []
    return sorted(p.name for p in PASTA_SESSOES.iterdir() if p.is_file())


def desligar_todas_as_sessoes() -> int:
    total = 0
    for nome in sessoes_ligadas():
        (PASTA_SESSOES / nome).unlink(missing_ok=True)
        total += 1
    return total


def _limpar_sessoes_antigas(dias: int = 7) -> None:
    """Sessão fechada nunca avisa; flags mais velhas que uma semana só acumulam."""
    limite = time.time() - dias * 86400
    for nome in sessoes_ligadas():
        arquivo = PASTA_SESSOES / nome
        try:
            if arquivo.stat().st_mtime < limite:
                arquivo.unlink()
        except OSError:
            pass
