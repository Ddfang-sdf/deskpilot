#Requires -Version 5.1
<#
.SYNOPSIS
  DeskPilot 一键安装（ISS-0011 §3.2-D 公开入口）。

.DESCRIPTION
  下载或就地使用发行 zip → 解压落位（policy.yml 与 exe 同目录）→ 可选注册 MCP
  客户端 → 可选启动常驻 daemon 并验证 /health → 可选写开机自启。
  幂等：同参数重复执行结果一致（覆盖落位；注册先 remove 后 add；JSON 合并按键覆盖）。

.PARAMETER InstallDir
  安装目录，默认 C:\tools\deskpilot。

.PARAMETER LocalZip
  就地使用指定 zip（内网/离线场景）；缺省时从 GitHub releases/latest 下载。

.PARAMETER Client
  none | claude-code | claude-desktop | cursor | all，默认 none（不写任何客户端配置）。

.PARAMETER WithDaemon
  安装后启动常驻 daemon（deskpilot.exe --daemon）并验证 http://127.0.0.1:9420/health。

.PARAMETER AutoStart
  写开机自启（启动文件夹快捷方式，daemon 形态）。

.EXIT CODES
  0 成功；2 zip 获取失败；3 解压落位失败；4 客户端注册失败；5 daemon 启动/验证失败；6 自启写入失败。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install.ps1 -Client claude-code -WithDaemon -AutoStart
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install.ps1 -LocalZip D:\pkgs\deskpilot-v0.3.1-windows-x64.zip -InstallDir D:\tools\deskpilot -Client all
#>
[CmdletBinding()]
param(
  [string]$InstallDir = "C:\tools\deskpilot",
  [string]$LocalZip = "",
  [ValidateSet("none", "claude-code", "claude-desktop", "cursor", "all")]
  [string]$Client = "none",
  [switch]$WithDaemon,
  [switch]$AutoStart
)

$ErrorActionPreference = "Stop"

function Fail([int]$Code, [string]$Msg) {
  Write-Host "[install] FAILED($Code): $Msg"
  exit $Code
}

# ---------- 1. 定位/下载 zip ----------
$zip = $null
if ($LocalZip -ne "") {
  if (-not (Test-Path $LocalZip)) { Fail 2 "LocalZip 不存在: $LocalZip" }
  $zip = (Resolve-Path $LocalZip).Path
} else {
  try {
    $rel = Invoke-RestMethod "https://api.github.com/repos/Ddfang-sdf/deskpilot/releases/latest" -Headers @{ "User-Agent" = "deskpilot-install" }
    $asset = $rel.assets | Where-Object { $_.name -like "deskpilot-*-windows-x64.zip" } | Select-Object -First 1
    if (-not $asset) { Fail 2 "latest release 中未找到 deskpilot-*-windows-x64.zip 资产" }
    $zip = Join-Path $env:TEMP $asset.name
    Invoke-WebRequest $asset.browser_download_url -OutFile $zip
  } catch {
    if ($PSItem.Exception.Message -notmatch "未找到") { Fail 2 "下载失败: $($PSItem.Exception.Message)" } else { throw }
  }
}
Write-Host "[install] zip: $zip"

# ---------- 2. 解压落位（幂等：覆盖） ----------
try {
  $stage = Join-Path $env:TEMP ("deskpilot-install-" + [guid]::NewGuid().ToString("N"))
  Expand-Archive $zip $stage -Force
  $exe = Get-ChildItem $stage -Recurse -Filter deskpilot.exe | Select-Object -First 1
  $pol = Get-ChildItem $stage -Recurse -Filter policy.yml | Select-Object -First 1
  if (-not $exe -or -not $pol) { Fail 3 "zip 内缺 deskpilot.exe 或 policy.yml" }
  New-Item -ItemType Directory -Force $InstallDir | Out-Null
  # ISS-0030 F：覆盖出厂策略前,把旧策略中用户入白的差额迁入 policy.local.yml
  # (尽力而为:迁移失败时警告并继续安装,用户重新审批即可恢复)
  # ISS-0032 A4:PowerShell 原生进程非零退出不抛异常——try/catch 拦不住,
  # 必须显式查 $LASTEXITCODE
  $existingPol = Join-Path $InstallDir "policy.yml"
  if (Test-Path $existingPol) {
    try {
      & $exe.FullName --migrate-policy $existingPol $pol.FullName (Join-Path $InstallDir "policy.local.yml") | Out-Null
      if ($LASTEXITCODE -ne 0) {
        Write-Host "[install] 入白迁移失败(退出码 $LASTEXITCODE),跳过并继续;重新审批可恢复"
      }
    } catch {
      Write-Host "[install] 入白迁移不可用,跳过(重新审批可恢复): $($PSItem.Exception.Message)"
    }
  }
  Copy-Item $exe.FullName (Join-Path $InstallDir "deskpilot.exe") -Force
  Copy-Item $pol.FullName (Join-Path $InstallDir "policy.yml") -Force
  Remove-Item $stage -Recurse -Force
} catch {
  Fail 3 "解压落位失败: $($PSItem.Exception.Message)"
}
$exePath = Join-Path $InstallDir "deskpilot.exe"
Write-Host "[install] 落位: $InstallDir"

