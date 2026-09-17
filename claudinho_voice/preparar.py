"""Preparação do texto para ser falado.

Camada determinística: markdown vira prosa, blocos de código viram um aviso,
tabelas viram resumo, números e datas vão por extenso, identificadores compostos
são separados e siglas passam pelo léxico.

As regras aqui não são palpite: foram medidas gerando com o Pocket TTS e
transcrevendo de volta com o Whisper. O que o modelo já acerta sozinho
(``pipeline``, ``deploy``, ``pull request``, ``use case``) passa intacto de
propósito — mexer piora.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .config import ARQUIVO_DESCONHECIDOS, ARQUIVO_LEXICO, Config

# --------------------------------------------------------------------- léxico

_LEXICO_CACHE: dict | None = None


def carregar_lexico() -> dict:
    """Léxico do usuário, com o padrão do pacote como base."""
    global _LEXICO_CACHE
    if _LEXICO_CACHE is not None:
        return _LEXICO_CACHE
    padrao = json.loads(
        (Path(__file__).parent / "lexico_padrao.json").read_text(encoding="utf-8")
    )
    lexico = {
        "soletrar": dict(padrao.get("soletrar", {})),
        "palavra": set(padrao.get("palavra", [])),
        "substituir": dict(padrao.get("substituir", {})),
        # chave em caixa baixa nas duas: o casamento no texto ignora caixa
        "pronuncia": {k.lower(): v for k, v in padrao.get("pronuncia", {}).items()},
        "fonemas": {k.lower(): v for k, v in padrao.get("fonemas", {}).items()},
    }
    if ARQUIVO_LEXICO.exists():
        try:
            usuario = json.loads(ARQUIVO_LEXICO.read_text(encoding="utf-8"))
            lexico["soletrar"].update(usuario.get("soletrar", {}))
            lexico["palavra"].update(usuario.get("palavra", []))
            lexico["substituir"].update(usuario.get("substituir", {}))
            lexico["pronuncia"].update(
                {k.lower(): v for k, v in usuario.get("pronuncia", {}).items()}
            )
            lexico["fonemas"].update(
                {k.lower(): v for k, v in usuario.get("fonemas", {}).items()}
            )
        except (json.JSONDecodeError, OSError):
            pass
    _LEXICO_CACHE = lexico
    return lexico


def registrar_desconhecido(termo: str) -> None:
    """Anota siglas que caíram na regra genérica, para você promovê-las ao léxico."""
    try:
        ARQUIVO_DESCONHECIDOS.parent.mkdir(parents=True, exist_ok=True)
        vistos = set()
        if ARQUIVO_DESCONHECIDOS.exists():
            vistos = set(ARQUIVO_DESCONHECIDOS.read_text(encoding="utf-8").split())
        if termo not in vistos:
            with ARQUIVO_DESCONHECIDOS.open("a", encoding="utf-8") as f:
                f.write(termo + "\n")
    except OSError:
        pass


# ------------------------------------------------------------------- números

_UNIDADES = "zero um dois três quatro cinco seis sete oito nove".split()
_DEZ_A_DEZENOVE = (
    "dez onze doze treze catorze quinze dezesseis dezessete dezoito dezenove".split()
)
_DEZENAS = (
    "  vinte trinta quarenta cinquenta sessenta setenta oitenta noventa".split(" ")
)
_CENTENAS = (
    " cento duzentos trezentos quatrocentos quinhentos seiscentos setecentos "
    "oitocentos novecentos"
).split(" ")
_MESES = (
    "janeiro fevereiro março abril maio junho julho agosto setembro outubro "
    "novembro dezembro"
).split()


def numero_por_extenso(n: int, feminino: bool = False) -> str:
    """Inteiro por extenso em português, até bilhões. O Pocket lê dígito a dígito
    de forma irregular, então o número nunca chega cru no modelo.

    ``feminino`` faz a concordância de gênero em um/uma e nos duzentos/duzentas,
    necessária para contagens como "duas linhas" e "trezentas páginas".
    """
    if n < 0:
        return "menos " + numero_por_extenso(-n, feminino)
    if feminino and n in (1, 2):
        return "uma" if n == 1 else "duas"
    if n < 10:
        return _UNIDADES[n]
    if n < 20:
        return _DEZ_A_DEZENOVE[n - 10]
    if n < 100:
        dezena, resto = divmod(n, 10)
        base = _DEZENAS[dezena]
        return base if resto == 0 else f"{base} e {numero_por_extenso(resto, feminino)}"
    if n == 100:
        return "cem"
    if n < 1000:
        centena, resto = divmod(n, 100)
        base = _CENTENAS[centena]
        if feminino and centena >= 2:
            base = base[:-2] + "as"  # duzentos -> duzentas
        return base if resto == 0 else f"{base} e {numero_por_extenso(resto, feminino)}"
    for limite, singular, plural in (
        (1_000_000_000, "bilhão", "bilhões"),
        (1_000_000, "milhão", "milhões"),
        (1000, "mil", "mil"),
    ):
        if n >= limite:
            quantidade, resto = divmod(n, limite)
            if limite == 1000:
                cabeca = (
                    "mil"
                    if quantidade == 1
                    else f"{numero_por_extenso(quantidade, feminino)} mil"
                )
            else:
                # milhão/bilhão são masculinos: "duas mil" mas "dois milhões"
                nome = singular if quantidade == 1 else plural
                cabeca = f"{numero_por_extenso(quantidade)} {nome}"
            if resto == 0:
                return cabeca
            ligacao = " e " if resto < 100 or resto % 100 == 0 else " "
            return f"{cabeca}{ligacao}{numero_por_extenso(resto, feminino)}"
    return str(n)


def _decimal_por_extenso(inteiro: str, decimal: str, feminino: bool = False) -> str:
    # só a parte inteira flexiona: "duas vírgula cinco décimos vezes"
    parte = numero_por_extenso(int(inteiro), feminino=feminino)
    casas = decimal.rstrip("0") or "0"
    if len(casas) <= 2:
        nome = "décimos" if len(casas) == 1 else "centésimos"
        return f"{parte} vírgula {numero_por_extenso(int(casas))} {nome}"
    digitos = " ".join(_UNIDADES[int(d)] for d in decimal)
    return f"{parte} vírgula {digitos}"


_RE_SIGLA_NUMERO = re.compile(r"\b([A-ZÀ-Þ]{2,6})[-–]0*(\d{1,4})\b")


def separar_sigla_de_numero(texto: str) -> str:
    """``ADR-0030`` vira ``ADR 30``; ``DV-49`` vira ``DV 49``.

    O hífen colado faz o modelo emendar a sigla no número ("a dê érre-trinta") e
    os zeros à esquerda viram fala inútil ("zero zero trinta").
    """
    return _RE_SIGLA_NUMERO.sub(lambda m: f"{m.group(1)} {int(m.group(2))}", texto)


def expandir_numeros(texto: str) -> str:
    # datas ISO e brasileiras
    def _data(m: re.Match) -> str:
        if m.group("iso"):
            ano, mes, dia = m.group("a"), m.group("m"), m.group("d")
        else:
            dia, mes, ano = m.group("d2"), m.group("m2"), m.group("a2")
        try:
            nome_mes = _MESES[int(mes) - 1]
        except (ValueError, IndexError):
            return m.group(0)
        dia_txt = "primeiro" if int(dia) == 1 else numero_por_extenso(int(dia))
        return f"{dia_txt} de {nome_mes} de {numero_por_extenso(int(ano))}"

    texto = re.sub(
        r"(?P<iso>\b(?P<a>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b)"
        r"|(?P<br>\b(?P<d2>\d{1,2})/(?P<m2>\d{1,2})/(?P<a2>\d{4})\b)",
        _data,
        texto,
    )
    # porcentagem, dinheiro, decimais, inteiros
    texto = re.sub(
        r"R\$\s*(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?",
        lambda m: (
            numero_por_extenso(int(m.group(1).replace(".", "")))
            + " reais"
            + (f" e {numero_por_extenso(int(m.group(2)))} centavos" if m.group(2) else "")
        ),
        texto,
    )
    texto = re.sub(
        r"\b(\d+)(?:[.,](\d+))?\s*%",
        lambda m: (
            (_decimal_por_extenso(m.group(1), m.group(2)) if m.group(2) else numero_por_extenso(int(m.group(1))))
            + " por cento"
        ),
        texto,
    )
    texto = re.sub(
        r"\b(\d+)[.,](\d+)\b", lambda m: _decimal_por_extenso(m.group(1), m.group(2)), texto
    )
    texto = re.sub(
        r"\b\d{1,3}(?:\.\d{3})+\b",
        lambda m: numero_por_extenso(int(m.group(0).replace(".", ""))),
        texto,
    )
    # unidades coladas ao número: "2h" vira "duas horas", "3x" vira "três vezes"
    unidades = {
        "h": ("hora", "horas", True), "min": ("minuto", "minutos", False),
        "s": ("segundo", "segundos", False), "ms": ("milissegundo", "milissegundos", False),
        "x": ("vez", "vezes", True), "×": ("vez", "vezes", True),
        "px": ("pixel", "pixels", False), "gb": ("giga", "gigas", False),
        "mb": ("mega", "megas", False), "kb": ("kabytes", "kabytes", False),
    }

    def _unidade(m: re.Match) -> str:
        inteiro, decimal, u = m.group(1), m.group(2), m.group(3).lower()
        singular, plural, fem = unidades[u]
        if decimal:
            # "2,5x" é uma medida só: quebrar no decimal deixava "dois,cinco vezes"
            # porque a regex de unidade comia o "5x" e abandonava o "2,".
            return f"{_decimal_por_extenso(inteiro, decimal, feminino=fem)} {plural}"
        n = int(inteiro)
        return f"{numero_por_extenso(n, feminino=fem)} {singular if n == 1 else plural}"

    texto = re.sub(
        r"\b(\d+)(?:[.,](\d+))?\s?(h|min|s|ms|x|×|px|gb|mb|kb)\b(?![\w/])",
        _unidade,
        texto,
        flags=re.I,
    )
    # "~2 dias" -> "cerca de dois dias"
    texto = re.sub(r"~\s*(?=\d)", "cerca de ", texto)
    texto = re.sub(r"\b\d+\b", lambda m: numero_por_extenso(int(m.group(0))), texto)
    # dígito grudado em letra ("e2e-jornadas", "v2", "3dias"): separa e expande
    texto = re.sub(r"(?<=[A-Za-zÀ-ÿ])(?=\d)|(?<=\d)(?=[A-Za-zÀ-ÿ])", " ", texto)
    texto = re.sub(r"\d+", lambda m: numero_por_extenso(int(m.group(0))), texto)
    return texto


# ------------------------------------------------------- identificadores/siglas

_RE_CAMEL = re.compile(r"(?<=[a-zà-ÿ0-9])(?=[A-ZÀ-Þ])|(?<=[A-ZÀ-Þ])(?=[A-ZÀ-Þ][a-zà-ÿ])")
_RE_SIGLA = re.compile(r"\b[A-ZÀ-Þ][A-ZÀ-Þ0-9]{1,6}\b")
_RE_IDENTIFICADOR = re.compile(r"\b\w*[a-zà-ÿ]\w*[A-ZÀ-Þ]\w*\b|\b\w+_\w+\b")


def _eh_pronunciavel(sigla: str) -> bool:
    """Heurística: sigla com vogal e alternância razoável costuma ser falada como
    palavra (DACPAC, RBAC, CRUD); só consoantes é soletrada (JWT, PKCE, XML)."""
    letras = "".join(c for c in unicodedata.normalize("NFD", sigla) if c.isalpha())
    if not letras:
        return True
    vogais = sum(1 for c in letras.lower() if c in "aeiouy")
    return vogais >= max(1, len(letras) // 3)


def separar_identificadores(texto: str) -> str:
    """``ApplicationUser`` vira ``Application User``; ``pessoa_id`` vira ``pessoa id``.

    Medido: colado, o modelo lê ``ApplicationUser`` como "a pique ionosa"; separado,
    ele acerta as duas palavras.
    """

    def _sep(m: re.Match) -> str:
        termo = m.group(0)
        # sigla de verdade não tem underscore: JWT fica, SEGUNDOS_POR_CARACTERE
        # vira três palavras. Sem esta ressalva o termo voltava intacto e o
        # underscore sumia mais adiante — "SEGUNDOSPORCARACTERE", uma palavra só.
        if termo.isupper() and "_" not in termo:  # sigla, tratada em outro passo
            return termo
        return _RE_CAMEL.sub(" ", termo.replace("_", " "))

    return _RE_IDENTIFICADOR.sub(_sep, texto)


_RE_PRONUNCIA_CACHE: tuple[tuple[str, ...], re.Pattern] | None = None


def _regex_da_pronuncia(chaves: tuple[str, ...]) -> re.Pattern | None:
    """Uma regex só com todos os verbetes, montada uma vez por conteúdo do léxico."""
    global _RE_PRONUNCIA_CACHE
    if not chaves:
        return None
    if _RE_PRONUNCIA_CACHE is None or _RE_PRONUNCIA_CACHE[0] != chaves:
        # o mais longo primeiro: "pull request" tem de vencer "pull"
        alternativas = "|".join(
            re.escape(c) for c in sorted(chaves, key=len, reverse=True)
        )
        _RE_PRONUNCIA_CACHE = (
            chaves,
            re.compile(rf"\b(?:{alternativas})\b", re.IGNORECASE),
        )
    return _RE_PRONUNCIA_CACHE[1]


def aplicar_pronuncia(texto: str) -> str:
    """Troca o termo pela grafia que se lê como ele se fala.

    Ao contrário de ``substituir``, casa **palavra inteira** e ignora caixa:
    ``cache`` não pode transformar ``cachear`` em "quécheear", e ``Cache`` no
    começo da frase tem de ser corrigido igual.
    """
    pronuncia = carregar_lexico()["pronuncia"]
    regex = _regex_da_pronuncia(tuple(pronuncia))
    if regex is None:
        return texto
    return regex.sub(lambda m: pronuncia[m.group(0).lower()], texto)


def aplicar_lexico(texto: str) -> str:
    lexico = carregar_lexico()
    for origem, destino in lexico["substituir"].items():
        texto = texto.replace(origem, destino)
    texto = aplicar_pronuncia(texto)

    def _sigla(m: re.Match) -> str:
        termo = m.group(0)
        if termo in lexico["soletrar"]:
            return lexico["soletrar"][termo]
        if termo in lexico["palavra"]:
            return termo
        if len(termo) < 2:
            return termo
        if _eh_pronunciavel(termo):
            return termo
        registrar_desconhecido(termo)
        nomes = {
            "H": "agá", "J": "jota", "K": "cá", "L": "éle", "M": "ême", "N": "ene",
            "R": "érre", "S": "ésse", "W": "dáblio", "X": "xis", "Y": "ípsilon",
            "Z": "zê", "F": "éfe", "B": "bê", "C": "cê", "D": "dê", "G": "gê",
            "P": "pê", "Q": "quê", "T": "tê", "V": "vê",
        }
        return " ".join(nomes.get(c, c.lower()) for c in termo)

    return _RE_SIGLA.sub(_sigla, texto)


# ------------------------------------------------------------------- markdown

_RE_BLOCO_CODIGO = re.compile(r"```(\w+)?\n(.*?)```", re.S)
_RE_CODIGO_INLINE = re.compile(r"`([^`\n]+)`")
_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_RE_IMAGEM = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_RE_TITULO = re.compile(r"^(#{1,6})\s+(.*)$", re.M)
_RE_LISTA = re.compile(r"^\s*[-*+]\s+", re.M)
_RE_LISTA_NUM = re.compile(r"^\s*(\d+)[.)]\s+", re.M)
_RE_ENFASE = re.compile(r"(\*\*|\*)(.+?)\1|(?<![\w])(__|_)(.+?)\3(?![\w])", re.S)
"""Ênfase de markdown. O `_` só conta como itálico quando não está grudado em
palavra: `_importante_` é ênfase, `SEGUNDOS_POR_CARACTERE` é identificador.
Sem essa borda, o `_POR_` era lido como itálico e os underscores sumiam antes
de `separar_identificadores` ver o termo — virava "SEGUNDOSPORCARACTERE"."""
_RE_CITACAO = re.compile(r"^\s*>\s?", re.M)
_RE_HR = re.compile(r"^\s*([-*_])\1{2,}\s*$", re.M)
_RE_HTML = re.compile(r"<[^>]+>")
_RE_LINHA_TABELA = re.compile(r"^\s*\|.*\|\s*$", re.M)


def _resumir_tabela(linhas: list[str]) -> str:
    linhas = [l for l in linhas if not re.match(r"^\s*\|[\s|:-]+\|\s*$", l)]
    if not linhas:
        return ""
    def celulas(linha: str) -> list[str]:
        return [c.strip() for c in linha.strip().strip("|").split("|")]

    cabecalho = celulas(linhas[0])
    corpo = [celulas(l) for l in linhas[1:]]
    nomes_colunas = [c for c in cabecalho if c]  # a 1ª coluna de rótulos costuma vir sem nome
    if not corpo:
        return f"Tabela com as colunas {', '.join(nomes_colunas)}."
    partes = [
        f"Tabela com {numero_por_extenso(len(corpo), feminino=True)} "
        f"{'linha' if len(corpo) == 1 else 'linhas'}, "
        f"colunas: {', '.join(nomes_colunas)}."
    ]
    for linha in corpo:
        pares = [
            f"{col}: {val}"
            for col, val in zip(cabecalho, linha)
            if val and val not in {"-", "—"}
        ]
        if pares:
            partes.append("; ".join(pares) + ".")
    return " ".join(partes)


_SIMBOLOS = [
    # (padrão, substituto) — travessão, seta e ponto-meio viram pausa;
    # caracteres de árvore de diretório e de caixa (U+2500–U+257F) somem;
    # marcas de ok/erro/alerta viram palavra.
    (re.compile(r"[—–·•←→⇒↔]"), ","),
    (re.compile(r"[─-╿]"), " "),
    (re.compile(r" "), " "),
    (re.compile(r"[✓✔✅]"), " ok "),
    (re.compile(r"[✗❌]"), " não "),
    (re.compile(r"⚠️?"), " atenção "),
    # Medido: reticências e aspas deixam resíduo sonoro no fim da frase (energia
    # final 1,17 e 1,32 contra 0,16 de um ponto simples). Reticências viram ponto;
    # aspas somem, porque a citação não muda o que é falado.
    (re.compile(r"\.{3,}|…"), "."),
    (re.compile(r"[\"“”«»]"), ""),
    (re.compile(r"(?<=\w)'(?=\w)"), ""),  # protege o apóstrofo interno
    (re.compile(r"[‘’']"), ""),
    (re.compile(r""), "'"),
]


def limpar_simbolos(texto: str) -> str:
    """Travessão, seta e ponto-meio viram pausa; caracteres de árvore de
    diretório e caixa somem. O modelo não fala nenhum deles, mas tenta."""
    for padrao, substituto in _SIMBOLOS:
        texto = padrao.sub(substituto, texto)
    texto = re.sub(r"\s*,\s*,+", ",", texto)
    texto = re.sub(r"[ \t]+,", ",", texto)
    texto = re.sub(r"^\s*,\s*", "", texto, flags=re.M)
    return texto


_PONTUACAO_FINAL = ".!?;:,"


def pontuar_linhas(texto: str) -> str:
    """Toda linha não vazia termina com pontuação. Sem isto, um título ou item
    de lista sem ponto final emenda na frase seguinte e vira uma frase só."""
    linhas = []
    for linha in texto.splitlines():
        limpa = linha.rstrip()
        if limpa and limpa[-1] not in _PONTUACAO_FINAL and limpa[-1] not in "]":
            limpa += "."
        linhas.append(limpa)
    return "\n".join(linhas)


def markdown_para_prosa(texto: str, cfg: Config) -> str:
    """Tira a marcação e transforma o que não se fala em descrição."""

    def _bloco(m: re.Match) -> str:
        linguagem, corpo = m.group(1), m.group(2)
        linhas = len([l for l in corpo.splitlines() if l.strip()])
        if cfg.ler_blocos_de_codigo:
            return f" Bloco de código. {corpo} Fim do bloco. "
        idioma = f" em {linguagem}" if linguagem else ""
        return (
            f" [bloco de código{idioma}, {numero_por_extenso(linhas, feminino=True)} "
            f"{'linha' if linhas == 1 else 'linhas'}, pulado] "
        )

    texto = _RE_BLOCO_CODIGO.sub(_bloco, texto)

    # tabelas (blocos consecutivos de linhas com pipe)
    saida: list[str] = []
    buffer: list[str] = []
    for linha in texto.splitlines():
        if _RE_LINHA_TABELA.match(linha):
            buffer.append(linha)
            continue
        if buffer:
            saida.append(_resumir_tabela(buffer))
            buffer = []
        saida.append(linha)
    if buffer:
        saida.append(_resumir_tabela(buffer))
    texto = "\n".join(saida)

    texto = _RE_IMAGEM.sub(lambda m: f" [imagem: {m.group(1) or 'sem legenda'}] ", texto)
    texto = _RE_LINK.sub(lambda m: m.group(1), texto)
    texto = _RE_TITULO.sub(lambda m: f"\n{m.group(2).rstrip('.')}. ", texto)
    texto = _RE_HR.sub("\n", texto)
    texto = _RE_CITACAO.sub("", texto)
    texto = _RE_LISTA_NUM.sub(lambda m: f"\n{numero_por_extenso(int(m.group(1)))}. ", texto)
    texto = _RE_LISTA.sub("\n", texto)
    # dois pares de grupos: asterisco (2) e underscore com borda (4)
    texto = _RE_ENFASE.sub(lambda m: m.group(2) if m.group(2) is not None else m.group(4), texto)
    texto = _RE_CODIGO_INLINE.sub(lambda m: m.group(1), texto)
    texto = _RE_HTML.sub(" ", texto)
    # parênteses viram vírgulas: o modelo não fala o parêntese, mas a pausa ajuda
    texto = re.sub(r"\s*\(([^)]{1,120})\)", r", \1,", texto)
    texto = re.sub(r",\s*,", ",", texto)
    texto = limpar_simbolos(texto)
    texto = pontuar_linhas(texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


# --------------------------------------------------------------------- frases

_RE_FIM_FRASE = re.compile(r"(?<=[.!?])\s+")
"""Fim de frase de verdade. ``;`` ficou de fora de propósito: ele separa
orações, não frases, e partir ali entrega ao modelo um trecho que começa em
minúscula e sem sujeito — lido com entonação de frase inteira."""

_RE_ORACAO = re.compile(r"(?<=[,;:])\s+")
"""Pontos de corte quando a frase passa do máximo, do respiro mais forte para o
mais fraco. Dois-pontos e ponto-e-vírgula entram aqui, não no fim de frase."""

_RE_ESPACO = re.compile(r"\s+")
"""Último recurso: frase longa sem nenhuma pontuação ainda precisa ser partida,
senão chega inteira ao modelo — que atropela e acelera."""


MARCA_PARAGRAFO = "¶"
"""Sufixo invisível na última frase de cada parágrafo, para o motor saber onde
dar o respiro maior. É removido antes de o texto chegar ao modelo."""


def dividir_em_frases(
    texto: str, maximo: int = 240, marcar_paragrafos: bool = False
) -> list[str]:
    """Quebra em unidades faladas. Frase longa demais vira orações, para o motor
    começar a falar cedo e para o modelo não se perder na geração."""
    if marcar_paragrafos and "\n\n" in texto:
        frases: list[str] = []
        for paragrafo in texto.split("\n\n"):
            do_paragrafo = dividir_em_frases(paragrafo, maximo)
            if do_paragrafo:
                do_paragrafo[-1] += MARCA_PARAGRAFO
                frases.extend(do_paragrafo)
        return frases

    frases = []
    for bruta in _RE_FIM_FRASE.split(texto):
        bruta = bruta.strip()
        if not bruta:
            continue
        if len(bruta) <= maximo:
            frases.append(bruta)
            continue
        frases.extend(_partir(bruta, maximo))
    return [f for f in frases if any(c.isalnum() for c in f)]


def _partir(bruta: str, maximo: int) -> list[str]:
    """Parte uma frase comprida em pedaços faláveis.

    Tenta primeiro os respiros naturais (vírgula, ponto-e-vírgula, dois-pontos);
    se um pedaço ainda passar do máximo — frase longa sem pontuação alguma —,
    parte no espaço. Uma frase de 200 caracteres entregue inteira ao Pocket sai
    atropelada, e é aí que a fala parece acelerar sem motivo.
    """
    pedacos: list[str] = []
    atual = ""
    for parte in _RE_ORACAO.split(bruta):
        if len(atual) + len(parte) + 1 > maximo and atual:
            pedacos.append(atual.strip())
            atual = parte
        else:
            atual = f"{atual} {parte}".strip()
    if atual:
        pedacos.append(atual.strip())

    final: list[str] = []
    for pedaco in pedacos:
        if len(pedaco) <= maximo:
            final.append(pedaco)
            continue
        atual = ""
        for palavra in _RE_ESPACO.split(pedaco):
            if len(atual) + len(palavra) + 1 > maximo and atual:
                final.append(atual.strip())
                atual = palavra
            else:
                atual = f"{atual} {palavra}".strip()
        if atual:
            final.append(atual.strip())
    return final


# ------------------------------------------------------------------ resultado


@dataclass
class TextoPreparado:
    texto: str
    frases: list[str] = field(default_factory=list)
    titulo: str = ""


def preparar(texto: str, cfg: Config | None = None) -> TextoPreparado:
    """Pipeline completo: markdown → prosa → identificadores → léxico → números."""
    cfg = cfg or Config.carregar()
    titulo = ""
    m = _RE_TITULO.search(texto)
    if m:
        titulo = m.group(2).strip()

    prosa = markdown_para_prosa(texto, cfg)
    prosa = separar_sigla_de_numero(prosa)
    prosa = separar_identificadores(prosa)
    prosa = aplicar_lexico(prosa)
    prosa = expandir_numeros(prosa)
    # a quebra de parágrafo sobrevive até a divisão em frases, para o motor saber
    # onde dar o respiro maior; só depois o texto é achatado
    prosa = re.sub(r"[ \t]+", " ", prosa)
    prosa = re.sub(r"\n{2,}", "\n\n", prosa).strip()
    frases = dividir_em_frases(prosa, cfg.max_caracteres_por_frase, marcar_paragrafos=True)
    return TextoPreparado(
        texto=re.sub(r"\s+", " ", prosa).strip(), frases=frases, titulo=titulo
    )
