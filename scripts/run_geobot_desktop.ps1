param(
    [string]$NpmCommand = "npm"
)

$desktopRoot = Resolve-Path (Join-Path $PSScriptRoot "..\geobot_desktop")
Push-Location $desktopRoot
try {
    & $NpmCommand run start
}
finally {
    Pop-Location
}
