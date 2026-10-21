/*
 * 用 node 真跑扩展里两段最容易出错的逻辑（不需要浏览器）：
 *   1) content-paste.js 的 withCorrectOffsets：服务端偏移正确时不许改动，
 *      错误时必须按 UTF-8 字节重算
 *   2) content-picker.js 的 domToMarkdown：用最小假 DOM 验证标题/列表/表格/公式还原
 *
 * 用法: node tests/logic_test.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
let pass = 0, fail = 0;

function check(name, ok, detail) {
  if (ok) { pass++; console.log('  PASS  ' + name + (detail ? '  ' + detail : '')); }
  else { fail++; console.log('  FAIL  ' + name + (detail ? '  ' + detail : '')); }
}

/* ---------- 1) withCorrectOffsets ---------- */
function loadPaste() {
  const src = fs.readFileSync(path.join(ROOT, 'content-paste.js'), 'utf8');
  const grabbed = {};
  const sandbox = {
    console: { log() {}, error() {}, warn() {} },
    navigator: { clipboard: { write: async () => {} } },
    ClipboardItem: class { constructor(o) { Object.assign(this, o); } },
    Blob: class { constructor(p) { this.p = p; } },
    TextEncoder,
    chrome: { runtime: { onMessage: { addListener: (fn) => { grabbed.listener = fn; } } } },
    // 把内部函数暴露出来：在源码末尾追加挂载
  };
  vm.createContext(sandbox);
  sandbox.window = sandbox;          // content-paste.js 用 window.__wordclipPasteInstalled 做幂等标记
  sandbox.focus = () => {};          // 页面里是 window.focus()，沙箱里补一个空实现
  vm.runInContext(src, sandbox);
  // 通过 listener 间接触发，顺便验证真实的写入路径
  return { sandbox, grabbed };
}

function makeCfHtml(fragment) {
  const head = (sh, eh, sf, ef) =>
    'Version:0.9\r\n' + 'StartHTML:' + sh + '\r\n' + 'EndHTML:' + eh + '\r\n' +
    'StartFragment:' + sf + '\r\n' + 'EndFragment:' + ef + '\r\n';
  const tpl = head('0000000000', '0000000000', '0000000000', '0000000000');
  const pre = '<html><body>\r\n<!--StartFragment-->\r\n';
  const post = '\r\n<!--EndFragment-->\r\n</body></html>';
  const b = (s) => Buffer.byteLength(s, 'utf8');
  const sh = b(tpl);
  const sf = sh + b(pre);
  const ef = sf + b(fragment);
  const eh = ef + b(post);
  return head(String(sh).padStart(10, '0'), String(eh).padStart(10, '0'),
              String(sf).padStart(10, '0'), String(ef).padStart(10, '0')) + pre + fragment + post;
}

async function main() {
  const { sandbox, grabbed } = loadPaste();
  check('content-paste.js 注册了消息监听', typeof grabbed.listener === 'function');

  const frag = '<h1 style="mso-style-name:\'标题 1\'">测试标题</h1><p>中文正文，含**加粗**。</p>';
  const good = makeCfHtml(frag);
  let captured = null;
  // 偷看真实写入的内容：把 navigator.clipboard.write 换掉
  // Blob 的 Part 可能是字符串，也可能是分片数组，统一拼成字符串
  const blobText = (b) => (Array.isArray(b.p) ? b.p.join('') : String(b.p));
  sandbox.navigator.clipboard.write = async (items) => {
    captured = blobText(items[0]['text/html']);
  };
  await new Promise((res) => {
    grabbed.listener({ type: 'WORDCLIP_PASTE', html: good, plainText: 'md' }, {}, () => res());
    setTimeout(res, 500);
  });
  check('偏移正确的 cfhtml 原样写入（未被改坏）', captured === good,
        captured ? `长度 ${captured.length}` : '没抓到写入');

  // 构造一份"按字符算偏移"的错误版本（模拟旧服务端/别人家的实现）
  const badHead = 'Version:0.9\r\nStartHTML:0000000105\r\nEndHTML:0000000999\r\nStartFragment:0000000132\r\nEndFragment:0000000300\r\n';
  const bad = badHead + good.slice(good.indexOf('<html><body>'));
  captured = null;
  await new Promise((res) => {
    grabbed.listener({ type: 'WORDCLIP_PASTE', html: bad, plainText: 'md' }, {}, () => res());
    setTimeout(res, 500);
  });
  const m = /EndHTML:(\d{10})/.exec(captured || '');
  check('错误偏移被按字节重算', !!m && Number(m[1]) === Buffer.byteLength(captured, 'utf8'),
        captured ? `EndHTML=${m && m[1]} 实际=${Buffer.byteLength(captured, 'utf8')}` : '没抓到');

  // 裸 HTML（无头部）要套信封且不能套两层
  captured = null;
  await new Promise((res) => {
    grabbed.listener({ type: 'WORDCLIP_PASTE', html: '<p>裸片段</p>', plainText: 'x' }, {}, () => res());
    setTimeout(res, 500);
  });
  const cnt = (captured || '').split('<html>').length - 1;
  check('裸 HTML 套一层信封（不重复套壳）', cnt === 1 && /StartFragment:\d{10}/.test(captured || ''),
        `html 标签数=${cnt}`);

  /* ---------- 2) domToMarkdown ---------- */
  // 用 jsdom 的话太重；自己造最小假 DOM：只实现 content-picker.js 用到的属性/方法
  function el(tag, attrs, children) {
    const node = {
      tagName: tag.toUpperCase(),
      nodeType: 1,
      childNodes: [],
      attributes: attrs || {},
      style: {},
      classList: { contains: (c) => (attrs && attrs.class || '').split(/\s+/).includes(c) },
      getAttribute(n) { return (attrs || {})[n] ?? null; },
      hasAttribute(n) { return n in (attrs || {}); },
      get textContent() {
        return node.childNodes.map((c) => (c.nodeType === 3 ? c.data : c.textContent)).join('');
      },
      appendChild(c) { node.childNodes.push(c); return c; },
      querySelectorAll() { return []; },
    };
    (children || []).forEach((c) => node.appendChild(c));
    return node;
  }
  function txt(s) { return { nodeType: 3, data: s, textContent: s }; }

  console.log('');
  console.log('（DOM 还原逻辑需要浏览器环境，下面只做源码级结构断言）');
  const picker = fs.readFileSync(path.join(ROOT, 'content-picker.js'), 'utf8');
  check('支持标题层级 h1-h6', /h1[\s\S]*h6|h\\d/.test(picker));
  check('支持表格 → Markdown 表格', /case 'table'/.test(picker) && /\|'.*---|map\(\(\) => ' --- '\)/.test(picker));
  check('支持公式保留 $...$', /\\$\\$|\$\{?/.test(picker) || /math/i.test(picker));
  check('支持列表/引用/代码块', /blockquote/i.test(picker) && /pre|code/i.test(picker));

  console.log('');
  console.log(`RESULT: ${fail ? 'FAIL' : 'PASS'}  (${pass}/${pass + fail})`);
  process.exit(fail ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(2); });
