/* 弹窗的公共逻辑：设置读写 + 状态显示 + 快捷入口
 *
 * 消息协议（和 background.js 一一对应，改一边必须改另一边）：
 *   {from:'popup', type:'PROBE'}                → {ok, selected:{chars}|null, answer:{chars}|null}
 *   {from:'popup', type:'RUN_CLIP', copyOnly}   → {ok, error?}
 *   {from:'popup', type:'RUN_DOCX'}             → {ok, error?}
 */
const DEFAULTS = {
  // 默认地址留空：公开仓库里不写任何真实站点，用户首次打开弹窗会被引导去设置页。
  server: '',
  token: '',
  preset: '',
  autoCopy: true,
};

const $ = (id) => document.getElementById(id);
let configured = false;

function normalizeServer(s) {
  s = (s || '').trim().replace(/\/+$/, '');
  if (!s) return '';
  if (!/^https?:\/\//i.test(s)) s = 'https://' + s;
  return s.replace(/\/+$/, '');
}

/* 服务器没配时给一句能看懂的话，而不是让用户看英文报错 */
function needSetup(s) {
  return !s || !s.server;
}

function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(DEFAULTS, (v) => {
      v.server = normalizeServer(v.server);
      resolve(v);
    });
  });
}

function send(msg) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ from: 'popup', ...msg }, (r) => {
      if (chrome.runtime.lastError) return resolve({ ok: false, error: chrome.runtime.lastError.message });
      resolve(r || { ok: false, error: '后台无响应' });
    });
  });
}

function flash(msg, kind = '') {
  const el = $('msg');
  el.textContent = msg;
  el.className = 'msg ' + kind;
  clearTimeout(flash._t);
  flash._t = setTimeout(() => { el.textContent = ''; el.className = 'msg'; }, 2600);
}

/* 把当前标签页的页面信息（是不是能选文字、有没有选区）显示出来，
   让用户一眼知道"现在能不能直接转" */
function refreshPageState() {
  const el0 = $('state');
  if (!configured) {
    el0.textContent = '还没设置服务器：点下方"打开设置"填地址和令牌';
    el0.className = 'state bad';
    return;
  }
  send({ type: 'PROBE' }).then((r) => {
    const el = el0;
    if (!r.ok) {
      el.textContent = '当前页面不支持（浏览器内置页 / 商店页不能注入脚本）';
      el.className = 'state bad';
      return;
    }
    if (r.selected && r.selected.chars) {
      el.textContent = `已选中 ${r.selected.chars} 字，可直接转换`;
      el.className = 'state good';
    } else {
      const n = r.answer ? r.answer.chars : 0;
      el.textContent = n
        ? `未选中内容；会转换识别到的最长回答（${n} 字）`
        : '未选中内容；将转换整个页面正文';
      el.className = 'state';
    }
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  const s = await getSettings();
  configured = !needSetup(s);
  $('server').textContent = s.server
    ? s.server.replace(/^https?:\/\//, '')
    : '（未设置）';
  $('tokenState').textContent = s.token ? '已填写' : '未填写';
  $('tokenState').className = s.token ? 'pill ok' : 'pill warn';

  $('btnOpen').onclick = () => {
    chrome.tabs.create({ url: chrome.runtime.getURL('options.html') });
  };

  if (!configured) {
    $('btnConvert').textContent = '打开设置';
    $('btnConvert').onclick = () => {
      chrome.tabs.create({ url: chrome.runtime.getURL('options.html') });
      window.close();
    };
    $('btnCopyOnly').disabled = true;
    $('btnCopyOnly').textContent = '只复制（先设置服务器）';
    refreshPageState();
    return;
  }

  $('btnConvert').onclick = async () => {
    flash('转换中…');
    const r = await send({ type: 'RUN_CLIP' });
    if (r.ok) {
      flash('已转成 Word 格式并复制', 'good');
      setTimeout(() => window.close(), 700);
    } else {
      flash(r.error || '转换失败', 'bad');
    }
  };

  $('btnCopyOnly').onclick = async () => {
    const r = await send({ type: 'RUN_CLIP', copyOnly: true });
    flash(r.ok ? '已按 Word 格式复制' : (r.error || '失败'), r.ok ? 'good' : 'bad');
  };

  refreshPageState();
});
