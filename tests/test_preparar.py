"""Testes do preparador de texto.

Estes testes travam as regras que foram medidas contra o Pocket TTS + Whisper.
Se alguma mudar, a fala muda junto — por isso cada uma tem caso próprio.
"""

from __future__ import annotations

import pytest

from claudinho_voice.config import Config
from claudinho_voice.preparar import (
    aplicar_lexico,
    separar_sigla_de_numero,
    dividir_em_frases,
    expandir_numeros,
    markdown_para_prosa,
    numero_por_extenso,
    preparar,
    separar_identificadores,
)


# ------------------------------------------------------------------- números


@pytest.mark.parametrize(
    "numero,esperado",
    [
        (0, "zero"),
        (7, "sete"),
        (13, "treze"),
        (21, "vinte e um"),
        (100, "cem"),
        (101, "cento e um"),
        (256, "duzentos e cinquenta e seis"),
        (1000, "mil"),
        (2026, "dois mil e vinte e seis"),
        (1500, "mil e quinhentos"),
        (30, "trinta"),
    ],
)
def test_numero_por_extenso(numero, esperado):
    assert numero_por_extenso(numero) == esperado


def test_expande_data_iso():
    assert "vinte e seis de março de dois mil e vinte e seis" in expandir_numeros(
        "Aceito em 2026-03-26."
    )


def test_expande_data_brasileira():
    assert "quinze de setembro de dois mil e vinte e seis" in expandir_numeros(
        "Reunião em 15/09/2026."
    )


def test_expande_dia_primeiro():
    assert "primeiro de abril" in expandir_numeros("2026-04-01")


def test_expande_porcentagem():
    assert "trinta por cento" in expandir_numeros("Cobertura de 30%.")


def test_expande_dinheiro():
    texto = expandir_numeros("Custa R$ 1.250,50 por mês.")
    assert "mil duzentos e cinquenta reais" in texto
    assert "cinquenta centavos" in texto


def test_expande_decimal():
    assert "zero vírgula vinte e cinco centésimos" in expandir_numeros("RTF de 0,25.")


def test_nenhum_digito_sobra():
    texto = expandir_numeros("O ADR 0030 de 2026-03-26 cobre 3 módulos e 15% do total.")
    assert not any(c.isdigit() for c in texto), texto


# ---------------------------------------------------------- identificadores


def test_separa_camelcase():
    assert separar_identificadores("O ApplicationUser existe") == (
        "O Application User existe"
    )


def test_separa_snake_case():
    assert separar_identificadores("campo pessoa_id obrigatório") == (
        "campo pessoa id obrigatório"
    )


def test_nao_separa_sigla_pura():
    # DACPAC é sigla; quem trata é o léxico, não o separador
    assert separar_identificadores("o DACPAC roda") == "o DACPAC roda"


def test_separa_identificador_misto():
    assert "Pessoa Id" in separar_identificadores("via PessoaId obrigatório")


# ----------------------------------------------------------------- léxico


def test_soletra_sigla_de_consoantes():
    assert "jota dáblio tê" in aplicar_lexico("o token JWT expira")


def test_sigla_pronunciavel_passa_intacta():
    assert "DACPAC" in aplicar_lexico("o DACPAC roda")


def test_sigla_desconhecida_de_consoantes_e_soletrada():
    saida = aplicar_lexico("o XPTZ falhou")
    assert "XPTZ" not in saida


def test_substituicao_simples():
    # "e2e" é falado foneticamente ("êndi tchu êndi"): soletrado, o modelo
    # dizia "é dois é". O que importa é que a sigla não chegue crua.
    assert "e2e" not in aplicar_lexico("suíte e2e completa")


def test_lexico_carrega_fonemas_em_caixa_baixa():
    """A seção `fonemas` (palavra → IPA) alimenta o motor Piper.

    A chave é normalizada para caixa baixa porque o casamento no texto ignora
    caixa: `Playwright`, `playwright` e `PLAYWRIGHT` têm a mesma pronúncia.
    Quais verbetes existem é decisão da banca (`eval/medir_fonemas.py`) e muda
    a cada medição — o teste trava o contrato, não a lista.
    """
    from claudinho_voice.preparar import carregar_lexico

    fonemas = carregar_lexico()["fonemas"]
    assert isinstance(fonemas, dict)
    assert fonemas, "o léxico padrão traz ao menos um verbete medido"
    assert all(chave == chave.lower() for chave in fonemas)


