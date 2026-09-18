"""Painel de controle da leitura — a janelinha que fica por cima de tudo.

Digitar comando no terminal enquanto se ouve é justamente o que o modo voz
existe para evitar. Esta janela dá os controles ao alcance do mouse: pausar,
andar de parágrafo, pular o texto inteiro, repetir, parar e ajustar o volume.

Desenho: a interface é HTML/CSS (``painel.html``) rodando no WebView2 do
Windows via ``pywebview``, e o Python é só a ponte para o serviço HTTP que já
existe. Nada de estado aqui — a verdade está sempre no serviço, e a janela
pergunta o estado a cada 0,6 s. Assim, fechar e reabrir o painel não muda nada
na leitura em curso.
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import ambiente
from .config import Config

log = logging.getLogger(__name__)

ARQUIVO_HTML = Path(__file__).with_name("painel.html")
ARQUIVO_ICONE = Path(__file__).resolve().parent.parent / "claudinho.ico"

LARGURA = 348
ALTURA = 440


class Ponte:
    """O que o HTML pode chamar. Cada método é um botão da janela.

    Toda falha vira ``{"ok": False}``: um erro de rede não pode derrubar a
    janela nem travar o clique seguinte.
    """

    def __init__(self, cfg: Config | None = None) -> None:
        self.janela = None  # preenchido por `abrir`, para minimizar/fechar
        self._x = 0.0
        self._y = 0.0
        """Posição da janela, mantida aqui para não interrogar o objeto nativo."""
        self.cfg = cfg or Config.carregar()
        self._base = f"http://{self.cfg.host}:{self.cfg.porta}"

    def _chamar(self, rota: str, metodo: str = "post", **json) -> dict:
        try:
            import httpx

            r = getattr(httpx, metodo)(f"{self._base}{rota}", timeout=4.0, **json)
            return r.json()
        except Exception as erro:  # serviço fora do ar, porta ocupada, etc.
            log.debug("painel: %s falhou (%s)", rota, erro)
            return {"ok": False, "motivo": "serviço fora do ar"}

    # --- leitura do estado (o laço da janela chama isto sem parar) ---
    # `_` existe porque o pywebview sempre repassa um argumento do JavaScript,
    # mesmo quando o HTML chama sem nada: sem ele, todo botão estoura TypeError.
    def estado(self, _=None) -> dict:
        return self._chamar("/estado", metodo="get")

    # --- controles ---
    def pausar(self, _=None) -> dict:
        return self._chamar("/pausar")

    def retomar(self, _=None) -> dict:
        return self._chamar("/retomar")

    def parar(self, _=None) -> dict:
        return self._chamar("/parar", json={"motivo": ""})

    def avancar(self, _=None) -> dict:
        return self._chamar("/avancar")

    def voltar(self, _=None) -> dict:
        return self._chamar("/voltar")

    def pular(self, _=None) -> dict:
        return self._chamar("/pular")

    def repetir(self, _=None) -> dict:
        return self._chamar("/repetir", json={"sessao": ""})

    # --- janela ---
    def mover(self, delta: dict) -> dict:
        """Move a janela pelo deslocamento do mouse, em pixels.

        O ``easy_drag`` do pywebview arrasta de qualquer ponto — inclusive de
        cima de um controle deslizante. Desligado, ele também ignora o
        ``-webkit-app-region`` do CSS, e a janela deixa de arrastar por
        completo. Sobra mover na mão: a barra de título manda o deslocamento e
        aqui ele vira posição.
        """
        if self.janela is None:
            return {"ok": False}
        try:
            # a posição é mantida aqui, não lida de `janela.x`: ler atributo do
            # objeto nativo faz o pywebview vasculhar o WebView2 fora da thread
            # da interface, e cada leitura vira uma enxurrada de E_NOINTERFACE
            self._x += float(delta.get("dx", 0))
            self._y += float(delta.get("dy", 0))
            self.janela.move(int(self._x), int(self._y))
        except Exception:
            return {"ok": False}
        return {"ok": True}

    def minimizar(self, _=None) -> dict:
        if self.janela is not None:
            self.janela.minimize()
        return {"ok": True}

    def fechar(self, _=None) -> dict:
        """Encerra tudo: cala a leitura, desliga o modo voz e derruba o serviço.

        Fechar a janela é o gesto de quem terminou. Deixar o serviço residente
        seria uma surpresa: a leitura automática continuaria falando por uma
        janela que não existe mais.
        """
        self._chamar("/parar", json={"motivo": ""})

        from .config import desligar_todas_as_sessoes

        try:
            desligar_todas_as_sessoes()
        except Exception:
            pass

        self._chamar("/desligar")  # o serviço se encerra sozinho em ~0,3 s
        if self.janela is not None:
            self.janela.destroy()
        return {"ok": True}

    def volume(self, valor: float) -> dict:
        return self._chamar("/volume", json={"volume": float(valor)})

    def taxa(self, valor: float) -> dict:
        return self._chamar("/taxa", json={"taxa": float(valor)})

    # --- ajustes (a segunda face da janela) ---
    def motores(self, _=None) -> dict:
        return self._chamar("/motores", metodo="get")

    def vozes(self, _=None) -> dict:
        return self._chamar("/vozes", metodo="get")

    def config(self, _=None) -> dict:
        """O que a face de ajustes precisa mostrar, já com os nomes dela.

        Lê do **serviço**, não do arquivo: ele mantém a config em memória e a
        grava por cima, então o arquivo em disco pode estar velho. Era por isso
        que a janela mostrava uma voz e o serviço falava com outra.
        """
        do_servico = self._chamar("/config", metodo="get")
        if do_servico.get("ok"):
            return do_servico

        cfg = Config.carregar()
        from .config import sessoes_ligadas

        return {
            "ok": True,
            # a janela controla o teto (alongamento nativo), não o alvo fixo
            "motor": cfg.motor,
            "voz": cfg.voz,
            "taxa": cfg.taxa,
            "ler_codigo": cfg.ler_blocos_de_codigo,
            "pausa_frases": cfg.pausa_entre_frases_s,
            "pausa_paragrafos": cfg.pausa_entre_paragrafos_s,
            "auto": bool(sessoes_ligadas()),
        }

    def ajustar(self, ajustes: dict) -> dict:
        return self._chamar("/ajustes", json={"ajustes": ajustes or {}})

    def auto(self, ligado: bool) -> dict:
        """Liga ou desliga a leitura automática em todas as sessões abertas.

        Pelo terminal isto é por sessão; aqui não há sessão a que se referir, e
        desligar tudo é o gesto que faz sentido com um interruptor só.
        """
        from .config import desligar_todas_as_sessoes

        if not ligado:
            return {"ok": True, "desligadas": desligar_todas_as_sessoes()}
        return {
            "ok": False,
            "motivo": "ligue com 'cvoice auto on' na janela do Claude",
        }


def _garantir_servico(espera_s: float = 90.0) -> None:
    """Sobe o serviço sem console, se ainda não estiver no ar.

    Não reaproveita o ``garantir_servico`` do CLI de propósito: aquele escreve
    com ``typer.echo``, e sob ``pythonw`` (sem console) isso abre uma janela de
    terminal — exatamente o que o atalho existe para evitar.
    """
    import subprocess
    import sys
    import time

    import httpx

    cfg = Config.carregar()
    base = f"http://{cfg.host}:{cfg.porta}"

    def no_ar(timeout: float = 0.6) -> bool:
        try:
            return httpx.get(f"{base}/saude", timeout=timeout).status_code == 200
        except Exception:
            return False

    if no_ar():
        return

    subprocess.Popen(
        [ambiente.executavel(sem_console=True), "-m", "claudinho_voice.servico"],
        **ambiente.opcoes_de_processo(),
    )

    limite = time.time() + espera_s
    while time.time() < limite:
        if no_ar(timeout=1.0):
            return
        time.sleep(0.5)
    log.warning("o serviço não respondeu a tempo; a janela abre assim mesmo")


def _dar_identidade_ao_processo() -> None:
    """Dá à janela um botão próprio na barra de tarefas do Windows.

    A barra agrupa e ilustra janelas pelo *AppUserModelID*; sem um explícito,
    todo processo ``pythonw.exe`` cai no mesmo grupo e herda o ícone do
    Python — e o ícone posto na janela é ignorado. Precisa acontecer antes de
    a janela ser criada.
    """
    if __import__("sys").platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ClaudinhoVoice.Painel")
    except Exception:
        pass


def _trazer_para_a_frente() -> bool:
    """Se já houver um painel aberto, mostra aquele e diz que não cabe outro.

    Duas janelas do mesmo painel confundem: fechar uma deixa a outra viva, e com
    ela o serviço — dá a impressão de que fechar não encerra nada.
    """
    if __import__("sys").platform != "win32":
        return False
    try:
        import ctypes

        u32 = ctypes.windll.user32
        alvo = u32.FindWindowW(None, "Claudinho's Voice")
        if not alvo:
            return False
        u32.ShowWindow(alvo, 9)  # SW_RESTORE, caso esteja minimizada
        u32.SetForegroundWindow(alvo)
        return True
    except Exception:
        return False


def abrir(sempre_no_topo: bool = True) -> None:
    """Abre a janela. Bloqueia até ela ser fechada."""
    import webview

    if _trazer_para_a_frente():
        return

    _dar_identidade_ao_processo()
    _garantir_servico()

    ponte = Ponte()
    # O HTML vai INLINE, não por URL: o WebView2 guarda o file:// no perfil
    # (%APPDATA%\pywebview) e continua servindo a versão antiga depois de uma
    # atualização — foi assim que botões novos ficaram invisíveis e o orbe
    # apareceu como a onda velha. Texto na mão não tem cache possível.
    janela = webview.create_window(
        "Claudinho's Voice",
        html=ARQUIVO_HTML.read_text(encoding="utf-8"),
        js_api=ponte,
        width=LARGURA,
        height=ALTURA,
        resizable=False,
        frameless=True,
        # easy_drag arrasta a janela de QUALQUER ponto — inclusive de cima de um
        # controle deslizante, que então nunca chega a ser arrastado. Quem define
        # a área de arrasto é o CSS (`-webkit-app-region`), como manda o padrão.
        easy_drag=False,
        on_top=sempre_no_topo,
        # sem transparência: o WebView2 no Windows não compõe com o que está
        # atrás, e o resultado era um fundo sujo em vez de vidro. A profundidade
        # vem das camadas do próprio HTML.
        background_color="#16161A",
    )
    ponte.janela = janela

    def _guardar_posicao_inicial() -> None:
        try:
            ponte._x, ponte._y = float(janela.x), float(janela.y)
        except Exception:
            pass

    janela.events.shown += _guardar_posicao_inicial


    # o painel é acessório: se o WebView2 não existir, avisa e sai sem quebrar
    def _trocar_icone() -> None:
        """Põe o ícone do projeto na janela e na barra de tarefas.

        Sem isto a janela herda o ícone do Python — o painel aparece na barra
        como se fosse um script solto. Tenta até a janela existir (o WebView2
        leva um tempo variável para criá-la; um timer fixo chegava cedo demais
        e não achava nada) e cobre os três tamanhos que o Windows consulta,
        mais o ícone da classe, que a barra usa quando agrupa.
        """
        if not ARQUIVO_ICONE.exists() or __import__("sys").platform != "win32":
            return
        try:
            import ctypes
            import time as _t

            u32 = ctypes.windll.user32
            alvo = 0
            for _ in range(80):  # até 20 s
                alvo = u32.FindWindowW(None, "Claudinho's Voice")
                if alvo:
                    break
                _t.sleep(0.25)
            if not alvo:
                return
            LR = 0x00000010 | 0x00008000  # LR_LOADFROMFILE | LR_SHARED
            grande = u32.LoadImageW(None, str(ARQUIVO_ICONE), 1, 32, 32, LR)
            pequeno = u32.LoadImageW(None, str(ARQUIVO_ICONE), 1, 16, 16, LR)
            for tipo, h in ((1, grande), (0, pequeno), (2, pequeno)):  # BIG, SMALL, SMALL2
                if h:
                    u32.SendMessageW(alvo, 0x0080, tipo, h)  # WM_SETICON
            # GCLP_HICON = -14, GCLP_HICONSM = -34
            if grande:
                u32.SetClassLongPtrW(alvo, -14, grande)
            if pequeno:
                u32.SetClassLongPtrW(alvo, -34, pequeno)
        except Exception:
            pass  # ícone é cosmético: nunca pode derrubar a janela

    import threading

    threading.Thread(target=_trocar_icone, name="cv-icone", daemon=True).start()
    webview.start(private_mode=False)
    del janela


if __name__ == "__main__":
    # quem chama é o lancar-painel.vbs, pelo wscript: ele já entra em pythonw
    # com a janela escondida, então aqui não há console a evitar.
    #
    # E é justamente por isso que a falha vai para arquivo: sem console, um
    # ``import webview`` que falha não deixa rastro nenhum — a janela não abre,
    # nenhum erro aparece, e quem for diagnosticar isso começa do zero.
    try:
        abrir()
    except Exception:
        import traceback

        from .config import PASTA_USUARIO

        try:
            PASTA_USUARIO.mkdir(parents=True, exist_ok=True)
            with open(PASTA_USUARIO / "painel.log", "a", encoding="utf-8") as arquivo:
                arquivo.write(traceback.format_exc() + chr(10))
        except OSError:
            pass
        raise
