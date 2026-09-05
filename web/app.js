'use strict';
const $  = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = t => String(t).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const gb = n => (n || 0).toFixed(n >= 10 ? 0 : 1) + ' GB';

let MODELS = [], STATUS = {}, F = { q: '', task: null, status: null };

const TASK_LABEL = { chat:'Trò chuyện', code:'Lập trình', vision:'Thị giác',
                     asr:'Giọng nói → chữ', tts:'Chữ → giọng nói', image:'Sinh ảnh' };
const BADGE = { present:['b-present','● có sẵn'], missing:['b-missing','○ chưa tải'],
                cloud:['b-cloud','☁ cloud'], partial:['b-missing','◐ thiếu file'],
                unsupported:['b-missing','⊘ khác nền tảng'] };

function toast(msg, ms = 2600) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => t.hidden = true, ms);
}
async function api(p, opt) {
  const r = await fetch(p, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.error) {
    const err = new Error(j.error || r.statusText);
    err.fatal = !!j.fatal;
    throw err;
  }
  return j;
}
function copy(text, what) {
  navigator.clipboard.writeText(text).then(
    () => toast('Đã sao chép ' + what),
    () => toast('Không sao chép được'));
}

/* ── thanh trạng thái ── */
function renderStatus() {
  const s = STATUS;
  $('#stats').innerHTML = `
    <span>kho <b>${gb(s.store_gb)}</b></span>
    <span>đĩa trống <b>${gb(s.free_gb)}</b></span>
    <span>RAM <b>${gb(s.ram_gb)}</b> · rảnh <b>${gb(s.ram_free_gb)}</b></span>
    <span><i class="dot ${s.ollama_up ? 'on' : 'off'}"></i>Ollama ${s.ollama_up ? 'đang chạy' : 'tắt'}</span>
    ${s.loaded?.length ? `<span>đang nạp <b>${s.loaded.map(m => `${m.name} (${gb(m.gb)})`).join(', ')}</b></span>` : ''}
    <span title="Dữ liệu đo lại từ đĩa mỗi 15 giây">cập nhật <b>${
      new Date().toLocaleTimeString('vi-VN', {hour:'2-digit', minute:'2-digit', second:'2-digit'})}</b></span>`;
  if ($('#storePath')) $('#storePath').textContent = s.store || '';
}

