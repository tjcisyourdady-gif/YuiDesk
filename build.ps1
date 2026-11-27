# 一键打包 YuiDesk（含桌宠全动画皮肤 + 极简前端 + Kimi 本机引擎，不含任何个人账号隐私）
# 常规代码更新默认只将程序与前端打进轻量补丁包（约 11 MB）；若新增/修改了角色皮肤图片，请附加 -IncludeSkins
param(
    [switch]$IncludeSkins,
    [string]$PatchSkin = ""
)
$ErrorActionPreference = "Stop"

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "未找到 .venv 虚拟环境，请先安装依赖。"
}

Write-Host "==> 1/4 清理旧构建产物..." -ForegroundColor Cyan
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "build", "dist"

Write-Host "==> 2/4 使用 PyInstaller 打包 YuiDesk.exe..." -ForegroundColor Cyan
& $py -m PyInstaller `
    --noconfirm `
    --windowed `
    --name "YuiDesk" `
    --icon "yuidesk.ico" `
    --add-data "web;web" `
    --add-data "skins;skins" `
    --hidden-import "uvicorn.logging" `
    --hidden-import "uvicorn.loops.auto" `
    --hidden-import "uvicorn.protocols.http.auto" `
    --hidden-import "uvicorn.lifespan.on" `
    --hidden-import "multipart" `
    --hidden-import "python_multipart" `
    --hidden-import "app.kimi_cli_bridge" `
    --hidden-import "app.doc_parser" `
    --hidden-import "app.llm_client" `
    --hidden-import "app.security" `
    --hidden-import "app.skins" `
    --hidden-import "app.pet_care" `
    --hidden-import "app.updater" `
    --hidden-import "app.version" `
    --hidden-import "app.desktop.care_window" `
    main.py

$distDir = Join-Path $PSScriptRoot "dist\YuiDesk"

Write-Host "==> 3/4 同步便携 Kimi 引擎、VC++运行库与使用说明（绝不打包个人账号隐私）..." -ForegroundColor Cyan
$kimiEngineDir = Join-Path $distDir "kimi_engine"
New-Item -ItemType Directory -Force -Path $kimiEngineDir | Out-Null

# 补齐 MSVC 运行库 DLL，确保没有装过 VC++ Redistributable 的全新 Windows 10/11 电脑也能直接打开
$internalDir = Join-Path $distDir "_internal"
$pysideDir = Join-Path $PSScriptRoot ".venv\Lib\site-packages\PySide6"
foreach ($dllName in @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll")) {
    $dstDll = Join-Path $internalDir $dllName
    if (-not (Test-Path $dstDll)) {
        $srcDll = Join-Path $pysideDir $dllName
        if (-not (Test-Path $srcDll)) { $srcDll = Join-Path "C:\Windows\System32" $dllName }
        if (Test-Path $srcDll) {
            Copy-Item -Force $srcDll $dstDll
            Write-Host "    已补齐运行库: _internal\$dllName" -ForegroundColor Gray
        }
    }
}

$kimiBinDir = Join-Path $env:USERPROFILE ".kimi-code\bin"
foreach ($binName in @("kimi.exe", "rg.exe")) {
    $srcBin = Join-Path $kimiBinDir $binName
    if (Test-Path $srcBin) {
        Copy-Item -Force $srcBin (Join-Path $kimiEngineDir $binName)
        Write-Host "    已内置引擎文件: kimi_engine\$binName" -ForegroundColor Gray
    }
}

# 内置极简便携 Git Bash（约 15 MB），彻底免去他人电脑单独安装 Git 或连 GitHub 超时的问题
$gitUsrBin = "C:\Program Files\Git\usr\bin"
if (Test-Path (Join-Path $gitUsrBin "bash.exe")) {
    $dstBashUsr = Join-Path $kimiEngineDir "git_bash\usr\bin"
    $dstBashTmp = Join-Path $kimiEngineDir "git_bash\tmp"
    New-Item -ItemType Directory -Force -Path $dstBashUsr, $dstBashTmp | Out-Null
    $bashFiles = @(
        "bash.exe","sh.exe",
        "msys-2.0.dll","msys-iconv-2.dll","msys-intl-8.dll","msys-readline8.dll",
        "msys-ncursesw6.dll","msys-gcc_s-seh-1.dll","msys-pcre2-8-0.dll","msys-z.dll",
        "msys-gmp-10.dll","msys-mpfr-6.dll","msys-unistring-5.dll","msys-crypto-3.dll","msys-ssl-3.dll",
        "ls.exe","cat.exe","head.exe","tail.exe","grep.exe","sed.exe","awk.exe","gawk.exe",
        "find.exe","pwd.exe","mkdir.exe","rm.exe","cp.exe","mv.exe","touch.exe","wc.exe",
        "sort.exe","uniq.exe","cut.exe","tr.exe","echo.exe","printf.exe","env.exe","which.exe",
        "xargs.exe","dirname.exe","basename.exe","cygpath.exe","sleep.exe","true.exe","false.exe",
        "test.exe","uname.exe","date.exe"
    )
    $copiedBash = 0
    foreach ($bf in $bashFiles) {
        $srcF = Join-Path $gitUsrBin $bf
        if (Test-Path $srcF) {
            Copy-Item -Force $srcF (Join-Path $dstBashUsr $bf)
            $copiedBash++
        }
    }
    Write-Host "    已内置便携 Bash 环境: kimi_engine\git_bash ($copiedBash 个核心文件，免装 Git)" -ForegroundColor Gray
}

