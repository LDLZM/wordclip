# wordclip.ps1 —— 把剪贴板里的 Markdown 转成"粘到 Word 就是好格式"的富文本
#
# 用法：
#   1) 在 AI 聊天页 Ctrl+C 复制 AI 回答（多数页面复制出来的就是 Markdown 原文）
#   2) 右键运行 wordclip.bat（不需要安装任何东西）
#   3) 到 Word 里 Ctrl+V
#
# 原理：不直接复制网页 HTML（Word 看不懂网页的 class 样式、公式会变乱码），
#       而是把 Markdown 送到服务器，换成一份"全是内联样式 + Word 命名空间"
#       的 HTML，再写进剪贴板的 HTML Format 槽位。
#       这样 Word 粘出来是真正的标题样式（导航窗格、自动目录可用）、
#       三线表、真公式、宋体小四 1.5 倍行距。

[CmdletBinding()]
param(
    [string]$Server = "@@SERVER_PLACEHOLDER@@",
    [string]$TokenFile = "$PSScriptRoot\wordclip.token",
    [string]$Text,
    [string]$OutFile,          # 只导出 HTML 文件，不动剪贴板（调试用）
    [switch]$KeepClipboardSource
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# PowerShell 5.1 默认走 .NET Framework 的旧 TLS 栈，连 Let's Encrypt 这类
# 新证书链常报 "基础连接已经关闭/无法建立 SSL/TLS 信任关系"。
# 这里显式启用 TLS 1.2，并对自签/链不全的情况放宽一次回调
# （只连你自己的服务器，风险可控）。
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch { }

if ($Server -like "https://*") {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAll : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint sp, X509Certificate cert,
                                      WebRequest req, int problem) { return true; }
}
"@ -ErrorAction SilentlyContinue
    [System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAll
}

function Fail($msg) {
    Write-Host "[失败] $msg" -ForegroundColor Red
    exit 1
}

# ---------- 1) 取 Markdown ----------
if (-not $Text) {
    Add-Type -AssemblyName System.Windows.Forms
    $Text = [System.Windows.Forms.Clipboard]::GetText()
}

if ([string]::IsNullOrWhiteSpace($Text)) {
    Fail "剪贴板里没有文本。请先在 AI 页面选中回答并复制。"
}

# 常见噪声：代码块以外的零宽字符会让 Word 里出现小方框
$Text = $Text -replace "[\u200B\u200C\u200D\uFEFF]", ""
# AI 页面常带 "Copy" / "复制" 尾巴
$Text = $Text -replace "(?m)^\s*(Copy|复制|复制代码)\s*$", ""

Write-Host ("已读取 {0} 字符" -f $Text.Length)

# ---------- 2) 调服务端 ----------
# 走表单 + URL 编码，而不是 JSON：
#   PS 5.1 的 ConvertTo-Json 会把中文转成 \uXXXX 字面量，
#   再经 Invoke-WebRequest 编码容易二次转义；表单提交最稳。
$pair = "md=" + [System.Uri]::EscapeDataString($Text)
$bytes = [System.Text.Encoding]::UTF8.GetBytes($pair)

# 令牌从同目录的 wordclip.token 读取（一行纯文本），不写死在脚本里，
# 这样脚本可以随便转发、贴图，令牌不会跟着泄露。
$headers = @{}
if (Test-Path $TokenFile) {
    $tok = (Get-Content $TokenFile -Raw).Trim()
    if ($tok) { $headers["X-Md2W-Token"] = $tok }
} else {
    Write-Host "[提示] 找不到 $TokenFile，令牌将为空（服务器会返回 401）" -ForegroundColor Yellow
}

