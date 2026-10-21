/*
 * content-paste.js —— 把服务端返回的 CF_HTML 写进剪贴板
 *
 * 关键点（踩过的坑，别改）：
 *  1) 写剪贴板用 navigator.clipboard.write + text/html。Word 粘贴时优先读
 *     "HTML Format" 槽位，浏览器会把它转成 Windows 剪贴板格式并带上来源标记。
 *  2) 偏移量必须按 **UTF-8 字节** 计，不是字符数。中文一个 3 字节，
 *     按字符算 StartFragment 会偏小，Word 读到错位就退化成纯文本。
 *     服务端 /api/clip 已经算好（cfhtml 字段），这里只在必要时兜底重算。
 *  3) 服务端返回的 cfhtml 已经带 CF_HTML 头和 StartFragment 标记，
 *     绝对不能再套一层 <html><body>，否则 Word 命名空间失效。
 *  4) 同时在纯文本槽位放 Markdown 原文，方便粘到不支持 HTML 的地方。
 *  5) 写剪贴板需要页面有焦点，所以先 focus 一下。
 */

(() => {
  if (window.__wordclipPasteInstalled) return;
  window.__wordclipPasteInstalled = true;

  function pad10(n) {
    return String(n).padStart(10, '0');
  }

  function byteLen(s) {
    return new TextEncoder().encode(s).length;
  }

  /** 通用信封：给没有 CF_HTML 头、也没有 Word 命名空间的裸 HTML 用 */
  function buildCfHtml(fragment) {
    const headOpen = '<html><body>\r\n<!--StartFragment-->\r\n';
    const tail = '\r\n<!--EndFragment-->\r\n</body></html>';
    const headerTpl =
      'Version:0.9\r\n' +
      'StartHTML:' + pad10(0) + '\r\n' +
      'EndHTML:' + pad10(0) + '\r\n' +
      'StartFragment:' + pad10(0) + '\r\n' +
      'EndFragment:' + pad10(0) + '\r\n';

    const startHtml = byteLen(headerTpl);
    const startFragment = startHtml + byteLen(headOpen);
    const endFragment = startFragment + byteLen(fragment);
    const endHtml = endFragment + byteLen(tail);

    const header =
      'Version:0.9\r\n' +
      'StartHTML:' + pad10(startHtml) + '\r\n' +
      'EndHTML:' + pad10(endHtml) + '\r\n' +
      'StartFragment:' + pad10(startFragment) + '\r\n' +
      'EndFragment:' + pad10(endFragment) + '\r\n';

    return header + headOpen + fragment + tail;
  }

  /**
   * 校验并（必要时）修正偏移量。
   * 服务端已经按字节算对时原样返回；发现头部偏移和实际字节数不符才重算，
   * 这样前端不会把服务端正确的结果改坏。
   */
  function withCorrectOffsets(html) {
    const m = /Version:0\.9\r?\nStartHTML:(\d{10})\r?\nEndHTML:(\d{10})\r?\nStartFragment:(\d{10})\r?\nEndFragment:(\d{10})\r?\n/i.exec(html);
    if (!m) {
      // 没有合法头部：可能是裸 HTML 片段，套一个通用信封
      if (!/xmlns:w=/i.test(html)) return buildCfHtml(html);
      return buildCfHtml(html);
    }

    const sh = Number(m[1]);
    const eh = Number(m[2]);
    const sf = Number(m[3]);
    const ef = Number(m[4]);
    const total = byteLen(html);
    const headOk = eh === total && sh === byteLen(m[0]) && sf <= ef && ef <= eh;
    if (headOk) return html;   // 服务端算对了，一个字都不动

    // 兜底：按 UTF-8 字节重算
    const headLen = byteLen(m[0]);
    const body = html.slice(m[0].length);
    const fragStart = body.indexOf('<!--StartFragment-->');
    const fragEnd = body.lastIndexOf('<!--EndFragment-->');
    if (fragStart < 0 || fragEnd < 0) return html;
    const startFragment = headLen + byteLen(body.slice(0, fragStart + '<!--StartFragment-->'.length));
    const endFragment = headLen + byteLen(body.slice(0, fragEnd));
    const header =
      'Version:0.9\r\n' +
      'StartHTML:' + pad10(headLen) + '\r\n' +
      'EndHTML:' + pad10(headLen + byteLen(body)) + '\r\n' +
      'StartFragment:' + pad10(startFragment) + '\r\n' +
      'EndFragment:' + pad10(endFragment) + '\r\n';
    return header + body;
  }

  async function writeClipboard(cfhtml, plainText) {
    // Chrome/Edge 会把 CF_HTML 头部剥掉，只取 text/html 部分写进系统剪贴板的
    // "HTML Format" 槽位；带头部也不会出错（旧版 Edge 还要求带）。
    const html = withCorrectOffsets(cfhtml);
    const item = new ClipboardItem({
      'text/html': new Blob([html], { type: 'text/html' }),
      'text/plain': new Blob([plainText || ''], { type: 'text/plain' }),
    });
    await navigator.clipboard.write([item]);
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg || msg.type !== 'WORDCLIP_PASTE') return;
    (async () => {
      try {
        if (!navigator.clipboard || !navigator.clipboard.write) {
          throw new Error('这个页面不是安全上下文（http://），浏览器禁止写剪贴板');
        }
        window.focus();
        await writeClipboard(msg.html, msg.plainText);
        sendResponse({ ok: true });
      } catch (e) {
        console.error('剪贴板写入失败', e);
        sendResponse({ ok: false, error: String((e && e.message) || e) });
      }
    })();
    return true; // 异步
  });
})();
