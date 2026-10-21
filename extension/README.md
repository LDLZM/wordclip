# 浏览器扩展（Edge / Chrome）

把 AI 回答（ChatGPT、DeepSeek、Claude、Kimi…）**选中就转成 Word 格式**，直接 `Ctrl+V` 粘进 Word/WPS，公式、三线表、标题层级都在。

不装任何软件、不装 PowerShell 脚本，浏览器里点一下就行。

---

## 它怎么工作

    你的浏览器                          服务器（wordclip）
    ──────────                          ──────────────────
    选中一段回答  ──── Markdown ────▶    pandoc + 自建 Word 样式表
                  ◀─── CF_HTML ────      （标题字号/三线表/公式/行距）
    写进剪贴板  ──▶  Ctrl+V 进 Word

浏览器本身**不能**把“带完整 Word 样式的 HTML”写进剪贴板（`navigator.clipboard`
只接受纯文本和有限的 HTML），所以格式计算放在服务器上；浏览器只负责把算好的
CF_HTML 信封塞进剪贴板。这就是为什么必须填一个服务器地址 + 令牌。

## 安装

1. 打开 Edge，地址栏输入 `edge://extensions`（Chrome 是 `chrome://extensions`）
2. 打开左下/右侧的 **开发人员模式**
3. 点 **加载解压缩的扩展**，选中本目录（就是含 `manifest.json` 的这个文件夹）
4. 点扩展图标 → **设置** → 填服务器地址和令牌 → **保存** → **测试连通**
5. 打开任意 AI 聊天页，选中回答 → 右键 → **转成 Word 格式并复制** → 去 Word 里 `Ctrl+V`

> Edge 每次启动会提示“是否关闭开发人员模式扩展”，选 **保留** 即可。
> 想彻底摆脱这个提示，得把扩展上架到 Edge 加载项商店（需要开发者账号）。

## 三种用法

| 用法 | 操作 | 取哪段内容 |
|---|---|---|
| 右键菜单 | 选中文字后右键 → “转成 Word 格式并复制” | 选中的那段 |
| 快捷键 | 选中后按 `Alt+Shift+W` | 选中的那段 |
| 工具栏图标 | 点扩展图标 → “转换并复制” | 有选区用选区，没选区自动找页面上最长的那段回答 |

没有选区时，扩展会去找页面上“最像 AI 回答”的那个块（`data-message-author-role`、
`.markdown`、`.prose` 等常见容器），取文字最多的一个。人工选中永远优先。

## 为什么要"读取所有网站数据"

扩展需要两件事：在你选中的页面上读文字，以及把你填的服务器地址发请求。
服务器是**你自己填的**，代码没法提前知道是谁，所以清单里只能写 `<all_urls>`
（安装时 Edge 会提示"可读取和更改你所有网站上的数据"）。

它实际只做三件事：读当前页面的 DOM（选取中的那段 / 识别 AI 回答）、
向你配置的那一个服务器地址发 POST、往剪贴板写。没有埋点、没有第三方域名、
不采集浏览记录。代码全部在本目录，可以自己审。
如果你改代码把服务器地址写死，可以把 `host_permissions` 收窄成那一个域名。

## 设置项

| 项 | 说明 |
|---|---|
| 站点地址 | 你的 wordclip 服务器，例如 `https://你的域名/md2word`；只填域名会自动补 `https://` |
| 访问令牌 | 服务器主人给的那串字符，只存在本机浏览器（`chrome.storage.sync`），不上传 |
| 样式预设 | 从服务器 `/api/presets` 拉取，改了服务器端预设这里会自动出现 |
| 自动复制 | 关掉后只在弹窗里提示“已转换”，需要你自己点“只复制” |

令牌、服务器地址都存在浏览器同步存储里，换电脑登录同一账号会自动带过去。
**不要**把令牌写进代码或公开仓库。

## 踩过的坑（改代码前先读）

1. **剪贴板格式名必须是 `HTML Format`，不是 `text/html`。**
   `text/html` 只带纯 HTML，Word 会当成普通网页处理，粘出来样式全丢。
2. **CF_HTML 的偏移量按 UTF-8 字节算，不是字符数。**
   中文一个字 3 字节，按字符算偏移会差几倍，Word 读到错位就退化成纯文本。
   `content-paste.js` 里 `withCorrectOffsets()` 负责重算，服务端 `to_cf_html()` 也算一份，
   两边对上才稳。
3. **`StartFragment` 标记和正文之间要有换行。** 贴在一起会吃掉第一个字符。
4. **HTML 片段不能只有一个裸 `<h1>`。** 必须保留 `<html><head><style>`，
   否则 Word 拿不到 `mso-*` 样式，粘出来就是“普通文字”而不是标题/三线表。
5. **浏览器扩展的内容脚本拿不到页面里的 `window` 变量**，只能读 DOM。
   所以 `content-picker.js` 是把渲染后的 DOM 反推成 Markdown（标题层级、表格、列表、
   `$$...$$` 公式），而不是去猜页面内部的 React state。
6. **`edge://` / `chrome://` / 扩展商店页面不允许注入脚本**，在这些页面上右键菜单会提示失败，属正常。

## 目录

    manifest.json        扩展清单（MV3）
    background.js        右键菜单/快捷键/弹窗的统一流程，负责调服务器 + 写剪贴板
    content-picker.js    从页面取内容（选区优先，DOM → Markdown）
    content-paste.js     把 CF_HTML 写进系统剪贴板
    popup.html/.js       工具栏弹窗
    options.html/.js     设置页（服务器、令牌、预设、测试连通）
    icons/               16/32/48/128 图标（tests/make_icons.py 生成，纯标准库）
    tests/selfcheck.py   静态自检（清单引用、HTML id 绑定、chrome API 权限、括号配平）
    tests/logic_test.js  node 跑：CF_HTML 偏移三种情况 + DOM→Markdown 结构断言
    tests/e2e_server.py  服务端契约验证（12 项，可打公网）
    tests/check_cfhtml_field.py   校验服务端返回的 cfhtml 偏移是否按字节算

## 自检

```bash
python3 tests/selfcheck.py                       # 静态自检（不需要 node）
node    tests/logic_test.js                      # CF_HTML 偏移 + 消息协议逻辑
python3 tests/e2e_server.py <站点地址> <令牌>    # 服务端 12 项契约验证
python3 tests/make_icons.py                      # 重新生成图标
python3 tests/check_cfhtml_field.py saved.cfhtml # 单独校验一份服务端输出
```

## 支持的站点

任何网页都能用（选中就能转）。下面这些站点会自动识别“整段回答”，不用手选：

- ChatGPT / chat.openai.com
- DeepSeek
- Claude
- Kimi / 豆包 / 通义 / 文心一言
- Gemini

遇到识别不到的站点，手动选中回答再右键即可。

## 许可

MIT
