/*
 * background.js —— 扩展的"大脑"
 *
 * 三条入口共用同一套流程：
 *   1) 右键菜单 / 快捷键 / 弹窗按钮
 *   2) 先由 content-picker.js 拿到"用户选中的内容"（优先用选区，
 *      没有选区才把整段回答识别出来）
 *   3) 请求服务器换成 Word 剪贴板 HTML（POST /api/clip）或 .docx（POST /api/docx）
 *   4) 剪贴板路径：把 HTML 交给 content-paste.js 写进页面剪贴板的 "HTML Format"
 *      槽位（浏览器切回 Word 时 Ctrl+V 就是好格式）；docx 路径：直接下载
 *
 * 为什么剪贴板要走页面里的 navigator.clipboard：
 *   service worker 里没有 ClipboardItem 的写权限上下文，
 *   扩展页面写 HTML 剪贴板依赖 focus，页面内写入最稳。
 */

const DEFAULTS = {
  // 公开仓库不写真实站点；首次使用由设置页填写
  server: '',
  token: '',
  // 选中内容为空时的兜底：是否自动识别页面里的整段回答
  allowWholeAnswer: true,
};

async function getCfg() {
  const got = await chrome.storage.sync.get(DEFAULTS);
  return { ...DEFAULTS, ...got };
}

function trimServer(s) {
  return (s || '').replace(/\/+$/, '');
}

function joinUrl(server, path) {
  return trimServer(server) + path;
}

function authHeaders(cfg, extra) {
  const h = Object.assign({}, extra || {});
  if (cfg.token) h['X-Md2W-Token'] = cfg.token;
  return h;
}

/** 给用户看的提示：优先用系统通知，失败就退回角标 */
async function notify(title, message) {
  try {
    await chrome.notifications.create({
      type: 'basic',
      iconUrl: 'icons/icon128.png',
      title,
      message: message || '',
    });
  } catch (e) {
    console.warn('通知失败', e);
  }
}

async function badge(text, color) {
  try {
    await chrome.action.setBadgeText({ text: text || '' });
    if (color) await chrome.action.setBadgeBackgroundColor({ color });
  } catch (e) { /* ignore */ }
}

/**
 * 让目标页面里的 content-paste.js 收到要写入剪贴板的 HTML。
 * 页面没注入过就先注入，再发消息。
 */
async function pasteHtmlInPage(tabId, html, plainText) {
  const payload = { type: 'WORDCLIP_PASTE', html, plainText };
  // 注意：内容脚本自己写失败时也会"正常回复"，所以必须看回包的 ok，
  // 不能只看 sendMessage 有没有抛异常。
  try {
    const r = await chrome.tabs.sendMessage(tabId, payload);
    if (r && r.ok) return true;
    console.warn('剪贴板写入被页面拒绝', r && r.error);
  } catch (e) {
    // 内容脚本还没注入（页面在扩展安装前就打开了）
    try {
      await chrome.scripting.executeScript({ target: { tabId }, files: ['content-paste.js'] });
      await new Promise((r) => setTimeout(r, 120));
      const r = await chrome.tabs.sendMessage(tabId, payload);
      if (r && r.ok) return true;
      console.warn('剪贴板写入被页面拒绝', r && r.error);
    } catch (e2) {
      console.error('写剪贴板失败', e2);
    }
  }
  // 页面里写不进去时，退一步：把纯文本写进剪贴板（格式丢了但至少能粘）
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: (t) => navigator.clipboard.writeText(t),
      args: [plainText || ''],
    });
    return true;
  } catch (e3) {
    return false;
  }
}

