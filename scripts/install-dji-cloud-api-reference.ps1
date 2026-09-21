[CmdletBinding()]
param(
    [string]$InstallRoot = ".vendor/dji-cloud-api",
    [switch]$IncludeDeprecatedDemo,
    [switch]$ForceRefresh
)

$ErrorActionPreference = "Stop"

function Assert-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

function Sync-GitRepository {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string]$Ref = "master"
    )

    if (Test-Path (Join-Path $Destination ".git")) {
        if (-not $ForceRefresh) {
            Write-Host "Already installed: $Destination"
            return
        }
        Write-Host "Refreshing $Destination ..."
        git -C $Destination fetch --prune origin
        git -C $Destination checkout $Ref
        git -C $Destination pull --ff-only origin $Ref
        return
    }

    if (Test-Path $Destination) {
        throw "Destination exists but is not a Git repository: $Destination"
    }

    $parent = Split-Path -Parent $Destination
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Write-Host "Cloning $Url -> $Destination"
    git clone --branch $Ref --single-branch $Url $Destination
}

Assert-Command git

$resolvedRoot = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $InstallRoot))
New-Item -ItemType Directory -Force -Path $resolvedRoot | Out-Null

Write-Host ""
Write-Host "DJI Cloud API"
Write-Host "============="
Write-Host "Official DJI product page currently reports Cloud API 1.14.0."
Write-Host "Cloud API is a protocol/server integration (MQTT + HTTPS + WebSocket),"
Write-Host "not a Gradle/Python package. M3-Cloud already implements the production"
Write-Host "server path; this installer adds DJI's official public reference sources."
Write-Host ""

$docDir = Join-Path $resolvedRoot "Cloud-API-Doc"
Sync-GitRepository -Url "https://github.com/dji-sdk/Cloud-API-Doc.git" -Destination $docDir -Ref "master"

$docCommit = (git -C $docDir rev-parse HEAD).Trim()
$docMessage = (git -C $docDir log -1 --pretty=%s).Trim()
Write-Host "Installed documentation mirror:"
Write-Host "  path:   $docDir"
Write-Host "  commit: $docCommit"
Write-Host "  note:   $docMessage"
Write-Warning "DJI's public Cloud-API-Doc GitHub mirror can lag behind developer.dji.com. Treat developer.dji.com/cloud-api as authoritative for the current version."

if ($IncludeDeprecatedDemo) {
    Write-Warning "DJI ended maintenance of DJI-Cloud-API-Demo on 2025-04-10 and warns against using it as a production service."
    $backendDemo = Join-Path $resolvedRoot "DJI-Cloud-API-Demo"
    Sync-GitRepository -Url "https://github.com/dji-sdk/DJI-Cloud-API-Demo.git" -Destination $backendDemo -Ref "master"
    $frontendDemo = Join-Path $resolvedRoot "Cloud-API-Demo-Web"
    Sync-GitRepository -Url "https://github.com/dji-sdk/Cloud-API-Demo-Web.git" -Destination $frontendDemo -Ref "master"
    Write-Host "Deprecated reference demos installed for protocol comparison only."
}

Write-Host ""
Write-Host "M3-Cloud integration:"
Write-Host "  production backend: backend/app/dji/"
Write-Host "  Pilot 2 bootstrap:  /api/v1/dji/pilot/bootstrap"
Write-Host "  Pilot 2 status:     /api/v1/dji/pilot/status"
Write-Host "  setup guide:        docs/dji-cloud-api.md"
Write-Host "Done."