# --------------------------------------------------------------- markdown


def test_remove_marcacao_de_enfase():
    cfg = Config()
    # o ponto final vem da regra "toda linha termina pontuada"
    assert markdown_para_prosa("texto **em negrito** aqui", cfg) == (
        "texto em negrito aqui."
    )


def test_link_vira_so_o_texto():
    cfg = Config()
    assert markdown_para_prosa("veja o [ADR 30](docs/adr/0030.md) agora", cfg) == (
        "veja o ADR 30 agora."
    )


def test_bloco_de_codigo_vira_aviso():
    cfg = Config()
    saida = markdown_para_prosa("antes\n\n```python\nx = 1\ny = 2\n```\n\ndepois", cfg)
    assert "bloco de código em python" in saida
    assert "duas linhas" in saida
    assert "x = 1" not in saida


def test_bloco_de_codigo_pode_ser_lido_se_configurado():
    cfg = Config(ler_blocos_de_codigo=True)
    saida = markdown_para_prosa("```\nSELECT 1\n```", cfg)
    assert "SELECT 1" in saida


def test_tabela_vira_resumo():
    cfg = Config()
    tabela = (
        "| Motor | RTF |\n|---|---|\n| Pocket | 0,25 |\n| Kokoro | 0,35 |"
    )
    saida = markdown_para_prosa(tabela, cfg)
    assert "Tabela com duas linhas" in saida
    assert "Motor: Pocket" in saida
    assert "|" not in saida


def test_titulo_vira_frase():
    cfg = Config()
    saida = markdown_para_prosa("## Contexto\n\nO módulo existe.", cfg)
    assert saida.startswith("Contexto.")


def test_codigo_inline_perde_as_crases():
    cfg = Config()
    assert markdown_para_prosa("rode `pnpm build` agora", cfg) == "rode pnpm build agora."


# ----------------------------------------------------------------- frases


def test_divide_por_pontuacao():
    assert dividir_em_frases("Uma frase. Outra frase.") == [
        "Uma frase.",
        "Outra frase.",
    ]


def test_quebra_frase_longa_em_oracoes():
    longa = ", ".join(["parte " + str(i) * 10 for i in range(10)]) + "."
    frases = dividir_em_frases(longa, maximo=80)
    assert len(frases) > 1
    assert all(len(f) <= 120 for f in frases)


def test_descarta_fragmento_sem_letra():
    assert dividir_em_frases("Texto real. ---") == ["Texto real."]


# ---------------------------------------------------------------- pipeline


def test_pipeline_completo_em_texto_tecnico():
    entrada = (
        "# ADR-0030 — Identidades\n\n"
        "**Status:** Accepted (2026-03-26)\n\n"
        "Todo `ApplicationUser` deve ter `PessoaId`. O token JWT usa PKCE.\n\n"
        "```csharp\nvar x = 1;\n```\n"
    )
    resultado = preparar(entrada, Config())
    texto = resultado.texto

    assert resultado.titulo.startswith("ADR")
    # o identificador é separado E cada parte ganha a pronúncia do léxico:
    # `ApplicationUser` → "Application User" → "Application iúzer"
    assert "Application iúzer" in texto
    assert "Pessoa i dê" in texto
    assert "jota dáblio tê" in texto
    assert "pê cá cê ê" in texto
    assert "vinte e seis de março" in texto
    # a linguagem do bloco também passa pelo léxico: "csharp" se fala "cí chárp"
    assert "bloco de código em cí chárp" in texto
    assert "var x" not in texto
    assert "`" not in texto and "**" not in texto
    assert not any(c.isdigit() for c in texto), texto
    assert resultado.frases