/* ── thẻ model ── */
function card(m) {
  const [cls, label] = BADGE[m.status] || BADGE.missing;
  // Cảnh báo RAM: model cần nhiều hơn RAM đang rảnh → sẽ tràn sang swap/CPU.
  const tight = m.ram_gb > 0 && STATUS.ram_free_gb && m.ram_gb > STATUS.ram_free_gb;
  const el = document.createElement('article');
  el.className = 'card' + (tight && m.status === 'present' ? ' warnram' : '')
               + (m.status === 'missing' || m.status === 'unsupported' ? ' dim' : '');
  el.innerHTML = `
    <div class="chead">
      <div class="ctitle">${m.recommended ? '<span class="star">★</span> ' : ''}${m.title}</div>
      <span class="badge ${cls}">${label}</span>
    </div>
    ${m.undeclared ? `<div class="tags"><span class="tag new">chưa khai báo — có trên đĩa nhưng chưa mô tả</span></div>` : ''}
    ${m.tags?.length ? `<div class="tags">${m.tags.map(t =>
        `<span class="tag${/dọn|cũ/.test(t) ? ' gc' : ''}">${esc(t)}</span>`).join('')}</div>` : ''}
    ${m.desc ? `<p class="desc">${m.desc}</p>` : ''}
    ${m.strengths?.length ? `<p class="desc"><b>Làm tốt:</b> ${m.strengths.join(' · ')}</p>` : ''}
    <div class="meta">
      <span>${TASK_LABEL[m.task] || m.task}</span>
      <span>${m.runtime}${m.quant ? ' · ' + m.quant : ''}</span>
      <span>đĩa <b>${gb(m.disk_gb ?? m.size_gb)}</b>${
        m.disk_gb == null && m.status === 'present' ? '' :
        m.disk_gb == null ? ' <i class="est">(ước tính)</i>' : ''}</span>
      <span>RAM <b>${gb(m.ram_gb)}</b></span>
    </div>
    ${tight && m.status === 'present'
      ? `<div class="ramwarn">⚠ Cần ${gb(m.ram_gb)} nhưng RAM chỉ còn rảnh ${gb(STATUS.ram_free_gb)} — sẽ chậm hoặc tràn sang CPU.</div>` : ''}
    ${m.owners?.length ? `<div class="owners">Dùng bởi: ${m.owners.join(', ')}</div>`
                       : `<div class="owners">Chưa dự án nào dùng</div>`}
    <div class="actions"></div>`;

  const act = el.querySelector('.actions');
  const btn = (txt, cls2, fn) => {
    const b = document.createElement('button');
    b.className = 'btn sm ' + cls2; b.textContent = txt;
    b.onclick = fn; act.appendChild(b); return b;
  };

  if (m.undeclared) {
    btn('Thêm vào thư viện', '', async () => {
      try { await api('/api/adopt', { method: 'POST' });
            toast('Đã thêm vào registry'); refresh(); }
      catch (e) { toast('Lỗi: ' + e.message, 4200); }
    });
  }
  if (m.status === 'present') {
    if (m.path) btn('Sao chép đường dẫn', 'ghost', () => copy(m.path, 'đường dẫn'));
    if (m.access?.includes('endpoint'))
      btn('Sao chép endpoint', 'ghost', () => copy(
        `http://127.0.0.1:11434/v1  |  model="${m.ref}"`, 'endpoint'));
    btn('Sao chép mã Python', 'ghost', () => copy(
      m.access?.includes('endpoint')
        ? `import aihub\nurl, model = aihub.endpoint("${m.name}")`
        : `import aihub\np = aihub.path("${m.name}")`, 'mã Python'));
    if (m.archive_candidate)
      btn('Xoá — thu hồi ' + gb(m.disk_gb ?? m.size_gb), 'danger', async () => {
        if (!confirm(`Xoá "${m.title}"?\n\n${m.desc}\n\nThu hồi ${gb(m.size_gb)}. Không hoàn tác được.`)) return;
        if (!confirm('Xác nhận lần cuối: xoá vĩnh viễn?')) return;
        try { await api('/api/models/' + m.name, { method: 'DELETE' });
              toast('Đã xoá ' + m.title); refresh(); }
        catch (e) { toast('Lỗi: ' + e.message, 4200); }
      });
  } else if (m.status === 'missing') {
    btn('Tải về', '', () => { showView('add'); $('#src').value = m.name; preview(); });
  }
  // status 'unsupported': không có nút tải — runtime của nó không chạy trên máy này.
  return el;
}

function renderGrid() {
  const q = F.q.toLowerCase();
  const rows = MODELS.filter(m => {
    if (F.task && m.task !== F.task) return false;
    if (F.status === 'archive' ? !m.archive_candidate
        : F.status && m.status !== F.status) return false;
    if (!q) return true;
    return (m.name + ' ' + m.title + ' ' + (m.desc || '') + ' ' +
            (m.tags || []).join(' ') + ' ' + (m.strengths || []).join(' ') + ' ' +
            m.runtime + ' ' + (m.owners || []).join(' ')).toLowerCase().includes(q);
  });
  const g = $('#grid'); g.innerHTML = '';
  rows.forEach(m => g.appendChild(card(m)));
  $('#empty').hidden = rows.length > 0;
}

function renderTaskChips() {
  const tasks = [...new Set(MODELS.map(m => m.task))];
  $('#taskChips').innerHTML = tasks.map(t =>
    `<button class="chip" data-task="${t}">${TASK_LABEL[t] || t}</button>`).join('');
  $$('#taskChips .chip').forEach(c => c.onclick = () => {
    const on = c.classList.contains('on');
    $$('#taskChips .chip').forEach(x => x.classList.remove('on'));
    if (!on) c.classList.add('on');
    F.task = on ? null : c.dataset.task;
    renderGrid();
  });
}

