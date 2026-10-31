<#
    SnapAnswer 启动/依赖引导脚本（Windows PowerShell 5.1+）

    改进自流程图：
      1. 定位脚本所在目录
      2. 查找 Python 3.10–3.12（优先 py launcher，其次 PATH，最后常见安装目录）
      3. 找不到时尝试 winget 安装 Python 3.12
      4. 创建/复用 .venv
      5. 检查并安装项目依赖
      6. 运行 python -m snapanswer --check，通过后启动

    不需要依赖 PATH：找到 Python 后一直使用它的绝对路径。
    用法：
      powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
      powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -CheckOnly
#>

[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AppArgs
)

$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {
    # Older consoles may not support changing the encoding; continue anyway.
}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-PythonVersion([string]$Executable) {
    if (-not (Test-Path -LiteralPath $Executable)) {
        return $false
    }
    try {
        & $Executable -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,13) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-Python {
    # 1) py launcher: the most reliable way to find a registered Python on Windows.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($version in @("3.12", "3.11", "3.10")) {
            try {
                $candidate = (& py "-$version" -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
                if ($LASTEXITCODE -eq 0 -and $candidate) {
                    $candidate = $candidate.Trim()
                    if (Test-PythonVersion $candidate) {
                        return $candidate
                    }
                }
            } catch {
                # Try the next version.
            }
        }
    }

    # 2) python on PATH.
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $candidate = $pythonCommand.Source
        if (Test-PythonVersion $candidate) {
            return $candidate
        }
    }

    # 3) Common per-user and system install locations (works without PATH).
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"),
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python310\python.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-PythonVersion $candidate)) {
            return $candidate
        }
    }

    # 4) Python registered in the registry but not on PATH.
    $registryRoots = @(
        "HKCU:\Software\Python\PythonCore",
        "HKLM:\Software\Python\PythonCore",
        "HKLM:\Software\WOW6432Node\Python\PythonCore"
    )
    foreach ($root in $registryRoots) {
        if (-not (Test-Path $root)) {
            continue
        }
        foreach ($versionKey in Get-ChildItem $root -ErrorAction SilentlyContinue) {
            if ($versionKey.PSChildName -notmatch '^3\.(10|11|12)') {
                continue
            }
            $installPath = Get-ItemProperty (Join-Path $versionKey.PSPath "InstallPath") -ErrorAction SilentlyContinue
            if (-not $installPath) {
                continue
            }
            $candidate = $installPath.ExecutablePath
            if (-not $candidate) {
                $candidate = Join-Path $installPath."(default)" "python.exe"
            }
            if ($candidate -and (Test-PythonVersion $candidate)) {
                return $candidate
            }
        }
    }
    return $null
}

function Install-Python {
    Write-Host "未检测到可用的 Python 3.10–3.12。" -ForegroundColor Yellow
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "系统没有 winget，无法自动安装 Python。" -ForegroundColor Yellow
        Write-Host "请手动安装 Python 3.12，并勾选 Add Python to PATH：" -ForegroundColor Yellow
        Write-Host "  https://www.python.org/downloads/windows/" -ForegroundColor Yellow
        Start-Process "https://www.python.org/downloads/windows/" -ErrorAction SilentlyContinue
        return $null
    }

    Write-Host "正在通过 winget 安装 Python 3.12（用户级，无需管理员）..." -ForegroundColor Yellow
    & winget install --id Python.Python.3.12 -e --scope user --silent `
        --accept-source-agreements --accept-package-agreements 2>&1 | Out-Host
    $wingetCode = $LASTEXITCODE
    if ($wingetCode -ne 0) {
        Write-Host "winget 返回代码 $wingetCode；继续尝试查找已安装的 Python。" -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 2
    return (Find-Python)
}

function Test-Dependencies([string]$Executable) {
    & $Executable -c "import PyQt6, httpx, numpy, PIL, rapidocr_onnxruntime, pynput, tomli_w" 2>$null
    return ($LASTEXITCODE -eq 0)
}

try {
    Write-Host "SnapAnswer 启动检查" -ForegroundColor Green
    Write-Host "项目目录：$ProjectRoot"

    Write-Step "1/5 定位 Python 3.10–3.12"
    $python = Find-Python
    if (-not $python) {
        $python = Install-Python
    }
    if (-not $python) {
        throw "未找到 Python 3.10–3.12。请安装后重新运行 run.bat。"
    }
    $version = (& $python -c "import platform; print(platform.python_version())").Trim()
    Write-Host "使用 Python $version：$python" -ForegroundColor Green
    Write-Host "说明：脚本使用绝对路径，不要求 Python 已经在 PATH 中。"

    Write-Step "2/5 准备虚拟环境"
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "创建 .venv ..."
        & $python -m venv .venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
            throw "创建虚拟环境失败。"
        }
    } else {
        Write-Host "复用已有 .venv。"
    }

    Write-Step "3/5 检查依赖"
    if (-not (Test-Dependencies $venvPython)) {
        Write-Host "依赖不完整，安装项目依赖（首次可能需要几分钟）..."
        & $venvPython -m pip install --disable-pip-version-check --no-input -e .
        if ($LASTEXITCODE -ne 0) {
            throw "依赖安装失败。请检查网络；SSL 错误时可换 PyPI 镜像。"
        }
    } else {
        Write-Host "依赖已齐全。"
    }
    if (-not (Test-Dependencies $venvPython)) {
        throw "依赖安装后导入仍然失败，请运行 .venv\Scripts\python.exe -m pip check 查看。"
    }

    Write-Step "4/5 运行自检"
    & $venvPython -m snapanswer --check
    if ($LASTEXITCODE -ne 0) {
        throw "自检未通过。请根据上面的输出修复配置/依赖。"
    }

    if ($CheckOnly) {
        Write-Host ""
        Write-Host "检查通过，未启动图形界面（-CheckOnly）。" -ForegroundColor Green
        exit 0
    }

    Write-Step "5/5 启动 SnapAnswer"
    & $venvPython -m snapanswer @AppArgs
    $appCode = $LASTEXITCODE
    if ($appCode -ne 0) {
        Write-Host "SnapAnswer 退出，代码 $appCode。" -ForegroundColor Yellow
    }
    exit $appCode
}
catch {
    Write-Host ""
    Write-Host "启动失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "请把上面的错误信息发给开发者，或查看日志目录。" -ForegroundColor Yellow
    exit 1
}
