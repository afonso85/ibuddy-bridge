<#
.SYNOPSIS
  Instala (ou remove) o autostart do iBuddy Bridge.

.DESCRIPTION
  Grava um .vbs na pasta Inicializar do Windows que sobe o daemon escondido,
  sem janela, a cada logon. Os caminhos (projeto e Python) sao resolvidos
  nesta maquina - nada fica fixo no repositorio.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1 -Remove
#>
param([switch]$Remove)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$target  = Join-Path ([Environment]::GetFolderPath("Startup")) "iBuddyBridge.vbs"

if ($Remove) {
    if (Test-Path $target) {
        Remove-Item $target
        Write-Host "Autostart removido: $target"
    } else {
        Write-Host "Nada a remover ($target nao existe)."
    }
    return
}

$python = (Get-Command python -ErrorAction Stop).Source
$daemon = Join-Path $project "run_daemon.py"
if (-not (Test-Path $daemon)) { throw "run_daemon.py nao encontrado em $project" }

$vbs = @"
' Gerado por scripts/install-autostart.ps1 - sobe o daemon do iBuddy Bridge sem janela.
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "$project"
shell.Run """$python"" ""$daemon""", 0, False
"@

# UTF-16 (com BOM): o Windows Script Host le caminhos com acento corretamente
Set-Content -Path $target -Value $vbs -Encoding Unicode

Write-Host "Autostart instalado: $target"
Write-Host "  Python : $python"
Write-Host "  Daemon : $daemon"
Write-Host "Para iniciar agora, sem reiniciar o Windows:  cscript //nologo `"$target`""
Write-Host "Para remover:  powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1 -Remove"