/* ── tải model ── */
async function preview() {
  const src = $('#src').value.trim();
  if (!src) return toast('Nhập nguồn trước');
  const inc = $('#inc').value.trim().split(/\s+/).filter(Boolean);
  const box = $('#preview'); box.hidden = false;
  box.innerHTML = '<div class="phead"><span>đang hỏi nguồn…</span></div>';
  const qs = new URLSearchParams({ source: src });
  inc.forEach(p => qs.append('include', p));
  try {
    const p = await api('/api/preview?' + qs);
    const files = (p.files || []).sort((a, b) => b.size - a.size);
    box.innerHTML = `
      <div class="phead">
        <span><b>${p.repo || src}</b> — ${p.count ?? files.length} file, <b>${gb(p.total_gb)}</b></span>
        <button class="btn sm" id="btnGo">Tải về kho</button>
      </div>
      ${p.note ? `<ul><li>${p.note}</li></ul>` : ''}
      <ul>${files.slice(0, 40).map(f =>
        `<li><span>${f.name}</span><span>${(f.size / 1e6).toFixed(1)} MB</span></li>`).join('')}
        ${files.length > 40 ? `<li><span>… còn ${files.length - 40} file</span><span></span></li>` : ''}</ul>`;
    $('#btnGo').onclick = () => doPull(src, inc);
  } catch (e) {
    // Lỗi fatal = nguồn sai bản chất; mời "vẫn tải" chỉ gây hiểu nhầm.
    box.innerHTML = `<div class="perr">${esc(e.message)}</div>` + (e.fatal ? '' :
      `<div class="phead"><span></span><button class="btn sm" id="btnGo">Vẫn tải</button></div>`);
    if (!e.fatal) $('#btnGo').onclick = () => doPull(src, inc);
    if (e.fatal && /aihub search (\S+)/.test(e.message)) {
      const kw = e.message.match(/aihub search (\S+)/)[1];
      const b = document.createElement('button');
      b.className = 'btn'; b.style.margin = '12px 14px';
      b.textContent = `Tìm "${kw}" trên HuggingFace`;
      b.onclick = () => { $('#src').value = kw; box.hidden = true; doSearch(); };
      box.appendChild(b);
    }
  }
}

function doPull(src, inc) {
  $('#progress').hidden = false;
  const log = $('#log'), fill = $('#barFill');
  log.textContent = ''; fill.style.width = '0%';
  const qs = new URLSearchParams({ source: src });
  (inc || []).forEach(p => qs.append('include', p));
  const es = new EventSource('/api/pull?' + qs);
  es.onmessage = ev => {
    const d = JSON.parse(ev.data);
    if (d.pct != null) fill.style.width = d.pct + '%';
    if (d.status) log.textContent += d.status + (d.pct != null ? `  ${d.pct}%` : '') + '\n';
    if (d.error) { log.textContent += 'LỖI: ' + d.error + '\n'; toast('Tải thất bại', 4200); }
    log.scrollTop = log.scrollHeight;
    if (d.done) { es.close(); fill.style.width = '100%';
                  if (!d.error) toast('Tải xong'); refresh(); }
  };
  es.onerror = () => { es.close(); log.textContent += '(mất kết nối)\n'; };
}

/* ── sức khoẻ ── */
async function loadDoctor() {
  const box = $('#doctor');
  box.innerHTML = '<span class="skel">đang kiểm tra…</span>';
  try {
    const d = await api('/api/doctor');
    const mark = { PASS: '✓', WARN: '!', FAIL: '✗' };
    box.innerHTML = d.rows.map(r =>
      `<div class="drow ${r.level}"><span class="m">${mark[r.level]}</span>
       <span class="n">${r.name}</span><span class="d">${r.detail}</span></div>`).join('');
  } catch (e) { box.innerHTML = `<div class="drow FAIL"><span class="m">✗</span>
      <span class="d">${e.message}</span></div>`; }
}

/* ── điều hướng ── */
function showView(v) {
  $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === v));
  $$('.view').forEach(m => m.hidden = m.id !== 'view-' + v);
  if (v === 'health') loadDoctor();
}

