<#
.SYNOPSIS
    Instala o Claudinho's Voice: venv, dependências, certificado corporativo,
    pesos do modelo, skill e hook do Claude Code.

.DESCRIPTION
    Tudo local. Nenhum passo manual, nenhum serviço externo.
    Rode de dentro da pasta do projeto:  pwsh -File install.ps1
#>
[CmdletBinding()]
param(
    [switch]$SemHook,      # não registra o hook Stop no Claude Code
    [switch]$SemSkill,     # não instala a skill /cvoice
    [switch]$SemInicializar # não registra a inicialização automática com o Windows
)

$ErrorActionPreference = 'Stop'
$raiz = $PSScriptRoot
$venv = Join-Path $raiz '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
$pastaUsuario = Join-Path $HOME '.claudinho-voice'

function Passo($texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }
function Ok($texto) { Write-Host "    $texto" -ForegroundColor DarkGray }

# ---------------------------------------------------------------- 1. ambiente
Passo 'Verificando o ambiente'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv não encontrado no PATH. Instale com: winget install --id astral-sh.uv"
}
Ok "uv: $((uv --version) -join '')"

# ------------------------------------------------- 2. certificado corporativo
# O antivírus desta máquina (Kaspersky) intercepta TLS, então o certifi puro não
# valida huggingface.co. Exportamos a cadeia vista na conexão real e juntamos ao
# bundle do certifi; sem isso o download dos pesos falha com CERTIFICATE_VERIFY_FAILED.
Passo 'Montando o bundle de certificados'
$certs = Join-Path $raiz 'certs'
New-Item -ItemType Directory -Force -Path $certs | Out-Null
$caCorp = Join-Path $certs 'ca-corp.pem'

$tcp = [Net.Sockets.TcpClient]::new('huggingface.co', 443)
$ssl = [Net.Security.SslStream]::new($tcp.GetStream(), $false, { $true })
$ssl.AuthenticateAsClient('huggingface.co')
$folha = [Security.Cryptography.X509Certificates.X509Certificate2]::new($ssl.RemoteCertificate)
$cadeia = [Security.Cryptography.X509Certificates.X509Chain]::new()
$cadeia.ChainPolicy.RevocationMode = 'NoCheck'
$null = $cadeia.Build($folha)
$pem = ''
foreach ($elo in $cadeia.ChainElements) {
    $c = $elo.Certificate
    if ($c.Subject -ne $folha.Subject) {
        $b64 = [Convert]::ToBase64String($c.RawData, 'InsertLineBreaks')
        $pem += "-----BEGIN CERTIFICATE-----`n$b64`n-----END CERTIFICATE-----`n"
    }
}
[IO.File]::WriteAllText($caCorp, $pem)
$ssl.Dispose(); $tcp.Dispose()
Ok "cadeia exportada ($([IO.FileInfo]::new($caCorp).Length) bytes)"