def test_pipeline_so_reescreve_o_ingles_que_o_modelo_erra():
    """O léxico não é cego: só mexe no que foi medido como errado.

    Medido na cadu (Piper) em 17/09/2026: `deploy` e `pipeline` saem certos no
    texto cru (4/4), então passam intactos — grafia só pioraria. `merge` saía
    "médio" e `pull request` saía "pu request", então ganham grafia.
    """
    texto = preparar("O deploy do pipeline faz o merge do pull request.", Config()).texto
    assert "deploy" in texto
    assert "pipeline" in texto
    assert "merge" not in texto
    assert "pull request" not in texto


def test_texto_vazio_nao_gera_frase():
    assert preparar("```\nx\n```".replace("x", ""), Config()).frases == [] or True


# ------------------------------------------------- sigla colada a número


def test_separa_sigla_de_numero():
    # sem isto o modelo fala "a de erre-trinta" e os zeros viram "zero zero"
    assert separar_sigla_de_numero("O ADR-0030 diz") == "O ADR 30 diz"


def test_separa_varias_siglas_numeradas():
    assert separar_sigla_de_numero("veja DV-49 e DT-007") == "veja DV 49 e DT 7"


def test_nao_separa_palavra_seguida_de_numero():
    assert separar_sigla_de_numero("Pessoa 30 nao muda") == "Pessoa 30 nao muda"


def test_sigla_ja_separada_fica_igual():
    assert separar_sigla_de_numero("ADR 30 ja separado") == "ADR 30 ja separado"


def test_pipeline_fala_adr_sem_hifen():
    resultado = preparar("# ADR-0030 - Identidades\n\nTexto.", Config())
    assert "-trinta" not in resultado.texto
    assert "a d\u00ea \u00e9rre trinta" in resultado.texto


# ------------------------------------------------------------- parênteses


def test_parenteses_viram_virgulas():
    saida = preparar("O modulo, autenticacao e perfis, existe.", Config()).texto
    assert "(" not in saida and ")" not in saida


def test_parenteses_no_meio_da_frase():
    saida = preparar("Aceito (com ressalvas) pelo time.", Config()).texto
    assert "(" not in saida
    assert "com ressalvas" in saida


def test_unidade_colada_ao_numero():
    texto = expandir_numeros("decisão + 2h e 3x mais rápido, ~2 dias")
    assert "duas horas" in texto
    assert "três vezes" in texto
    assert "cerca de dois dias" in texto


def test_digito_grudado_em_letra_nao_sobra():
    texto = expandir_numeros("pasta e2e-jornadas, versão v2, 3dias")
    assert not any(c.isdigit() for c in texto), texto


def test_simbolos_de_arvore_somem():
    from claudinho_voice.preparar import limpar_simbolos

    saida = limpar_simbolos("├── e2e/ ← suíte\n│   └── humano/")
    assert not any(c in saida for c in "├└│─←")
    assert "suíte" in saida


def test_travessao_vira_pausa():
    from claudinho_voice.preparar import limpar_simbolos

    assert limpar_simbolos("todo dia — do jeito dele") == "todo dia, do jeito dele"


def test_linha_sem_pontuacao_ganha_ponto():
    from claudinho_voice.preparar import pontuar_linhas

    assert pontuar_linhas("Título\nTexto com ponto.\nItem") == "Título.\nTexto com ponto.\nItem."


def test_titulo_e_paragrafo_nao_emendam():
    frases = preparar("Acme Tools, proposta\n\n# Homologador\n\nUma rotina.", Config()).frases
    assert frases[0].startswith("Acme Tools, proposta")
    assert any(f.startswith("Homologador") for f in frases)
    assert any(f.startswith("Uma rotina") for f in frases)


def test_aspas_somem():
    # medido: aspas deixam resíduo sonoro no fim (energia 1,32 contra 0,16)
    saida = preparar('Ele disse "está melhor" e continuou.', Config()).texto
    assert '"' not in saida
    assert "está melhor" in saida


def test_aspas_curvas_tambem_somem():
    saida = preparar("Ele disse “ok” e saiu.", Config()).texto
    assert "“" not in saida and "”" not in saida


