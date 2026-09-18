<#
Primeira execução do Claudinho's Voice no Windows: acha (ou traz) um Python e
prepara a instalação. Só roda enquanto não existe .venv — depois disso o
bin\cvoice.cmd encaminha direto para o cvoice.exe e este arquivo não é lido.

Por que PowerShell e não .cmd: a lógica de "qual Python serve" não cabe em
batch de forma legível, e o PowerShell 5.1 existe em todo Windows 10/11.

Regras:
- "Python utilizável" = 3.12 ou mais E com ensurepip. Testado EXECUTANDO, não
  pela existência do arquivo: o `python3` de uma máquina limpa costuma ser o
  atalho da Microsoft Store, que existe no PATH e não roda nada.
- Sem Python utilizável, o próprio ativar instala um: o uv (astral.sh) vai
  para %USERPROFILE%\.local\bin sem admin, e `uv python install 3.12` baixa um
  CPython portátil para %APPDATA%\uv\python. O download do uv é feito pelo
  PowerShell (SChannel do Windows), não pelo SSL do Python — que é justamente
  o que antivírus corporativo costuma quebrar.
- Tudo visível: é a primeira vez, a pessoa está olhando. Qualquer etapa que
  falhe para aqui, com a causa. Nunca segue em frente pela metade.
#>
param(
    [Parameter(Mandatory = $true)][string]$Raiz,
    [switch]$SoLocalizar   # só diz qual Python usaria e sai (diagnóstico)
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch {}
$env:PYTHONUTF8 = '1'   # os Pythons do preparo (e os filhos deles) escrevem UTF-8 também por pipe

function Diz([string]$t)   { Write-Host $t }
function Falha([string]$t) { Write-Host "erro: $t"; exit 1 }

$TESTE = 'import sys, ensurepip; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'

function Utilizavel([string[]]$cmd) {
    try {
        $exe = $cmd[0]
        $resto = @(); if ($cmd.Length -gt 1) { $resto = $cmd[1..($cmd.Length - 1)] }
        & $exe @resto -c $TESTE 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function AchaUv {
    foreach ($p in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")) {
        if (Test-Path -LiteralPath $p) { return $p }
    }
    $c = Get-Command uv -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

# 1) Python já instalado, na ordem em que o Windows costuma ter
$candidatos = @(
    @('py', '-3.12'), @('py', '-3'), @('python3'), @('python')
)
$uvDir = Join-Path $env:APPDATA 'uv\python'
if (Test-Path -LiteralPath $uvDir) {
    Get-ChildItem -LiteralPath $uvDir -Directory -Filter 'cpython-3.1[2-9]*' -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        ForEach-Object { $candidatos += ,@((Join-Path $_.FullName 'python.exe')) }
}

$python = $null
foreach ($c in $candidatos) {
    if (Utilizavel $c) { $python = $c; break }
}

# 2) Nenhum serve: o uv traz um
#    O uv é Rust com rustls e raízes próprias: NÃO lê a loja de certificados do
#    Windows, então o CA de um antivírus que intercepta TLS (Kaspersky e afins) é
#    "emissor desconhecido" e o download do Python morre com UnknownIssuer — de
#    forma intermitente, o que é pior. UV_SYSTEM_CERTS faz o uv confiar no que o
#    Windows confia. (UV_NATIVE_TLS é a forma antiga; hoje só emite aviso.)
$env:UV_SYSTEM_CERTS = '1'
if (-not $python) {
    Diz 'nenhum Python 3.12+ utilizável nesta máquina.'
    $uv = AchaUv
    if (-not $uv) {
        Diz 'instalando o uv (gerenciador de Python, sem admin, em %USERPROFILE%\.local\bin)...'
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $env:UV_NO_MODIFY_PATH = '1'   # não mexe no PATH da pessoa; usamos pelo caminho completo
            Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1' | Invoke-Expression
        } catch { Falha "não consegui baixar/instalar o uv: $($_.Exception.Message)" }
        $uv = AchaUv
        if (-not $uv) { Falha 'o instalador do uv terminou mas o uv.exe não apareceu em %USERPROFILE%\.local\bin' }
    }
    Diz 'baixando o Python 3.12 com o uv (uma vez só)...'
    & $uv python install 3.12
    if ($LASTEXITCODE -ne 0) { Falha "'uv python install 3.12' saiu com código $LASTEXITCODE" }
    # --system: sem isto o uv devolve um .venv que exista no diretório — e se este
    # código está rodando, é porque esse .venv não serve
    $achado = (& $uv python find --system 3.12 2>$null | Select-Object -First 1)
    if (-not $achado) { Falha 'o uv instalou o Python mas não consegui localizá-lo (uv python find 3.12)' }
    if (-not (Utilizavel @($achado))) { Falha "o Python do uv ($achado) não passou na checagem (3.12+ com ensurepip)" }
    $python = @($achado)
}

Diz ("usando o Python: " + ($python -join ' '))
if ($SoLocalizar) { exit 0 }

# 3) Preparo síncrono e falante: venv, pip, dependências (com o painel) e voz
$exe = $python[0]
$resto = @(); if ($python.Length -gt 1) { $resto = $python[1..($python.Length - 1)] }
& $exe @resto (Join-Path $Raiz 'bin\cvoice-hook.py') preparar
if ($LASTEXITCODE -ne 0) { Falha "o preparo da instalação falhou (código $LASTEXITCODE); veja as mensagens acima" }
exit 0
