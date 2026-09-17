"""Linha de comando do Claudinho's Voice (``cvoice``).

Todos os comandos falam com o serviço residente. Se ele não estiver no ar, o
CLI o sobe sozinho em segundo plano e espera ficar pronto — quem chama nunca
precisa saber que existe um serviço.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import typer

from . import ambiente
from .config import (
    PASTA_TMP,
    Config,
    definir_sessao,
    desligar_todas_as_sessoes,
    sessao_ligada,
    sessoes_ligadas,
)

def _saida_em_utf8() -> None:
    """Faz o console do Windows aceitar acento.

    O stdout do Python no Windows nasce em cp1252, e toda mensagem nossa é em
    português: sem isto a saída vira "auto ligado nesta sess?o". É cosmético,
    mas quem está justamente depurando a leitura de texto em português não
    precisa desse susto.
    """
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


_saida_em_utf8()

app = typer.Typer(
    add_completion=False,
    help="Claudinho's Voice — leitor por voz local para o Claude Code.",
    no_args_is_help=True,
)

_cfg = Config.carregar()
BASE = f"http://{_cfg.host}:{_cfg.porta}"


def _no_ar(timeout: float = 0.6) -> bool:
    try:
        return httpx.get(f"{BASE}/saude", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


def _subir_servico() -> None:
    subprocess.Popen(
        [ambiente.executavel(sem_console=True), "-m", "claudinho_voice.servico"],
        **ambiente.opcoes_de_processo(),
    )


def garantir_servico(espera_s: float = 90.0) -> None:
    """Sobe o serviço se preciso. A primeira subida carrega o modelo (~3 s)."""
    if _no_ar():
        return
    typer.echo("subindo o serviço...", err=True)
    _subir_servico()
    limite = time.time() + espera_s
    while time.time() < limite:
        if _no_ar(timeout=1.0):
            return
        time.sleep(0.5)
    typer.echo("o serviço não respondeu a tempo; veja ~/.claudinho-voice/claudinho-voice.log", err=True)
    raise typer.Exit(code=1)


def garantir_servico_silencioso(espera_s: float = 25.0) -> bool:
    """Versão para o hook: sem saída, devolve se o serviço ficou disponível."""
    if _no_ar():
        return True
    _subir_servico()
    limite = time.time() + espera_s
    while time.time() < limite:
        if _no_ar(timeout=1.0):
            return True
        time.sleep(0.5)
    return False


def _post(rota: str, corpo: dict | None = None) -> dict:
    garantir_servico()
    resposta = httpx.post(f"{BASE}{rota}", json=corpo or {}, timeout=30.0)
    resposta.raise_for_status()
    return resposta.json()


def _texto_de_arquivo(caminho: Path) -> tuple[str, str]:
    """Lê um arquivo e devolve ``(texto, titulo)``, convertendo HTML se for o caso."""
    from .html_para_texto import html_para_markdown, parece_html

    bruto = caminho.read_text(encoding="utf-8", errors="replace")
    if caminho.suffix.lower() in {".html", ".htm"} or parece_html(bruto):
        texto, titulo = html_para_markdown(bruto)
        return texto, (titulo or caminho.stem)
    return bruto, caminho.stem


@app.command()
def ler(
    alvo: str = typer.Argument(
        None, help="Arquivo a ler (.md, .txt, .html…). Sem argumento, lê a entrada padrão."
    ),
    titulo: str = typer.Option("", "--titulo", "-t", help="Nome anunciado antes da leitura."),
    agora: bool = typer.Option(
        False, "--agora", "-a", help="Interrompe a leitura atual e lê isto primeiro."
    ),
) -> None:
    """Lê um arquivo ou o texto recebido por pipe. HTML é convertido sozinho."""
    if alvo:
        caminho = Path(alvo)
        if not caminho.exists():
            typer.echo(f"arquivo não encontrado: {alvo}", err=True)
            raise typer.Exit(code=1)
        texto, titulo_arquivo = _texto_de_arquivo(caminho)
        titulo = titulo or titulo_arquivo
    else:
        texto = sys.stdin.read()
    if not texto.strip():
        typer.echo("nada para ler", err=True)
        raise typer.Exit(code=1)
    from .sessao import sessao_atual

    dados = _post(
        "/ler",
        {
            "texto": texto,
            "titulo": titulo,
            "prioridade": agora,
            "sessao": sessao_atual() or "",
            # leitura pedida: sobrevive ao barge-in da próxima mensagem
            "protegido": True,
        },
    )
    minutos = len(texto) * 0.056 / 60
    typer.echo(f"lendo {titulo or 'texto'} (~{minutos:.0f} min)" if minutos >= 1 else f"lendo {titulo or 'texto'}")


@app.command()
def parar() -> None:
    """Cala imediatamente e esvazia a fila."""
    if not _no_ar():
        typer.echo("nada tocando")
        return
    _post("/parar")
    typer.echo("parado")


@app.command()
def pausar() -> None:
    """Pausa a leitura sem perder o lugar."""
    _post("/pausar")
    typer.echo("pausado")


@app.command()
def retomar() -> None:
    """Retoma de onde parou."""
    _post("/retomar")
    typer.echo("lendo")


@app.command()
def preparar() -> None:
    """Prepara a instalação: ambiente, dependências e voz. Roda uma vez só."""
    from .preparar_ambiente import preparar as _preparar

    if not _preparar():
        raise typer.Exit(code=1)


def _hook_carregado(sessao: str) -> bool:
    """O Claude Code desta sessão carregou os hooks do plugin?

    O ``hooks.json`` do plugin é lido **na inicialização** do Claude Code. Quem
    instala o plugin com a janela já aberta liga a voz, vê tudo indicar sucesso
    — sessão marcada, serviço no ar — e não ouve nada, porque o hook que lê as
    respostas nunca é chamado.

    A prova é a marca que o hook de prompt deixa a cada mensagem, com o id da
    sessão: a mensagem que disparou este comando já passou por ele. Procurar
    pelo id, e não por "log recente", é o que separa "hook não carregou" de
    "log recém-criado" — numa instalação nova o log nasce vazio e o hook está
    lá; com a heurística de tempo o aviso gritaria em toda primeira execução.
    """
    from .config import PASTA_USUARIO

    log = PASTA_USUARIO / "hook.log"
    if not log.exists():
        return False
    marca = f"sessao {sessao[:8]}"
    try:
        # a linha desta sessão acabou de ser escrita: está no fim do arquivo
        with log.open("rb") as arquivo:
            arquivo.seek(max(0, log.stat().st_size - 200_000))
            return marca in arquivo.read().decode("utf-8", errors="replace")
    except OSError:
        return False


@app.command()
def ativar(
    sem_painel: bool = typer.Option(False, "--sem-painel", help="não abre a janela de controle"),
) -> None:
    """Liga a voz: prepara o que falta, sobe o serviço e abre o painel.

    É o comando da primeira vez e o de todo dia — a diferença é só quanto tempo
    demora. Numa instalação nova ele cria o ambiente, instala as dependências e
    baixa a voz; numa já pronta, ele apenas liga. A voz e a janela sobem juntas:
    nunca uma sem a outra.
    """
    from .preparar_ambiente import preparar as _preparar
    from .preparar_ambiente import tudo_pronto

    # No fluxo real quem prepara é o lançador (bin/cvoice.cmd), ANTES deste
    # executável existir: quando o cli nasce, a instalação já está pronta e
    # tudo_pronto() não distingue "primeira vez" de "dia a dia". O lançador
    # avisa por ambiente.
    precisa_preparar = not tudo_pronto()
    primeira_vez = precisa_preparar or os.environ.get("CVOICE_RECEM_PREPARADO") == "1"
    if precisa_preparar:
        typer.echo("primeira execução: preparando a instalação (alguns minutos)...", err=True)
        if not _preparar():
            typer.echo("não consegui preparar a instalação; veja as mensagens acima", err=True)
            raise typer.Exit(code=1)

    # a ordem importa: o serviço primeiro, para o painel achar tudo no ar
    garantir_servico()

    if not sem_painel:
        _abrir_painel_em_segundo_plano()

    from .sessao import sessao_atual

    sessao = sessao_atual()
    if sessao:
        definir_sessao(sessao, True)
        typer.echo(f"voz ligada nesta sessão ({sessao[:8]})")
        # Na primeira vez a marca do hook de prompt NÃO PODE existir: sem venv o
        # hook sai antes de importar qualquer coisa nossa. Checar aqui daria um
        # aviso falso no exato momento em que tudo acabou de funcionar — e o
        # hook Stop deste mesmo turno já roda com o venv pronto e lê a resposta.
        if not primeira_vez and not _hook_carregado(sessao):
            typer.echo(
                "atenção: os hooks do plugin não estão carregados nesta janela. "
                "O Claude Code só lê o hooks.json ao iniciar — abra uma janela "
                "nova para as respostas serem lidas.",
                err=True,
            )
    else:
        typer.echo("voz ligada (não identifiquei a sessão; a leitura automática ficou de fora)")


def _abrir_painel_em_segundo_plano() -> None:
    """Abre a janela de controle sem prender este comando.

    O painel roda um laço de interface que não devolve; chamá-lo aqui
    penduraria a chamada do Claude Code até a janela fechar.
    """
    subprocess.Popen(
        [ambiente.executavel(sem_console=True), "-m", "claudinho_voice.painel"],
        **ambiente.opcoes_de_processo(),
    )


@app.command()
def painel(
    no_topo: bool = typer.Option(True, "--no-topo/--sem-topo", help="fica por cima das outras janelas"),
) -> None:
    """Abre a janela de controle da leitura."""
    from .painel import abrir

    abrir(sempre_no_topo=no_topo)


@app.command()
def pular() -> None:
    """Abandona o item atual e vai para o próximo da fila."""
    _post("/pular")
    typer.echo("pulado")


def _navegar(rota: str) -> None:
    dados = _post(rota)
    if dados.get("ok"):
        typer.echo(f"frase {dados.get('frase')} de {dados.get('total')}")
    else:
        typer.echo(dados.get("motivo", "não deu"))


@app.command()
def avancar() -> None:
    """Pula para o próximo parágrafo do texto que está sendo lido."""
    _navegar("/avancar")


@app.command()
def voltar() -> None:
    """Volta ao começo do parágrafo atual (ou ao anterior, se já no começo)."""
    _navegar("/voltar")


@app.command()
def estado() -> None:
    """Mostra o que está sendo lido e quais sessões têm leitura automática."""
    ligadas = sessoes_ligadas()
    auto = f"auto em {len(ligadas)} sessão(ões)" if ligadas else "auto desligado"
    if not _no_ar():
        typer.echo(f"serviço parado · {auto}")
        return
    dados = httpx.get(f"{BASE}/estado", timeout=5.0).json()
    if not dados["lendo"]:
        typer.echo(f"ocioso (fila: {dados['itens_na_fila']}) · {auto}")
        return
    typer.echo(
        f"lendo {dados['titulo_atual'] or 'texto'} "
        f"— frase {dados['frase_atual']}/{dados['total_frases']} "
        f"(fila: {dados['itens_na_fila']}){' [pausado]' if dados['pausado'] else ''} · {auto}"
    )


@app.command()
def auto(
    valor: str = typer.Argument(
        None, help="on liga a leitura automática nesta sessão do Claude Code; off desliga; vazio consulta."
    ),
    sessao: str = typer.Option(
        None, "--sessao", "-s", help="Id da sessão. Sem isto, detecta a sessão que está chamando."
    ),
    todas: bool = typer.Option(False, "--todas", help="Com off: desliga em todas as sessões."),
) -> None:
    """Liga/desliga a leitura automática das respostas — por janela de contexto."""
    if valor is None:
        ligadas = sessoes_ligadas()
        typer.echo("desligado" if not ligadas else "ligado em: " + ", ".join(s[:8] for s in ligadas))
        return
    valor = valor.lower()
    if valor not in {"on", "off"}:
        typer.echo("use: cvoice auto on | cvoice auto off [--todas]", err=True)
        raise typer.Exit(code=1)

    if valor == "off" and todas:
        n = desligar_todas_as_sessoes()
        typer.echo(f"auto desligado em {n} sessão(ões)")
        return

    if not sessao:
        from .sessao import sessao_atual

        sessao = sessao_atual()
    if not sessao:
        typer.echo(
            "não consegui identificar a sessão do Claude Code; passe --sessao <id>", err=True
        )
        raise typer.Exit(code=1)

    definir_sessao(sessao, valor == "on")
    if valor == "on":
        # sobe o serviço já, para a primeira resposta sair falada sem espera
        garantir_servico_silencioso()
        typer.echo(f"auto ligado nesta sessão ({sessao[:8]}): as respostas serão lidas")
        if not _hook_carregado(sessao):
            typer.echo(
                "atenção: os hooks do plugin não estão carregados nesta janela. "
                "O Claude Code só lê o hooks.json ao iniciar — abra uma janela "
                "nova para as respostas serem lidas.",
                err=True,
            )
    else:
        typer.echo(f"auto desligado nesta sessão ({sessao[:8]})")


@app.command()
def repetir(
    parte: str = typer.Argument(
        None, help="'fim' repete só as últimas frases; vazio repete tudo de novo."
    ),
    frases: int = typer.Option(3, "--frases", "-n", help="Quantas frases, com 'fim'."),
) -> None:
    """Fala de novo a última coisa lida — inteira ou só o final."""
    from .sessao import sessao_atual

    ultimas = frases if (parte or "").lower() in {"fim", "final", "ultima", "última"} else 0
    dados = _post("/repetir", {"sessao": sessao_atual() or "", "ultimas_frases": ultimas})
    if not dados.get("ok"):
        typer.echo(dados.get("erro", "não deu para repetir"), err=True)
        raise typer.Exit(code=1)
    quanto = "as últimas frases" if ultimas else f"{dados.get('frases', 0)} frases"
    typer.echo(
        f"repetindo {dados['titulo'] or 'a última leitura'} ({quanto}, "
        f"lida há {dados['ha_minutos']:.0f} min)"
    )


@app.command()
def historico(limite: int = typer.Option(5, "--limite", "-n")) -> None:
    """Mostra o que foi lido recentemente."""
    from .sessao import sessao_atual

    garantir_servico()
    dados = httpx.get(
        f"{BASE}/historico",
        params={"sessao": sessao_atual() or "", "limite": limite},
        timeout=5.0,
    ).json()
    if not dados["itens"]:
        typer.echo("nada foi lido ainda")
        return
    for item in dados["itens"]:
        typer.echo(
            f"há {item['ha_minutos']:.0f} min · {item['titulo'] or 'sem título'} "
            f"({item['frases']} frases): {item['inicio']}…"
        )


@app.command()
def testar(
    texto: str = typer.Argument(
        "Claudinho's Voice no ar. Leitura local, sem nuvem: o modelo roda aqui "
        "na sua máquina e o token JWT nunca sai daqui.",
        help="Frase de teste.",
    )
) -> None:
    """Fala uma frase para conferir voz, dispositivo e volume."""
    _post("/ler", {"texto": texto, "titulo": "teste", "prioridade": True})
    typer.echo("falando…")


@app.command()
def velocidade(
    palavras_por_minuto: int = typer.Argument(
        None,
        help="Velocidade da fala. 130 é conversa calma, 150 audiolivro, 170 o padrão, "
        "0 desliga o ajuste (voz crua do modelo, ~258).",
    ),
    ouvir: bool = typer.Option(True, "--ouvir/--sem-ouvir", help="Fala uma amostra depois de ajustar."),
) -> None:
    """Ajusta a velocidade da fala. Sem argumento, mostra a atual."""
    cfg = Config.carregar()
    if palavras_por_minuto is None:
        atual = cfg.palavras_por_minuto or "desligado (voz crua)"
        typer.echo(f"velocidade: {atual}")
        return
    if palavras_por_minuto and not 80 <= palavras_por_minuto <= 300:
        typer.echo("use um valor entre 80 e 300, ou 0 para desligar", err=True)
        raise typer.Exit(code=1)
    cfg.palavras_por_minuto = palavras_por_minuto
    cfg.salvar()
    _post("/recarregar")
    typer.echo(f"velocidade: {palavras_por_minuto or 'desligada'}")
    if ouvir:
        _post(
            "/ler",
            {
                "texto": "Esta é a velocidade da fala agora. Veja se fica confortável para ouvir.",
                "titulo": "amostra",
                "prioridade": True,
                "registrar": False,
            },
        )


@app.command()
def motor(
    nome: str = typer.Argument(
        None,
        help="Atalho ('pocket', 'kokoro') ou caminho de qualquer classe que "
        "implemente MotorDeVoz, como 'meupacote.xtts:MotorXTTS'. Sem argumento, mostra o atual.",
    ),
    voz: str = typer.Option(None, "--voz", "-v", help="Voz do motor novo."),
    instalar: bool = typer.Option(False, "--instalar", help="Baixa os pesos, se o motor precisar."),
) -> None:
    """Troca o modelo que fala. É só configuração — nenhum código muda."""
    from .motores import VozIndisponivel, motores_disponiveis, resolver

    cfg = Config.carregar()
    if nome is None:
        typer.echo(f"motor: {cfg.motor} · voz: {cfg.voz}")
        typer.echo("disponíveis: " + ", ".join(motores_disponiveis()))
        typer.echo("(ou qualquer 'modulo:Classe' que implemente MotorDeVoz)")
        return

    try:
        classe = resolver(nome)
    except VozIndisponivel as erro:
        typer.echo(str(erro), err=True)
        raise typer.Exit(code=1)

    if instalar and hasattr(classe, "baixar"):
        typer.echo("baixando os pesos, isso leva alguns minutos...")
        classe.baixar()

    cfg.motor = nome
    if voz:
        cfg.voz = voz
    cfg.salvar()
    typer.echo(f"motor: {nome}" + (f" · voz: {voz}" if voz else ""))
    typer.echo("reinicie o serviço para valer: cvoice reiniciar")


@app.command()
def reiniciar() -> None:
    """Derruba e sobe o serviço, para trocar de motor ou de voz."""
    if _no_ar():
        try:
            httpx.post(f"{BASE}/desligar", timeout=5.0)
        except httpx.HTTPError:
            pass
        time.sleep(1.5)
    garantir_servico()
    dados = httpx.get(f"{BASE}/saude", timeout=5.0).json()
    typer.echo(f"no ar: {dados['motor']} · {dados['voz']}")


@app.command()
def dispositivos() -> None:
    """Lista os dispositivos de saída de áudio disponíveis."""
    import sounddevice as sd

    padrao = sd.query_devices(kind="output")["name"]
    for indice, info in enumerate(sd.query_devices()):
        if info["max_output_channels"] > 0:
            marca = "*" if info["name"] == padrao else " "
            typer.echo(f"{marca} [{indice}] {info['name']}")
    typer.echo("\n* = padrão do sistema. Fixe um em ~/.claudinho-voice/config.json (dispositivo_saida).")


@app.command(hidden=True)
def tmp() -> None:
    """Imprime a pasta transitória (usada pela skill para depositar HTML de artefatos)."""
    PASTA_TMP.mkdir(parents=True, exist_ok=True)
    typer.echo(str(PASTA_TMP))


if __name__ == "__main__":
    app()
