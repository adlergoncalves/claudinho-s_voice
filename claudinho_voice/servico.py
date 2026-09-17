"""Serviço local do Claudinho's Voice.

Fica residente com o modelo carregado e expõe uma API em ``127.0.0.1`` para o
CLI, a skill e o hook do Claude Code. Sem isso, cada leitura pagaria o custo de
subir o Python e o modelo de novo.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .config import ARQUIVO_LOG, Config, sessoes_ligadas
from .motor import Motor

log = logging.getLogger("claudinho_voice")

_motor: Motor | None = None


def obter_motor() -> Motor:
    global _motor
    if _motor is None:
        _motor = Motor(Config.carregar())
    return _motor


class PedidoLeitura(BaseModel):
    texto: str = Field(min_length=1)
    titulo: str = ""
    prioridade: bool = False
    """Quando verdadeiro, interrompe o que está sendo lido e assume o lugar."""
    sessao: str = ""
    """Sessão do Claude Code que originou a leitura, para o histórico."""
    registrar: bool = True
    """Repetições não voltam para o histórico, senão "repete" repetiria a si mesmo."""
    protegido: bool = False
    """Leitura pedida de propósito: não morre com o barge-in da próxima mensagem."""


class PedidoParar(BaseModel):
    motivo: str = ""
    """'barge-in' respeita leituras protegidas; vazio é o parar explícito."""


class PedidoRepetir(BaseModel):
    sessao: str = ""
    ultimas_frases: int = 0
    """0 = repete o item inteiro; N = só as N últimas frases."""


@asynccontextmanager
async def _ciclo_de_vida(app: FastAPI):
    ARQUIVO_LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(ARQUIVO_LOG, encoding="utf-8")],
    )
    logging.getLogger("pocket_tts").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    motor = obter_motor()
    # instalação nova não tem os pesos da voz: baixa aqui, uma vez, em vez de
    # falhar na primeira leitura com um erro que ninguém sabe interpretar
    try:
        from .preparar_ambiente import baixar_voz, voz_pronta

        if not voz_pronta():
            log.info("baixando a voz pela primeira vez (~63 MB)...")
            baixar_voz()
    except Exception:
        log.warning("não consegui preparar a voz; seguindo mesmo assim")

    motor.carregar()  # paga o custo do modelo agora, não na primeira leitura
    motor.iniciar()
    log.info("Claudinho's Voice pronto em http://%s:%s", motor.cfg.host, motor.cfg.porta)
    yield
    motor.desligar()


app = FastAPI(title="Claudinho's Voice", version="0.2.0", lifespan=_ciclo_de_vida)


@app.get("/saude")
def saude() -> dict:
    motor = obter_motor()
    return {
        "ok": True,
        "motor": motor.cfg.motor,
        "modelo": motor.cfg.idioma,
        "voz": motor.cfg.voz,
        "sessoes_com_auto": sessoes_ligadas(),
    }


@app.post("/desligar")
def desligar() -> dict:
    """Encerra o processo. O CLI usa isto para trocar de motor sem pedir ajuda."""
    import os
    import threading

    threading.Timer(0.3, lambda: os._exit(0)).start()
    return {"ok": True}


@app.post("/ler")
def ler(pedido: PedidoLeitura) -> dict:
    from . import historico
    from .preparar import preparar

    motor = obter_motor()
    na_fila = motor.ler(
        pedido.texto,
        titulo=pedido.titulo,
        prioridade=pedido.prioridade,
        protegido=pedido.protegido,
    )
    if pedido.registrar:
        preparado = preparar(pedido.texto, motor.cfg)
        historico.registrar(
            pedido.texto, pedido.titulo, preparado.frases, sessao=pedido.sessao
        )
    return {"ok": True, "itens_na_fila": na_fila}


@app.post("/repetir")
def repetir(pedido: PedidoRepetir) -> dict:
    from . import historico

    item = historico.ultimo(pedido.sessao)
    if item is None:
        return {"ok": False, "erro": "nada foi falado ainda"}
    texto = (
        historico.trecho_final(item, pedido.ultimas_frases)
        if pedido.ultimas_frases
        else item.texto
    )
    motor = obter_motor()
    # repetição é sempre protegida: foi pedida agora, não pode morrer na
    # próxima mensagem que a pessoa digitar
    motor.ler(texto, titulo=item.titulo, prioridade=True, protegido=True)
    return {
        "ok": True,
        "titulo": item.titulo,
        "ha_minutos": round(item.idade_min, 1),
        "frases": len(item.frases),
    }


@app.get("/historico")
def ver_historico(sessao: str = "", limite: int = 5) -> dict:
    from . import historico

    itens = historico.ultimos(limite, sessao)
    return {
        "itens": [
            {
                "titulo": i.titulo,
                "ha_minutos": round(i.idade_min, 1),
                "frases": len(i.frases),
                "inicio": i.texto[:80],
            }
            for i in itens
        ]
    }


@app.post("/parar")
def parar(pedido: PedidoParar | None = None) -> dict:
    motor = obter_motor()
    barge_in = bool(pedido and pedido.motivo == "barge-in")
    protegido = motor.estado().protegido
    motor.parar(respeitar_protegido=barge_in)
    return {"ok": True, "ignorado": barge_in and protegido}


@app.post("/pausar")
def pausar() -> dict:
    obter_motor().pausar()
    return {"ok": True}


@app.post("/retomar")
def retomar() -> dict:
    obter_motor().retomar()
    return {"ok": True}


@app.post("/pular")
def pular() -> dict:
    obter_motor().pular()
    return {"ok": True}


AJUSTES = {
    # nome no painel  →  campo da Config
    # "velocidade" vira o TETO, não o alvo fixo: com motor de ritmo nativo
    # (Piper) o alongamento entra na geração. `palavras_por_minuto` estica o
    # áudio depois e foi o que deixou a voz metálica — não se expõe na janela.
    "motor": "motor",
    "voz": "voz",
    "volume": "volume",
    "ler_codigo": "ler_blocos_de_codigo",
    "pausa_frases": "pausa_entre_frases_s",
    "pausa_paragrafos": "pausa_entre_paragrafos_s",
    "dispositivo": "dispositivo_saida",
}
"""O que a janela pode mudar. Lista fechada: endereço, porta e threads ficam
de fora de propósito — mexer neles pela interface só quebraria o serviço."""

RECARREGAM_O_MODELO = {"voz", "motor"}
"""Ajustes que só valem depois de recarregar: a voz é carregada uma vez."""


def campos_ajustaveis() -> set[str]:
    return set(AJUSTES)


def exige_reinicio(ajustes: dict) -> bool:
    return bool(RECARREGAM_O_MODELO & set(ajustes))


class PedidoAjustes(BaseModel):
    ajustes: dict = {}
    """Só os campos que o painel mexeu; o resto fica como está."""


@app.post("/ajustes")
def aplicar_ajustes(pedido: PedidoAjustes) -> dict:
    """Muda configuração pela janela, sem editar o arquivo na mão."""
    motor = obter_motor()
    aplicados = {}
    for nome, valor in pedido.ajustes.items():
        campo = AJUSTES.get(nome)
        if campo is None:
            continue
        if campo == "volume":
            valor = limitar_volume(float(valor))
        setattr(motor.cfg, campo, valor)
        aplicados[nome] = valor

    motor.cfg.salvar()

    trocou_voz = exige_reinicio(aplicados)
    if trocou_voz:
        # a voz é carregada uma vez: sem soltar o modelo, a troca não vale.
        # Recarregar aqui custa ~1 s e evita pedir reinício.
        motor._modelo = None
        motor.carregar()
    elif getattr(motor._modelo, "ritmo_nativo", False):
        motor._modelo.definir_ritmo(motor.cfg.teto_ppm)

    return {"ok": True, "aplicados": aplicados, "reinicio_necessario": False}


@app.get("/config")
def ver_config() -> dict:
    """A configuração viva, com os nomes que a janela usa."""
    motor = obter_motor()
    return {
        "ok": True,
        "motor": motor.cfg.motor,
        "voz": motor.cfg.voz,
        "taxa": motor.cfg.taxa,
        "volume": motor.cfg.volume,
        "ler_codigo": motor.cfg.ler_blocos_de_codigo,
        "pausa_frases": motor.cfg.pausa_entre_frases_s,
        "pausa_paragrafos": motor.cfg.pausa_entre_paragrafos_s,
        "auto": bool(sessoes_ligadas()),
    }


@app.get("/motores")
def motores() -> dict:
    """Motores instalados e as vozes pt-BR de cada um.

    Só entra na lista o que está pronto para falar: um motor sem pesos no disco
    seria escolhido, gravado na config e falharia calado na primeira leitura.
    """
    motor = obter_motor()
    disponiveis = []

    from .motores.piper import VOZES as VOZES_PIPER
    from .motores.piper import MotorPiper

    instaladas = [v for v in VOZES_PIPER if MotorPiper.instalado(v)]
    if instaladas:
        disponiveis.append(
            {
                "nome": "piper",
                "rotulo": "Piper",
                "descricao": "vozes gravadas por brasileiros",
                "vozes": instaladas,
            }
        )

    try:
        from .motores.kokoro import VOZES_PT
        from .motores.kokoro import MotorKokoro

        if MotorKokoro.instalado():
            disponiveis.append(
                {
                    "nome": "kokoro",
                    "rotulo": "Kokoro",
                    "descricao": "pronúncia exata, timbre mais sintético",
                    "vozes": list(VOZES_PT),
                }
            )
    except Exception:
        pass

    return {"ok": True, "motores": disponiveis, "atual": motor.cfg.motor}


@app.get("/vozes")
def vozes() -> dict:
    """Vozes do motor atual, para a janela montar a lista."""
    motor = obter_motor()
    try:
        # o motor carregado sabe listar as suas; é a fonte mais confiável
        disponiveis = motor._modelo.vozes() if motor._modelo else []
    except Exception:
        disponiveis = []
    if not disponiveis:
        disponiveis = [motor.cfg.voz]
    return {"ok": True, "vozes": disponiveis, "atual": motor.cfg.voz}


class PedidoTaxa(BaseModel):
    taxa: float


@app.post("/taxa")
def definir_taxa(pedido: PedidoTaxa) -> dict:
    """Velocidade de reprodução, como no YouTube. Vale na frase em curso."""
    motor = obter_motor()
    motor.cfg.taxa = max(0.5, min(2.0, float(pedido.taxa)))
    motor.cfg.salvar()
    return {"ok": True, "taxa": motor.cfg.taxa}


class PedidoVolume(BaseModel):
    volume: float


def limitar_volume(valor: float) -> float:
    """Mantém o volume em [0, 1]; o painel manda o valor cru do deslizante."""
    return max(0.0, min(1.0, valor))


@app.post("/volume")
def volume(pedido: PedidoVolume) -> dict:
    """Muda o volume na hora — vale já na próxima frase."""
    motor = obter_motor()
    motor.cfg.volume = limitar_volume(pedido.volume)
    motor.cfg.salvar()
    return {"ok": True, "volume": motor.cfg.volume}


@app.post("/avancar")
def avancar() -> dict:
    """Pula para o próximo parágrafo do que está sendo lido."""
    return obter_motor().navegar(adiante=True)


@app.post("/voltar")
def voltar() -> dict:
    """Volta ao começo do parágrafo atual — ou ao anterior, se já no começo."""
    return obter_motor().navegar(adiante=False)


@app.get("/estado")
def estado() -> dict:
    """Situação da fala, mais o que o painel precisa para se desenhar."""
    motor = obter_motor()
    return {
        **vars(motor.estado()),
        "volume": motor.cfg.volume,
        "taxa": motor.cfg.taxa,
        "voz": motor.cfg.voz,
        "motor": motor.cfg.motor,
    }


class PedidoNarracao(BaseModel):
    texto: str = Field(min_length=1)
    """O que o Claude acabou de escrever antes de chamar a ferramenta."""


VALIDADE_DA_NARRACAO_S = 10.0
"""Quanto tempo uma narração continua fazendo sentido.