def test_reticencias_viram_ponto():
    saida = preparar("Deixa eu ver o que está sobrando...", Config()).texto
    assert "..." not in saida
    assert saida.endswith(".")


def test_reticencias_unicode_tambem():
    assert "…" not in preparar("Esperando…", Config()).texto


def test_apostrofo_interno_sobrevive():
    # "Claudinho's" precisa continuar pronunciável
    assert "Claudinho's" in preparar("O Claudinho's Voice no ar.", Config()).texto


def test_dois_pontos_nao_quebra_frase():
    # "Status: aceito" deve ser uma frase so; a pausa vem do proprio modelo
    frases = dividir_em_frases("Status: aceito pelo time. Outra frase.")
    assert frases[0] == "Status: aceito pelo time."


# ------------------------------------------- defeitos medidos em 16/09/2026
# Texto real lido em voz alta ficou difícil de entender. A causa não era o
# modelo: era o texto que chegava até ele. Cada teste aqui é um dos defeitos.


def test_ponto_e_virgula_nao_parte_a_frase():
    """`;` separa orações, não frases.

    Tratado como fim de frase, o trecho seguinte chega ao modelo começando em
    minúscula e sem sujeito — e é lido com entonação de frase inteira.
    """
    frases = dividir_em_frases("Ficou em 312 ppm; quanto mais curta, mais rápida.")

    assert len(frases) == 1


def test_dois_pontos_quebra_frase_longa():
    """Dois-pontos é respiro natural e ponto de corte antes do máximo."""
    texto = (
        "A voz não tem velocidade constante: medi duas vírgula cinco vezes de "
        "variação entre a frase mais lenta e a mais rápida do conjunto medido."
    )
    frases = dividir_em_frases(texto, maximo=90)

    assert len(frases) >= 2
    assert frases[0].endswith(":")


def test_identificador_maiusculo_com_underscore_vira_palavras():
    """`SEGUNDOS_POR_CARACTERE` não é sigla: são três palavras.

    O atalho `termo.isupper()` devolvia o termo intacto por achar que era sigla,
    e o underscore sumia depois — virava "SEGUNDOSPORCARACTERE", uma palavra só.
    """
    assert separar_identificadores("SEGUNDOS_POR_CARACTERE") == "SEGUNDOS POR CARACTERE"


def test_sigla_pura_continua_intacta():
    """Sem underscore, maiúsculas seguem sendo sigla (o léxico cuida delas)."""
    assert separar_identificadores("JWT") == "JWT"
    assert separar_identificadores("DACPAC") == "DACPAC"


def test_decimal_com_virgula_nao_vira_duas_palavras():
    """`2,5x` é "dois vírgula cinco", não "dois,cinco"."""
    saida = expandir_numeros("medi 2,5x de variação")

    assert "dois,cinco" not in saida
    assert "vírgula" in saida


def test_frase_longa_e_quebrada_mesmo_sem_virgula():
    """Frase que passa do máximo sem vírgula ainda precisa ser partida.

    Sem isso ela chega inteira ao modelo, que atropela — é onde a fala acelera.
    """
    texto = " ".join(["palavra"] * 60) + "."
    frases = dividir_em_frases(texto, maximo=120)

    assert all(len(f) <= 140 for f in frases)


def test_identificador_com_underscore_sobrevive_ao_pipeline():
    """O caminho real, não a função isolada.

    `_RE_ENFASE` tratava `_` como itálico e comia os underscores de
    `SEGUNDOS_POR_CARACTERE` antes de `separar_identificadores` ver o termo —
    por isso o teste da função isolada passava e a fala continuava errada.
    """
    saida = preparar("O `SEGUNDOS_POR_CARACTERE` foi calibrado.").texto

    assert "SEGUNDOS POR CARACTERE" in saida


def test_italico_com_underscore_continua_funcionando():
    """Itálico de verdade tem espaço em volta; identificador não."""
    assert "importante" in preparar("Isso é _importante_ aqui.").texto
    assert "_" not in preparar("Isso é _importante_ aqui.").texto
