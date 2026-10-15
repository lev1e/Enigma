$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
Set-Location $PSScriptRoot

# Версия берётся из anonymizer/__init__.py: единственный источник (packaging/version_info.txt проверяется ниже).
$version = [regex]::Match((Get-Content anonymizer\__init__.py -Raw), '__version__ = "([^"]+)"').Groups[1].Value
if (-not $version) { throw "Не удалось прочитать версию из anonymizer/__init__.py." }
if (-not (Select-String -Path packaging\version_info.txt -Pattern ("'" + $version + "'") -Quiet)) { throw "packaging/version_info.txt не совпадает с версией $version." }

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
  throw "Установите Python 3.12 x64 с python.org только на машине сборки. Пользователю Python не нужен."
}

py -3.12 -m venv .build-venv
& .\.build-venv\Scripts\python.exe -m pip install --upgrade pip
& .\.build-venv\Scripts\python.exe -m pip install -r requirements-build.txt
& .\.build-venv\Scripts\python.exe tools\fetch_office_js.py
& .\.build-venv\Scripts\python.exe run_tests.py
if ($LASTEXITCODE -ne 0) { throw "Проверки не прошли." }
$version = (& .\.build-venv\Scripts\python.exe -c "import anonymizer; print(anonymizer.__version__)").Trim()
if (-not $version) { throw "Не удалось прочитать anonymizer.__version__." }
& .\.build-venv\Scripts\python.exe tools\gen_version_info.py
if ($LASTEXITCODE -ne 0) { throw "Не удалось сформировать packaging\version_info.txt." }
& .\.build-venv\Scripts\pyinstaller.exe --noconfirm --clean Anonymizer.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с ошибкой." }

# Самопроверка собранной программы: ресурсы страницы, словарь, компонент окна, сервер, полный круг. У программы нет
# консоли, поэтому итог записывается в файл.
$report = Join-Path $env:TEMP "anonymizer-selfcheck.json"
Remove-Item $report -ErrorAction SilentlyContinue
$check = Start-Process -FilePath ".\dist\Anonymizer.exe" -ArgumentList "--selfcheck", "`"$report`"" -Wait -PassThru
if (Test-Path $report) { Get-Content $report -Raw | Write-Host }
if ($check.ExitCode -ne 0) { throw "Самопроверка собранной программы не пройдена (код $($check.ExitCode))." }

# Загрузчик WebView2 Runtime кладётся в установщик: на части компьютеров с Windows 10 этого компонента нет.
$bootstrapper = "packaging\MicrosoftEdgeWebview2Setup.exe"
if (-not (Test-Path $bootstrapper)) {
  try {
    Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $bootstrapper
  } catch {
    Write-Warning "Не удалось скачать загрузчик WebView2. Установщик предупредит пользователя, если компонента нет."
  }
}

$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
  & $iscc "/DMyAppVersion=$version" packaging\Anonymizer.iss
  if ($LASTEXITCODE -ne 0) { throw "Inno Setup завершился с ошибкой." }
  Write-Host "Installer: dist\Anonymizer-Setup-$version.exe"
} else {
  Write-Host "Inno Setup 6 не найден. Portable build готов: dist\Anonymizer.exe"
}

# Контрольные суммы для проверки скачанного файла (подпись кода: docs/superpowers/release-checklist.md, раздел Signing).
Get-ChildItem dist\Anonymizer*.exe | ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.Name } | Tee-Object dist\SHA256SUMS.txt