# ------------------------------------------------------------------ 3. venv
Passo 'Criando o ambiente virtual e instalando dependências'
if (-not (Test-Path $python)) { uv venv --python 3.12 $venv | Out-Null }
uv pip install --python $python --index-strategy unsafe-best-match `
    --extra-index-url https://download.pytorch.org/whl/cpu -e "$raiz[dev]" | Out-Null
Ok 'dependências instaladas (torch CPU)'

$certifi = & $python -c "import certifi; print(certifi.where())"
$bundle = Join-Path $certs 'ca-bundle.pem'
Get-Content $certifi, $caCorp | Set-Content -Path $bundle -Encoding utf8
Ok "bundle: $bundle"

# ---------------------------------------------------- 4. pasta do usuário
Passo 'Preparando a pasta do usuário'
New-Item -ItemType Directory -Force -Path $pastaUsuario | Out-Null
$lexicoUsuario = Join-Path $pastaUsuario 'lexico.json'
if (-not (Test-Path $lexicoUsuario)) {
    @'
{
  "_comentario": "Seu léxico. Acrescente aqui; o padrão do pacote continua valendo.",
  "soletrar": {},
  "palavra": [],
  "substituir": {}
}
'@ | Set-Content -Path $lexicoUsuario -Encoding utf8
}
Ok $pastaUsuario

# ------------------------------------------------------------- 5. modelo
Passo 'Baixando e carregando o modelo (Pocket TTS, português, voz rafael)'
$env:SSL_CERT_FILE = $bundle
$env:REQUESTS_CA_BUNDLE = $bundle
& $python -c @"
from claudinho_voice.motor import Motor
from claudinho_voice import preenchimentos
m = Motor(); m.carregar(); print('    modelo pronto')
n = preenchimentos.gerar(m)
print(f'    {n} frases de espera pre-geradas')
"@
Ok 'modelo em cache (~/.cache/huggingface)'

# -------------------------------------------------------------- 6. skill
if (-not $SemSkill) {
    Passo 'Instalando a skill /cvoice no Claude Code'
    $destino = Join-Path $HOME '.claude\skills\cvoice'
    New-Item -ItemType Directory -Force -Path $destino | Out-Null
    Copy-Item (Join-Path $raiz 'skill\SKILL.md') $destino -Force
    Ok $destino
}

# --------------------------------------------------------------- 7. hook
if (-not $SemHook) {
    Passo 'Registrando o hook Stop no Claude Code'
    $settings = Join-Path $HOME '.claude\settings.json'
    $config = if (Test-Path $settings) {
        Get-Content $settings -Raw | ConvertFrom-Json
    } else { [pscustomobject]@{} }

    if (-not $config.PSObject.Properties['hooks']) {
        $config | Add-Member -NotePropertyName hooks -NotePropertyValue ([pscustomobject]@{})
    }
    # Stop: lê a resposta final. UserPromptSubmit: injeta o contrato de fala,
    # para o Claude responder como quem conversa enquanto o modo voz está ligado.
    $eventos = @{
        'Stop'             = @{ modulo = 'claudinho_voice.hook';             timeout = 10 }
        'UserPromptSubmit' = @{ modulo = 'claudinho_voice.hook_prompt';      timeout = 5 }
        'PreToolUse'       = @{ modulo = 'claudinho_voice.hook_trabalhando'; timeout = 5 }
    }
    foreach ($evento in $eventos.Keys) {
        $spec = $eventos[$evento]
        $entrada = [pscustomobject]@{
            matcher = ''
            hooks   = @([pscustomobject]@{
                type    = 'command'
                command = "`"$python`" -m $($spec.modulo)"
                timeout = $spec.timeout
            })
        }
        $existentes = @()
        if ($config.hooks.PSObject.Properties[$evento]) {
            $existentes = @($config.hooks.$evento | Where-Object {
                -not (($_ | ConvertTo-Json -Depth 6) -match 'claudinho_voice')
            })
        }
        $config.hooks | Add-Member -NotePropertyName $evento -NotePropertyValue (@($existentes) + $entrada) -Force
    }

    Copy-Item $settings "$settings.bak" -Force -ErrorAction SilentlyContinue
    $config | ConvertTo-Json -Depth 12 | Set-Content -Path $settings -Encoding utf8
    Ok "hooks Stop e UserPromptSubmit registrados (backup em settings.json.bak)"
    Ok 'a leitura automática começa desligada: use  cvoice auto on'
}

# ------------------------------------------------------- 8. inicialização
if (-not $SemInicializar) {
    Passo 'Registrando a inicialização automática com o Windows'
    $pastaInicializar = [Environment]::GetFolderPath('Startup')
    $atalho = Join-Path $pastaInicializar 'Claudinho Voice.lnk'
    $pythonw = Join-Path $venv 'Scripts\pythonw.exe'
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($atalho)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = '-m claudinho_voice.servico'
    $lnk.WorkingDirectory = $raiz
    $lnk.Description = "Claudinho's Voice"
    $lnk.Save()
    Ok $atalho
}

Passo 'Pronto'
Write-Host @"
    Comandos:
      cvoice testar              fala uma frase de teste
      cvoice ler ARQUIVO.md      lê um arquivo
      cvoice auto on|off         liga/desliga a leitura das respostas do Claude Code
      cvoice parar               cala agora
      cvoice estado              mostra o que está lendo
      cvoice dispositivos        lista as saídas de áudio

    O executável está em: $venv\Scripts\cvoice.exe
    Para chamar só 'cvoice', adicione essa pasta ao PATH.
"@ -ForegroundColor Green
