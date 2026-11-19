'use strict';
// Echoic 本機版：網頁介面。資料全部來自 window.pywebview.api（本機 Python），不連任何外部網站。

const S = {
  boot: null, tree: null, view: 'list', mid: null, tab: 'summary', file: null, meeting: null,
  list: { labels: {}, query: '', from: '', to: '', transcript: true }, sel: new Set(), expanded: new Set(),
  project: null, rec: { phase: 'setup', source: null, labels: {}, name: '', attendees: '', notes: [], ctx: null, result: null, job: '' },
  cursor: 0, log: [], busy: '', busyJob: '', recLive: null,
};
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const api = (name, ...args) => window.pywebview.api[name](...args);
const SWATCH = ['#8fd3c9', '#ffd166', '#ff7a59', '#c7b8ff', '#b5e48c', '#f4a7c0', '#9ecbff'];
const SPK = ['#ffd166', '#8fd3c9', '#ffb59f', '#c7b8ff', '#b5e48c', '#f4a7c0', '#9ecbff'];
const ICON = {
  search: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  mic: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
  doc: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9fb3ae" stroke-width="2" aria-hidden="true"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/></svg>',
  check: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9fb3ae" stroke-width="2" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="m8 12 3 3 5-6"/></svg>',
  chev: '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>',
  plug: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9fb3ae" stroke-width="2" aria-hidden="true"><path d="M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0zM12 16v5"/></svg>',
  gear: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9fb3ae" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/></svg>',
  down: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg>',
  logo: '<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><rect width="26" height="26" rx="7" fill="#0f5c57"/><path d="M6 13v0M9.5 9v8M13 6v14M16.5 10v6M20 12v2" stroke="#ffd166" stroke-width="2" stroke-linecap="round"/></svg>',
};

function toast(msg, ms = 2600) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, ms);
}
function swatch(value) {
  const vals = (S.tree?.groups || []).map((g) => g.value);
  const i = vals.indexOf(value);
  return i < 0 ? '#7f948f' : SWATCH[i % SWATCH.length];
}
function speakerColor(name, map) {
  if (!map.has(name)) map.set(name, SPK[map.size % SPK.length]);
  return map.get(name);
}
function fmtClock(sec) {
  sec = Math.max(0, Math.floor(sec)); const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  return [h, m, s].map((x) => String(x).padStart(2, '0')).join(':');
}
function tsToSec(t) { const [h, m, s] = t.split(':').map(Number); return h * 3600 + m * 60 + s; }
function shortDate(d) { return d ? d.slice(5).replace('-', '/') : ''; }
function labelsText(labels) { return Object.values(labels || {}).filter(Boolean).join(' / '); }
function mdLite(text) {  // AI 整理段落：條列與粗體即可
  const lines = String(text || '').split('\n').filter((l) => l.trim());
  let out = '', inList = false;
  for (const l of lines) {
    const m = l.match(/^\s*(?:[-*]|\d+[.)])\s+(.*)$/);
    const body = esc(m ? m[1] : l).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    if (m) { if (!inList) { out += '<ul>'; inList = true; } out += `<li>${body}</li>`; }
    else { if (inList) { out += '</ul>'; inList = false; } out += `<p>${body}</p>`; }
  }
  return `<div class="md">${out}${inList ? '</ul>' : ''}</div>`;
}
function highlight(text) { return esc(text).replace(/\*\*(.+?)\*\*/g, '<mark>$1</mark>'); }

// ------------------------------------------------------------------ 啟動
async function start() {
  S.boot = await api('bootstrap');
  await refreshTree();
  go('list');
  setInterval(pollTick, 400);
  if (S.boot.update_due) api('check_update').then((r) => { if (r && r.newer) toast(`有新版 ${r.version}：到「設定 › 更新」按一下就會換新版`, 6000); });
  if (S.boot.missing.length) toast('初次設定還沒完成：到「設定」下載語音辨識模型', 6000);
}
async function refreshTree() { S.tree = await api('tree'); renderSide(); renderStatus(); }
window.addEventListener('pywebviewready', start);
window.addEventListener('error', (e) => { try { api('js_error', `${e.message} @${e.lineno}:${e.colno}`); } catch (_) { /* 還沒連上 */ } });
window.addEventListener('unhandledrejection', (e) => { try { api('js_error', 'promise: ' + (e.reason && (e.reason.stack || e.reason.message) || e.reason)); } catch (_) { /* 還沒連上 */ } });

// ------------------------------------------------------------------ 導覽
function go(view, params = {}) {
  Object.assign(S, { view }, params);
  if (view !== 'meeting') S.meeting = null;
  renderSide(); render();
  $('#view').scrollTop = 0;
}
function render() {
  const v = S.view;
  if (v === 'list') return renderList();
  if (v === 'meeting') return renderMeeting();
  if (v === 'record') return renderRecord();
  if (v === 'project') return renderProject();
  if (v === 'todos') return renderTodos();
  if (v === 'settings') return renderSettings();
}
function crumbs(parts, path = '') {
  $('#crumbs').innerHTML = parts.map((p) => p.go ? `<a data-go='${esc(JSON.stringify(p.go))}'>${esc(p.t)}</a>` : `<span${p.cur ? ' style="color:var(--fg)"' : ''}>${esc(p.t)}</span>`)
    .join('<span aria-hidden="true">/</span>') + (path ? `<span class="path">${esc(path)}</span>` : '');
  $$('#crumbs a[data-go]').forEach((a) => a.onclick = () => { const g = JSON.parse(a.dataset.go); go(g.view, g.params || {}); });
}

// ------------------------------------------------------------------ 側欄
function renderSide() {
  const t = S.tree; if (!t) return;
  const top = t.top, sub = t.sub, L = S.list.labels;
  const live = S.recLive;
  let h = `<div class="brand">${ICON.logo}<span>Echoic 本機版</span></div>
    <button class="searchbtn" id="sbtn" type="button">${ICON.search}<span>搜尋會議</span><kbd>⌘K</kbd></button>
    ${live ? `<button class="recbtn live" id="rbtn" type="button"><span class="dot"></span>錄音中 <span class="mono" id="sideclock">${fmtClock(live.elapsed)}</span></button>`
            : `<button class="recbtn" id="rbtn" type="button">${ICON.mic}開始錄音</button>`}
    <div class="navlist">
      <button class="navitem${S.view === 'list' && !Object.keys(L).length && !S.list.query ? ' on' : ''}" data-nav="all" type="button">${ICON.doc}<span>全部會議</span><span class="n">${t.total}</span></button>
      <button class="navitem${S.view === 'todos' ? ' on' : ''}" data-nav="todos" type="button">${ICON.check}<span>未完成待辦</span><span class="n">${t.open_todos}</span></button>
    </div>
    <div class="navlist"><div class="sidehead">${esc(top)}${sub ? ' › ' + esc(sub) : ''}</div>`;
  for (const g of t.groups) {
    const open = S.expanded.has(g.value);
    const onTop = (S.view === 'list' || S.view === 'project') && L[top] === g.value && !(sub && L[sub]);
    h += `<button class="navitem${onTop ? ' on' : ''}" data-top="${esc(g.value)}" type="button">${g.children.length ? ICON.chev.replace('class="chev"', `class="chev${open ? ' open' : ''}"`) : '<span style="width:12px"></span>'}
      <span class="sw" style="background:${swatch(g.value)}"></span><span>${esc(g.value)}</span><span class="n">${g.count}</span></button>`;
    if (open) for (const c of g.children) {
      const on = S.view === 'project' && L[top] === g.value && L[sub] === c.value;
      h += `<button class="navitem child${on ? ' on' : ''}" data-top="${esc(g.value)}" data-sub="${esc(c.value)}" type="button"><span>${esc(c.value)}</span><span class="n">${c.count}</span></button>`;
    }
  }
  if (t.unlabeled) h += `<button class="navitem${L[top] === '' ? ' on' : ''}" data-top="" type="button"><span style="width:12px"></span><span class="sw none"></span><span class="muted">未分類</span><span class="n">${t.unlabeled}</span></button>`;
  h += `</div><div class="navlist sidefoot">
      <button class="navitem" data-nav="mcp" type="button">${ICON.plug}<span>AI 助理連線</span><span class="pill${S.boot.settings.mcp_enabled ? ' on' : ''}" style="margin-left:auto">${S.boot.settings.mcp_enabled ? '開' : '關'}</span></button>
      <button class="navitem${S.view === 'settings' ? ' on' : ''}" data-nav="settings" type="button">${ICON.gear}<span>設定</span></button></div>`;
  $('#side').innerHTML = h;
  $('#sbtn').onclick = openSearch;
  $('#rbtn').onclick = () => go('record');
  $$('#side [data-nav]').forEach((b) => b.onclick = () => {
    const n = b.dataset.nav;
    if (n === 'all') { S.list = { labels: {}, query: '', from: '', to: '', transcript: true }; S.sel.clear(); go('list'); }
    else if (n === 'todos') go('todos');
    else if (n === 'settings') go('settings', { settingsFocus: '' });
    else if (n === 'mcp') go('settings', { settingsFocus: 'mcp' });
  });
  $$('#side [data-top]').forEach((b) => b.onclick = (e) => {
    const topV = b.dataset.top, subV = b.dataset.sub;
    if (subV !== undefined) { S.list.labels = { [top]: topV, [sub]: subV }; return go('project', { project: null }); }
    const onChev = e.target.closest('.chev');
    if (onChev || (S.view === 'list' && L[top] === topV && !(sub && L[sub]))) {
      S.expanded.has(topV) ? S.expanded.delete(topV) : S.expanded.add(topV);
      if (onChev) return renderSide();
    } else S.expanded.add(topV);
    S.list = { labels: { [top]: topV }, query: '', from: '', to: '', transcript: true }; S.sel.clear();
    go('list');
  });
}