Quando várias ferramentas rápidas se emendam, os textos saem mais depressa do
que a fala acompanha. Passado esse prazo o Claude já avançou, e falar o passo
antigo confunde mais do que o silêncio — a fila descarta."""

INTERVALO_ENTRE_NARRACOES_S = 6.0
"""Piso entre duas narrações. Sem isto, uma sequência de chamadas curtas vira
tagarelice — o mesmo motivo do intervalo das frases de espera, só que menor,
porque aqui o conteúdo é útil."""

_ultima_narracao: float | None = None


@app.post("/narrar")
def narrar(pedido: PedidoNarracao) -> dict:
    """Fala o que o Claude escreveu antes de usar a ferramenta.

    A narração é perecível e só entra se houver espaço: o que envelheceu na
    fila confunde mais do que o silêncio."""
    global _ultima_narracao

    motor = obter_motor()
    if motor.estado().lendo:
        return {"ok": False, "motivo": "já está falando"}

    agora = time.monotonic()
    if (
        _ultima_narracao is not None
        and agora - _ultima_narracao < INTERVALO_ENTRE_NARRACOES_S
    ):
        return {"ok": False, "motivo": "acabou de narrar"}

    motor.ler(pedido.texto, titulo="narração", validade_s=VALIDADE_DA_NARRACAO_S)
    _ultima_narracao = agora
    return {"ok": True, "narrado": pedido.texto[:60]}


@app.post("/recarregar")
def recarregar() -> dict:
    """Relê a configuração sem derrubar o modelo da memória.

    Velocidade, volume e pausas passam a valer na próxima frase. Trocar a voz
    ou o idioma exige reiniciar, porque são carregados uma vez só.
    """
    motor = obter_motor()
    nova = Config.carregar()
    trocou_modelo = (nova.idioma, nova.voz) != (motor.cfg.idioma, motor.cfg.voz)
    motor.cfg = nova
    return {"ok": True, "reinicio_necessario": trocou_modelo}


def main() -> None:
    import uvicorn

    cfg = Config.carregar()
    uvicorn.run(app, host=cfg.host, port=cfg.porta, log_level="warning")


if __name__ == "__main__":
    main()
