# -*- coding: utf-8 -*-
"""Funde no léxico do produto o que a medição aprovou.

Lê um ou mais resultados de ``medir_pronuncia.py`` e grava em
``claudinho_voice/lexico_padrao.json``:

* ``vencedores`` → entram (ou substituem) na seção ``pronuncia``;
* ``ja_certo``   → se o termo estava na ``pronuncia``, **sai**: o cru já acerta e
  a grafia só pode piorar (medido: ``sharepoint``, ``azure``, ``release``).

``sem_solucao`` não é tocado — fica para IPA ou para o ouvido do Adler.

Uso::

    python eval/aplicar_pronuncia.py eval/resultados/pronuncia-cadu-2026-09-17*.json
    python eval/aplicar_pronuncia.py resultado.json --dry-run
"""

from __future__ import annotations

import argparse
import collections
import glob
import io
import json
from pathlib import Path

LEXICO = Path(__file__).resolve().parent.parent / "claudinho_voice" / "lexico_padrao.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("resultados", nargs="+", help="JSON(s) do medir_pronuncia.py; aceita glob")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    arquivos = [p for padrao in args.resultados for p in glob.glob(padrao)]
    if not arquivos:
        parser.error("nenhum resultado encontrado")

    lexico = json.loads(
        io.open(LEXICO, encoding="utf-8").read(), object_pairs_hook=collections.OrderedDict
    )
    pronuncia = lexico.setdefault("pronuncia", collections.OrderedDict())
    entraram, removidos = {}, []
    for arquivo in arquivos:
        r = json.loads(Path(arquivo).read_text(encoding="utf-8"))
        for termo, dado in r.get("vencedores", {}).items():
            pronuncia[termo.lower()] = dado["grafia"]
            entraram[termo] = dado["grafia"]
        for termo in r.get("ja_certo", {}):
            if pronuncia.pop(termo.lower(), None) is not None:
                removidos.append(termo)

    lexico["pronuncia"] = collections.OrderedDict(sorted(pronuncia.items()))
    print(f"entraram/atualizados ({len(entraram)}): {entraram}")
    print(f"removidos por já saírem certos ({len(removidos)}): {removidos}")
    print(f"pronuncia agora tem {len(lexico['pronuncia'])} verbetes")
    if args.dry_run:
        return
    io.open(LEXICO, "w", encoding="utf-8", newline="").write(
        json.dumps(lexico, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"→ {LEXICO}")


if __name__ == "__main__":
    main()
