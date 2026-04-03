param(
    [string]$RuntimeHost = "127.0.0.1",
    [int]$Port = 18999,
    [int]$QgisPort = 5555,
    [string]$PythonCommand = "python"
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    & $PythonCommand -m geobot_runtime.main --host $RuntimeHost --port $Port --qgis-port $QgisPort
}
finally {
    Pop-Location
}
