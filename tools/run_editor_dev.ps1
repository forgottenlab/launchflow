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
    throw "无法定位 LOCALAPPDATA，LaunchFlow 开发模式未启动。"
}

$devDataRoot = Join-Path $localAppData "LaunchFlow-Dev"
$devLicensePath = Join-Path $devDataRoot "licenses\license.lic"
$previousDataRoot = $env:LAUNCHFLOW_DATA_DIR

try {
    $env:LAUNCHFLOW_DATA_DIR = $devDataRoot
    Write-Host "LaunchFlow developer data: $devDataRoot"

    if (Test-Path -LiteralPath $devLicensePath -PathType Leaf) {
        Write-Host "Developer license found: $devLicensePath"
    }
    else {
        Write-Warning "尚未找到 developer license。程序将进入正常激活页面，不会跳过签名验证。"
        Write-Host "请将已签名且绑定本机的 lflic-1 license 放置到："
        Write-Host $devLicensePath
    }

    Push-Location -LiteralPath $sourceRoot
    try {
        & $PythonCommand -m editor.main
        $editorExitCode = $LASTEXITCODE
        if ($null -eq $editorExitCode) {
            $editorExitCode = 0
        }
    }
    finally {
        Pop-Location
    }

    if ($editorExitCode -ne 0) {
        throw "LaunchFlow 开发模式退出码：$editorExitCode"
    }
}
catch {
    Write-Error "LaunchFlow 开发模式启动失败：$($_.Exception.Message)" -ErrorAction Continue
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