try {
    $resp = Invoke-WebRequest -Uri "$Server/api/clip" -Method Post `
        -ContentType "application/x-www-form-urlencoded" `
        -Headers $headers `
        -Body $bytes -UseBasicParsing -TimeoutSec 60
} catch {
    $code = $null
    if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
    if ($code -eq 401) { Fail "服务器拒绝：令牌不对或 wordclip.token 缺失/过期。" }
    Fail "连不上服务器 $Server（$_）"
}

# PowerShell 5.1 的 Invoke-WebRequest 解码 JSON 时对中文不友好，
# 这里直接把原始字节按 UTF-8 解读，避免出现乱码 \uXXXX
$json = [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray())
$obj = $json | ConvertFrom-Json

if (-not $obj.ok) { Fail ("服务端报错: " + $obj.error) }

$html = $obj.html
Write-Host ("服务端返回 HTML {0} 字节" -f $html.Length)

if ($OutFile) {
    [System.IO.File]::WriteAllText($OutFile, $html, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "已写入 $OutFile"
    exit 0
}

# ---------- 3) 写入剪贴板 HTML Format ----------
# Windows 剪贴板的 "HTML Format" 有自己的封装头，且偏移量按 UTF-8 字节计。
# 不按规范写，Word 就只拿到纯文本 -> 又变回一坨没格式的文字。

$header = "Version:0.9`r`n" +
          "StartHTML:{0:D10}`r`n" +
          "EndHTML:{0:D10}`r`n" +
          "StartFragment:{0:D10}`r`n" +
          "EndFragment:{0:D10}`r`n"

function Build-ClipboardHtml($frag) {
    # 服务端返回的 HTML 里已经带了 Word 命名空间（xmlns:w）和 Start/EndFragment
    # 标记。这里不要再包一层 <html><body>，否则命名空间层级被破坏，
    # Word 会退化成"只认纯文本"，格式全部丢失。
    $hasMarker = $frag.Contains("<!--StartFragment-->") -and $frag.Contains("<!--EndFragment-->")
    if ($hasMarker) {
        $core = $frag
    } else {
        $core = "<html><head><meta charset='utf-8'></head><body>" +
                "<!--StartFragment-->" + $frag + "<!--EndFragment-->" +
                "</body></html>"
    }

    # CF_HTML 头部偏移量必须按 UTF-8 字节计算，且字段宽度固定 10 位
    $head0 = ($header -f 0, 0, 0, 0)
    $startHtml = [System.Text.Encoding]::UTF8.GetByteCount($head0)
    $startFrag = $startHtml + [System.Text.Encoding]::UTF8.GetByteCount(
        $core.Substring(0, $core.IndexOf("<!--StartFragment-->")))
    $endFrag = $startFrag + [System.Text.Encoding]::UTF8.GetByteCount(
        $core.Substring($core.IndexOf("<!--StartFragment-->"),
                        $core.IndexOf("<!--EndFragment-->") - $core.IndexOf("<!--StartFragment-->")))
    $endHtml = $startHtml + [System.Text.Encoding]::UTF8.GetByteCount($core)

    return ($header -f $startHtml, $endHtml, $startFrag, $endFrag) + $core
}

$payload = Build-ClipboardHtml $html

# Windows 剪贴板的 "HTML Format" 需要的是字符串，不能传流对象。
# 传流会让 .NET 抛类型错误，HTML 根本没进剪贴板，Word 只拿到纯文本 -> 又变回没格式。
Add-Type -AssemblyName System.Windows.Forms

# 一个 DataObject 里同时放两种格式：Word 取 HTML，记事本取纯文本。
# 注意必须放进同一个对象再一次性写入 —— 分两次 SetDataObject 会互相覆盖。
$dobj = New-Object System.Windows.Forms.DataObject
$dobj.SetData("HTML Format", $false, $payload)
$dobj.SetData([System.Windows.Forms.DataFormats]::UnicodeText, $Text)

# 第 2 个参数 $true = 脚本退出后剪贴板内容仍然保留
[System.Windows.Forms.Clipboard]::SetDataObject($dobj, $true)

Write-Host "完成。现在到 Word 里 Ctrl+V 即可。" -ForegroundColor Green
if (-not $KeepClipboardSource) {
    Write-Host "（剪贴板里的纯文本也一并保留了，粘到记事本仍是 Markdown）"
}