async function refresh() {
  [STATUS, MODELS] = await Promise.all([api('/api/status'), api('/api/models')]);
  renderStatus(); renderGrid();
}

/* ── khởi động ── */
$$('.tab').forEach(t => t.onclick = () => showView(t.dataset.view));
$('#q').oninput = e => { F.q = e.target.value; renderGrid(); };
$$('#statusChips .chip').forEach(c => c.onclick = () => {
  const on = c.classList.contains('on');
  $$('#statusChips .chip').forEach(x => x.classList.remove('on'));
  if (!on) c.classList.add('on');
  F.status = on ? null : c.dataset.status;
  renderGrid();
});
async function doSearch() {
  const q = $('#src').value.trim();
  if (!q) return toast('Nhập tên model trước');
  const box = $('#results'); box.hidden = false;
  box.innerHTML = '<div class="rhead">đang tìm trên HuggingFace…</div>';
  try {
    const rows = await api('/api/search?q=' + encodeURIComponent(q));
    if (!rows.length) { box.innerHTML = `<div class="rhead">Không thấy gì cho "${q}".</div>`; return; }
    box.innerHTML = `<div class="rhead">${rows.length} kết quả — <b>★</b> hợp với máy này ·
        <b>◆</b> GGUF dùng được với Ollama. Bấm một dòng để xem trước.</div>` +
      rows.map(r => `<button class="rrow" data-spec="${r.spec}">
          <span class="rmark">${r.preferred ? '★' : (r.gguf || r.mlx) ? '◆' : ''}</span>
          <span class="rid">${r.id}</span>
          <span class="rsz">${r.gb ? r.gb.toFixed(2) + ' GB' : '?'}</span>
          <span class="rdl">⬇${r.downloads.toLocaleString('vi-VN')}</span>
        </button>`).join('');
    box.querySelectorAll('.rrow').forEach(b => b.onclick = () => {
      $('#src').value = b.dataset.spec; box.hidden = true; preview();
    });
  } catch (e) { box.innerHTML = `<div class="rhead" style="color:var(--err)">Lỗi: ${e.message}</div>`; }
}
$('#btnSearch').onclick = doSearch;
$('#btnPreview').onclick = preview;
$('#src').addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const v = $('#src').value.trim();
  // Có dấu "/" hoặc tiền tố nguồn → là một spec cụ thể; ngược lại coi là từ khoá tìm.
  (v.includes('/') || /^(ollama|hf|gguf|gh|url|git):/.test(v)) ? preview() : doSearch();
});
$('#btnDoctor').onclick = loadDoctor;
$('#btnServe').onclick = async () => {
  try { await api('/api/serve', { method: 'POST' }); toast('Đang bật Ollama…');
        setTimeout(() => { refresh(); loadDoctor(); }, 2500); }
  catch (e) { toast('Lỗi: ' + e.message, 4200); } };
$('#btnStop').onclick = async () => {
  try { await api('/api/stop', { method: 'POST' }); toast('Đã tắt Ollama');
        setTimeout(() => { refresh(); loadDoctor(); }, 1200); }
  catch (e) { toast('Lỗi: ' + e.message, 4200); } };

refresh().then(renderTaskChips).catch(e => toast('Không tải được dữ liệu: ' + e.message, 5000));
// Làm mới toàn bộ (status + model) mỗi 15 s — /api/models đo lại đĩa mỗi lần gọi
// và chỉ mất ~50 ms, nên trang luôn khớp thực tế hệ thống mà không cần F5.
// Tạm dừng khi tab bị ẩn để không tốn tài nguyên vô ích.
// /api/models đo lại đĩa mỗi lần gọi và chỉ mất ~50 ms, nên cứ làm mới vô điều kiện:
// trình duyệt đã tự giảm nhịp timer ở tab nền, không cần tự chặn thêm.
setInterval(() => refresh().catch(() => {}), 15000);
// Quay lại tab thì cập nhật ngay, không đợi hết chu kỳ.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') refresh().catch(() => {});
});
