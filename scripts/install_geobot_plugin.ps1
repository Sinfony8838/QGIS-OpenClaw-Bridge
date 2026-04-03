param(
    [string]$ProfileName = "default",
    [switch]$Force
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$source = Join-Path $repoRoot "geoai_agent_plugin"
$pluginRoot = Join-Path $env:APPDATA "QGIS\QGIS3\profiles\$ProfileName\python\plugins"
$target = Join-Path $pluginRoot "geoai_agent_plugin"

if (-not (Test-Path $source)) {
    throw "Plugin source not found: $source"
}

New-Item -ItemType Directory -Path $pluginRoot -Force | Out-Null

if (Test-Path $target) {
    if (-not $Force) {
        throw "Target plugin directory already exists. Re-run with -Force to replace it."
    }
    Remove-Item -LiteralPath $target -Recurse -Force
}

Copy-Item -Path $source -Destination $target -Recurse -Force
Write-Host "GeoBot plugin installed to $target"
