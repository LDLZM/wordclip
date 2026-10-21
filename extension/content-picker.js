/*
 * content-picker.js —— 负责"从页面里取出要转换的文字"
 *
 * 两种取法：
 *   PICK：用户选中的内容（最准，用户指哪打哪）。如果选中的是渲染后的 DOM 而
 *         不是 Markdown 原文，就用 domToMarkdown() 把常见结构还原成 Markdown：
 *         标题、粗体、列表、表格、代码块、公式（保留 $...$ / $$...$$）。
 *   WHOLE：没有选中时，识别页面里"最后一段回答"的主体容器。
 *         AI 聊天页选择器常变，所以用多套选择器 + 兜底"最长的文本块"策略。
 *
 * 只读 DOM，不改页面、不发网络请求。所有结果都返回给 background.js。
 */

(() => {
  if (window.__wordclipPickerInstalled) return;
  window.__wordclipPickerInstalled = true;

  // 各站回答容器的候选选择器（按可靠性排序，取第一个命中的）
  const ANSWER_SELECTORS = [
    // ChatGPT
    '[data-message-author-role="assistant"]',
    'article[data-testid^="conversation-turn"] [data-message-author-role="assistant"]',
    // Claude
    '[data-testid="assistant-message"]',
    'div[class*="font-claude-message"]',
    // DeepSeek
    '.ds-markdown',
    '[class*="ds-markdown"]',
    // 豆包 / 通义 / Kimi / 文心
    '[class*="markdown-body"]',
    '[class*="markdown"]',
    // 通用
    'article',
    'main',
  ];

  function norm(s) {
    return (s || '').replace(/\u00a0/g, ' ').replace(/[\u200B-\u200D\uFEFF]/g, '');
  }

  function isVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) return false;
    const st = getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
  }

  // ---------- DOM -> Markdown ----------
  function domToMarkdown(root) {
    const out = [];
    const push = (s) => { if (s != null) out.push(s); };

    function inlineMd(node) {
      let s = '';
      node.childNodes.forEach((n) => {
        if (n.nodeType === Node.TEXT_NODE) { s += norm(n.nodeValue); return; }
        if (n.nodeType !== Node.ELEMENT_NODE) return;
        const tag = n.tagName.toLowerCase();
        if (tag === 'br') { s += '\n'; return; }
        if (tag === 'script' || tag === 'style' || tag === 'button' || tag === 'svg') return;
        const inner = inlineMd(n);
        switch (tag) {
          case 'strong': case 'b':
            s += inner.trim() ? '**' + inner.trim() + '**' : inner; break;
          case 'em': case 'i':
            s += inner.trim() ? '*' + inner.trim() + '*' : inner; break;
          case 'del': case 's':
            s += inner.trim() ? '~~' + inner.trim() + '~~' : inner; break;
          case 'code':
            s += inner ? '`' + inner.replace(/`/g, '\\`') + '`' : ''; break;
          case 'a': {
            const href = n.getAttribute('href') || '';
            s += inner.trim() && href ? '[' + inner.trim() + '](' + href + ')' : inner;
            break;
          }
          case 'img': {
            const alt = n.getAttribute('alt') || '';
            const src = n.getAttribute('src') || '';
            if (/^https?:/i.test(src) && !src.startsWith('blob:')) s += '![' + alt + '](' + src + ')';
            break;
          }
          case 'sup': s += inner.trim() ? '^' + inner.trim() : inner; break;
          case 'sub': s += inner.trim() ? '~' + inner.trim() : inner; break;
          // 公式：多数站点用 katex/mathjax，把源码或 tex 注解捞回来
          case 'math': case 'mjx-container': case 'span': case 'div': {
            const ann = n.querySelector && n.querySelector('annotation[encoding="application/x-tex"]');
            if (ann) {
              const disp = n.classList && (n.classList.contains('katex-display') || n.classList.contains('math-display'));
              const tex = ann.textContent.trim();
              s += disp ? '\n\n$$\n' + tex + '\n$$\n\n' : '$' + tex + '$';
              break;
            }
            s += inner;
            break;
          }
          default:
            s += inner;
        }
      });
      return s;
    }

    function block(el) {
      if (!el || el.nodeType !== Node.ELEMENT_NODE) return;
      const tag = el.tagName.toLowerCase();
      if (['script', 'style', 'button', 'svg', 'noscript'].includes(tag)) return;
      if (el.getAttribute && el.getAttribute('aria-hidden') === 'true') return;

      switch (tag) {
        case 'h1': case 'h2': case 'h3': case 'h4': case 'h5': case 'h6': {
          const lvl = Number(tag[1]);
          const t = inlineMd(el).replace(/\s+/g, ' ').trim();
          if (t) push('\n' + '#'.repeat(lvl) + ' ' + t + '\n');
          return;
        }
        case 'p': {
          const t = inlineMd(el).trim();
          if (t) push('\n' + t + '\n');
          return;
        }
        case 'ul': case 'ol': {
          push('');
          let i = 1;
          el.querySelectorAll(':scope > li').forEach((li) => {
            const t = inlineMd(li).replace(/\s+/g, ' ').trim();
            const marker = tag === 'ol' ? (i++) + '. ' : '- ';
            if (t) push(marker + t);
          });
          push('');
          return;
        }
        case 'pre': {
          const code = el.querySelector('code') || el;
          let txt = code.innerText.replace(/\u00a0/g, ' ');
          txt = txt.replace(/\s+$/, '');
          const lang = (code.className || '').match(/language-([\w+-]+)/);
          push('\n```' + (lang ? lang[1] : '') + '\n' + txt + '\n```\n');
          return;
        }
        case 'blockquote': {
          const t = inlineMd(el).trim();
          if (t) push('\n' + t.split('\n').map((l) => '> ' + l).join('\n') + '\n');
          return;
        }
        case 'table': {
          const rows = [...el.querySelectorAll('tr')].filter(isVisible);
          if (!rows.length) return;
          const cellText = (c) => inlineMd(c).replace(/\s+/g, ' ').trim().replace(/\|/g, '\\|');
          const header = [...rows[0].children].map(cellText);
          push('');
          push('| ' + header.join(' | ') + ' |');
          push('|' + header.map(() => ' --- ').join('|') + '|');
          rows.slice(1).forEach((r) => {
            push('| ' + [...r.children].map(cellText).join(' | ') + ' |');
          });
          push('');
          return;
        }
        case 'hr': push('\n---\n'); return;
        case 'math': case 'mjx-container': {
          const ann = el.querySelector('annotation[encoding="application/x-tex"]');
          if (ann) push('\n$$\n' + ann.textContent.trim() + '\n$$\n');
          return;
        }
        default: {
          // 容器：看有没有块级孩子，有就递归，没有就按段落处理
          const hasBlock = [...el.children].some((c) =>
            ['p', 'div', 'ul', 'ol', 'pre', 'table', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'section', 'article']
              .includes(c.tagName.toLowerCase()));
          if (hasBlock) {
            [...el.childNodes].forEach((c) => {
              if (c.nodeType === Node.ELEMENT_NODE) block(c);
              else if (c.nodeType === Node.TEXT_NODE && norm(c.nodeValue).trim()) push('\n' + norm(c.nodeValue).trim() + '\n');
            });
          } else {
            const t = inlineMd(el).trim();
            if (t) push('\n' + t + '\n');
          }
        }
      }
    }

    block(root);
    return out.join('\n')
      .replace(/[ \t]+\n/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  // ---------- 取标题 ----------
  function guessTitle() {
    const sel = ['h1', '.conversation-title', '[class*="title"]'];
    for (const s of sel) {
      const el = document.querySelector(s);
      if (el && isVisible(el)) {
        const t = norm(el.innerText).trim().split('\n')[0];
        if (t && t.length <= 80) return t;
      }
    }
    return norm(document.title).split(/[-|]/)[0].trim().slice(0, 60);
  }

  // ---------- 选区 -> Markdown ----------
  function selectionMarkdown() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) return '';
    const text = norm(sel.toString()).trim();
    if (!text) return '';

    // 选区里有富结构（表格/列表/代码/公式）时走 DOM 还原，纯文字直接用字符串
    try {
      const frag = sel.getRangeAt(0).cloneContents();
      const host = document.createElement('div');
      host.appendChild(frag);
      const rich = host.querySelector('table, ul, ol, pre, math, mjx-container, .katex');
      if (rich) {
        const md = domToMarkdown(host);
        if (md && md.length > 10) return md;
      }
    } catch (e) { /* 跨 shadow DOM 等情况下退回纯文本 */ }
    return text;
  }

  // ---------- 无选区时：找最后一段回答 ----------
  function wholeAnswer() {
    let best = null;
    let bestScore = 0;
    for (const s of ANSWER_SELECTORS) {
      const list = [...document.querySelectorAll(s)].filter(isVisible);
      if (!list.length) continue;
      const el = list[list.length - 1];
      const score = norm(el.innerText).length;
      if (score > bestScore) { best = el; bestScore = score; }
      if (bestScore > 200) break; // 命中可靠选择器就停
    }
    if (!best) {
      // 兜底：页面里最长的一段可见文本块
      let cands = [...document.querySelectorAll('div, section, article, main')].filter((el) =>
        isVisible(el) && el.children.length <= 40 && norm(el.innerText).length > 80);
      cands.sort((a, b) => norm(b.innerText).length - norm(a.innerText).length);
      best = cands[0] || null;
    }
    if (!best) return { text: '', title: '' };
    return { text: domToMarkdown(best), title: guessTitle() };
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg) return;
    if (msg.type === 'WORDCLIP_PICK') {
      const text = selectionMarkdown();
      sendResponse({ text, title: text ? guessTitle() : '' });
      return true;
    }
    if (msg.type === 'WORDCLIP_WHOLE') {
      sendResponse(wholeAnswer());
      return true;
    }
  });
})();
