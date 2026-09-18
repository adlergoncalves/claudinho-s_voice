<#
.SYNOPSIS
    Instala o Claudinho's Voice a partir de um clone, do zero ao áudio tocando.

.DESCRIPTION
    Casca fina sobre o mesmo preparo que o plugin do Claude Code usa na primeira
    ativação — não existe um segundo caminho de instalação para divergir.

    O que acontece, nesta ordem, tudo visível:
      1. acha um Python 3.12+ utilizável; se não houver, instala um (uv, sem admin);
      2. cria o .venv e instala as dependências, com o painel e o Kokoro;
      3. baixa as três vozes pt-BR do Piper e o modelo Kokoro;
      4. TOCA uma frase de teste — a prova de que funciona é ouvir.

    Nada além da pasta do projeto e de %USERPROFILE%\.claudinho-voice é tocado:
    sem atalho, sem inicialização automática, sem mexer no PATH nem no Claude Code.

    Quem instala como PLUGIN não precisa disto: "ativa a voz" faz o mesmo.

    Rode de dentro da pasta do projeto:  powershell -File install.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$raiz = $PSScriptRoot

if (-not (Test-Path (Join-Path $raiz 'pyproject.toml'))) {
    Write-Host 'erro: rode este script de dentro da pasta do projeto (onde está o pyproject.toml)'
    exit 1
}

# o powershell 5.1 herda o PSModulePath de um pwsh 7 que o tenha lançado e
# carrega um módulo Security incompatível; vazio, reconstrói o padrão dele
$env:PSModulePath = ''

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $raiz 'bin\primeira-execucao.ps1') -Raiz $raiz
if ($LASTEXITCODE -ne 0) {
    Write-Host 'a instalação parou; a causa está nas mensagens acima'
    exit $LASTEXITCODE
}

Write-Host ''
Write-Host 'Pronto. O executável é:'
Write-Host "  $raiz\.venv\Scripts\cvoice.exe"
Write-Host ''
Write-Host 'Uso:'
Write-Host '  cvoice ativar             liga a voz nesta sessão do Claude Code e abre o painel'
Write-Host '  cvoice ler ARQUIVO.md     lê um arquivo'
Write-Host '  cvoice testar             fala uma frase de teste'
Write-Host '  cvoice parar              cala agora'
Write-Host '  cvoice dispositivos       lista as saídas de áudio'
exit 0
