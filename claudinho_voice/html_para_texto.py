"""Converte HTML (um artefato do Claude, uma página salva) em markdown simples.

O preparador já sabe falar markdown — títulos, listas, tabelas, blocos de código.
Então a conversão mira o markdown, não prosa direta, e reaproveita tudo que já
foi medido lá. Só a biblioteca padrão: sem dependência nova.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

# "head" fica de fora da lista: é onde mora o <title>, que vira o nome anunciado.
# Só entram aqui elementos COM tag de fechamento: o controle é um contador que
# sobe no início e desce no fim. Um elemento vazio (<meta>, <link>) aqui dentro
# subiria o contador para sempre e engoliria a página inteira — aconteceu.
_IGNORAR = {"script", "style", "noscript", "svg", "template", "iframe", "canvas"}
_VAZIOS = {"meta", "link", "img", "input", "source", "track", "wbr", "area", "base", "col", "embed", "param"}
_BLOCOS = {"p", "div", "section", "article", "main", "header", "footer", "aside", "nav", "blockquote", "figure", "figcaption", "details", "summary"}
_TITULOS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


class _Conversor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self._ignorando = 0
        self._em_pre = False
        self._em_tabela = False
        self._linha_tabela: list[str] = []
        self._celula: list[str] | None = None
        self._linhas_tabela = 0
        self._lista: list[str] = []
        self._item_num: list[int] = []
        self._titulo_pagina: list[str] | None = None
        self.titulo = ""

    # -------------------------------------------------------------- utilidades

    def _quebra(self, n: int = 1) -> None:
        texto = "".join(self.partes)
        faltam = n - (len(texto) - len(texto.rstrip("\n")))
        if faltam > 0:
            self.partes.append("\n" * faltam)

    def _escrever(self, texto: str) -> None:
        if self._celula is not None:
            self._celula.append(texto)
        else:
            self.partes.append(texto)

    # ----------------------------------------------------------------- eventos

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _VAZIOS:
            return
        if tag in _IGNORAR:
            self._ignorando += 1
            return
        if self._ignorando:
            return
        if tag == "title":
            self._titulo_pagina = []
        elif tag in _TITULOS:
            self._quebra(2)
            self._escrever("#" * _TITULOS[tag] + " ")
        elif tag == "pre":
            self._quebra(2)
            self._escrever("```\n")
            self._em_pre = True
        elif tag == "br":
            self._escrever("\n")
        elif tag in ("ul", "ol"):
            self._quebra(1)
            self._lista.append(tag)
            self._item_num.append(0)
        elif tag == "li":
            self._quebra(1)
            if self._lista and self._lista[-1] == "ol":
                self._item_num[-1] += 1
                self._escrever(f"{self._item_num[-1]}. ")
            else:
                self._escrever("- ")
        elif tag == "table":
            self._quebra(2)
            self._em_tabela = True
            self._linhas_tabela = 0
        elif tag == "tr" and self._em_tabela:
            self._linha_tabela = []
        elif tag in ("td", "th") and self._em_tabela:
            self._celula = []
        elif tag in _BLOCOS:
            self._quebra(2 if tag in ("p", "blockquote") else 1)
        elif tag == "hr":
            self._quebra(2)

    def handle_endtag(self, tag: str) -> None:
        if tag in _IGNORAR:
            self._ignorando = max(0, self._ignorando - 1)
            return
        if self._ignorando:
            return
        if tag == "title" and self._titulo_pagina is not None:
            self.titulo = " ".join("".join(self._titulo_pagina).split())
            self._titulo_pagina = None
        elif tag in _TITULOS:
            self._quebra(2)
        elif tag == "pre":
            self._em_pre = False
            self._quebra(1)
            self._escrever("```\n\n")
        elif tag in ("ul", "ol"):
            if self._lista:
                self._lista.pop()
                self._item_num.pop()
            self._quebra(2)
        elif tag == "li":
            self._quebra(1)
        elif tag in ("td", "th") and self._celula is not None:
            self._linha_tabela.append(" ".join("".join(self._celula).split()))
            self._celula = None
        elif tag == "tr" and self._em_tabela and self._linha_tabela:
            self.partes.append("| " + " | ".join(self._linha_tabela) + " |\n")
            self._linhas_tabela += 1
            if self._linhas_tabela == 1:
                self.partes.append("|" + "---|" * len(self._linha_tabela) + "\n")
            self._linha_tabela = []
        elif tag == "table":
            self._em_tabela = False
            self._quebra(2)
        elif tag in _BLOCOS:
            self._quebra(2 if tag in ("p", "blockquote") else 1)

    def handle_data(self, dados: str) -> None:
        if self._ignorando:
            return
        if self._titulo_pagina is not None:
            self._titulo_pagina.append(dados)
            return
        if self._em_pre:
            self._escrever(dados)
            return
        texto = re.sub(r"\s+", " ", dados)
        if texto.strip() or (self.partes and not self.partes[-1].endswith(("\n", " "))):
            self._escrever(texto)


def html_para_markdown(html: str) -> tuple[str, str]:
    """Devolve ``(markdown, titulo)``. Aceita HTML completo ou fragmento."""
    conversor = _Conversor()
    conversor.feed(html)
    conversor.close()
    texto = "".join(conversor.partes)
    texto = unescape(texto)
    texto = re.sub(r"[ \t]+\n", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip(), conversor.titulo


def parece_html(texto: str) -> bool:
    inicio = texto.lstrip()[:400].lower()
    return inicio.startswith("<!doctype") or inicio.startswith("<html") or (
        "<body" in inicio or "<div" in inicio or "<p>" in inicio or "<h1" in inicio
    )