function renderStatus() {
  const s = S.boot.settings;
  const engine = s.stt_engine === 'api' ? `線上（${esc(s.stt_api_host)}）` : `本機 whisper${s.local_speed === 'background' ? '（背景模式）' : ''}`;
  const busy = S.busy ? `<a class="busy" id="busylink">⏳ ${esc({ pipeline: '轉逐字稿中', summary: '產生摘要中', models: '下載模型中', update: '更新中', project: 'Claude 整理進度中' }[S.busy] || S.busy)}…</a>` : '';
  $('#status').innerHTML = `<span>🔒 存在這台 Mac</span><span>語音辨識：${engine}</span>
    <span>摘要：${S.boot.has_claude ? (s.auto_summary ? '你的 Claude（自動）' : '你的 Claude（手動）') : '沒裝 Claude Code'}</span>
    <span>AI 助理讀取：${s.mcp_enabled ? '開' : '關'}</span>${busy}<span class="grow">v${esc(S.boot.version)}</span>`;
  const bl = $('#busylink'); if (bl) bl.onclick = () => showLog();
}
function showLog() {
  dialog(`<div class="dh">工作紀錄</div><div class="db"><div class="logbox" id="dlog">${esc(S.log.slice(-400).join('\n'))}</div></div>
    <div class="df"><button class="btn" data-close type="button">關閉</button></div>`);
  const l = $('#dlog'); l.scrollTop = l.scrollHeight;
}

