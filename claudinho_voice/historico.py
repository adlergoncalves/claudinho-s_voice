"""Memória do que já foi falado, por sessão.

Dá continuidade à conversa: "repete", "repete a última parte", "o que você
disse mesmo?". Sem isto, o áudio acabou e a informação sumiu — a diferença
entre um leitor e um assistente de voz.

Cada item guardado é o texto original (antes do preparador), porque é ele que
a pessoa quer ouvir de novo, com as frases já divididas para poder repetir só
o final.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import PASTA_USUARIO

ARQUIVO = PASTA_USUARIO / "historico.json"
MAX_ITENS = 30


@dataclass
class ItemFalado:
    texto: str
    titulo: str
    quando: float = field(default_factory=time.time)
    frases: list[str] = field(default_factory=list)
    sessao: str = ""

    @property
    def idade_min(self) -> float:
        return (time.time() - self.quando) / 60


def _carregar() -> list[ItemFalado]:
    if not ARQUIVO.exists():
        return []
    try:
        dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    itens = []
    for d in dados:
        try:
            itens.append(ItemFalado(**d))
        except TypeError:
            continue
    return itens


def _salvar(itens: list[ItemFalado]) -> None:
    try:
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        ARQUIVO.write_text(
            json.dumps([asdict(i) for i in itens[-MAX_ITENS:]], ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def registrar(texto: str, titulo: str, frases: list[str], sessao: str = "") -> None:
    itens = _carregar()
    itens.append(ItemFalado(texto=texto, titulo=titulo, frases=frases, sessao=sessao))
    _salvar(itens)


def ultimo(sessao: str = "") -> ItemFalado | None:
    """O último item falado; filtra por sessão quando informada."""
    itens = _carregar()
    if sessao:
        da_sessao = [i for i in itens if i.sessao == sessao]
        if da_sessao:
            return da_sessao[-1]
    return itens[-1] if itens else None


def ultimos(quantidade: int = 5, sessao: str = "") -> list[ItemFalado]:
    itens = _carregar()
    if sessao:
        itens = [i for i in itens if i.sessao == sessao] or itens
    return itens[-quantidade:]


def trecho_final(item: ItemFalado, frases: int = 3) -> str:
    """As últimas frases de um item — para "repete a última parte"."""
    if not item.frases:
        return item.texto
    return " ".join(item.frases[-frases:])
