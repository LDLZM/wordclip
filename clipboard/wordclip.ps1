# wordclip.ps1 —— 把剪贴板里的 Markdown / AI 回答转成 Word 富文本
#
# 原理：
#   本机剪贴板支持同时存放多个格式（text/plain、text/html、RTF ...）。
#   Word 粘贴时优先读 text/html，并据此生成段落样式。
#   所以我们只需要把「Word 能看懂的 HTML」写进剪贴板的 text/html 槽位，
#   就会得到和网页版"复制为 Word 格式"完全一致的效果。
#
# 依赖：只需要 Windows 自带的 PowerShell 5.1（无需装任何东西）
# 用法：
#   .\wordclip.ps1                  读取剪贴板 → 转换 → 写回剪贴板
#   .\wordclip.ps1 -File input.md   从文件读
#   .\wordclip.ps1 -Server http://你的服务器:8020   （用服务器算样式）
#
param(
    [string]$File = "",
    [string]$Server = "@@SERVER_PLACEHOLDER@@"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Write-Ok($m)   { Write-Host "  $(Char 0x2713) $m" -ForegroundColor Green }
function Write-Err($m)  { Write-Host "  $(Char 0x2717) $m" -ForegroundColor Red }
function Char($c)       { [char]$c }

function Get-ClipboardText {
    # Get-Clipboard 在 PS5.1 里可用；退路用 Forms
    try { return Get-Clipboard -Raw -Format Text }
    catch { return [System.Windows.Forms.Clipboard]::GetText() }
}

function Get-Markdown {
    param([string]$Path)
    if ($Path -and (Test-Path $Path)) {
        return [System.IO.File]::ReadAllText((Resolve-Path $Path), [System.Text.Encoding]::UTF8)
    }
    return (Get-ClipboardText)
}

function Convert-ViaServer {
    param([string]$Md, [string]$Srv)
    $body = @{ md = $Md } | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
    try {
        $resp = Invoke-RestMethod -Uri "$Srv/api/clip" -Method Post `
            -ContentType "application/json; charset=utf-8" `
            -Body $bytes -TimeoutSec 60
        if (-not $resp.ok) { throw $resp.error }
        return $resp.html
    } catch {
        throw "调用转换服务失败（$Srv）：$($_.Exception.Message)"
    }
}

function Set-ClipboardRich {
    param([string]$Html)
    # 写多格式剪贴板：HTML 用 UTF-8 字节流 + 显式声明 charset，
    # 这是 Word 正确识别中文的关键（否则会乱码或当成纯文本）
    $dataObj = New-Object System.Windows.Forms.DataObject
    $utf8Html = "<meta charset='utf-8'>" + $Html
    $ms = New-Object System.IO.MemoryStream
    $sw = New-Object System.IO.StreamWriter($ms, (New-Object System.Text.UTF8Encoding($false)))
    $sw.Write($utf8Html); $sw.Flush()
    $ms.Position = 0
    # "HTML Format" 是 Windows 剪贴板里 Word 读取的官方格式名
    $dataObj.SetData([System.Windows.Forms.DataFormats]::Html, $ms)

    # 同时放纯文本，保证记事本/邮件等场景可用
    $plain = [System.Text.RegularExpressions.Regex]::Replace($Html, '<[^>]+>', '')
    $dataObj.SetData([System.Windows.Forms.DataFormats]::UnicodeText, $plain)

    [System.Windows.Forms.Clipboard]::SetDataObject($dataObj, $true)
}

# ------------------------------- 主流程 -------------------------------
Write-Host ""
Write-Host "  AI 回答 → Word 富文本" -ForegroundColor Cyan
Write-Host "  " + ("-" * 46)

$md = Get-Markdown $File
if ([string]::IsNullOrWhiteSpace($md)) {
    Write-Err "剪贴板是空的，也没有指定 -File。请先复制 AI 的回答再运行。"
    exit 1
}
Write-Host "  读到 $($md.Length) 个字符"

Write-Host "  正在请求转换服务 $Server ..."
try {
    $html = Convert-ViaServer -Md $md -Srv $Server
} catch {
    Write-Err $_.Exception.Message
    Write-Host ""
    Write-Host "  提示：转换服务需要先在本机或服务器上跑起来。" -ForegroundColor Yellow
    exit 1
}

Set-ClipboardRich -Html $html
Write-Ok "已写入剪贴板（Word 富文本格式）"
Write-Host ""
Write-Host "  现在切到 Word，按 Ctrl+V 粘贴即可。" -ForegroundColor White
Write-Host "  （标题会变成真正的“标题 1/2/3”，可在导航窗格里看到）" -ForegroundColor DarkGray
Write-Host ""