// ------------------------------------------------------------------ 會議清單
async function renderList() {
  const t = S.tree, L = S.list;
  const lab = labelsText(L.labels);
  crumbs([{ t: '會議庫' }, ...(lab ? [{ t: lab, cur: true }] : L.labels[t.top] === '' ? [{ t: '未分類', cur: true }] : [{ t: '全部會議', cur: true }])]);
  const res = await api('list_meetings', { labels: L.labels, query: L.query, date_from: L.from, date_to: L.to, transcript: L.transcript });
  S.listItems = res.meetings;
  const sels = t.categories.map((c) => {
    const vals = Object.keys(t.values[c] || {});
    const cur = L.labels[c];
    return `<label>${esc(c)}<select data-cat="${esc(c)}"><option value="__all"${cur === undefined ? ' selected' : ''}>全部</option>
      <option value="__none"${cur === '' ? ' selected' : ''}>未分類</option>${vals.map((v) => `<option${cur === v ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
  }).join('');
  const hasLab = Object.values(L.labels).some(Boolean);
  let h = `<div class="selbar${S.sel.size ? '' : ' hidden'}" id="selbar"><b id="seln">${S.sel.size}</b> 場已選
      <button class="btn" id="bLabel" type="button">設定分類…</button><button class="btn" id="bExp" type="button">${ICON.down}匯出…</button>
      <span class="spacer"></span><button class="btn" id="bClr" type="button">取消選取</button></div>
    <div class="toolbar">${sels}
      <label>日期<input type="date" id="fFrom" value="${esc(L.from)}"></label><label>到<input type="date" id="fTo" value="${esc(L.to)}"></label>
      <label style="flex:1;min-width:200px"><input type="text" id="fQ" placeholder="關鍵字（空白分隔＝都要出現）" value="${esc(L.query)}" style="flex:1"></label>
      <label><input type="checkbox" id="fTr"${L.transcript ? ' checked' : ''}> 也搜逐字稿</label>
      ${hasLab ? `<button class="btn primary" id="bProj" type="button">專案追蹤</button>` : ''}
      ${res.meetings.length ? `<button class="btn" id="bAllExp" type="button">${ICON.down}匯出清單</button>` : ''}
    </div><div class="muted small" style="padding:0 40px 6px">${res.total} 場${L.query ? `符合「${esc(L.query)}」` : ''}</div><div class="rows">`;
  if (!res.meetings.length) h += `<div class="empty">沒有符合的會議。${t.total ? '' : '按左上「開始錄音」錄第一場。'}</div>`;
  for (const m of res.meetings) {
    const tags = Object.entries(m.labels).map(([k, v]) => `<span class="tag" title="${esc(k)}">${esc(v)}</span>`).join('');
    const hits = (m.hits || []).slice(0, 2).map((x) => `<div class="hit"><span class="ts" style="pointer-events:none">${esc(x.source)}${x.timestamp ? ' ' + esc(x.timestamp) : ''}</span>${highlight(x.text)}</div>`).join('');
    h += `<div class="row${S.sel.has(m.id) ? ' sel' : ''}" data-id="${esc(m.id)}"><input type="checkbox" aria-label="選取 ${esc(m.title)}"${S.sel.has(m.id) ? ' checked' : ''}>
      <span class="when">${esc(m.date)}<br>${esc(m.time)}</span>
      <div class="body"><button class="name" type="button">${esc(m.title)}</button>
        <div class="tags">${tags}${m.open_todos ? `<span class="tag" style="background:#2b2a1a;color:var(--sun)">待辦 ${m.open_todos}</span>` : ''}${m.stage !== '摘要完成' ? `<span class="tag">${esc(m.stage)}</span>` : ''}${m.private ? '<span class="tag">🔒 不給 AI 助理</span>' : ''}</div>
        ${hits || (m.one_liner ? `<div class="one">${esc(m.one_liner)}</div>` : '')}</div>
      <span class="muted small">${m.duration_min ? Math.round(m.duration_min) + ' 分' : ''}</span></div>`;
  }
  $('#view').innerHTML = h + '</div>';
  $$('#view select[data-cat]').forEach((s) => s.onchange = () => {
    const v = s.value; if (v === '__all') delete L.labels[s.dataset.cat]; else L.labels[s.dataset.cat] = v === '__none' ? '' : v;
    renderSide(); renderList();
  });
  const q = $('#fQ'); q.onkeydown = (e) => { if (e.key === 'Enter') { L.query = q.value.trim(); renderList(); } };
  $('#fFrom').onchange = (e) => { L.from = e.target.value; renderList(); };
  $('#fTo').onchange = (e) => { L.to = e.target.value; renderList(); };
  $('#fTr').onchange = (e) => { L.transcript = e.target.checked; if (L.query) renderList(); };
  if ($('#bProj')) $('#bProj').onclick = () => go('project', { project: null });
  if ($('#bAllExp')) $('#bAllExp').onclick = () => exportDialog(S.listItems.map((m) => m.id), lab ? `${lab} 會議彙整` : '會議彙整');
  $$('#view .row').forEach((r) => {
    const id = r.dataset.id;
    $('input', r).onchange = (e) => { e.target.checked ? S.sel.add(id) : S.sel.delete(id); r.classList.toggle('sel', e.target.checked); updSel(); };
    $('.name', r).onclick = () => openMeeting(id);
  });
  $('#bLabel').onclick = () => labelDialog([...S.sel]);
  $('#bExp').onclick = () => exportDialog([...S.sel], lab ? `${lab} 會議彙整` : '會議彙整');
  $('#bClr').onclick = () => { S.sel.clear(); renderList(); };
  function updSel() { $('#seln').textContent = S.sel.size; $('#selbar').classList.toggle('hidden', !S.sel.size); }
}

// ------------------------------------------------------------------ 單場會議
async function openMeeting(id, tab = 'summary') {
  S.mid = id; S.tab = tab; S.file = null;
  S.meeting = null; S.view = 'meeting'; renderSide();
  $('#view').innerHTML = '<p class="muted pad">載入中…</p>';
  const m = await api('get_meeting', id);
  if (m.ok === false) { $('#view').innerHTML = `<p class="pad warnline">${esc(m.error)}</p>`; return; }
  S.meeting = m; renderMeeting();
}
function renderMeeting() {
  const m = S.meeting; if (!m) return openMeeting(S.mid, S.tab);
  const t = S.tree, cats = t.categories;
  const pl = m.context.labels || {};
  crumbs([...cats.slice(0, 2).filter((c) => m.labels[c]).map((c, i) => ({ t: m.labels[c], go: { view: 'project', params: { list: { ...S.list, labels: Object.fromEntries(cats.slice(0, i + 1).filter((x) => m.labels[x]).map((x) => [x, m.labels[x]])) }, project: null } } })),
    { t: `${shortDate(m.date)} ${m.title}`, cur: true }], m.id);
  const chips = [`<span class="chip">📅 ${esc(m.date)} ${esc(m.time)}${m.duration_min ? ' · ' + Math.round(m.duration_min) + ' 分' : ''}</span>`,
    ...cats.map((c) => m.labels[c] ? `<button class="chip" type="button" data-lab="${esc(c)}"><span class="sw" style="background:${c === cats[0] ? swatch(m.labels[c]) : '#3a4945'}"></span>${esc(m.labels[c])}</button>` : ''),
    m.attendees.length ? `<span class="chip">👥 ${esc(m.attendees.slice(0, 3).join('、'))}${m.attendees.length > 3 ? ' +' + (m.attendees.length - 3) : ''}</span>` : '',
    m.private ? '<span class="chip">🔒 不給 AI 助理</span>' : ''].join('');
  const busyHere = S.busy && S.busyJob === m.id;
  const hasTr = m.transcript.length > 0, hasSum = !!m.summary_html;
  const failed = m.stt_failed;
  const failBox = failed ? `<div class="box warn" style="margin-top:14px"><div class="h">線上語音辨識失敗</div>
      ${esc(failed.host || '線上服務')} 回來的結果有 ${Math.round((failed.coverage || 0) * 100)}% 是重複的幻覺，所以沒有拿去做逐字稿和摘要。
      常見原因：線上會議只錄了麥克風，對方的聲音是隔著喇叭收進來的（下次錄線上會議請選「麥克風＋系統音」）。
      錄音本身通常沒問題，可以用本機重轉：只這一場，不改你的設定，錄音不會再上傳。
      <div style="margin-top:10px"><button class="btn hot" id="bLocal" type="button"${S.busy ? ' disabled' : ''}>用本機重轉${S.boot.settings.auto_summary && S.boot.has_claude ? '＋摘要' : ''}</button></div></div>`
    : m.stt_partial ? `<div class="box warn" style="margin-top:14px"><div class="h">部分內容可能遺失</div>
      線上語音辨識有 ${Math.round(m.stt_partial * 100)}% 的時間是重複的幻覺（逐字稿裡標「幻覺，已略」的地方），那幾段的內容沒有轉出來。
      想救回來可以用本機重轉：只這一場，錄音不會再上傳；會覆蓋這場現在的逐字稿${hasSum ? '和摘要（摘要裡勾過的待辦也會重來）' : ''}。
      <div style="margin-top:10px"><button class="btn" id="bLocal" type="button"${S.busy ? ' disabled' : ''}>用本機重轉${S.boot.settings.auto_summary && S.boot.has_claude ? '＋摘要' : ''}</button></div></div>` : '';
  const action = failed ? '' : !hasTr ? `<button class="btn hot" id="bRun" type="button"${busyHere || S.busy ? ' disabled' : ''}>轉逐字稿${S.boot.settings.auto_summary && S.boot.has_claude ? '＋摘要' : ''}</button>`
    : (!hasSum && S.boot.has_claude ? `<button class="btn primary" id="bSum" type="button"${S.busy ? ' disabled' : ''}>產生摘要（Claude）</button>` : '');
  const tabs = [['summary', '摘要'], ['transcript', '逐字稿'], ['entities', '專名表'], ['files', '原始檔（MD／HTML）']]
    .map(([k, l]) => `<button class="tab${S.tab === k ? ' on' : ''}" data-tab="${k}" role="tab" aria-selected="${S.tab === k}" type="button">${l}</button>`).join('');
  let body = '';
  if (S.tab === 'summary') body = hasSum ? `<div class="md" id="sum">${linkTs(m.summary_html)}</div>`
    : `<div class="empty">${hasTr ? (S.boot.has_claude ? '這場還沒有摘要。按上面「產生摘要」，會用你自己 Claude 方案的額度。' : '沒有偵測到 Claude Code，所以只有逐字稿。') : '還沒轉逐字稿。'}</div>`;
  if (S.tab === 'transcript') body = hasTr ? transcriptHtml(m.transcript) : '<div class="empty">還沒有逐字稿。</div>';
  if (S.tab === 'entities') body = m.entities_html ? `<div class="md">${m.entities_html}</div><p class="note">要更正專名：打開 entities.md 填「確認正解」，或把常錯的詞加進詞彙表，再按「產生摘要」重做。</p>` : '<div class="empty">這場沒有專名表（做摘要時才會產生）。</div>';
  if (S.tab === 'files') body = filesHtml(m);
  const ctx = m.context;
  const rail = Object.keys(pl).length ? railHtml(ctx, m) : `<div><div class="railh">專案</div><p class="muted">這場還沒分類。設好客戶／專案，就會在這裡看到同專案的其他場、待辦和前後不一致。</p>
    <button class="btn" id="bLab2" type="button">設定分類…</button></div>`;
  $('#view').innerHTML = `<div class="page"><article class="article">
      <h1 class="title">${esc(m.title)}</h1>
      <div class="chips">${chips}<span class="spacer"></span>${action}
        <button class="btn" id="bLab" type="button">分類…</button>
        <button class="btn" id="bExp1" type="button">${ICON.down}匯出</button>
        <button class="btn" id="bFind" type="button">在 Finder 顯示</button></div>
      ${failBox}
      ${busyHere ? `<div class="logbox" id="mlog" style="margin-top:14px">${esc(S.log.slice(-60).join('\n'))}</div>` : ''}
      <div class="tabs" role="tablist" aria-label="這場會議">${tabs}</div>
      <div id="tabbody">${body}</div>
      ${m.has_audio ? `<div class="player"><audio id="aud" controls preload="none" src="media/${encodeURIComponent(m.id)}/audio.wav"></audio></div>` : ''}
    </article><aside class="rail" aria-label="同專案">${rail}</aside></div>`;
  wireMeeting(m);
}
function linkTs(html) {
  return html.replace(/\[(\d{1,2}:\d{2}:\d{2})\]/g, '<button class="ts" type="button" data-t="$1">▶ $1</button>')
    .replace(/｜\s*(<button class="ts")/g, ' $1');  // 待辦最後一欄是時間戳，前面的分隔線不用留
}
function transcriptHtml(lines) {
  const map = new Map();
  return lines.map((l) => {
    if (l.flag === 'hallucination') return `<div class="tr warn"><span class="t"></span><div><p>${esc(l.text)}</p></div></div>`;
    const c = l.speaker ? speakerColor(l.speaker, map) : null;
    return `<div class="tr" data-sec="${l.sec}"><button class="t" type="button" data-t="${l.t}">${l.t}</button><div style="flex:1">
      ${l.speaker ? `<span class="spk" style="background:${c};color:#1d2321">${esc(l.speaker)}</span>` : ''}
      <p>${esc(l.text)}${l.flag === 'suspect' ? ' <span class="muted small">（疑似幻覺）</span>' : ''}</p></div></div>`;
  }).join('') + '<p class="note">點時間就從那裡播放原音。逐字稿是機器轉的，可能有同音錯字；SPEAKER_xx 是機器分的說話人。</p>';
}
function filesHtml(m) {
  const cards = m.files.map((f) => `<button class="file${S.file === f.name ? ' on' : ''}" type="button" data-file="${esc(f.name)}"><div class="nm">${esc(f.name)}</div>
    <div class="muted small">${{ md: 'Markdown', html: 'HTML', text: '文字', audio: '錄音', other: '其他' }[f.kind]} · ${f.bytes > 1e6 ? (f.bytes / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(f.bytes / 1024)) + ' KB'}</div></button>`).join('');
  return `<p class="note" style="margin-top:0">這場資料夾裡的檔案。Markdown 和 HTML 直接在這裡看；你自己放進資料夾的 HTML 檔也會出現在這裡。</p>
    <div class="files">${cards}</div><div id="fview"></div>`;
}
function railHtml(ctx, m) {
  const cats = S.tree.categories;
  const pname = labelsText(ctx.labels);
  const tl = ctx.meetings.slice(0, 8).map((x) => `<a data-mid="${esc(x.id)}" class="${x.id === m.id ? 'cur' : ''}">${shortDate(x.date)}　${esc(x.title)}</a>`).join('');
  const conf = ctx.conflicts && !/沒有發現前後不一致/.test(ctx.conflicts) ? `<div class="box warn"><div class="h">前後不一致</div>${mdLite(ctx.conflicts)}
    ${ctx.report_stale ? '<div class="small" style="margin-top:6px">（整理之後有新會議，可能過期）</div>' : ''}</div>` : '';
  const todos = ctx.open_todos.slice(0, 8).map((t) => `<label class="todo"><input type="checkbox" data-tm="${esc(t.meeting_id)}" data-ti="${t.index}">
    <span>${esc(t.text)} <span class="src">· ${shortDate(t.date)}${t.owner && t.owner !== '未指定' ? ' · ' + esc(t.owner) : ''}</span></span></label>`).join('');
  return `<div><div class="railh">${esc(pname)} 的其他場</div><div class="tl">${tl}</div></div>${conf}
    <div><div class="railh">這個專案還沒做完的（${ctx.open_todos.length}）</div>${todos || '<p class="muted">沒有。</p>'}</div>
    <a id="toProj">看整個專案追蹤 →</a>`;
}
function wireMeeting(m) {
  $$('#view [data-tab]').forEach((b) => b.onclick = () => { S.tab = b.dataset.tab; renderMeeting(); });
  $$('#view [data-lab]').forEach((b) => b.onclick = () => { const cats = S.tree.categories; const i = cats.indexOf(b.dataset.lab);
    S.list.labels = Object.fromEntries(cats.slice(0, i + 1).filter((c) => m.labels[c]).map((c) => [c, m.labels[c]])); go('project', { project: null }); });
  $('#bLab').onclick = () => labelDialog([m.id]); if ($('#bLab2')) $('#bLab2').onclick = () => labelDialog([m.id]);
  $('#bExp1').onclick = () => exportDialog([m.id], m.title);
  $('#bFind').onclick = () => api('reveal', m.id, '');
  if ($('#bRun')) $('#bRun').onclick = () => runPipeline(m.id);
  if ($('#bLocal')) $('#bLocal').onclick = () => runPipeline(m.id, 'local');
  if ($('#bSum')) $('#bSum').onclick = async () => { const r = await api('run_summary', m.id); if (r.ok === false) toast(r.error); else { S.busy = 'summary'; S.busyJob = m.id; renderMeeting(); } };
  $$('#view [data-t]').forEach((b) => b.onclick = () => seek(tsToSec(b.dataset.t)));
  $$('#sum li.task').forEach((li, i) => {
    const cb = $('input', li); cb.disabled = false; li.classList.toggle('done', cb.checked);
    cb.onchange = async () => { const r = await api('set_todo', m.id, i, cb.checked); li.classList.toggle('done', cb.checked); if (!r.ok) toast('沒存起來：' + (r.error || '')); refreshTree(); };
  });
  $$('#view .rail [data-tm]').forEach((cb) => cb.onchange = async () => { await api('set_todo', cb.dataset.tm, Number(cb.dataset.ti), cb.checked); refreshTree(); });
  $$('#view .tl a[data-mid]').forEach((a) => a.onclick = () => openMeeting(a.dataset.mid));
  if ($('#toProj')) $('#toProj').onclick = () => { S.list.labels = { ...m.context.labels }; go('project', { project: null }); };
  $$('#view [data-file]').forEach((b) => b.onclick = () => showFile(m, b.dataset.file));
  const aud = $('#aud');
  if (aud) aud.ontimeupdate = () => {
    if (S.tab !== 'transcript') return;
    const now = aud.currentTime; let cur = null;
    for (const el of $$('#tabbody .tr[data-sec]')) { if (Number(el.dataset.sec) <= now) cur = el; else break; }
    $$('#tabbody .tr.now').forEach((e) => e !== cur && e.classList.remove('now'));
    if (cur && !cur.classList.contains('now')) { cur.classList.add('now'); cur.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
  };
  if (S.file) showFile(m, S.file);
}
function seek(sec) {
  const a = $('#aud'); if (!a) return toast('這場沒有錄音檔');
  const go2 = () => { a.currentTime = sec; a.play(); };
  if (a.readyState >= 1) go2(); else { a.preload = 'auto'; a.addEventListener('loadedmetadata', go2, { once: true }); a.load(); }
}
async function showFile(m, name) {
  S.file = name;
  $$('#view .file').forEach((b) => b.classList.toggle('on', b.dataset.file === name));
  const box = $('#fview'); if (!box) return;
  const r = await api('read_file', m.id, name);
  if (r.ok === false) { box.innerHTML = `<p class="warnline">${esc(r.error)}</p>`; return; }
  const bar = (note) => `<div class="bar">${esc(name)}<span class="spacer"></span>${note}<button class="btn" id="fOpen" type="button">用預設 App 開</button></div>`;
  if (r.kind === 'md') box.innerHTML = `<div class="viewer">${bar('')}<div class="md">${linkTs(r.html)}</div></div>`;
  else if (r.kind === 'html') {
    box.innerHTML = `<div class="viewer">${bar('<span>安全預覽：不執行程式、不連外部網站</span>')}<iframe sandbox="" title="${esc(name)}"></iframe></div>`;
    $('iframe', box).srcdoc = r.text;
  } else if (r.kind === 'text') box.innerHTML = `<div class="viewer">${bar('')}<pre>${esc(r.text)}</pre></div>`;
  else if (r.kind === 'audio') box.innerHTML = `<div class="viewer">${bar('')}<div style="padding:12px"><audio controls preload="none" style="width:100%" src="media/${encodeURIComponent(m.id)}/${encodeURIComponent(name)}"></audio></div></div>`;
  else box.innerHTML = `<div class="viewer">${bar('這種檔案不在這裡預覽')}</div>`;
  $('#fOpen').onclick = () => api('open_external', m.id, name);
  $$('[data-t]', box).forEach((b) => b.onclick = () => seek(tsToSec(b.dataset.t)));
}
async function runPipeline(id, engine = '') {
  const r = await api('run_pipeline', id, null, '', engine);
  if (r.ok === false) return toast(r.error);
  S.busy = 'pipeline'; S.busyJob = id; renderStatus(); render();
}

// ------------------------------------------------------------------ 錄音
async function renderRecord() {
  crumbs([{ t: '錄音', cur: true }]);
  const R = S.rec, t = S.tree, b = S.boot;
  if (S.recLive) R.phase = 'live';
  const cats = t.categories;
  const opts = (c) => Object.keys(t.values[c] || {}).map((v) => `<option value="${esc(v)}">`).join('');
  const labelInputs = cats.map((c) => `<label>${esc(c)}</label><div><input type="text" list="dl-${esc(c)}" data-rl="${esc(c)}" value="${esc(R.labels[c] || '')}" placeholder="選填，可打新的"><datalist id="dl-${esc(c)}">${opts(c)}</datalist></div>`).join('');
  const srcs = [['mic', '只錄麥克風（實體會議）', !!b.mic], ['both', '麥克風＋系統音（線上會議）', !!(b.mic && b.blackhole)], ['system', '只錄系統音', !!b.blackhole]];
  // 預設照舊版（ui.py）：有 BlackHole 就「兩者都錄」。只錄麥克風時，線上會議對方的聲音是隔著喇叭收進來的，
  // 線上辨識會整段判成沒人講話而幻覺（2026-11-19 實例）。選過就沿用使用者的選擇。
  if (!R.source || !srcs.some(([v, , ok]) => v === R.source && ok)) {
    R.source = (srcs.find(([v, , ok]) => v === 'both' && ok) || srcs.find(([, , ok]) => ok) || ['mic'])[0];
  }
  const ready = !b.missing.length;
  let main = '';
  if (R.phase === 'setup') {
    main = `<h1 class="title">新會議</h1>
      ${ready ? '' : `<div class="box warn"><div class="h">初次設定還沒完成</div>還沒下載語音辨識模型。可以先錄，轉逐字稿前到「設定」下載（約 1.6 GB，一次）。</div>`}
      <div class="form" style="margin-top:14px">
        <label>錄音來源</label><div class="radios">${srcs.map(([v, l, ok]) => `<label class="radio${R.source === v ? ' on' : ''}"><input type="radio" name="src" value="${v}"${R.source === v ? ' checked' : ''}${ok ? '' : ' disabled'}>${l}${ok ? '' : '（找不到裝置）'}</label>`).join('')}</div>
        <label>會議名稱</label><input type="text" id="rName" value="${esc(R.name)}" placeholder="選填；留空＝摘要後由模型取名">
        ${labelInputs}
        <label>與會者</label><input type="text" id="rAtt" value="${esc(R.attendees)}" placeholder="選填，逗號分隔；填了就照人數分離、摘要用人名">
      </div>
      <p class="note">麥克風：${esc(b.mic || '找不到')}　｜　系統音（BlackHole）：${esc(b.blackhole || '未安裝')}</p>
      <div><button class="btn hot" id="rStart" type="button" style="min-height:44px;padding:10px 20px">${ICON.mic}開始錄音</button></div>`;
  } else if (R.phase === 'live') {
    const live = S.recLive || { elapsed: 0, db: -90 };
    main = `<div class="recpanel"><div class="chips"><span class="chip" style="color:var(--warn-fg);border-color:var(--coral)"><span class="dot" style="animation:pulse 1.2s infinite"></span>錄音中</span>
        <span class="clock" id="rClock">${fmtClock(live.elapsed)}</span><span class="spacer"></span><span class="mono small" id="rDb" style="color:var(--mint)">${Math.round(live.db)} dB</span></div>
        <canvas class="wave" id="wave" height="240"></canvas>
        <div class="chips"><button class="btn hot" id="rStop" type="button" style="min-height:44px">■ 停止錄音</button><span class="spacer"></span>
        <span class="muted small">${esc(labelsText(R.labels) || '未分類')}${R.attendees ? ' · ' + esc(R.attendees) : ''}</span></div></div>
      <section style="margin-top:20px"><div style="display:flex;gap:10px;align-items:baseline"><h2 style="margin:0;font-size:17px;color:var(--sun)">我的筆記</h2>
        <span class="note">邊錄邊打，按 Enter 記一行，自動記下錄音時間；做摘要時會參考</span></div>
        <div class="notes" style="margin-top:8px">${R.notes.map((n) => `<div class="n"><span class="mono">${esc(n.t)}</span><span>${esc(n.text)}</span></div>`).join('')}
        <div class="n"><span class="mono" id="nowT">${fmtClock(live.elapsed)}</span><input type="text" id="noteIn" placeholder="輸入重點，按 Enter" aria-label="筆記"></div></div></section>`;
  } else {
    const res = R.result || {};
    const busyThis = S.busy && S.busyJob === R.job;
    const s = b.settings;
    main = `<h1 class="title">${res.ok ? '錄好了' : '錄音沒有成功'}</h1><p>${esc(res.message || '')}</p>
      ${res.quiet ? `<p class="warnline">這場偏小聲（平均 ${esc(res.mean_db)} dB），轉錄會先正規化。</p>` : ''}
      ${res.ok ? `<div class="chips" style="margin:10px 0 16px">
        <button class="btn hot" id="rRun" type="button"${S.busy ? ' disabled' : ''}>轉逐字稿${s.auto_summary && b.has_claude ? '＋摘要' : ''}（${s.stt_engine === 'api' ? '線上 ' + esc(s.stt_api_host) : '本機'}）</button>
        <button class="btn" id="rOpen" type="button">打開這場</button><button class="btn" id="rNew" type="button">＋ 再錄一場</button></div>
        <p class="note">${s.stt_engine === 'api' ? '⚠️ 線上語音辨識會把錄音上傳到 ' + esc(s.stt_api_host) + '。要改回本機：設定 › 語音辨識。' : '本機轉錄：一小時的會議大約 12～16 分鐘，轉的時候電腦照常能用。'}</p>` : `<button class="btn" id="rNew" type="button">再試一次</button>`}
      ${busyThis || R.ran ? `<div class="logbox" id="rlog">${esc(S.log.slice(-80).join('\n'))}</div>` : ''}`;
  }
  const ctx = R.ctx;
  const rail = ctx && ctx.meetings && ctx.meetings.length ? recRail(ctx) : `<div class="note">選了客戶／專案，這裡會列出上一場還沒做完的事和之前講法不一樣的地方，開會時就能順手問。</div>`;
  $('#view').innerHTML = `<div class="page"><main class="article">${main}</main><aside class="rail" aria-label="這場可以問">${rail}</aside></div>`;
  wireRecord();
}
function recRail(ctx) {
  const last = ctx.last;
  const lt = last ? last.todos.map((t) => `<label class="todo${t.done ? ' done' : ''}"><input type="checkbox" data-tm="${esc(t.meeting_id)}" data-ti="${t.index}"${t.done ? ' checked' : ''}><span>${esc(t.text)}${t.owner && t.owner !== '未指定' ? ` <span class="src">${esc(t.owner)}</span>` : ''}</span></label>`).join('') : '';
  const conf = ctx.conflicts && !/沒有發現前後不一致/.test(ctx.conflicts) ? `<div class="box warn"><div class="h">之前講法不一樣的</div>${mdLite(ctx.conflicts)}</div>` : '';
  const next = ctx.next_up ? `<div class="box"><div class="h">上次整理的「下次要追」</div>${mdLite(ctx.next_up)}</div>` : '';
  return `${last ? `<div class="box mint"><div class="h">上次（${shortDate(last.date)}）的待辦</div>${lt || '<p class="muted">沒有待辦。</p>'}
      <div class="small muted" style="margin-top:6px">會議中就能順手問，不用等會議記錄出來才發現漏問。</div></div>` : ''}
    ${conf}${next}<div class="note">右欄來自這個專案以前的摘要，錄音時不送任何東西出去。</div>`;
}
function wireRecord() {
  const R = S.rec;
  $$('#view input[name=src]').forEach((r) => r.onchange = () => { R.source = r.value; renderRecord(); });
  if ($('#rName')) $('#rName').oninput = (e) => { R.name = e.target.value; };
  if ($('#rAtt')) $('#rAtt').oninput = (e) => { R.attendees = e.target.value; };
  $$('#view [data-rl]').forEach((i) => i.onchange = async () => {
    R.labels[i.dataset.rl] = i.value.trim();
    R.ctx = await api('recording_context', R.labels); renderRecord();
  });
  $$('#view .rail [data-tm]').forEach((cb) => cb.onchange = () => api('set_todo', cb.dataset.tm, Number(cb.dataset.ti), cb.checked));
  if ($('#rStart')) $('#rStart').onclick = async () => {
    const r = await api('record_start', { source: R.source, labels: R.labels, name: R.name, attendees: R.attendees });
    if (r.ok === false) return toast(r.error, 5000);
    (r.notes || []).forEach((n) => toast(n, 6000));
    R.phase = 'live'; R.job = r.job; R.notes = []; S.recLive = { elapsed: 0, db: -90, levels: [] }; R.ran = false;
    renderSide(); renderRecord(); setTimeout(() => $('#noteIn') && $('#noteIn').focus(), 50);
  };
  if ($('#rStop')) $('#rStop').onclick = async () => {
    $('#rStop').disabled = true;
    const r = await api('record_stop');
    S.recLive = null; R.phase = 'done'; R.result = r; R.job = r.job || R.job;
    await refreshTree(); renderRecord();
  };
  const ni = $('#noteIn');
  if (ni) ni.onkeydown = async (e) => {
    if (e.key !== 'Enter' || e.isComposing || !ni.value.trim()) return;
    const text = ni.value.trim(); ni.value = '';
    const r = await api('add_note', text);
    if (r.ok) { R.notes.push({ t: r.t, text }); const row = document.createElement('div'); row.className = 'n';
      row.innerHTML = `<span class="mono">${esc(r.t)}</span><span>${esc(text)}</span>`; ni.parentElement.before(row); }
  };
  if ($('#rRun')) $('#rRun').onclick = async () => {
    const r = await api('run_pipeline', R.job, null, R.attendees);
    if (r.ok === false) return toast(r.error);
    S.busy = 'pipeline'; S.busyJob = R.job; R.ran = true; renderStatus(); renderRecord();
  };
  if ($('#rOpen')) $('#rOpen').onclick = () => openMeeting(R.job);
  if ($('#rNew')) $('#rNew').onclick = () => { S.rec = { phase: 'setup', source: R.source, labels: { ...R.labels }, name: '', attendees: R.attendees, notes: [], ctx: R.ctx, result: null, job: '' }; renderRecord(); };
  drawWave();
}
function drawWave() {
  const c = $('#wave'); if (!c || !S.recLive) return;
  const w = c.clientWidth * 2; if (c.width !== w) c.width = w;
  const g = c.getContext('2d'), h = c.height, lv = S.recLive.levels || [];
  g.clearRect(0, 0, c.width, h);
  const n = 160, bw = c.width / n;
  for (let i = 0; i < n; i++) {
    const db = lv[lv.length - n + i]; if (db === undefined) continue;
    const v = Math.max(0.03, Math.min(1, (db + 60) / 55)), bh = v * h * 0.92;
    g.fillStyle = i > n - 12 ? '#ffd166' : '#2f7d73';
    g.fillRect(i * bw + 1, (h - bh) / 2, Math.max(2, bw - 3), bh);
  }
}

// ------------------------------------------------------------------ 專案追蹤
async function renderProject() {
  const labels = Object.fromEntries(Object.entries(S.list.labels).filter(([, v]) => v));
  if (!Object.keys(labels).length) return go('list');
  const p = await api('project', labels);
  if (p.ok === false) { $('#view').innerHTML = `<p class="pad warnline">${esc(p.error)}</p>`; return; }
  S.project = p;
  const name = labelsText(labels), cats = S.tree.categories;
  crumbs(Object.entries(labels).map(([k, v], i, arr) => i < arr.length - 1 ? { t: v, go: { view: 'list', params: {} } } : { t: v, cur: true }), p.thread_file.replace(/^.*\/meetings\//, ''));
  const ms = p.meetings, first = ms[ms.length - 1], last = ms[0];
  const running = S.busy === 'project';
  const cards = p.progress || p.conflicts || p.next_up ? `<div class="cards3">
      <div class="box"><div class="h" style="color:var(--muted);font-weight:500;font-size:13px">目前進度</div>${mdLite(p.progress) }</div>
      <div class="box warn"><div class="h" style="font-size:13px">前後不一致</div>${mdLite(p.conflicts)}</div>
      <div class="box mint"><div class="h" style="font-size:13px">下次會議要追的</div>${mdLite(p.next_up)}</div></div>
      <div class="note">${esc(p.report_at)}${p.report_stale ? '　⚠️ 之後有新會議，建議重新整理' : ''}</div>`
    : `<div class="empty">還沒請 Claude 整理過。按右上「請 Claude 整理進度」：會讀這 ${p.with_summary} 場的摘要（不含逐字稿），整理出目前進度、前後不一致、待辦追蹤、下次要追的事；用你自己 Claude 方案的額度。</div>`;
  const tl = ms.map((m) => `<div class="it"><div class="chips" style="gap:10px"><span class="mono small muted">${esc(m.date)}</span><a data-mid="${esc(m.id)}" style="font-weight:700;color:var(--fg)">${esc(m.title)}</a></div>
      ${m.one_liner ? `<div class="small" style="color:var(--fg3)">${esc(m.one_liner)}</div>` : ''}
      ${m.decisions.length ? `<ul class="small" style="margin:4px 0 0;padding-left:18px;color:var(--fg3)">${m.decisions.slice(0, 4).map((d) => `<li>${esc(d.replace(/\s*\[\d{1,2}:\d{2}:\d{2}\]/g, ''))}</li>`).join('')}</ul>` : ''}</div>`).join('');
  const todo = (t) => `<label class="card todo${t.done ? ' done' : ''}"><input type="checkbox" data-tm="${esc(t.meeting_id)}" data-ti="${t.index}"${t.done ? ' checked' : ''}>
      <span style="flex:1"><span>${esc(t.text)}</span><br><span class="src">${t.owner ? esc(t.owner) + ' · ' : ''}${t.due && t.due !== '未指定' ? esc(t.due) + ' · ' : ''}出自 ${shortDate(t.date)}</span></span></label>`;
  $('#view').innerHTML = `<div class="pad" style="display:flex;flex-direction:column;gap:22px;max-width:1100px">
    <div class="chips" style="align-items:flex-end"><div style="flex:1;min-width:260px">
      <div class="muted small"><span class="sw" style="display:inline-block;background:${swatch(labels[cats[0]] || '')}"></span> ${esc(Object.keys(labels).join(' › '))}</div>
      <h1 class="title" style="margin:2px 0 0">${esc(name)}</h1>
      <div class="muted small">${ms.length} 場會議${ms.length ? ` · ${esc(first.date)} ～ ${esc(last.date)}` : ''} · 未完成待辦 ${p.open_todos.length} · 已完成 ${p.done_todos.length}</div></div>
      <button class="btn primary" id="pAI" type="button"${!S.boot.has_claude || S.busy || !p.with_summary ? ' disabled' : ''}>${running ? '⏳ Claude 整理中…' : '請 Claude 整理進度'}</button>
      <button class="btn" id="pExp" type="button">${ICON.down}匯出</button>
      <button class="btn hot" id="pRec" type="button">${ICON.mic}錄這個專案的會</button></div>
    ${cards}
    <div class="cols"><section style="flex:3 1 420px"><h2 style="margin:0 0 12px;font-size:17px;color:var(--sun)">時間線（新 → 舊）</h2><div class="tl2">${tl}</div></section>
      <section style="flex:2 1 300px"><h2 style="margin:0 0 12px;font-size:17px;color:var(--sun)">跨會議待辦</h2>
        <div style="display:flex;flex-direction:column;gap:8px">${p.open_todos.map(todo).join('') || '<p class="muted">沒有未完成的。</p>'}
        ${p.done_todos.length ? `<details><summary class="muted small" style="cursor:pointer">已完成 ${p.done_todos.length}</summary><div style="display:flex;flex-direction:column;gap:8px;margin-top:8px">${p.done_todos.map(todo).join('')}</div></details>` : ''}</div></section></div></div>`;
  $$('#view [data-mid]').forEach((a) => a.onclick = () => openMeeting(a.dataset.mid));
  $$('#view [data-tm]').forEach((cb) => cb.onchange = async () => { await api('set_todo', cb.dataset.tm, Number(cb.dataset.ti), cb.checked); await refreshTree(); renderProject(); });
  $('#pExp').onclick = () => exportDialog(ms.map((m) => m.id), `${name} 會議彙整`);
  $('#pRec').onclick = async () => { S.rec = { ...S.rec, phase: 'setup', labels: { ...labels }, ctx: await api('recording_context', labels) }; go('record'); };
  $('#pAI').onclick = () => confirmDialog('請 Claude 整理進度',
    `會把「${esc(name)}」${p.with_summary} 場會議的摘要（一句話、決議、待辦、數字表，<b>不含逐字稿</b>）送給這台電腦登入的 Claude，整理出目前進度、決議前後不一致、待辦追蹤、下次要追的事。<br><br>會用到你自己 Claude 方案的用量。`,
    '開始整理', async () => { const r = await api('run_project_report', labels); if (r.ok === false) toast(r.error); else { S.busy = 'project'; renderStatus(); renderProject(); } });
}

// ------------------------------------------------------------------ 未完成待辦
async function renderTodos() {
  crumbs([{ t: '未完成待辦', cur: true }]);
  const todos = await api('open_todos');
  const top = S.tree.top;
  const groups = new Map();
  for (const t of todos) { const k = labelsText(t.labels) || '未分類'; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(t); }
  let h = `<div class="pad" style="max-width:960px"><h1 class="title">未完成待辦 <span class="muted" style="font-size:18px">${todos.length}</span></h1>
    <p class="note">勾掉會直接改那場的 summary.md，Obsidian 那邊也會跟著變。</p>`;
  for (const [k, list] of groups) {
    h += `<h2 style="font-size:16px;margin:22px 0 8px"><span class="sw" style="display:inline-block;background:${swatch(list[0].labels[top] || '')}"></span> ${esc(k)} <span class="muted small">${list.length}</span></h2>
      <div style="display:flex;flex-direction:column;gap:6px">${list.map((t) => `<label class="card todo"><input type="checkbox" data-tm="${esc(t.meeting_id)}" data-ti="${t.index}">
        <span style="flex:1">${esc(t.text)}<br><span class="src">${t.owner ? esc(t.owner) + ' · ' : ''}${t.due && t.due !== '未指定' ? esc(t.due) + ' · ' : ''}<a data-mid="${esc(t.meeting_id)}">${shortDate(t.date)} ${esc(t.title)}</a></span></span></label>`).join('')}</div>`;
  }
  if (!todos.length) h += '<div class="empty">沒有未完成的待辦。</div>';
  $('#view').innerHTML = h + '</div>';
  $$('#view [data-tm]').forEach((cb) => cb.onchange = async () => { await api('set_todo', cb.dataset.tm, Number(cb.dataset.ti), cb.checked); cb.closest('label').classList.toggle('done', cb.checked); refreshTree(); });
  $$('#view a[data-mid]').forEach((a) => a.onclick = (e) => { e.preventDefault(); openMeeting(a.dataset.mid); });
}

// ------------------------------------------------------------------ 設定
async function renderSettings() {
  crumbs([{ t: '設定', cur: true }]);
  const b = S.boot, s = b.settings = await api('get_settings');
  const mi = await api('mcp_info');
  const cats = s.categories;
  const recent = mi.recent.slice(0, 8).map((r) => `<div class="small"><span class="mono muted">${esc(r.at)}</span> ${esc(r.client)} · ${esc(r.tool)}${r.meetings && r.meetings.length ? ` · ${r.meetings.length} 場` : ''}</div>`).join('') || '<div class="note">還沒有任何 AI 助理讀取過。</div>';
  $('#view').innerHTML = `<div class="settings">
    <section><h2>語音辨識</h2>
      <div class="seg" role="radiogroup" aria-label="語音辨識"><button type="button" role="radio" data-eng="local" class="${s.stt_engine === 'local' ? 'on' : ''}" aria-checked="${s.stt_engine === 'local'}">本機 whisper（錄音不出電腦）</button>
        <button type="button" role="radio" data-eng="api" class="${s.stt_engine === 'api' ? 'on' : ''}" aria-checked="${s.stt_engine === 'api'}">線上 API（較快，會上傳錄音）</button></div>
      <label class="check"><input type="checkbox" id="sBg"${s.local_speed === 'background' ? ' checked' : ''}><span>本機背景模式：降低優先權、少用核心，其他程式更不受影響，但多花約 4 成時間</span></label>
      <details${s.stt_engine === 'api' ? ' open' : ''}><summary style="cursor:pointer">線上 API 設定（${esc(s.stt_api_host)}，${esc(s.stt_api_model)}，key ${s.has_api_key ? '已設定' : '未設定'}）</summary>
        <div class="form" style="margin-top:10px"><label>網址</label><input type="text" id="aUrl" value="${esc(s.stt_api_base_url)}">
          <label>模型</label><input type="text" id="aModel" value="${esc(s.stt_api_model)}">
          <label>API key</label><input type="password" id="aKey" placeholder="${s.has_api_key ? '已存過，留空就沿用' : '只存在這台電腦'}" autocomplete="off">
          <label>快速填入</label><div class="chips">${Object.entries(b.presets).map(([n, [u, m]]) => `<button class="btn" type="button" data-pre="${esc(u)}|${esc(m)}">${esc(n)}</button>`).join('')}</div></div>
        <p class="warnline">${esc(b.api_warning)}</p><button class="btn primary" id="aSave" type="button">儲存並改用線上</button></details></section>
    <section><h2>摘要</h2>
      <label class="check"><input type="checkbox" id="sAuto"${s.auto_summary ? ' checked' : ''}${b.has_claude ? '' : ' disabled'}><span>轉完逐字稿後，自動用 Claude 產生摘要</span></label>
      <p class="note">${b.has_claude ? '摘要用這台電腦登入的 Claude Code，算進你自己 Claude 方案的用量：一小時的會議大約送出 4～5 萬字。不勾也能用，想要哪場再按「產生摘要」。' : '沒有偵測到 Claude Code，只會產出逐字稿。安裝並登入後重開 App 就能用。'}</p></section>
    <section><h2>分類欄位</h2><p class="note" style="margin:0">會議用哪些欄位分類，逗號分隔，最多 6 個。第一個是側欄的大類，第二個是底下的小類（例：客戶, 專案）。</p>
      <div class="chips"><input type="text" id="sCats" value="${esc(cats.join(', '))}" style="flex:1;min-width:240px"><button class="btn" id="sCatsSave" type="button">儲存</button></div></section>
    <section id="mcpSec"><h2>AI 助理連線（MCP）</h2>
      <p class="note" style="margin:0">打開後，你自己設定的 AI 助理（Claude Desktop、Claude Code 等）可以列出、搜尋、讀取會議摘要與逐字稿，也能查客戶／專案的進度與待辦。只能讀，不能改或刪。</p>
      <p class="warnline" style="margin:0">⚠️ 助理讀到的內容會送到那個助理背後的 AI 服務（例如 Claude 就是 Anthropic）。公司或客戶的會議，先確認那家服務可以用；不想給的會議在「分類…」勾「不給 AI 助理讀」。</p>
      <label class="check"><input type="checkbox" id="mOn"${s.mcp_enabled ? ' checked' : ''}><span><b>允許 AI 助理讀取會議記錄</b></span></label>
      <label class="check"><input type="checkbox" id="mTr"${s.mcp_transcripts ? ' checked' : ''}><span>也給逐字稿（不勾＝只給摘要、待辦與專案追蹤）</span></label>
      <div class="form">${cats.map((c) => `<label>只開放這些${esc(c)}</label><input type="text" data-scope="${esc(c)}" value="${esc((s.mcp_scope[c] || []).join(', '))}" placeholder="留空＝全部；多個用逗號分隔">`).join('')}</div>
      <div class="chips"><button class="btn primary" id="mSave" type="button">儲存</button></div>
      <div><b>接到 Claude Desktop</b>：設定 › 開發者 › 編輯設定，把下面的 echoic-local 加進 mcpServers，存檔後重開。</div>
      <pre class="snip">${esc(mi.config_json)}</pre>
      <div class="chips"><button class="btn" id="mCopy1" type="button">複製 Claude Desktop 設定</button><button class="btn" id="mCopy2" type="button">複製 Claude Code 指令</button></div>
      <div><b>最近的讀取紀錄</b> <span class="note">（${esc(mi.log_path.replace(/^.*\/\.config\//, '~/.config/'))}）</span></div>${recent}</section>
    <section><h2>語音辨識模型</h2>${b.missing.length ? `<p>還沒下載：${b.missing.includes('engine') ? '語音辨識引擎（請重新安裝 App，或從原始碼跑的話 brew install whisper-cpp）' : ''}${b.missing.includes('model') ? 'Whisper 模型（約 1.6 GB，一次）' : ''}</p>
      ${b.missing.includes('model') ? `<div><button class="btn primary" id="sDl" type="button"${S.busy ? ' disabled' : ''}>下載語音辨識模型</button></div>` : ''}` : '<p class="note" style="margin:0">✅ 引擎與模型都就緒。</p>'}</section>
    <section><h2>更新</h2><label class="check"><input type="checkbox" id="uAuto"${s.update_check ? ' checked' : ''}><span>每天自動檢查一次有沒有新版（只連 GitHub、不送會議內容）</span></label>
      <div class="chips"><button class="btn" id="uChk" type="button">檢查更新</button><span id="uMsg" class="note">目前 ${esc(b.version)}</span></div></section>
    <section><h2>資料在哪</h2><p class="note" style="margin:0">會議都在 <span class="mono">${esc(b.out_root)}</span>（可直接當 Obsidian vault 開）。錄音、逐字稿、摘要只在這台電腦。</p>
      <div><button class="btn" id="sFolder" type="button">打開資料夾</button></div></section></div>`;
  if (S.settingsFocus === 'mcp') $('#mcpSec').scrollIntoView();
  const save = async (vals) => { const r = await api('save_settings', vals); if (r.ok === false) { toast(r.error); return false; } S.boot.settings = r.settings; renderStatus(); renderSide(); toast('已儲存'); return true; };
  $$('#view [data-eng]').forEach((btn) => btn.onclick = async () => {
    if (btn.dataset.eng === 'api') {
      if (!s.has_api_key) { $('details').open = true; return toast('先填線上 API 設定'); }
      const warn = await api('api_warning', s.stt_api_base_url);
      return confirmDialog('改用線上語音辨識？', esc(warn) + '<br><br>之後的會議都用線上辨識，隨時可以改回本機。', '改用線上', async () => { await save({ stt_engine: 'api' }); renderSettings(); });
    }
    await save({ stt_engine: 'local' }); renderSettings();
  });
  $('#sBg').onchange = (e) => save({ local_speed: e.target.checked ? 'background' : 'fast' });
  $$('#view [data-pre]').forEach((x) => x.onclick = () => { const [u, m] = x.dataset.pre.split('|'); $('#aUrl').value = u; $('#aModel').value = m; });
  $('#aSave').onclick = async () => {
    const url = $('#aUrl').value, model = $('#aModel').value, key = $('#aKey').value;
    const warn = await api('api_warning', url);
    confirmDialog('改用線上語音辨識？', esc(warn) + '<br><br>儲存後，之後的會議都用線上辨識。', '儲存並改用', async () => {
      const r = await api('save_api', url, model, key); $('#aKey').value = '';
      if (r.ok === false) return toast(r.error); S.boot.settings = r.settings; renderStatus(); renderSettings(); toast('已改用線上語音辨識');
    });
  };
  $('#sAuto').onchange = (e) => save({ auto_summary: e.target.checked });
  $('#sCatsSave').onclick = async () => { const cats2 = $('#sCats').value.split(/[,，、]/).map((x) => x.trim()).filter(Boolean); if (await save({ categories: cats2 })) { await refreshTree(); renderSettings(); } };
  $('#mSave').onclick = () => {
    const scope = {}; $$('#view [data-scope]').forEach((i) => { const v = i.value.split(/[,，、]/).map((x) => x.trim()).filter(Boolean); if (v.length) scope[i.dataset.scope] = v; });
    save({ mcp_enabled: $('#mOn').checked, mcp_transcripts: $('#mTr').checked, mcp_scope: scope });
  };
  $('#mCopy1').onclick = async () => { await api('copy_text', mi.config_json); toast('已複製'); };
  $('#mCopy2').onclick = async () => { await api('copy_text', mi.claude_code); toast('已複製'); };
  if ($('#sDl')) $('#sDl').onclick = () => confirmDialog('下載語音辨識模型', '從 Hugging Face 官方下載約 1.6 GB 的 Whisper 模型與小型 VAD 模型，下載後比對 SHA256。下載不會上傳任何會議內容。', '下載',
    async () => { const r = await api('download_models'); if (r.ok === false) toast(r.error); else { S.busy = 'models'; renderStatus(); showLog(); } });
  $('#uAuto').onchange = (e) => save({ update_check: e.target.checked });
  $('#uChk').onclick = async () => {
    $('#uMsg').textContent = '檢查中…'; const r = await api('check_update');
    if (r.ok === false) { $('#uMsg').textContent = '檢查失敗：' + r.error; return; }
    if (!r.newer) { $('#uMsg').textContent = `已經是最新版（${r.version}）`; return; }
    $('#uMsg').innerHTML = `有新版 ${esc(r.version)} <button class="btn primary" id="uGo" type="button">更新到 ${esc(r.version)}</button>`;
    $('#uGo').onclick = () => confirmDialog(`更新到 ${esc(r.version)}？`, '會從 GitHub 下載新版（約 55 MB）、比對官方 SHA-256，再關閉 App、換成新版並自動重開。會議資料、設定、模型都不會動。', '更新',
      async () => { const x = await api('do_update'); if (x.ok === false) toast(x.error, 5000); else { S.busy = 'update'; renderStatus(); showLog(); } });
  };
  $('#sFolder').onclick = () => api('reveal', '', '');
}

// ------------------------------------------------------------------ 對話框
function dialog(html, cls = '') {
  const o = $('#overlay'); o.innerHTML = `<div class="dialog ${cls}" role="dialog" aria-modal="true">${html}</div>`; o.hidden = false;
  o.onclick = (e) => { if (e.target === o || e.target.closest('[data-close]')) closeDialog(); };
  return $('.dialog', o);
}
function closeDialog() { const o = $('#overlay'); o.hidden = true; o.innerHTML = ''; }
function confirmDialog(title, bodyHtml, okText, onOk) {
  const d = dialog(`<div class="dh">${esc(title)}</div><div class="db">${bodyHtml}</div><div class="df"><button class="btn" data-close type="button">取消</button><button class="btn primary" id="dOk" type="button">${esc(okText)}</button></div>`, 'small');
  $('#dOk', d).onclick = () => { closeDialog(); onOk(); };
}
function labelDialog(ids) {
  if (!ids.length) return;
  const t = S.tree, cats = t.categories;
  const items = (S.listItems || []).filter((m) => ids.includes(m.id));
  const one = S.meeting && ids.length === 1 && S.meeting.id === ids[0] ? S.meeting : null;
  const cur = (c) => { const vals = new Set((one ? [one] : items).map((m) => (m.labels || {})[c] || '')); return vals.size === 1 ? [...vals][0] : null; };
  const privs = new Set((one ? [one] : items).map((m) => !!m.private));
  const d = dialog(`<div class="dh">設定分類（${ids.length} 場）</div><div class="db">
    <p class="note" style="margin-top:0">可直接打新的值，或從清單選既有的；清空＝移除這個分類。${ids.length > 1 ? '「不改」＝這幾場各自維持原本的值。' : ''}</p>
    <div class="form">${cats.map((c) => { const v = cur(c); return `<label>${esc(c)}</label><div><input type="text" list="ld-${esc(c)}" data-lc="${esc(c)}" value="${esc(v ?? '')}" placeholder="${v === null ? '（不改）' : ''}" data-keep="${v === null ? 1 : 0}">
      <datalist id="ld-${esc(c)}">${Object.keys(t.values[c] || {}).map((x) => `<option value="${esc(x)}">`).join('')}</datalist></div>`; }).join('')}</div>
    <label class="check" style="margin-top:12px"><input type="checkbox" id="lPriv"${privs.size === 1 && privs.has(true) ? ' checked' : ''}><span>不給 AI 助理讀（MCP 連線的助理看不到、搜不到；App 裡照常可看）${privs.size > 1 ? '<br><span class="note">這幾場目前不一致；不動這格就維持原狀</span>' : ''}</span></label></div>
    <div class="df"><button class="btn" data-close type="button">取消</button><button class="btn primary" id="lOk" type="button">儲存</button></div>`, 'small');
  let privTouched = false; $('#lPriv', d).onchange = () => { privTouched = true; };
  $$('[data-lc]', d).forEach((i) => i.oninput = () => { i.dataset.keep = 0; });
  $('#lOk', d).onclick = async () => {
    const labels = {}; $$('[data-lc]', d).forEach((i) => { if (i.dataset.keep !== '1') labels[i.dataset.lc] = i.value.trim(); });
    const priv = privTouched || privs.size === 1 ? $('#lPriv', d).checked : null;
    const r = await api('set_labels', ids, labels, priv);
    closeDialog(); if (r.ok === false) return toast(r.error);
    toast('已更新分類；會議索引與專案追蹤已同步'); S.sel.clear(); await refreshTree();
    if (S.view === 'meeting') openMeeting(S.mid, S.tab); else render();
  };
}
function exportDialog(ids, title) {
  if (!ids.length) return toast('沒有可匯出的會議');
  const d = dialog(`<div class="dh">匯出 ${ids.length} 場</div><div class="db">
    <div class="radios"><label class="radio on"><input type="radio" name="ef" value="html" checked>HTML（單一檔案，可直接寄）</label><label class="radio"><input type="radio" name="ef" value="md">Markdown</label></div>
    <label class="check" style="margin-top:12px"><input type="checkbox" id="eTr"${ids.length === 1 ? ' checked' : ''}><span>附上逐字稿（很長；只要摘要就不勾）</span></label>
    ${ids.length > 1 ? `<div class="form" style="margin-top:10px"><label>標題</label><input type="text" id="eTitle" value="${esc(title)}"></div>` : ''}</div>
    <div class="df"><button class="btn" data-close type="button">取消</button><button class="btn primary" id="eOk" type="button">選存檔位置…</button></div>`, 'small');
  $$('input[name=ef]', d).forEach((r) => r.onchange = () => $$('.radio', d).forEach((x) => x.classList.toggle('on', $('input', x).checked)));
  $('#eOk', d).onclick = async () => {
    const fmt = $('input[name=ef]:checked', d).value, tr = $('#eTr', d).checked, ti = $('#eTitle', d) ? $('#eTitle', d).value : title;
    closeDialog();
    const r = await api('export', ids, fmt, tr, ti);
    if (r.ok) toast('已匯出：' + r.path.replace(/^.*\//, '')); else if (!r.cancelled) toast(r.error);
  };
}

// ------------------------------------------------------------------ ⌘K 搜尋
function openSearch() {
  const t = S.tree, top = t.top;
  const st = { q: '', tr: true, top: S.list.labels[top] ?? null, idx: 0, res: [] };
  const d = dialog(`<div class="sq">${ICON.search}<input type="text" id="sq" placeholder="搜尋會議（摘要＋逐字稿；空白分隔＝都要出現）" aria-label="關鍵字"><button class="btn" data-close type="button">esc</button></div>
    <div class="schips" id="schips"></div><div class="sres" id="sres"><div class="muted small" style="padding:10px 18px">輸入關鍵字。</div></div>
    <div class="sfoot"><span>↑↓ 選擇</span><span>↵ 打開</span><span style="margin-left:auto">只在這台 Mac 上搜，不連網</span></div>`);
  const chips = () => {
    $('#schips', d).innerHTML = [`<button class="schip${st.tr ? ' on' : ''}" data-c="tr" type="button" aria-pressed="${st.tr}">含逐字稿</button>`,
      `<button class="schip${st.top === null ? ' on' : ''}" data-c="all" type="button">${esc(top)}：全部</button>`,
      ...t.groups.slice(0, 8).map((g) => `<button class="schip${st.top === g.value ? ' on' : ''}" data-c="g" data-v="${esc(g.value)}" type="button">${esc(g.value)}</button>`)].join('');
    $$('#schips button', d).forEach((b) => b.onclick = () => {
      if (b.dataset.c === 'tr') st.tr = !st.tr; else if (b.dataset.c === 'all') st.top = null; else st.top = b.dataset.v;
      chips(); run();
    });
  };
  let timer = null;
  const run = async () => {
    if (!st.q) { $('#sres', d).innerHTML = '<div class="muted small" style="padding:10px 18px">輸入關鍵字。</div>'; return; }
    const r = await api('list_meetings', { query: st.q, transcript: st.tr, labels: st.top === null ? {} : { [top]: st.top }, limit: 30 });
    st.res = r.meetings; st.idx = 0; paint(r.total);
  };
  const paint = (total) => {
    $('#sres', d).innerHTML = `<div class="muted small" style="padding:4px 18px">${total} 場符合</div>` + st.res.map((m, i) => `<button class="r${i === st.idx ? ' on' : ''}" data-i="${i}" type="button">
      <span class="t1">${esc(m.title)}</span><span class="t2">${shortDate(m.date)}${labelsText(m.labels) ? ' · ' + esc(labelsText(m.labels)) : ''}</span>
      ${m.hits.slice(0, 2).map((x) => `<div class="h1"><span class="mono small" style="color:var(--mint);margin-right:8px">${x.timestamp || x.source}</span>${highlight(x.text)}</div>`).join('')}</button>`).join('');
    $$('#sres .r', d).forEach((b) => b.onclick = () => pick(Number(b.dataset.i)));
  };
  const pick = (i) => { const m = st.res[i]; if (!m) return; closeDialog(); const hit = m.hits.find((x) => x.source === '逐字稿'); openMeeting(m.id, hit && !m.hits.some((x) => x.source === '摘要') ? 'transcript' : 'summary'); };
  const q = $('#sq', d); q.focus();
  q.oninput = () => { st.q = q.value.trim(); clearTimeout(timer); timer = setTimeout(run, 180); };
  q.onkeydown = (e) => {
    if (e.key === 'ArrowDown') { st.idx = Math.min(st.res.length - 1, st.idx + 1); paint(st.res.length); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { st.idx = Math.max(0, st.idx - 1); paint(st.res.length); e.preventDefault(); }
    else if (e.key === 'Enter' && !e.isComposing) { if (st.res.length) pick(st.idx); else { S.list.query = st.q; closeDialog(); go('list'); } }
  };
  chips();
}
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openSearch(); }
  else if (e.key === 'Escape' && !$('#overlay').hidden) closeDialog();
});

// ------------------------------------------------------------------ 輪詢（錄音音量、背景工作進度）
let polling = false;
async function pollTick() {
  if (polling || !window.pywebview) return;
  polling = true;
  try {
    const p = await api('poll', S.cursor);
    S.cursor = p.cursor;
    if (p.log.length) {
      S.log.push(...p.log); if (S.log.length > 3000) S.log.splice(0, 1000);
      for (const id of ['#mlog', '#rlog', '#dlog']) { const el = $(id); if (el) { el.textContent = S.log.slice(id === '#dlog' ? -400 : -80).join('\n'); el.scrollTop = el.scrollHeight; } }
    }
    const wasBusy = S.busy;
    S.busy = p.busy; S.busyJob = p.busy_job;
    if (wasBusy !== S.busy) renderStatus();
    if (p.rec) {
      const first = !S.recLive; S.recLive = p.rec;
      const sc = $('#sideclock'); if (sc) sc.textContent = fmtClock(p.rec.elapsed); else if (first) renderSide();
      if (S.view === 'record') { const c = $('#rClock'); if (c) c.textContent = fmtClock(p.rec.elapsed); const n = $('#nowT'); if (n) n.textContent = fmtClock(p.rec.elapsed);
        const db = $('#rDb'); if (db) db.textContent = Math.round(p.rec.db) + ' dB'; drawWave(); }
    }
    if (p.done) await onDone(p.done);
  } catch (err) { /* 視窗關閉中 */ } finally { polling = false; }
}
async function onDone(d) {
  renderStatus();
  if (d.step === 'pipeline' || d.step === 'summary') {
    await refreshTree();
    const id = d.new_id || d.job;
    if (d.ok) toast(d.summary_failed ? '逐字稿完成；摘要沒做成，可稍後再按「產生摘要」' : (d.step === 'summary' ? '摘要完成' : '轉錄完成'), 4000);
    else if (d.stt_failed) toast('線上語音辨識失敗（整段幻覺）。錄音沒丟，可以在這場按「用本機重轉」', 8000);
    else toast(`沒有完成（看工作紀錄）${d.error ? '：' + d.error : ''}`, 6000);
    if (S.rec.job === d.job) S.rec.job = id;
    if (d.stt_failed) { S.meeting = null; return openMeeting(id, 'summary'); }
    if ((S.view === 'meeting' && S.mid === d.job) || (S.view === 'record' && S.rec.phase === 'done')) { if (d.ok) openMeeting(id); else render(); }
  } else if (d.step === 'project') {
    toast(d.ok ? '進度整理完成' : '整理失敗：' + (d.error || ''), 4000);
    if (S.view === 'project') renderProject();
  } else if (d.step === 'models') {
    S.boot = await api('bootstrap'); toast(d.ok ? '語音辨識模型已就緒' : '下載失敗：' + (d.error || ''), 5000); if (S.view === 'settings') renderSettings();
  } else if (d.step === 'update' && !d.ok) toast('更新沒有完成，舊版沒動：' + (d.error || ''), 6000);
}
