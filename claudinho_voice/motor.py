"""Motor de fala: Pocket TTS carregado uma vez, fila de leitura e saída em streaming.

Desenho:

* uma *thread* dedicada consome a fila e fala item a item;
* cada item é quebrado em frases pelo :mod:`claudinho_voice.preparar`;
* cada frase é gerada em pedaços (``generate_audio_stream``) e escrita direto no
  dispositivo de áudio, então a fala começa antes de a frase inteira existir;
* ``parar()`` derruba a frase em curso e esvazia a fila em menos de um pedaço de áudio.
"""

from __future__ import annotations

import logging
import queue
import threading
from concurrent import futures
import time
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np

from .config import Config

log = logging.getLogger(__name__)


@dataclass
class Item:
    """Uma unidade de leitura: um documento, uma resposta, um trecho."""

    texto: str
    titulo: str = ""
    frases: list[str] = field(default_factory=list)
    geracao: int = 0
    protegido: bool = False
    """Leitura pedida de propósito (arquivo, artefato, "repete"). Sobrevive ao
    barge-in: quem pediu quer ouvir até o fim, mesmo que continue digitando."""

    inicio: int = 0
    """Frase em que a leitura começa. `navegar` reenfileira o item inteiro com
    outro início, em vez de fatiar as frases — fatiar encolhia o documento a
    cada salto e impedia voltar para antes do ponto de partida."""

    criado_em: float = field(default_factory=time.time)

    validade_s: float = 0.0
    """Segundos de vida do item. ``0`` = não vence.

    Narração de trabalho é perecível: quando várias ferramentas rápidas se
    emendam, os textos saem mais depressa do que a fala acompanha, e falar o
    passo de dois passos atrás é pior do que não falar. A resposta final não
    tem validade — ela espera a vez."""

    def vencido(self, agora: float | None = None) -> bool:
        if self.validade_s <= 0:
            return False
        return (agora if agora is not None else time.time()) - self.criado_em > self.validade_s


FIM_DE_PARAGRAFO = "¶"
"""Marca que o preparador deixa na última frase de cada parágrafo."""


def proximo_paragrafo(frases: list[str], atual: int) -> int | None:
    """Índice da primeira frase do parágrafo seguinte, ou ``None`` no fim.

    Navegar dentro de um documento longo é por bloco: num texto de 263 frases,
    avançar de uma em uma não serve, e abandonar o item inteiro serve menos
    ainda.
    """
    for i in range(atual, len(frases)):
        if frases[i].endswith(FIM_DE_PARAGRAFO):
            return i + 1 if i + 1 < len(frases) else None
    return None


def paragrafo_anterior(frases: list[str], atual: int) -> int:
    """Índice da primeira frase do parágrafo atual, ou do anterior se já nele.

    É o gesto de quem não entendeu um trecho: volta ao começo do bloco. No
    início do bloco, volta ao bloco de trás.
    """
    inicio = 0
    for i in range(atual - 1, -1, -1):
        if frases[i].endswith(FIM_DE_PARAGRAFO):
            inicio = i + 1
            break
    if inicio < atual:
        return inicio
    # já estava no começo do bloco: procura o começo do anterior
    anterior = 0
    for i in range(inicio - 2, -1, -1):
        if frases[i].endswith(FIM_DE_PARAGRAFO):
            anterior = i + 1
            break
    return anterior


@dataclass
class Estado:
    lendo: bool = False
    pausado: bool = False
    titulo_atual: str = ""
    frase_atual: int = 0
    total_frases: int = 0
    itens_na_fila: int = 0
    protegido: bool = False
    """A leitura atual foi pedida de propósito e ignora o barge-in."""


