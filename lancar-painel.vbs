' Lançador silencioso do painel.
'
' Duas armadilhas empilhadas, ambas descobertas na marra:
'
' 1. O Windows Terminal, quando é o terminal padrão do sistema, intercepta
'    qualquer processo de console e abre uma aba preta — trazendo junto as
'    outras abas do perfil, inclusive o Teams. O Windows Script Host não aloca
'    console nenhum, então o atalho passa por aqui.
'
' 2. O .venv é gerido pelo uv, e o pythonw.exe dele NÃO é um Python: é um
'    lançador que chama o python.exe base, COM console. Por isso se chama aqui
'    o pythonw do Python base (lido de pyvenv.cfg) e se aponta o ambiente pelo
'    VIRTUAL_ENV — o console nasceria antes de qualquer código nosso rodar.

Option Explicit

Dim fso, shell, raiz, cfg, linha, home, pythonw, venv

Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

raiz = fso.GetParentFolderName(WScript.ScriptFullName)
venv = raiz & "\.venv"

' home = onde mora o Python base deste venv
home = ""
' o pyvenv.cfg do uv usa quebra de linha do Unix: normaliza antes de dividir
For Each linha In Split(Replace(Replace(fso.OpenTextFile(venv & "\pyvenv.cfg", 1).ReadAll, vbCrLf, vbLf), vbCr, vbLf), vbLf)
    If Left(LCase(Trim(linha)), 5) = "home " Or Left(LCase(Trim(linha)), 5) = "home=" Then
        home = Trim(Mid(linha, InStr(linha, "=") + 1))
    End If
Next

pythonw = home & "\pythonw.exe"
If home = "" Or Not fso.FileExists(pythonw) Then
    pythonw = venv & "\Scripts\pythonw.exe"   ' venv comum, sem uv
End If

' o VIRTUAL_ENV faz o Python base enxergar os pacotes do venv
shell.Environment("PROCESS")("VIRTUAL_ENV") = venv
shell.Environment("PROCESS")("PYTHONPATH") = venv & "\Lib\site-packages"
shell.CurrentDirectory = raiz
shell.Run """" & pythonw & """ -m claudinho_voice.painel", 0, False
