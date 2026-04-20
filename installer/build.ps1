<#
.SYNOPSIS
    Build the Manalog MSI installer using WiX v4.

.DESCRIPTION
    Requires:
    - WiX Toolset v4 (dotnet tool: dotnet-wix) installed
    - Manalog.exe already built and placed in $SourceDir

.PARAMETER SourceDir
    Directory containing Manalog.exe (output from PyInstaller build).
    Default: dist\

.PARAMETER OutputDir
    Directory to write the .msi to. Default: installer\dist\

.PARAMETER Version
    Override version string (e.g. "0.3.2"). If omitted, WiX reads it
    from the .exe file version via !(bind.fileVersion.*).

.EXAMPLE
    .\installer\build.ps1 -SourceDir dist -OutputDir installer\dist
#>
param(
    [string]$SourceDir = "dist",
    [string]$OutputDir = "installer\dist"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$WxsFile = Join-Path $PSScriptRoot "manalog.wxs"
$MsiName = "Manalog.msi"
$OutMsi  = Join-Path $OutputDir $MsiName

# Ensure output dir exists
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "Building MSI from $WxsFile ..."
Write-Host "Source dir: $SourceDir"
Write-Host "Output: $OutMsi"

# Build using wix CLI (dotnet tool)
wix build $WxsFile `
    -d "SourceDir=$SourceDir" `
    -o $OutMsi

if ($LASTEXITCODE -ne 0) {
    Write-Error "WiX build failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

# Generate SHA256 checksum alongside the MSI
$Sha = (Get-FileHash $OutMsi -Algorithm SHA256).Hash.ToLower()
$ShaFile = "$OutMsi.sha256"
"$Sha  $MsiName" | Out-File -Encoding ASCII $ShaFile

Write-Host "MSI: $OutMsi"
Write-Host "SHA256: $Sha"
Write-Host "Checksum: $ShaFile"