# 同时在便携根目录放一份可读的皮肤模板说明，方便朋友导入自定义皮肤
$portableSkins = Join-Path $distDir "skins"
New-Item -ItemType Directory -Force -Path $portableSkins | Out-Null
Copy-Item -Recurse -Force (Join-Path $PSScriptRoot "skins\yui_template") (Join-Path $portableSkins "yui_template")

$guide = @"
======================================================
  YuiDesk · 多角色桌宠 Kimi 助手（绿色便携版）
======================================================

【重要提醒：先解压再运行！】
请先将整个压缩包「全部解压」到一个普通文件夹后再双击 YuiDesk.exe，
不要直接在压缩包预览窗口里双击打开，否则会缺少资源文件。

【1. 启动方式（免安装 Python，无黑框）】
双击本文件夹内的 YuiDesk.exe 即可静默启动，桌宠会出现在桌面右侧。
（若再次双击 YuiDesk.exe，会自动唤醒已有桌宠与对话框，不会重复多开。）

【2. 首次配置 Kimi（二选一，只需做一次）】
右键点击桌宠 ->「设置（Kimi 连接 / 外观）」->「Kimi 连接」：
- 方式一（推荐 · 本机 Kimi 账号登录，免安装 Git）：
  1) 本文件夹已完整内置 kimi_engine\kimi.exe 与便携 Bash 环境，无需额外安装任何软件；
  2) 点击「登录 Kimi 账号」，在弹出的浏览器中登录你自己的 Kimi 账号即可使用。
- 方式二（备用 · 官方 API Key，无需安装 Git）：
  直接填入你在 platform.moonshot.cn 申请的 Kimi API Key 并点击「启用 API 模式」。

【3. 内置 3 套全动画角色（共 90 帧），随时右键一键切换】
右键桌宠 ->「切换角色形象」：
1) 轻音元气少女（30 帧全动画）
2) 桃橘小狐狸·四足原生态版（30 帧全动画）
3) 桃橘小狐狸·Q版站姿（30 帧全动画）
（也支持在设置中导入自己的 PNG / GIF / ZIP 皮肤包）

【4. 常用玩法】
- 单击桌宠 / 按 Alt+Space：弹出桌宠下方对话框，支持左侧「工作 / 聊天」模式切换、独立任务与聊天记录、独立记忆策略、项目目录与权限等级选择，支持在设置里自由调节对话框宽高与字号。
- 拖入 1 个或多个文件到桌宠身上：可选择「吃掉」（啃食动画，默认不删除原文件）或「读取」（放大镜研究并由 AI 解析总结）。
- 悬停点「养成」或摸摸桌宠头顶：打开完全离线独立的养成系统（互动陪伴、小卖部与背包、每日任务、成就墙）。
- 拖到屏幕左右边缘：桌宠会扒着屏幕边探头偷看；右键桌宠可一键开关「桌面自由漫游」。
- 设置 ->「时间与轮询」：可自定义待机轮询间隔、漫游时长、自动打盹与本地定时提醒。
"@
Set-Content -Path (Join-Path $distDir "使用说明.txt") -Value $guide -Encoding UTF8
$manualSrc = Join-Path $PSScriptRoot "使用手册.md"
if (Test-Path $manualSrc) {
    Copy-Item -Force $manualSrc (Join-Path $distDir "使用手册.md")
}

Write-Host "==> 4/4 生成完整便携包、轻量增量更新包与 SHA-256 清单 (latest.json)..." -ForegroundColor Cyan
$zipPath = Join-Path $PSScriptRoot "dist\YuiDesk_portable.zip"
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Compress-Archive -Path $distDir -DestinationPath $zipPath -CompressionLevel Optimal

