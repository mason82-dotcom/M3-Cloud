[CmdletBinding()]
param(
    [switch]$IncludeDeprecatedCloudDemo,
    [switch]$ForceRefreshCloudReference
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

function Assert-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

Assert-Command git
Assert-Command java

Write-Host "=== DJI Cloud API reference ==="
$cloudArgs = @{}
if ($IncludeDeprecatedCloudDemo) { $cloudArgs.IncludeDeprecatedDemo = $true }
if ($ForceRefreshCloudReference) { $cloudArgs.ForceRefresh = $true }
& (Join-Path $PSScriptRoot "install-dji-cloud-api-reference.ps1") @cloudArgs

Write-Host ""
Write-Host "=== DJI Mobile SDK V5 ==="
$gradleDir = Join-Path $repoRoot "lyrebird\LyrebirdApp\android-sdk-v5-as"
$gradlew = Join-Path $gradleDir "gradlew.bat"
if (-not (Test-Path $gradlew)) {
    throw "Gradle wrapper not found: $gradlew"
}

Push-Location $gradleDir
try {
    $dependencyOutput = & $gradlew --no-daemon :app:dependencies --configuration currentDebugRuntimeClasspath 2>&1
    if ($LASTEXITCODE -ne 0) {
        $dependencyOutput | ForEach-Object { Write-Host $_ }
        throw "Gradle dependency resolution failed with exit code $LASTEXITCODE"
    }

    $required = @(
        "com.dji:dji-sdk-v5-aircraft:5.18.0",
        "com.dji:dji-sdk-v5-networkImp:5.18.0",
        "com.dji:wpmzsdk:1.0.5.1"
    )

    $text = $dependencyOutput -join [Environment]::NewLine
    foreach ($dependency in $required) {
        if ($text -notmatch [regex]::Escape($dependency)) {
            throw "Required DJI dependency was not resolved: $dependency"
        }
        Write-Host "OK: $dependency"
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "DJI development setup is ready."
Write-Host "MSDK Android: 5.18.0"
Write-Host "Cloud API: protocol/server integration; official reference is under .vendor/dji-cloud-api/"
Write-Host "Production Cloud API implementation remains backend/app/dji/ + EMQX."
