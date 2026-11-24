[CmdletBinding()]
param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$localAppData = $env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($localAppData)) {
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
}
if ([string]::IsNullOrWhiteSpace($localAppData)) {
    throw "无法定位 LOCALAPPDATA，LaunchFlow Basic 开发模式未启动。"
}

$devDataRoot = Join-Path $localAppData "LaunchFlow-Basic-Dev"
$previousDataRoot = $env:LAUNCHFLOW_DATA_DIR

try {
    $env:LAUNCHFLOW_DATA_DIR = $devDataRoot
    Write-Host "LaunchFlow Basic developer data: $devDataRoot"
    Write-Host "Basic 开发模式不读取 Professional 数据目录，也不要求许可证。"

    Push-Location -LiteralPath $sourceRoot
    try {
        & $PythonCommand -m editor.main_basic
        $editorExitCode = $LASTEXITCODE
        if ($null -eq $editorExitCode) {
            $editorExitCode = 0
        }
    }
    finally {
        Pop-Location
    }

    if ($editorExitCode -ne 0) {
        throw "LaunchFlow Basic 开发模式退出码：$editorExitCode"
    }
}
catch {
    Write-Error "LaunchFlow Basic 开发模式启动失败：$($_.Exception.Message)" -ErrorAction Continue
    throw
}
finally {
    if ($null -eq $previousDataRoot) {
        Remove-Item Env:LAUNCHFLOW_DATA_DIR -ErrorAction SilentlyContinue
    }
    else {
        $env:LAUNCHFLOW_DATA_DIR = $previousDataRoot
    }
}