class Motor:
    """Carrega o modelo uma vez e mantém uma fila de leitura em segundo plano."""

    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or Config.carregar()
        self._fila: queue.Queue[Item] = queue.Queue()
        # Cada item carrega a "geração" em que foi enfileirado. parar() incrementa
        # o contador, então o item em curso percebe que foi invalidado e para,
        # enquanto o item recém-enfileirado (geração nova) nasce válido. Isso evita
        # a corrida de usar um Event compartilhado entre o item antigo e o novo.
        self._geracao = 0
        self._geracao_valida = 0
        self._parar_item = threading.Event()
        self._parar_tudo = threading.Event()
        self._pausado = threading.Event()
        self._pular = threading.Event()
        self._estado = Estado()
        self._trava_estado = threading.Lock()
        self._modelo = None
        self._voz = None
        self._saida = None
        self._thread: threading.Thread | None = None
        self._pronto = threading.Event()
        self._item_atual: Item | None = None
        """O que está sendo lido agora, para `navegar` poder recomeçar dele."""

    # ------------------------------------------------------------------ modelo

    def carregar(self) -> None:
        """Carrega o motor de voz configurado. Idempotente."""
        if self._modelo is not None:
            return
        from .motores import criar

        inicio = time.perf_counter()
        self._modelo = criar(self.cfg.motor)
        self._modelo.carregar(self.cfg.idioma, self.cfg.voz, self.cfg.threads)
        # motor com ritmo nativo alonga na geração; o esticamento fica desligado
        if getattr(self._modelo, "ritmo_nativo", False):
            self._modelo.definir_ritmo(self.cfg.teto_ppm)
        log.info(
            "motor pronto: %s (%s / %s) em %.1fs",
            self._modelo.descrever(),
            self.cfg.idioma,
            self.cfg.voz,
            time.perf_counter() - inicio,
        )
        self._pronto.set()

    @property
    def sample_rate(self) -> int:
        self.carregar()
        return self._modelo.sample_rate

    def _cancelado(self, geracao: int) -> bool:
        return (
            self._parar_tudo.is_set()
            or geracao < self._geracao_valida
        )

    # ------------------------------------------------------------------- áudio

    def _abrir_saida(self):
        import sounddevice as sd

        if self._saida is not None:
            return self._saida
        dispositivo = None
        if self.cfg.dispositivo_saida:
            alvo = self.cfg.dispositivo_saida.lower()
            for indice, info in enumerate(sd.query_devices()):
                if info["max_output_channels"] > 0 and alvo in info["name"].lower():
                    dispositivo = indice
                    break
            else:
                log.warning(
                    "dispositivo %r não encontrado; usando o padrão do sistema",
                    self.cfg.dispositivo_saida,
                )
        self._saida = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=dispositivo,
            blocksize=0,
        )
        self._saida.start()
        return self._saida

    def _tocar(self, audio: np.ndarray, geracao: int) -> None:
        saida = self._abrir_saida()
        from .ritmo import esticar

        # Volume e velocidade são lidos A CADA bloco, não uma vez por frase.
        # Ambos são de reprodução: mexer no controle tem de valer no som que
        # está saindo agora. Ler uma vez por frase atrasaria o efeito em vários
        # segundos — e como a geração trabalha adiantada, o áudio da fila já
        # sairia com o valor velho.
        #
        # Blocos de ~0,4 s: curtos para o controle responder e para `parar()`
        # ser quase imediato, longos o bastante para o WSOLA (que precisa de
        # janelas de 40 ms) não deixar emenda audível entre um bloco e o
        # seguinte.
        bloco = max(1, int(self.sample_rate * 0.4))
        for inicio in range(0, len(audio), bloco):
            if self._cancelado(geracao):
                return
            while self._pausado.is_set() and not self._cancelado(geracao):
                time.sleep(0.05)

            pedaco = audio[inicio : inicio + bloco]

            taxa = getattr(self.cfg, "taxa", 1.0) or 1.0
            if abs(taxa - 1.0) > 0.01:
                pedaco = esticar(pedaco, 1.0 / taxa, self.sample_rate)

            volume = self.cfg.volume
            if volume != 1.0:
                pedaco = pedaco * volume

            saida.write(np.ascontiguousarray(pedaco))

    def _silencio(self, segundos: float, geracao: int) -> None:
        if segundos <= 0:
            return
        self._tocar(np.zeros(int(self.sample_rate * segundos), dtype=np.float32), geracao)

    # ------------------------------------------------------------------- fala

    # Medido no Pocket/rafael: a fala leva ~0,056 s por caractere, estável entre
    # frases curtas e longas. Em ~20% das gerações o modelo encerra cedo e devolve
    # só ~0,3 s de áudio — a frase sai engolida. Como a relação é previsível,
    # detectamos o corte comparando com esta constante e geramos de novo.
    SEGUNDOS_POR_CARACTERE = 0.056
    FRACAO_MINIMA = 0.45
    TENTATIVAS = 3
    FRASES_ADIANTADAS = 6
    """Quantas frases prontas o produtor acumula à frente da reprodução."""

    FIM_DE_PARAGRAFO = "¶"
    """Marca que o preparador deixa na última frase de cada parágrafo."""

    def _duracao_minima_esperada(self, texto: str) -> float:
        return len(texto) * self.SEGUNDOS_POR_CARACTERE * self.FRACAO_MINIMA

    def _gerar_frase(self, frase: str, geracao: int) -> Iterator[np.ndarray]:
        """Gera uma frase em pedaços, já sem o prefixo de aquecimento.

        Cada tentativa é bufferizada para que um corte prematuro possa ser
        descartado antes de chegar ao alto-falante; só o áudio aprovado é emitido.
        """
        # motor que não corta frase não precisa da validação nem da regeração
        if not getattr(self._modelo, "corta_frases", True):
            yield from self._ajustar_ritmo(
                list(self._gerar_uma_vez(frase, geracao)), frase
            )
            return

        minimo = self._duracao_minima_esperada(frase.rstrip(self.FIM_DE_PARAGRAFO))
        for tentativa in range(1, self.TENTATIVAS + 1):
            if self._cancelado(geracao):
                return
            pedacos = list(self._gerar_uma_vez(frase, geracao))
            if self._cancelado(geracao):
                return
            total = sum(len(p) for p in pedacos) / self.sample_rate
            if total >= minimo or tentativa == self.TENTATIVAS:
                if total < minimo:
                    log.warning(
                        "frase saiu curta (%.1fs < %.1fs) mesmo após %d tentativas: %.60s",
                        total, minimo, tentativa, frase,
                    )
                yield from self._ajustar_ritmo(pedacos, frase)
                return
            log.info(
                "corte prematuro (%.1fs < %.1fs), gerando de novo (%d/%d)",
                total, minimo, tentativa, self.TENTATIVAS,
            )

    def gerar_audio_simples(self, frase: str) -> np.ndarray | None:
        """Gera uma frase curta e devolve o áudio pronto, sem fila nem streaming.

        Gera uma frase inteira de uma vez, sem streaming. Repete
        até passar pela validação de corte, para o arquivo guardado nunca sair
        pela metade.
        """
        self.carregar()
        minimo = self._duracao_minima_esperada(frase)
        melhor: np.ndarray | None = None
        for _ in range(self.TENTATIVAS):
            audio = self._modelo.gerar(frase).astype(np.float32)
            if melhor is None or len(audio) > len(melhor):
                melhor = audio
            if len(audio) / self.sample_rate >= minimo:
                break
        if melhor is None:
            return None
        from .ritmo import aparar_silencio

        return aparar_silencio(melhor, self.sample_rate)

    def tocar_arquivo(self, caminho) -> bool:
        """Toca um wav pronto na frente da fila, sem passar pelo modelo.

        Não interfere na leitura: se algo estiver tocando, o áudio é
        descartado.
        """
        if self.estado().lendo:
            return False
        try:
            import soundfile as sf

            audio, sr = sf.read(str(caminho), dtype="float32")
        except Exception:
            return False
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != self.sample_rate:
            indices = np.linspace(0, len(audio) - 1, int(len(audio) * self.sample_rate / sr))
            audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)
        self._geracao += 1
        self._tocar(audio, self._geracao)
        return True

    def _ajustar_ritmo(
        self, pedacos: list[np.ndarray], frase: str = ""
    ) -> list[np.ndarray]:
        """Apara o silêncio das bordas e acerta o ritmo da frase.

        Roda sobre a frase inteira, não pedaço a pedaço: esticar cada pedaço
        isolado deixaria emendas audíveis. Como a frase já vem bufferizada pela
        detecção de corte, isto não custa latência extra.

        Dois ajustes, nesta ordem e excludentes: ``palavras_por_minuto`` mira um
        alvo fixo (desligado por padrão — arrasta as frases já lentas), e
        ``teto_ppm`` freia só a frase que saiu rápida demais. O teto precisa da
        frase para contar as palavras; sem ela, não há o que medir.
        """
        if not pedacos:
            return pedacos
        from .ritmo import (
            aparar_silencio,
            esticar,
            fator_para_teto,
            fator_para_velocidade,
            ppm_medido,
        )

        audio = np.concatenate(pedacos) if len(pedacos) > 1 else pedacos[0]
        if self.cfg.aparar_silencio_das_bordas:
            audio = aparar_silencio(audio, self.sample_rate)
        if self.cfg.palavras_por_minuto:
            fator = fator_para_velocidade(self.cfg.palavras_por_minuto)
            audio = esticar(audio, fator, self.sample_rate)
        elif (
            self.cfg.teto_ppm
            and frase
            and not getattr(self._modelo, "ritmo_nativo", False)
        ):
            palavras = len(frase.rstrip(self.FIM_DE_PARAGRAFO).split())
            ppm = ppm_medido(palavras, len(audio) / self.sample_rate)
            fator = fator_para_teto(ppm, self.cfg.teto_ppm)
            if fator > 1.0:
                audio = esticar(audio, fator, self.sample_rate)
        return [audio]

    def _gerar_uma_vez(self, frase: str, geracao: int) -> Iterator[np.ndarray]:
        # a marca de fim de parágrafo é nossa, não do texto: nunca vai ao modelo
        texto = frase.rstrip(self.FIM_DE_PARAGRAFO)
        descartar_amostras = 0
        if self.cfg.aquecimento and self.cfg.descartar_aquecimento:
            texto = f"{self.cfg.aquecimento} {texto}"
            # o prefixo some do áudio: mede-se o tamanho dele sozinho uma única vez
            descartar_amostras = self._amostras_do_aquecimento()
        descartados = 0
        for pedaco in self._modelo.gerar_em_pedacos(texto):
            if self._cancelado(geracao):
                return
            # o adaptador já entrega numpy float32; aqui só normalizamos a forma
            dados = np.asarray(pedaco, dtype=np.float32).squeeze()
            if descartados < descartar_amostras:
                faltam = descartar_amostras - descartados
                descartados += min(faltam, len(dados))
                dados = dados[faltam:] if len(dados) > faltam else np.empty(0, np.float32)
                if len(dados) == 0:
                    continue
            yield dados

    _amostras_aquecimento: int | None = None


    def _amostras_do_aquecimento(self) -> int:
        """Duração, em amostras, do prefixo de aquecimento falado sozinho."""
        if self._amostras_aquecimento is None:
            audio = self._modelo.gerar(self.cfg.aquecimento)
            # 85% da duração: corta o prefixo sem comer o começo da frase real
            self._amostras_aquecimento = int(len(audio) * 0.85)
        return self._amostras_aquecimento

    def _falar_item(self, item: Item) -> None:
        from .preparar import dividir_em_frases

        frases = item.frases or dividir_em_frases(
            item.texto, self.cfg.max_caracteres_por_frase
        )
        item.frases = frases
        self._item_atual = item
        with self._trava_estado:
            self._estado.lendo = True
            self._estado.titulo_atual = item.titulo
            self._estado.total_frases = len(frases)
            self._estado.frase_atual = 0
            self._estado.protegido = item.protegido

        self._pular.clear()

        # A validação contra corte prematuro exige a frase inteira antes de tocar,
        # o que sozinho mataria o streaming. Como o modelo gera ~4x mais rápido do
        # que fala, um produtor gera as frases seguintes em sequência enquanto a
        # atual toca, acumulando até FRASES_ADIANTADAS na fila. Uma frase só de
        # antecipação não bastava: título curto seguido de parágrafo longo que
        # precisou ser regenerado por corte deixava segundos de silêncio.
        pronto: queue.Queue[tuple[int, list[np.ndarray]] | None] = queue.Queue(
            maxsize=self.FRASES_ADIANTADAS
        )
        geracao = item.geracao

        def produzir() -> None:
            try:
                # começa no ponto pedido: `navegar` entrega o documento
                # inteiro com outro início, para o total continuar verdadeiro
                for indice, frase in enumerate(
                    frases[item.inicio :], start=item.inicio + 1
                ):
                    if self._cancelado(geracao):
                        break
                    pedacos = list(self._gerar_frase(frase, geracao))
                    # put bloqueia quando a fila está cheia: é o freio do produtor
                    while not self._cancelado(geracao):
                        try:
                            pronto.put((indice, pedacos), timeout=0.2)
                            break
                        except queue.Full:
                            continue
            finally:
                while not self._cancelado(geracao):
                    try:
                        pronto.put(None, timeout=0.2)
                        break
                    except queue.Full:
                        continue

        produtor = threading.Thread(target=produzir, name="cv-gera", daemon=True)
        produtor.start()

        fim_ultimo_som = 0.0
        while True:
            if self._cancelado(geracao):
                break
            try:
                proximo = pronto.get(timeout=0.2)
            except queue.Empty:
                continue
            if proximo is None:
                break
            indice, pedacos = proximo
            if self._pular.is_set():
                self._pular.clear()
                break
            with self._trava_estado:
                self._estado.frase_atual = indice
            # Diagnóstico de pausa: buraco entre o fim do som anterior e o início
            # deste. Fila vazia = a geração não acompanhou; fila cheia = o áudio
            # travou em outro lugar (dispositivo, sistema).
            agora = time.perf_counter()
            if fim_ultimo_som and agora - fim_ultimo_som > 0.3:
                log.info(
                    "buraco de %.2fs antes da frase %d/%d (prontas na fila: %d, %d chars): %.50s",
                    agora - fim_ultimo_som, indice, len(frases), pronto.qsize(),
                    len(frases[indice - 1]), frases[indice - 1],
                )
            for pedaco in pedacos:
                self._tocar(pedaco, geracao)
            # respiro depois da frase: maior quando o texto muda de parágrafo,
            # que é o que dá contorno ao ouvido
            if indice < len(frases):
                fim_paragrafo = frases[indice - 1].endswith(self.FIM_DE_PARAGRAFO)
                self._silencio(
                    self.cfg.pausa_entre_paragrafos_s
                    if fim_paragrafo
                    else self.cfg.pausa_entre_frases_s,
                    geracao,
                )
            fim_ultimo_som = time.perf_counter()

        # se saímos por cancelamento/pular, o produtor pode estar travado no put;
        # invalidar a geração o libera (o laço dele checa _cancelado)
        if produtor.is_alive() and not self._cancelado(geracao):
            self._geracao_valida = max(self._geracao_valida, geracao + 1)
        produtor.join(timeout=5.0)

        with self._trava_estado:
            self._estado.lendo = False
            self._estado.titulo_atual = ""
            self._estado.protegido = False

    def _laco(self) -> None:
        self.carregar()
        while not self._parar_tudo.is_set():
            try:
                item = self._fila.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if item.vencido():
                    # narração que envelheceu na fila: falar o passo de dois
                    # passos atrás confunde mais do que o silêncio
                    log.debug("item vencido, descartado: %.40s", item.texto)
                    continue
                self._falar_item(item)
                self._silencio(self.cfg.pausa_entre_itens_s, item.geracao)
            except Exception:  # nunca deixa a thread morrer por um item ruim
                log.exception("falha ao ler item %r", item.titulo)
            finally:
                self._fila.task_done()
                with self._trava_estado:
                    self._estado.itens_na_fila = self._fila.qsize()

    # ----------------------------------------------------------------- público

    def iniciar(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._parar_tudo.clear()
        self._thread = threading.Thread(
            target=self._laco, name="claudinho-voice", daemon=True
        )
        self._thread.start()

    def ler(
        self,
        texto: str,
        titulo: str = "",
        prioridade: bool = False,
        protegido: bool = False,
        validade_s: float = 0.0,
    ) -> int:
        """Enfileira um texto. Devolve o tamanho da fila."""
        from .preparar import preparar

        preparado = preparar(texto, self.cfg)
        if not preparado.frases:
            return self._fila.qsize()
        if prioridade:
            # prioridade cede à leitura pedida: um documento de 263 frases não
            # pode morrer porque uma resposta chegou no meio. Só "parar"
            # explícito cala o que se mandou ler.
            self.parar(limpar_fila=False, respeitar_protegido=True)
        self._geracao += 1
        item = Item(
            texto=preparado.texto,
            titulo=titulo or preparado.titulo,
            frases=preparado.frases,
            geracao=self._geracao,
            protegido=protegido,
            validade_s=validade_s,
        )
        self._fila.put(item)
        with self._trava_estado:
            self._estado.itens_na_fila = self._fila.qsize()
        self.iniciar()
        return self._fila.qsize()

    def parar(self, limpar_fila: bool = True, respeitar_protegido: bool = False) -> None:
        """Interrompe a leitura atual. Com ``limpar_fila``, descarta o que falta.

        ``respeitar_protegido`` é o que o barge-in usa: uma leitura pedida de
        propósito ("lê esse arquivo", "repete") não morre porque a pessoa
        continuou digitando. Só o pedido explícito de parar a cala.
        """
        if respeitar_protegido and self.estado().protegido:
            log.info("barge-in ignorado: leitura protegida em curso")
            return
        self._geracao_valida = self._geracao + 1
        self._parar_item.set()
        self._pausado.clear()
        if limpar_fila:
            while True:
                try:
                    self._fila.get_nowait()
                    self._fila.task_done()
                except queue.Empty:
                    break
        with self._trava_estado:
            self._estado.itens_na_fila = self._fila.qsize()
            # parar() já limpou o Event de pausa; o estado exposto tem de acompanhar,
            # senão uma leitura nova nasce marcada como "pausada" sem estar
            self._estado.pausado = False

    def pausar(self) -> None:
        self._pausado.set()
        with self._trava_estado:
            self._estado.pausado = True

    def retomar(self) -> None:
        self._pausado.clear()
        with self._trava_estado:
            self._estado.pausado = False

    def pular(self) -> None:
        """Abandona o item atual e vai para o próximo da fila."""
        self._pular.set()

    def navegar(self, adiante: bool) -> dict:
        """Salta um parágrafo à frente ou volta ao começo do bloco atual.

        Reenfileira o mesmo item a partir do ponto novo: a produção de áudio
        trabalha adiantada, então não há como "rebobinar" a fila já gerada —
        recomeçar dali é o caminho honesto e custa a latência de uma frase.
        """
        item = self._item_atual
        if item is None:
            return {"ok": False, "motivo": "nada sendo lido"}

        frases = item.frases
        atual = max(0, self.estado().frase_atual - 1)
        if adiante:
            destino = proximo_paragrafo(frases, atual)
            if destino is None:
                return {"ok": False, "motivo": "fim do documento"}
        else:
            destino = paragrafo_anterior(frases, atual)

        self.parar(limpar_fila=False)
        self._geracao += 1
        self._fila.put(
            Item(
                texto=item.texto,
                titulo=item.titulo,
                frases=frases,
                inicio=destino,
                geracao=self._geracao,
                protegido=item.protegido,
            )
        )
        return {"ok": True, "frase": destino + 1, "total": len(frases)}

    def estado(self) -> Estado:
        with self._trava_estado:
            self._estado.itens_na_fila = self._fila.qsize()
            return Estado(**vars(self._estado))

    def desligar(self) -> None:
        self._parar_tudo.set()
        self.parar()
        if self._saida is not None:
            try:
                self._saida.stop()
                self._saida.close()
            finally:
                self._saida = None