# ---------- 3. 客户端注册 ----------
function Register-ClaudeCode {
  # 与手工命令完全等价：先 remove（未注册时报错可忽略）后 add，幂等不堆积。
  # 经 cmd /c 重定向，避免 PS5.1 把原生命令 stderr 包成 NativeCommandError。
  & cmd /c "claude mcp remove deskpilot >nul 2>&1" | Out-Null
  & claude mcp add deskpilot -- "$exePath" | Out-Null
  if ($LASTEXITCODE -ne 0) { Fail 4 "claude mcp add 失败(exit $LASTEXITCODE)" }
  Write-Host "[install] 已注册 Claude Code: claude mcp add deskpilot -- `"$exePath`""
}

function Register-Json([string]$ConfigPath) {
  # JSON 合并：mcpServers.deskpilot 按键覆盖（幂等），既有 server 保留。
  $cfg = $null
  if (Test-Path $ConfigPath) {
    try { $cfg = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { Fail 4 "客户端配置 JSON 无法解析: $ConfigPath" }
  }
  if (-not $cfg) { $cfg = [pscustomobject]@{} }
  if (-not ($cfg.PSObject.Properties.Name -contains "mcpServers")) {
    $cfg | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{})
  }
  $entry = [pscustomobject]@{ command = $exePath }
  if ($cfg.mcpServers.PSObject.Properties.Name -contains "deskpilot") {
    $cfg.mcpServers.deskpilot = $entry
  } else {
    $cfg.mcpServers | Add-Member -NotePropertyName deskpilot -NotePropertyValue $entry
  }
  $dir = Split-Path $ConfigPath -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
  ConvertTo-Json $cfg -Depth 10 | Out-File $ConfigPath -Encoding utf8
  Write-Host "[install] 已写入: $ConfigPath"
}

if ($Client -ne "none") {
  try {
    if ($Client -in @("claude-code", "all")) { Register-ClaudeCode }
    if ($Client -in @("claude-desktop", "all")) {
      Register-Json (Join-Path $env:APPDATA "Claude\claude_desktop_config.json")
    }
    if ($Client -in @("cursor", "all")) {
      Register-Json (Join-Path $env:USERPROFILE ".cursor\mcp.json")
    }
  } catch {
    if ($LASTEXITCODE -eq 0) { Fail 4 "客户端注册失败: $($PSItem.Exception.Message)" } else { throw }
  }
}

# ---------- 4. 启动 daemon 并验证 ----------
if ($WithDaemon) {
  Start-Process $exePath -ArgumentList "--daemon" -WindowStyle Hidden
  $healthy = $false
  for ($i = 0; $i -lt 20; $i++) {
    try {
      $h = Invoke-RestMethod "http://127.0.0.1:9420/health" -TimeoutSec 2
      if ($h) { $healthy = $true; break }
    } catch { Start-Sleep -Milliseconds 500 }
  }
  if (-not $healthy) { Fail 5 "daemon 启动后 /health 验证未通过（10 秒内无响应）" }
  Write-Host "[install] daemon 在线: http://127.0.0.1:9420/health"
}

# ---------- 5. 开机自启 ----------
if ($AutoStart) {
  try {
    $startup = [Environment]::GetFolderPath("Startup")
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path $startup "DeskPilot.lnk"))
    $lnk.TargetPath = $exePath
    $lnk.Arguments = "--daemon"
    $lnk.Save()
  } catch { Fail 6 "自启写入失败: $($PSItem.Exception.Message)" }
  Write-Host "[install] 开机自启已写入（启动文件夹 DeskPilot.lnk）"
}

# ---------- 6. 验证输出 ----------
Write-Host "[install] OK"
Write-Host "  exe:    $exePath"
Write-Host "  policy: $(Join-Path $InstallDir 'policy.yml')"
Write-Host "  client: $Client"
Write-Host "  验证: 重启客户端后对 AI 说「用 deskpilot 截个屏」"
exit 0
