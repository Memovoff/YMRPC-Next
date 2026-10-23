# Сборка портативной версии YMRPC Next.
#
# Примеры:
#   .\build.ps1                  # полная сборка с предпросмотром оверлея
#   .\build.ps1 -NoWebEngine     # компактная сборка без Qt WebEngine
#   .\build.ps1 -SkipChecks      # пропустить ruff и pytest

[CmdletBinding()]
param(
    [switch]$NoWebEngine,
    [switch]$SkipChecks
)

$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # Старые консоли могут не поддерживать UTF-8 — это не критично.
}
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Не найден venv: $Python. Создайте его и установите зависимости: py -3.13 -m venv .venv; .\.venv\Scripts\pip install -e .[dev]"
}

& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller не установлен. Выполните: .\.venv\Scripts\pip install -e .[dev]"
}

if (-not $SkipChecks) {
    Write-Host "==> ruff" -ForegroundColor Cyan
    & $Python -m ruff check src tests tools
    if ($LASTEXITCODE -ne 0) { throw "ruff нашёл ошибки" }

    Write-Host "==> pytest" -ForegroundColor Cyan
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "тесты не прошли" }
}

$Version = (& $Python -c "import sys; sys.path.insert(0, 'src'); import ymrpc; print(ymrpc.__version__)").Trim()
if (-not $Version) { throw "Не удалось определить версию" }

if ($NoWebEngine) {
    $env:YMRPC_BUILD_NO_WEBENGINE = "1"
    Write-Host "==> сборка без Qt WebEngine" -ForegroundColor Yellow
} else {
    Remove-Item Env:\YMRPC_BUILD_NO_WEBENGINE -ErrorAction SilentlyContinue
}

Write-Host "==> PyInstaller $Version" -ForegroundColor Cyan
& $Python -m PyInstaller --noconfirm --clean "ymrpc-next.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с ошибкой" }

$Exe = Join-Path $Root "dist\YMRPC-Next.exe"
if (-not (Test-Path $Exe)) { throw "Не найден результат сборки: $Exe" }

$Suffix = if ($NoWebEngine) { "-lite" } else { "" }
$Zip = Join-Path $Root ("dist\YMRPC-Next-{0}-win64{1}.zip" -f $Version, $Suffix)
Write-Host "==> упаковка $Zip" -ForegroundColor Cyan
Compress-Archive -Path $Exe -DestinationPath $Zip -Force

$Hash = (Get-FileHash $Exe -Algorithm SHA256).Hash
$ZipHash = (Get-FileHash $Zip -Algorithm SHA256).Hash
$SizeMb = [math]::Round((Get-Item $Exe).Length / 1MB, 1)
@(
    "$Hash  YMRPC-Next.exe"
    "$ZipHash  $(Split-Path -Leaf $Zip)"
) | Set-Content (Join-Path $Root "dist\SHA256SUMS.txt") -Encoding ASCII

Write-Host ""
Write-Host "Готово: $Exe ($SizeMb МБ)" -ForegroundColor Green
Write-Host "ZIP:    $Zip"
Write-Host "SHA256: $Hash"
