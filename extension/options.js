/* 设置页：服务器地址 / 令牌 / 默认样式 / 自动复制 */
const DEFAULTS = {
  // 默认地址留空：公开仓库里不写任何真实站点，用户首次打开弹窗会被引导去设置页。
  server: '',
  token: '',
  preset: '',
  autoCopy: true,
};

const $ = (id) => document.getElementById(id);

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

function say(t, kind = '') {
  const el = $('status');
  el.textContent = t;
  el.className = 'status ' + kind;
}

function mask(t) {
  if (!t) return '（未填写）';
  if (t.length <= 8) return t[0] + '…';
  return t.slice(0, 4) + '…' + t.slice(-4);
}

async function load() {
  const s = await new Promise((r) => chrome.storage.sync.get(DEFAULTS, r));
  $('server').value = normalizeServer(s.server);
  $('token').value = s.token || '';
  $('autoCopy').checked = !!s.autoCopy;
  $('preset').value = s.preset || '';
  say(`当前令牌：${mask(s.token)}（共 ${(s.token || '').length} 字符）`, s.token ? 'ok' : 'warn');

  // 样式预设从服务器拉，扩展里不写死
  try {
    const r = await fetch(normalizeServer(s.server) + '/api/presets');
    const d = await r.json();
    if (d && d.ok && Array.isArray(d.presets)) {
      const sel = $('preset');
      sel.innerHTML = '<option value="">默认（宋体小四，1.5 倍行距）</option>';
      for (const p of d.presets) {
        const o = document.createElement('option');
        o.value = p.key;
        o.textContent = p.label || p.name || p.key;
        sel.appendChild(o);
      }
      sel.value = s.preset || '';
    }
  } catch (e) {
    $('preset').innerHTML = '<option value="">（连不上服务器，先用默认）</option>';
  }
}

$('btnSave').onclick = async () => {
  const server = normalizeServer($('server').value);
  await new Promise((r) => chrome.storage.sync.set({
    server,
    token: $('token').value.trim(),
    autoCopy: $('autoCopy').checked,
    preset: $('preset').value,
  }, r));
  $('server').value = server;
  say('已保存', 'ok');
};

$('btnTest').onclick = async () => {
  const server = normalizeServer($('server').value);
  const token = $('token').value.trim();
  if (!token) return say('请先填写令牌再测试', 'warn');
  say('正在测试…');
  try {
    const r = await fetch(server + '/api/clip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Md2W-Token': token },
      body: JSON.stringify({ md: '# 测试\n\n令牌有效检查。' }),
    });
    if (r.status === 401) return say('令牌不对（401）', 'bad');
    if (!r.ok) return say(`服务器返回 ${r.status}`, 'bad');
    const d = await r.json();
    say(d.ok ? '连通，转换正常' : ('失败：' + (d.error || '未知')), d.ok ? 'ok' : 'bad');
  } catch (e) {
    say('连不上：' + (e.message || e), 'bad');
  }
};

$('btnShow').onclick = () => {
  const t = $('token');
  t.type = t.type === 'password' ? 'text' : 'password';
  $('btnShow').textContent = t.type === 'password' ? '显示' : '隐藏';
};

document.addEventListener('DOMContentLoaded', load);