# 生成超轻量增量热更新补丁包（常规代码更新仅约 11 MB；附加 -IncludeSkins 时包含全部角色皮肤图片约 28 MB）
$patchStage = Join-Path $PSScriptRoot "dist\_patch_stage"
if (Test-Path $patchStage) { Remove-Item -Recurse -Force $patchStage }
New-Item -ItemType Directory -Force -Path $patchStage | Out-Null
Copy-Item -Force (Join-Path $distDir "YuiDesk.exe") (Join-Path $patchStage "YuiDesk.exe")
foreach ($doc in @("使用说明.txt", "使用手册.md")) {
    $p = Join-Path $distDir $doc
    if (Test-Path $p) { Copy-Item -Force $p (Join-Path $patchStage $doc) }
}
New-Item -ItemType Directory -Force -Path (Join-Path $patchStage "_internal") | Out-Null
Copy-Item -Recurse -Force (Join-Path $distDir "_internal\web") (Join-Path $patchStage "_internal\web")
if ($IncludeSkins) {
    Copy-Item -Recurse -Force (Join-Path $distDir "_internal\skins") (Join-Path $patchStage "_internal\skins")
    Copy-Item -Recurse -Force (Join-Path $distDir "skins") (Join-Path $patchStage "skins")
    Write-Host "    补丁包模式：含全量角色皮肤图片" -ForegroundColor Gray
} elseif ($PatchSkin) {
    $skinDst = Join-Path $patchStage "_internal\skins\$PatchSkin"
    New-Item -ItemType Directory -Force -Path (Split-Path $skinDst -Parent) | Out-Null
    Copy-Item -Recurse -Force (Join-Path $distDir "_internal\skins\$PatchSkin") $skinDst
    Write-Host "    补丁包模式：程序+前端+新增皮肤 [$PatchSkin]（增量极速下载）" -ForegroundColor Gray
} else {
    Write-Host "    补丁包模式：超轻量程序+前端补丁（约 11 MB，极速下载）" -ForegroundColor Gray
}

$patchZipPath = Join-Path $PSScriptRoot "dist\YuiDesk_patch.zip"
if (Test-Path $patchZipPath) { Remove-Item -Force $patchZipPath }
Compress-Archive -Path (Join-Path $patchStage "*") -DestinationPath $patchZipPath -CompressionLevel Optimal
Remove-Item -Recurse -Force $patchStage

# 自动读取 app/version.py 版本并生成含真实 SHA-256 的 latest.json（同步写入 dist/ 与仓库根目录）
$manifestScript = @"
import hashlib, json, time
from pathlib import Path
from app.version import APP_VERSION, GITHUB_OWNER, GITHUB_REPO

root = Path(r'$PSScriptRoot')
dist = root / 'dist'
patch_p = dist / 'YuiDesk_patch.zip'
full_p = dist / 'YuiDesk_portable.zip'

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest().lower()

tag = f'v{APP_VERSION}'
base_dl = f'https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/{tag}'
manifest = {
    'version': APP_VERSION,
    'released_at': time.strftime('%Y-%m-%d'),
    'notes': (
        '1. 重磅新增「深海怪兽王·哥斯拉」30 帧全动画巨型皮肤，专属 1.85 倍超大巨兽体型（约 325px），升级后自动切换登场（随时可在右键菜单切回小狐狸/轻音少女）\n'
        '2. 30 帧全套怪兽原创动作：原子吐息回复、啃核能小电池、泡海面温泉降温、背鳍蓄能、巡视微缩城市、怪兽胜利蹦迪、短手害羞捂脸、扒边偷看\n'
        '3. 养成面板同步专属「怪兽补给站」互动与道具文案，支持角色独立体型倍率（size_multiplier）自动贴合屏幕边界'
    ),
    'min_patch_version': '1.0.0',
    'patch': {
        'filename': 'YuiDesk_patch.zip',
        'url': f'{base_dl}/YuiDesk_patch.zip',
        'sha256': sha256_file(patch_p),
        'size_bytes': patch_p.stat().st_size,
    },
    'full': {
        'filename': 'YuiDesk_portable.zip',
        'url': f'{base_dl}/YuiDesk_portable.zip',
        'sha256': sha256_file(full_p),
        'size_bytes': full_p.stat().st_size,
    },
}
text = json.dumps(manifest, ensure_ascii=False, indent=2) + '\n'
(dist / 'latest.json').write_text(text, encoding='utf-8')
(root / 'latest.json').write_text(text, encoding='utf-8')
print(f'latest.json generated: v{APP_VERSION}')
print('  patch sha256:', manifest['patch']['sha256'])
print('  full  sha256:', manifest['full']['sha256'])
"@
& $py -c $manifestScript

$zipSizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
$patchSizeMB = [math]::Round((Get-Item $patchZipPath).Length / 1MB, 1)
Write-Host "==> 打包全部完成！" -ForegroundColor Green
Write-Host "    可执行目录: $distDir\YuiDesk.exe" -ForegroundColor Green
Write-Host "    完整便携包: $zipPath ($zipSizeMB MB)" -ForegroundColor Yellow
Write-Host "    增量更新包: $patchZipPath ($patchSizeMB MB)" -ForegroundColor Yellow
Write-Host "    更新清单  : dist\latest.json" -ForegroundColor Yellow
