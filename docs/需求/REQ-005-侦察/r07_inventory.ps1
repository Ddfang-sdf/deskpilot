$paths = @(
  'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
  'C:\Program Files\Google\Chrome\Application\chrome.exe',
  'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
  'C:\Program Files\Mozilla Firefox\firefox.exe',
  'C:\Program Files (x86)\Mozilla Firefox\firefox.exe',
  'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe',
  'C:\Program Files\Opera\opera.exe',
  'C:\Program Files\Vivaldi\Application\vivaldi.exe',
  'C:\Program Files (x86)\360\360se6\Application\360se.exe',
  'C:\Program Files (x86)\Tencent\QQBrowser\QQBrowser.exe',
  'C:\Program Files (x86)\SogouExplorer\SogouExplorer.exe'
)
foreach ($p in $paths) { if (Test-Path $p) { $v=(Get-Item $p).VersionInfo.ProductVersion; Write-Output "FOUND $p [$v]" } }
Write-Output '--- StartMenuInternet (HKLM) ---'
Get-ChildItem 'HKLM:\SOFTWARE\Clients\StartMenuInternet' -ErrorAction SilentlyContinue | ForEach-Object { $_.PSChildName }
Write-Output '--- running ---'
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'msedge|chrome|firefox|brave|opera|vivaldi|360|sogou|qqbrowser' } | Group-Object ProcessName | ForEach-Object { "$($_.Name) x$($_.Count)" }