async function saveDocx(blob, name) {
  const reader = new FileReader();
  const b64 = await new Promise((resolve, reject) => {
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
  // service worker 里不能直接 URL.createObjectURL 下载，用 downloads API 的 data URL
  await chrome.downloads.download({
    url: 'data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,' + b64,
    filename: name || 'ai-answer.docx',
    saveAs: false,
  });
}

/** 主流程 */
async function run(kind, tab, opts) {
  const o = opts || {};
  const cfg = await getCfg();
  if (!trimServer(cfg.server)) {
    await notify('还没设置服务器', '打开扩展选项，填入你自己部署的 md2word 地址');
    // 直接把设置页弹出来，别让用户自己去找入口
    try { await chrome.runtime.openOptionsPage(); } catch (e) { /* ignore */ }
    return { ok: false, error: '还没设置服务器地址' };
  }
  if (!cfg.token) {
    await notify('还没填令牌', '打开扩展选项，填入服务器给你的调用令牌');
    try { await chrome.runtime.openOptionsPage(); } catch (e) { /* ignore */ }
    return { ok: false, error: '还没填访问令牌' };
  }

  // 1) 取内容：先要选区
  let picked = null;
  try {
    picked = await chrome.tabs.sendMessage(tab.id, { type: 'WORDCLIP_PICK' });
  } catch (e) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['content-picker.js'],
      });
      picked = await chrome.tabs.sendMessage(tab.id, { type: 'WORDCLIP_PICK' });
    } catch (e2) {
      await notify('拿不到页面内容', '这个页面不允许扩展读取（chrome:// 页面、扩展商店等）');
      return { ok: false, error: '这个页面不允许扩展读取内容' };
    }
  }

  let md = (picked && picked.text || '').trim();
  let title = (picked && picked.title || '').trim();

  if (!md) {
    if (!cfg.allowWholeAnswer) {
      await notify('没有选中文字', '先在页面上选中要转换的回答，再点一次');
      return;
    }
    try {
      const whole = await chrome.tabs.sendMessage(tab.id, { type: 'WORDCLIP_WHOLE' });
      md = (whole && whole.text || '').trim();
      if (whole && whole.title) title = whole.title;
    } catch (e) { /* ignore */ }
  }

  if (!md) {
    await notify('没有找到可转换的内容', '请先用鼠标选中 AI 的回答');
    return { ok: false, error: '没有找到可转换的内容' };
  }

  await badge('…', '#a8791f');

  // 2) 请服务器转换
  const body = { md, title, style: await lastStyle() };
  const url = joinUrl(cfg.server, kind === 'docx' ? '/api/docx' : '/api/clip');

  let resp;
  try {
    resp = await fetch(url, {
      method: 'POST',
      headers: authHeaders(cfg, { 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    });
  } catch (e) {
    await badge('!', '#a8341f');
    await notify('连不上服务器', '检查扩展选项里的服务器地址，以及网络是否可达：' + cfg.server);
    return { ok: false, error: '连不上服务器' };
  }

  if (resp.status === 401) {
    await badge('!', '#a8341f');
    await notify('令牌不对', '打开扩展选项，填入服务器给你的调用令牌');
    return { ok: false, error: '令牌不对（401）' };
  }
  if (!resp.ok) {
    let msg = '转换失败（HTTP ' + resp.status + '）';
    try { msg = (await resp.json()).error || msg; } catch (e) { }
    await badge('!', '#a8341f');
    await notify('转换失败', msg);
    return { ok: false, error: msg };
  }

  // 3) 落地
  if (kind === 'docx') {
    const blob = await resp.blob();
    const cd = resp.headers.get('Content-Disposition') || '';
    let name = '';
    const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    if (star) {
      try { name = decodeURIComponent(star[1]); } catch (e) { }
    }
    await saveDocx(blob, name || (title ? title + '.docx' : 'ai-answer.docx'));
    await badge('✓', '#2f6b3a');
    await notify('已下载 Word 文件', name || 'ai-answer.docx');
    setTimeout(() => badge(''), 2500);
    return { ok: true };
  } else {
    // 服务端返回 JSON：html 是 Word HTML 片段，cfhtml 是带 CF_HTML 信封的版本
    // （偏移量按 UTF-8 字节算好）。写剪贴板要用 cfhtml，否则 Word 读到错位会退化成纯文本。
    let html = '';
    let cfhtml = '';
    try {
      const d = await resp.json();
      html = d.html || '';
      cfhtml = d.cfhtml || html;
    } catch (e) {
      html = await resp.text();
      cfhtml = html;
    }
    if (!html) {
      await badge('!', '#a8341f');
      await notify('服务器返回空内容', '检查服务器日志');
      return { ok: false, error: '服务器返回空内容' };
    }
    const ok = await pasteHtmlInPage(tab.id, cfhtml, md);
    if (ok) {
      await badge('✓', '#2f6b3a');
      if (!o.quiet) await notify('已复制为 Word 格式', '切换到 Word，Ctrl+V 粘贴即可');
    } else {
      await badge('!', '#a8341f');
      if (!o.quiet) await notify('写入剪贴板失败', '改用"下载 .docx"，或在这台电脑上用网页版');
      return { ok: false, error: '写入剪贴板失败（页面不允许写剪贴板）' };
    }
    setTimeout(() => badge(''), 2500);
  }
}

/** 排版预设：和网页版共用一套，记在本地，下次沿用 */
async function lastStyle() {
  try {
    const { lastStyle } = await chrome.storage.local.get('lastStyle');
    return lastStyle || null;
  } catch (e) {
    return null;
  }
}

// ---------- 右键菜单 ----------
chrome.runtime.onInstalled.addListener(async () => {
  await chrome.contextMenus.removeAll();
  chrome.contextMenus.create({
    id: 'wc-clip',
    title: '转成 Word 格式（复制到剪贴板）',
    contexts: ['selection', 'page'],
  });
  chrome.contextMenus.create({
    id: 'wc-docx',
    title: '转成 Word 文件（.docx 下载）',
    contexts: ['selection', 'page'],
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab) return;
  if (info.menuItemId === 'wc-clip') run('clip', tab);
  else if (info.menuItemId === 'wc-docx') run('docx', tab);
});

// ---------- 快捷键 ----------
chrome.commands.onCommand.addListener(async (cmd, tab) => {
  const t = tab || (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
  if (!t) return;
  if (cmd === 'convert-selection-to-clipboard') run('clip', t);
  else if (cmd === 'convert-selection-to-docx') run('docx', t);
});

// ---------- 弹窗按钮发来的请求 ----------
/* 给弹窗的探测：返回当前标签页上"有没有选中内容 / 有没有可识别的整段回答"，
   只回字数不回正文（正文没必要离开页面）。 */
async function probe(tab) {
  try {
    let r = null;
    try {
      r = await chrome.tabs.sendMessage(tab.id, { type: 'WORDCLIP_PICK' });
    } catch (e) {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content-picker.js'] });
      await new Promise((x) => setTimeout(x, 80));
      r = await chrome.tabs.sendMessage(tab.id, { type: 'WORDCLIP_PICK' });
    }
    const selected = r && r.text ? { chars: r.text.length } : null;
    let answer = null;
    if (!selected) {
      try {
        const w = await chrome.tabs.sendMessage(tab.id, { type: 'WORDCLIP_WHOLE' });
        if (w && w.text) answer = { chars: w.text.length };
      } catch (e) { /* ignore */ }
    }
    return { ok: true, selected, answer };
  } catch (e) {
    return { ok: false, error: '页面不允许扩展读取' };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.from !== 'popup') return;
  (async () => {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const tab = tabs[0];
    if (!tab) { sendResponse({ ok: false, error: '没有活动标签页' }); return; }
    if (msg.type === 'PROBE') {
      sendResponse(await probe(tab));
    } else if (msg.type === 'RUN_CLIP') {
      sendResponse(await run('clip', tab, { quiet: !!msg.copyOnly }));
    } else if (msg.type === 'RUN_DOCX') {
      sendResponse(await run('docx', tab));
    } else if (msg.type === 'SAVE_STYLE') {
      await chrome.storage.local.set({ lastStyle: msg.style || null });
      sendResponse({ ok: true });
    } else {
      sendResponse({ ok: false, error: '未知消息类型: ' + msg.type });
    }
  })();
  return true; // 异步响应
});
