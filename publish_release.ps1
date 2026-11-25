# 一键发布新版本到 GitHub（需要本机已登录 Git / GitHub CLI）
# 用法：先在 app\version.py 更新 APP_VERSION，再运行 .\publish_release.ps1
$ErrorActionPreference = "Stop"

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$ver = (& $py -c "from app.version import APP_VERSION; print(APP_VERSION)").Trim()
$tag = "v$ver"

Write-Host "==> 1/3 重新打包 YuiDesk $tag（含完整包、增量更新包与 latest.json）..." -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "build.ps1")

Write-Host "==> 2/3 提交最新源码与 latest.json 到 Git..." -ForegroundColor Cyan
git add latest.json
git status -s

$ghExe = $null
if (Get-Command gh -ErrorAction SilentlyContinue) {
    $ghExe = (Get-Command gh).Source
} elseif (Test-Path "C:\Program Files\GitHub CLI\gh.exe") {
    $ghExe = "C:\Program Files\GitHub CLI\gh.exe"
}

if ($ghExe) {
    Write-Host "==> 3/3 检测到 GitHub CLI，自动推送并发布 Release $tag ..." -ForegroundColor Cyan
    git push origin main
    & $ghExe release create $tag `
        (Join-Path $PSScriptRoot "dist\YuiDesk_patch.zip") `
        (Join-Path $PSScriptRoot "dist\YuiDesk_portable.zip") `
        (Join-Path $PSScriptRoot "dist\latest.json") `
        --title "YuiDesk $tag" `
        --notes "YuiDesk $tag 自动更新发布"
    Write-Host "发布成功！朋友打开桌宠检查更新即可自动拉取 $tag。" -ForegroundColor Green
} else {
    Write-Host "==> 3/3 未安装 gh CLI，请手动推送代码并在 GitHub Releases 上传以下 3 个文件（Tag 填 $tag）：" -ForegroundColor Yellow
    Write-Host "    1. dist\YuiDesk_patch.zip" -ForegroundColor White
    Write-Host "    2. dist\YuiDesk_portable.zip" -ForegroundColor White
    Write-Host "    3. dist\latest.json" -ForegroundColor White
}
