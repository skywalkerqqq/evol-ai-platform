/* EVOL-AI 前端 · 所有计算走后端 API */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const clamp = (v, a = 0, b = 100) => Math.max(a, Math.min(b, v));
const fmt = (v, d = 1) => Number(v).toFixed(d);

const TITLES = {
  dash: '管线总览', target: '靶点与机制', seq: '载体序列工作台',
  struct: '结构与结合预测', loop: '预测-实验闭环', models: '模型评估矩阵', data: '数据资产目录'
};

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' }, ...opts
  });
  let data;
  try { data = await res.json(); } catch { throw new Error('服务返回非 JSON'); }
  if (!res.ok || data.ok === false) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
}

const state = { analysis: null, optimization: null, records: [], metrics: null, weights: null, protein: null, card: null, inferTasks: [] };

/* ---------------- 导航 ---------------- */
$('#nav').addEventListener('click', e => {
  const item = e.target.closest('.nav-item');
  if (!item) return;
  $$('.nav-item').forEach(n => n.classList.toggle('active', n === item));
  const v = item.dataset.view;
  $$('.section').forEach(s => s.classList.toggle('active', s.id === 'view-' + v));
  $('#crumb').textContent = TITLES[v];
  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (v === 'seq') requestAnimationFrame(() => { drawGC(); drawRadar(state.analysis); });
  if (v === 'loop') requestAnimationFrame(drawScatter);
  if (v === 'struct') requestAnimationFrame(drawHydro);
});

/* ---------------- 画布工具 ---------------- */
function fit(cv, h) {
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 600;
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  cv.style.height = h + 'px';
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

function drawGC() {
  const cv = $('#gcCanvas');
  const { ctx, w, h } = fit(cv, 150);
  const a = state.analysis;
  if (!a || !a.gc_windows || !a.gc_windows.length) {
    ctx.fillStyle = '#93a0a3'; ctx.font = '12px system-ui'; ctx.fillText('等待分析…', 12, 70);
    return;
  }
  const padL = 34, padR = 8, padT = 10, padB = 18;
  const iw = w - padL - padR, ih = h - padT - padB;
  ctx.strokeStyle = '#eef1f1';
  [0, 25, 50, 75, 100].forEach(v => {
    const y = padT + ih - v / 100 * ih;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    ctx.fillStyle = '#93a0a3'; ctx.font = '10px ui-monospace,monospace'; ctx.textAlign = 'right';
    ctx.fillText(v, padL - 6, y + 3);
  });
  ctx.strokeStyle = '#c9d2d2'; ctx.setLineDash([3, 3]);
  ctx.beginPath(); ctx.moveTo(padL, padT + ih / 2); ctx.lineTo(w - padR, padT + ih / 2); ctx.stroke();
  ctx.setLineDash([]);

  const pts = a.gc_windows.map(p => [padL + p.x * iw, padT + ih - clamp(p.v) / 100 * ih]);
  const grd = ctx.createLinearGradient(0, padT, 0, padT + ih);
  grd.addColorStop(0, 'rgba(13,138,122,.22)'); grd.addColorStop(1, 'rgba(13,138,122,0)');
  ctx.beginPath();
  pts.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
  ctx.strokeStyle = '#0d8a7a'; ctx.lineWidth = 1.6; ctx.stroke();
  ctx.lineTo(padL + iw, padT + ih); ctx.lineTo(padL, padT + ih); ctx.closePath();
  ctx.fillStyle = grd; ctx.fill();

  ctx.fillStyle = '#93a0a3'; ctx.font = '10px system-ui'; ctx.textAlign = 'left';
  ctx.fillText('0 bp', padL, h - 4);
  ctx.textAlign = 'right'; ctx.fillText(a.length + ' bp', w - padR, h - 4);
}

const RADAR_KEYS = ['表达强度', '基因组稳定性', '免疫安全', '制造可行性', '肿瘤选择性'];
const RADAR_SHORT = ['表达强度', '基因组稳定', '免疫安全', '制造可行', '肿瘤选择性'];

function drawRadar(a) {
  const cv = $('#radar');
  const dpr = window.devicePixelRatio || 1;
  const W = 300, H = 270;
  cv.width = W * dpr; cv.height = H * dpr;
  cv.style.width = W + 'px'; cv.style.height = H + 'px';
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const cx = W / 2, cy = H / 2 + 4, R = 88, N = 5;
  const ang = i => -Math.PI / 2 + i * 2 * Math.PI / N;
  const pt = (i, r) => [cx + Math.cos(ang(i)) * r, cy + Math.sin(ang(i)) * r];

  for (let g = 1; g <= 4; g++) {
    ctx.beginPath();
    for (let i = 0; i < N; i++) { const [x, y] = pt(i, R * g / 4); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
    ctx.closePath(); ctx.strokeStyle = '#edf1f1'; ctx.lineWidth = 1; ctx.stroke();
  }
  for (let i = 0; i < N; i++) {
    const [x, y] = pt(i, R);
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.strokeStyle = '#edf1f1'; ctx.stroke();
  }

  if (a) {
    const vals = RADAR_KEYS.map(k => a.scores[k]);
    ctx.beginPath();
    vals.forEach((v, i) => { const [x, y] = pt(i, R * clamp(v) / 100); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.closePath(); ctx.fillStyle = 'rgba(13,138,122,.16)'; ctx.fill();
    ctx.strokeStyle = '#0d8a7a'; ctx.lineWidth = 1.8; ctx.stroke();
    vals.forEach((v, i) => {
      const [x, y] = pt(i, R * clamp(v) / 100);
      ctx.beginPath(); ctx.arc(x, y, 3.2, 0, 7); ctx.fillStyle = '#0d8a7a'; ctx.fill();
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 1; ctx.stroke();
    });
  }

  ctx.font = '11px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  RADAR_SHORT.forEach((lab, i) => {
    const [x, y] = pt(i, R + 22);
    ctx.fillStyle = '#6c797c'; ctx.fillText(lab, x, y);
    if (a) {
      ctx.fillStyle = '#0a6b5f'; ctx.font = '10.5px ui-monospace,monospace';
      ctx.fillText(Math.round(a.scores[RADAR_KEYS[i]]), x, y + 13);
      ctx.font = '11px system-ui';
    }
  });
  ctx.textBaseline = 'alphabetic';
}

function drawHydro() {
  const cv = $('#hydroCanvas');
  if (!cv) return;
  const { ctx, w, h } = fit(cv, 190);
  const p = state.protein;
  const padL = 36, padR = 10, padT = 12, padB = 22;
  const iw = w - padL - padR, ih = h - padT - padB;
  const lo = -4.6, hi = 4.6;
  const Y = v => padT + ih - (clamp(v, lo, hi) - lo) / (hi - lo) * ih;

  [4, 2, 0, -2, -4].forEach(v => {
    const y = Y(v);
    ctx.strokeStyle = v === 0 ? '#dfe5e5' : '#f2f5f5';
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    ctx.fillStyle = '#93a0a3'; ctx.font = '10px ui-monospace,monospace'; ctx.textAlign = 'right';
    ctx.fillText(v > 0 ? '+' + v : v, padL - 6, y + 3);
  });

  if (!p || !p.profile || !p.profile.length) {
    ctx.fillStyle = '#93a0a3'; ctx.font = '12px system-ui'; ctx.textAlign = 'left';
    ctx.fillText('等待分析…', padL + 8, padT + ih / 2);
    return;
  }
  const n = p.n_aa;
  const X = i => padL + i / Math.max(1, n - 1) * iw;

  // 连续超阈段着色
  ctx.fillStyle = 'rgba(180,57,47,.07)';
  (p.hydrophobic_runs || []).forEach(r => {
    const x1 = X(r.start - 1), x2 = X(r.end - 1);
    ctx.fillRect(x1, padT, Math.max(2, x2 - x1), ih);
  });

  // 阈值线
  ctx.strokeStyle = 'rgba(180,57,47,.45)'; ctx.setLineDash([3, 3]);
  ctx.beginPath(); ctx.moveTo(padL, Y(p.tm_threshold)); ctx.lineTo(w - padR, Y(p.tm_threshold)); ctx.stroke();
  ctx.setLineDash([]);

  // 曲线
  const grd = ctx.createLinearGradient(0, padT, 0, padT + ih);
  grd.addColorStop(0, 'rgba(13,138,122,.22)'); grd.addColorStop(1, 'rgba(13,138,122,0)');
  ctx.beginPath();
  p.profile.forEach((pt, k) => {
    const x = X(pt.i + (p.hydro_window - 1) / 2), y = Y(pt.mean);
    k ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.strokeStyle = '#0d8a7a'; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.lineTo(X(p.profile[p.profile.length - 1].i + (p.hydro_window - 1) / 2), Y(0));
  ctx.lineTo(X(p.profile[0].i + (p.hydro_window - 1) / 2), Y(0));
  ctx.closePath(); ctx.fillStyle = grd; ctx.fill();

  ctx.fillStyle = '#93a0a3'; ctx.font = '10px system-ui'; ctx.textAlign = 'left';
  ctx.fillText('1 aa', padL, h - 6);
  ctx.textAlign = 'right'; ctx.fillText(n + ' aa', w - padR, h - 6);
  ctx.textAlign = 'center'; ctx.fillStyle = '#6c797c';
  ctx.fillText(`阈值 ${p.tm_threshold}（≥15 aa 连续才判跨膜）`, padL + iw / 2, h - 6);
}

function drawScatter() {
  const cv = $('#scatter');
  if (!cv) return;
  const { ctx, w, h } = fit(cv, 260);
  const padL = 44, padR = 16, padT = 14, padB = 30;
  const iw = w - padL - padR, ih = h - padT - padB;
  const lo = 3, hi = 9;
  const X = v => padL + (v - lo) / (hi - lo) * iw;
  const Y = v => padT + ih - (v - lo) / (hi - lo) * ih;
  ctx.strokeStyle = '#f0f3f3';
  for (let v = lo; v <= hi; v++) {
    ctx.beginPath(); ctx.moveTo(padL, Y(v)); ctx.lineTo(w - padR, Y(v)); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(X(v), padT); ctx.lineTo(X(v), padT + ih); ctx.stroke();
    ctx.fillStyle = '#93a0a3'; ctx.font = '10px ui-monospace,monospace';
    ctx.textAlign = 'right'; ctx.fillText(v, padL - 6, Y(v) + 3);
    ctx.textAlign = 'center'; ctx.fillText(v, X(v), h - 10);
  }
  ctx.strokeStyle = '#b9c3c3'; ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(X(lo), Y(lo)); ctx.lineTo(X(hi), Y(hi)); ctx.stroke();
  ctx.setLineDash([]);

  const flagged = new Set((state.metrics && state.metrics.flagged) || []);
  state.records.forEach(r => {
    if ((r.outcome || 'hit') === 'fail') return;   // 无有效实测值，散点图上不该有它
    const bad = flagged.has(r.id);
    const miss = (r.outcome || 'hit') === 'miss';
    ctx.beginPath(); ctx.arc(X(r.pred), Y(r.obs), bad ? 5 : 3.6, 0, 7);
    ctx.fillStyle = bad ? 'rgba(180,57,47,.85)' : miss ? 'rgba(201,138,28,.85)' : 'rgba(13,138,122,.75)';
    ctx.fill();
    if (bad) {
      ctx.fillStyle = '#b4392f'; ctx.font = '10px system-ui'; ctx.textAlign = 'left';
      ctx.fillText(r.id, X(r.pred) + 7, Y(r.obs) - 6);
    }
  });
  ctx.fillStyle = '#6c797c'; ctx.font = '11px system-ui'; ctx.textAlign = 'left';
  ctx.fillText('预测 →', padL + 4, padT + 12);
  ctx.textAlign = 'right';
  ctx.fillStyle = 'rgba(13,138,122,.9)'; ctx.fillText('● 达阈值', w - padR - 52, padT + 12);
  ctx.fillStyle = 'rgba(201,138,28,.9)'; ctx.fillText('● 阴性', w - padR, padT + 12);
  ctx.textAlign = 'left';
  ctx.fillStyle = '#6c797c';
  ctx.save(); ctx.translate(15, padT + ih / 2); ctx.rotate(-Math.PI / 2);
  ctx.textAlign = 'center'; ctx.fillText('实测 ↑', 0, 0); ctx.restore();
}

/* ---------------- 序列分析 ---------------- */
function renderAnalysis(a) {
  $('#seqLenTag').textContent = a.length + ' bp';
  const pill = $('#seqVerdict');
  pill.textContent = a.verdict;
  pill.className = 'pill ' + (a.verdict === '建议下单' ? 't' : a.verdict === '可下单 · 需复核' ? 'a' : 'r');

  const metrics = [
    { k: 'GC 含量', v: fmt(a.gc) + '%', s: `AT skew ${fmt(a.at_skew, 2)} · GC skew ${fmt(a.gc_skew, 2)}` },
    { k: 'CpG 密度', v: fmt(a.cpg_per_100) + '/100bp', s: `O/E ${fmt(a.cpg_ratio, 2)} · 岛 ${a.cpg_islands.length} 个` },
    { k: '同聚物 / 重复', v: `${a.runs.length} / ${a.tandem.length}`, s: a.runs.length ? `最长 ${Math.max(...a.runs.map(x => x.len))} bp` : '无 ≥6 bp 长串' },
    { k: '免疫刺激基序', v: String(a.immuno.length), s: 'TLR9 相关 CpG 基序计数' },
    { k: '酶切位点', v: String(a.sites.length), s: a.sites.length ? a.sites.slice(0, 3).map(s => s.name).join(' · ') : '无常用位点' },
    { k: 'Kozak', v: a.kozak ? '强' : '弱/缺', s: `ATG @ ${a.start_codon || '—'}` },
    { k: '稀有密码子', v: fmt(a.rare_frac * 100) + '%', s: `${a.rare} / ${a.codons} codons` },
    { k: '隐蔽剪接 / polyA', v: `${a.splice} / ${a.poly_a}`, s: '供体位点 / AATAAA' }
  ];
  $('#seqMetrics').innerHTML = metrics.map(m => `
    <div class="card metric" style="box-shadow:none">
      <span class="m-k">${m.k}</span><span class="m-v">${m.v}</span><span class="m-s">${m.s}</span>
    </div>`).join('');

  $('#riskCount').textContent = a.risks.length + ' 条';
  $('#riskCount').className = 'pill ' + (a.risks.some(r => r.lv === 'hi') ? 'r' : a.risks.length ? 'a' : 't');
  $('#risks').innerHTML = a.risks.length ? a.risks.map(r => `
    <div class="risk ${r.lv}"><span class="dot"></span>
      <div style="flex:1">
        <div><b>${r.t}</b><span class="pos">${r.p}</span></div>
        <div class="act">${r.d}</div>
        <div class="act" style="color:var(--teal-ink)">→ ${r.a}</div>
      </div></div>`).join('') : '<div class="hint">未检出风险位点。</div>';

  const lvPill = { hi: 'r', md: 'a', lo: '' };
  const top3 = a.risks.slice(0, 3);
  $('#seqTopRisk').innerHTML = `<div style="font-size:11.5px;color:var(--muted);letter-spacing:.04em">主要风险 · Top 3</div>` +
    (top3.length ? top3.map(r => `<div style="display:flex;align-items:center;gap:8px;font-size:12.5px">
        <span class="pill ${lvPill[r.lv]}">${r.lv === 'hi' ? '高' : r.lv === 'md' ? '中' : '低'}</span>
        <span style="flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${r.t}</span>
        <span class="mono" style="color:var(--muted);font-size:11px">${r.p}</span>
      </div>`).join('') : '<div class="hint">未检出。</div>');
}

async function runAnalysis() {
  const btn = $('#runSeq');
  btn.disabled = true; btn.innerHTML = '<span class="loading"></span> 分析中';
  try {
    const seq = $('#seqInput').value;
    const a = await api('/api/analyze', { method: 'POST', body: JSON.stringify({ sequence: seq }) });
    state.analysis = a;
    renderAnalysis(a); drawGC(); drawRadar(a);
    // 蛋白画像必须跟着同一条构建体走，否则结构页会挂着一份过期数据
    try {
      renderProtein(await api('/api/protein', { method: 'POST', body: JSON.stringify({ sequence: seq }) }));
      drawHydro();
    } catch (e) { console.warn('蛋白画像失败：' + e.message); }
  } catch (e) {
    alert('分析失败：' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = '分析';
  }
}

/* ---------------- 同义优化 ---------------- */
function renderOptimize(o) {
  const b = o.before, af = o.after, c = o.changes;
  const relaxKeys = Object.keys(o.relaxation).filter(k => k !== '全部满足');
  const relaxLine = relaxKeys.length
    ? `<div class="hint" style="color:#8a5a10;background:#fdf7ea;border:1px solid #f2dfb8;border-radius:8px;padding:8px 10px">
        约束有放宽：${relaxKeys.map(k => `${k} ${o.relaxation[k]} 个密码子`).join('，')}。这些位点建议人工复核。</div>`
    : `<div class="hint" style="color:var(--teal-ink)">全部约束满足，无需放宽。</div>`;

  // 尾部不是 3 的倍数：整密码子才参与优化，余下的碱基不复制、不能默认吞掉
  const truncLine = c.truncated_nt
    ? `<div class="hint" style="color:#8a5a10;background:#fdf7ea;border:1px solid #f2dfb8;border-radius:8px;padding:8px 10px;margin-top:8px">
         输入 CDS 长度非 3 的倍数，末尾 <b>${c.truncated_nt} nt</b> 不构成完整密码子，已从输出中剔除
         （CDS ${c.codons * 3 + c.truncated_nt} nt → ${c.codons * 3} nt，ATG 之前的载体骨架原样保留）。如需保留，请补齐至整密码子后重跑。</div>`
    : '';

  const rows = [
    { k: 'GC 含量', from: fmt(b.gc) + '%', to: fmt(af.gc) + '%' },
    { k: 'CpG /100bp', from: fmt(b.cpg_per_100), to: fmt(af.cpg_per_100) },
    { k: '稀有密码子', from: fmt(b.rare_frac * 100) + '%', to: fmt(af.rare_frac * 100) + '%' },
    { k: '风险条目', from: b.risks.length + ' 条', to: af.risks.length + ' 条' },
    { k: '综合分', from: fmt(b.composite), to: fmt(af.composite) }
  ];

  $('#optBody').innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">
      <span class="pill t">优化完成</span>
      <span class="hint">同义替换 ${c.codons_changed} / ${c.codons} 个密码子 · 改动 ${c.nt_changed} nt（${fmt(c.nt_changed_pct)}%）· 序列一致性 ${fmt(c.identity_pct)}%
        · 求解回溯 ${c.backtracks} 次</span>
    </div>
    <div class="grid g2" style="gap:8px">
      ${rows.map(r => `<div class="ba"><span class="ba-k">${r.k}</span>
        <span class="ba-v"><span class="ba-from">${r.from}</span><span style="color:var(--faint)">→</span><span class="ba-to">${r.to}</span></span></div>`).join('')}
    </div>
    <div style="margin-top:10px">${relaxLine}</div>
    ${truncLine}
    <div class="seqbox" style="margin-top:12px">${diffHtml(state.analysis_seq || '', o.sequence)}</div>
    <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
      <button class="btn sm primary" id="downloadFa">下载 FASTA</button>
      <button class="btn sm" id="applyOpt">应用到工作台并重新分析</button>
      <button class="btn sm" id="copyOpt">复制序列</button>
    </div>`;

  $('#downloadFa').onclick = () => {
    const fasta = `>ECD-AI-optimised | synonymous | ${c.identity_pct}% identity\n` +
      (o.sequence.match(/.{1,70}/g) || []).join('\n') + '\n';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([fasta], { type: 'text/plain' }));
    a.download = 'ECD-AI-optimised.fasta'; a.click();
    URL.revokeObjectURL(a.href);
  };
  $('#copyOpt').onclick = async () => {
    await navigator.clipboard.writeText(o.sequence);
    $('#copyOpt').textContent = '已复制';
    setTimeout(() => { $('#copyOpt').textContent = '复制序列'; }, 1400);
  };
  $('#applyOpt').onclick = () => {
    $('#seqInput').value = o.sequence;
    runAnalysis();
  };
}

function diffHtml(oldSeq, newSeq) {
  if (!oldSeq) return newSeq.slice(0, 600);
  let out = '';
  for (let i = 0; i < Math.min(newSeq.length, 700); i++) {
    const ch = newSeq[i];
    out += oldSeq[i] === ch ? `<span class="same">${ch}</span>` : `<span class="chg">${ch}</span>`;
  }
  return out + (newSeq.length > 700 ? '\n…' : '');
}

async function runOptimize() {
  const btn = $('#runOpt');
  const seq = $('#seqInput').value;
  btn.disabled = true; btn.innerHTML = '<span class="loading"></span> 求解中';
  try {
    const o = await api('/api/optimize', {
      method: 'POST',
      body: JSON.stringify({
        sequence: seq,
        options: { cpg_free: $('#optCpg').checked, avoid_sites: $('#optSite').checked }
      })
    });
    state.optimization = o;
    state.analysis_seq = (state.analysis && state.analysis.sequence) || seq.replace(/[^ACGTNacgtn]/g, '').toUpperCase();
    if (!state.analysis) await runAnalysis();
    renderOptimize(o);
    drawRadar(o.after_detail);
    drawGC();
  } catch (e) {
    alert('优化失败：' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = '同义优化';
  }
}

/* ---------------- 靶点 ---------------- */
function renderWeights(dims, weights) {
  $('#weights').innerHTML = dims.map(d => `
    <div class="slider">
      <label>${d.label}</label>
      <input type="range" min="0" max="40" value="${weights[d.key]}" data-k="${d.key}">
      <span class="val">${weights[d.key]}%</span>
    </div>`).join('');
  $$('#weights input').forEach(inp => inp.addEventListener('input', e => {
    e.target.parentElement.querySelector('.val').textContent = e.target.value + '%';
    state.weights[e.target.dataset.k] = +e.target.value;
    clearTimeout(state.wTimer);
    state.wTimer = setTimeout(loadTargets, 140);
  }));
}

function renderTargets(data) {
  const dims = data.dims, rows = data.rows;
  $('#targetTable').innerHTML = `
    <thead><tr><th style="width:30px">#</th><th style="min-width:182px">适应症 / 分子</th>
      ${dims.map(d => `<th class="right" style="font-size:10.5px">${d.label.slice(0, 5)}</th>`).join('')}
      <th style="width:140px">加权得分</th></tr></thead>
    <tbody>${rows.map(r => `
      <tr>
        <td class="num" style="color:var(--faint)">${r.rank}</td>
        <td style="min-width:182px"><b style="white-space:nowrap">${r.name}</b>
          <div class="hint" style="white-space:nowrap">${r.mol}</div></td>
        ${dims.map(d => `<td class="right num" style="color:${r[d.key] >= 80 ? 'var(--teal-ink)' : r[d.key] < 60 ? 'var(--red)' : 'var(--ink-2)'}">${r[d.key]}</td>`).join('')}
        <td><div style="display:flex;align-items:center;gap:8px">
          <div class="bar" style="flex:1"><i style="width:${r.score}%"></i></div>
          <span class="num" style="font-size:12px;width:26px;text-align:right">${fmt(r.score, 0)}</span></div></td>
      </tr>`).join('')}</tbody>`;

  const top = rows[0];
  $('#topEvidence').innerHTML = (top.ev || []).map(e => `
    <div class="ev-row"><div class="ev-date" style="flex:0 0 40px">${e.d}</div>
      <div class="ev-txt">${e.t}<br><span>${e.s}</span></div></div>`).join('');
  $('#navTargets').textContent = rows.length;
}

async function loadTargets() {
  const q = state.weights ? '?weights=' + encodeURIComponent(JSON.stringify(state.weights)) : '';
  const data = await api('/api/targets' + q);
  state.weights = data.weights;
  renderTargets(data);
  return data;
}

/* ---------------- 台账 ---------------- */
function renderLoop() {
  const m = state.metrics, rows = state.records;
  const flagged = new Set(m.flagged || []);
  $('#loopKpis').innerHTML = [
    {
      k: '计入指标', v: m.n, u: '条',
      d: m.n_fail ? `台账 ${m.n_total} 条，${m.n_fail} 条技术失败未计入` : `台账共 ${m.n_total} 条`
    },
    { k: 'MAE', v: fmt(m.mae, 2), u: '×10⁹ VP/mL', d: `σ = ${fmt(m.sigma, 2)}` },
    { k: 'R²', v: fmt(m.r2, 2), u: '', d: m.r2 >= 0.55 ? '达标（目标 ≥0.55）' : '未达标，需扩样' },
    { k: 'Spearman ρ', v: fmt(m.spearman, 2), u: '', d: `超 2σ 记录 ${m.flagged.length} 条` }
  ].map(x => `<div class="card kpi"><div class="k">${x.k}</div>
      <div class="v">${x.v}<small>${x.u}</small></div><div class="d">${x.d}</div></div>`).join('');

  $('#recCount').textContent = rows.length + ' 条';
  const oc = r => r.outcome || 'hit';
  // 技术失败排在最后：它的实测值无效，不该跟正常记录一起比谁偏差大
  const sorted = [...rows].sort((a, b) => {
    const fa = oc(a) === 'fail', fb = oc(b) === 'fail';
    if (fa !== fb) return fa ? 1 : -1;
    return Math.abs(b.pred - b.obs) - Math.abs(a.pred - a.obs);
  });
  const OCLS = { hit: 't', miss: 'a', fail: 'r' };
  const ONAME = { hit: '达阈值', miss: '阴性', fail: '技术失败' };
  $('#loopTable').innerHTML = `
    <thead><tr><th>构建体</th><th class="right">预测</th><th class="right">实测</th><th class="right">偏差</th><th>结局</th><th>模型</th><th>日期</th><th></th></tr></thead>
    <tbody>${sorted.map(r => {
      const k = oc(r), isFail = k === 'fail';
      const e = r.pred - r.obs, bad = flagged.has(r.id) && !isFail;
      const note = r.note
        ? `<div class="hint"${bad ? ' style="color:var(--red)"' : ''}>${r.note}</div>`
        : (bad ? '<div class="hint" style="color:var(--red)">偏差 > 2σ，待归因</div>' : '');
      return `<tr${isFail ? ' style="background:#fdf5f4"' : ''}>
        <td><b>${r.id}</b>${note}</td>
        <td class="right num">${fmt(r.pred)}</td>
        <td class="right num"${isFail ? ' style="color:var(--faint)"' : ''}>${isFail ? '—' : fmt(r.obs)}</td>
        <td class="right num" style="color:${bad ? 'var(--red)' : 'var(--ink-2)'};font-weight:${bad ? 600 : 400}">${isFail ? '不计入' : `${e > 0 ? '+' : ''}${fmt(e)}`}</td>
        <td><span class="pill ${OCLS[k]}">${ONAME[k]}</span></td>
        <td><span class="pill ${r.model.startsWith('b2') ? 't' : 'v'}">${r.model}</span></td>
        <td class="num" style="color:var(--muted)">${r.created}</td>
        <td><button class="btn sm" data-del="${r.id}" style="padding:2px 8px">删除</button></td></tr>`;
    }).join('')}</tbody>`;

  $$('#loopTable [data-del]').forEach(b => b.onclick = async () => {
    if (!confirm(`删除 ${b.dataset.del}？`)) return;
    const res = await api('/api/records/' + encodeURIComponent(b.dataset.del), { method: 'DELETE' });
    state.records = res.rows; state.metrics = res.metrics;
    renderLoop(); renderDash();
    loadCard();                      // 记录变了，模型卡必须重算，否则两处数字打架
  });

  $('#navLoop').textContent = rows.length;
  $('#loopCount').textContent = rows.length;
  renderAudit(m.audit);
  drawScatter();
}

/* ---------------- 结局审计 ---------------- */
function renderAudit(a) {
  if (!a) return;
  const pill = $('#auditPill');
  const LV = { ok: ['t', '结局分布可接受'], warn: ['a', '阳性率偏高'], alarm: ['r', '疑似选择性录入'] };
  const [cls, txt] = LV[a.level] || ['', '—'];
  pill.className = 'pill ' + cls;
  pill.textContent = txt;

  const segs = [
    { k: 'hit', c: 'var(--teal)', w: a.counts.hit },
    { k: 'miss', c: '#c98a1c', w: a.counts.miss },
    { k: 'fail', c: '#b4392f', w: a.counts.fail }
  ].filter(s => s.w > 0);
  const total = a.total || 1;

  $('#auditBox').innerHTML = `
    <div style="display:flex;height:26px;border-radius:6px;overflow:hidden;background:#eef2f2">
      ${segs.map(s => `<div title="${a.labels[s.k]} ${s.w} 条"
          style="width:${s.w / total * 100}%;background:${s.c};display:flex;align-items:center;justify-content:center;
                 color:#fff;font-size:11px;font-weight:600">${s.w / total >= 0.08 ? s.w : ''}</div>`).join('')}
    </div>
    <div style="display:flex;gap:16px;margin-top:9px;font-size:12px;flex-wrap:wrap">
      ${['hit', 'miss', 'fail'].map(k => `<span style="display:flex;align-items:center;gap:5px">
        <i style="width:9px;height:9px;border-radius:2px;display:inline-block;background:${
          k === 'hit' ? 'var(--teal)' : k === 'miss' ? '#c98a1c' : '#b4392f'}"></i>
        ${a.labels[k]} <b>${a.counts[k]}</b></span>`).join('')}
      <span style="margin-left:auto;color:var(--muted)">
        阳性率 <b style="color:${a.hit_rate >= a.alarm_rate ? 'var(--red)' : 'var(--ink)'}">${
          (a.hit_rate * 100).toFixed(0)}%</b>（警戒 ${(a.alarm_rate * 100).toFixed(0)}%）
        · 技术失败率 ${(a.fail_rate * 100).toFixed(0)}%</span>
    </div>
    <div style="margin-top:10px;padding:9px 11px;border-radius:8px;font-size:12.5px;line-height:1.6;
        background:${a.level === 'alarm' ? '#fdf5f4' : a.level === 'warn' ? '#fdf7ea' : '#f2f8f6'};
        border:1px solid ${a.level === 'alarm' ? '#f0d5d2' : a.level === 'warn' ? '#f2dfb8' : '#d6ece7'}">
      <b>${a.level === 'alarm' ? '⚠ ' : ''}${a.verdict}</b>
      ${a.unattributed && a.unattributed.length
        ? `<div style="margin-top:6px;color:#8a5a10">${a.unattributed.length} 条技术失败未填归因（${
            a.unattributed.slice(0, 3).join('、')}${a.unattributed.length > 3 ? '…' : ''}），失败原因比失败本身更值钱。</div>`
        : ''}
    </div>`;
}

function drawSens(s) {
  const cv = $('#sensChart');
  if (!cv) return;
  const meta = $('#sensMeta'), vb = $('#sensVerdict'), ab = $('#sensAssump');
  if (!s || !s.available) {
    meta.textContent = '—';
    vb.innerHTML = `<div class="hint">${(s && s.reason) || '模型卡尚未加载完成。'}</div>`;
    ab.textContent = '';
    return;
  }
  meta.textContent = `每个比例重复 ${s.repeats} 次取中位数 · seed=${s.seed}`;

  const { ctx, w, h } = fit(cv, 220);
  const padL = 34, padR = 14, padT = 14, padB = 34;
  const iw = w - padL - padR, ih = h - padT - padB;
  const X = v => padL + v / 0.5 * iw;
  const Y = r => padT + ih - clamp(r, 0, 1) * ih;

  [0, 0.25, 0.5, 0.75, 1].forEach(r => {
    const y = Y(r);
    ctx.strokeStyle = '#f0f3f3'; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    ctx.fillStyle = '#93a0a3'; ctx.font = '10px ui-monospace,monospace'; ctx.textAlign = 'right';
    ctx.fillText(r.toFixed(2), padL - 6, y + 3);
  });
  s.curve.forEach(c => {
    ctx.fillStyle = '#93a0a3'; ctx.font = '10px ui-monospace,monospace'; ctx.textAlign = 'center';
    ctx.fillText((c.miss_rate * 100).toFixed(0) + '%', X(c.miss_rate), h - 16);
  });

  // 目标线 / 崩塌线
  [[s.target_r2, 'rgba(180,57,47,.55)', `目标线 ${s.target_r2}`],
   [s.tip_level, 'rgba(120,120,120,.4)', `崩塌线 ${s.tip_level}`]].forEach(([v, col, lab]) => {
    ctx.strokeStyle = col; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(padL, Y(v)); ctx.lineTo(w - padR, Y(v)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = col; ctx.font = '10px system-ui'; ctx.textAlign = 'left';
    ctx.fillText(lab, padL + 3, Y(v) - 4);
  });

  // 25–75 分位带
  ctx.beginPath();
  s.curve.forEach((c, i) => { const x = X(c.miss_rate), y = Y(c.r2_band[1]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  [...s.curve].reverse().forEach(c => ctx.lineTo(X(c.miss_rate), Y(c.r2_band[0])));
  ctx.closePath(); ctx.fillStyle = 'rgba(13,138,122,.13)'; ctx.fill();

  // 曲线
  ctx.beginPath();
  s.curve.forEach((c, i) => { const x = X(c.miss_rate), y = Y(c.r2); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.strokeStyle = '#0d8a7a'; ctx.lineWidth = 2; ctx.stroke(); ctx.lineWidth = 1;
  s.curve.forEach(c => {
    ctx.beginPath(); ctx.arc(X(c.miss_rate), Y(c.r2), 3.6, 0, 7);
    ctx.fillStyle = c.r2 < s.target_r2 ? '#b4392f' : '#0d8a7a'; ctx.fill();
  });

  // tipping point 标注
  const tipC = s.curve.find(c => c.miss_rate === s.tip_target);
  if (tipC) {
    const x = X(tipC.miss_rate), y = Y(tipC.r2);
    ctx.strokeStyle = 'rgba(180,57,47,.5)'; ctx.setLineDash([2, 3]);
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x, padT + ih); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = '#b4392f'; ctx.font = '600 10px system-ui'; ctx.textAlign = 'center';
    ctx.fillText('tipping point', x, padT + 8);
  }
  ctx.fillStyle = '#6c797c'; ctx.font = '11px system-ui'; ctx.textAlign = 'left';
  ctx.fillText('假设未入库的阴性样本比例 →', padL + 4, h - 2);

  const tipTxt = s.tip_target == null
    ? `在 0–50% 范围内 R² 未跌破目标线 ${s.target_r2}`
    : `<b style="color:var(--red)">tipping point = ${(s.tip_target * 100).toFixed(0)}%</b>`;
  vb.innerHTML = `<div style="font-size:12.5px;line-height:1.65">${tipTxt}：${s.verdict}</div>`;
  ab.innerHTML = `<b>假设条件（缺一不可）</b><br>${s.assumptions.map(x => '· ' + x).join('<br>')}`;
}

/* ---------------- 模型卡 ---------------- */
function ciTxt(ci) {
  return ci ? `<span class="mono" style="color:var(--muted)">[${fmt(ci.lo, 2)}, ${fmt(ci.hi, 2)}]</span>`
            : '<span style="color:var(--red)">样本不足</span>';
}

function renderModelCard(card) {
  state.card = card;
  const o = card.overall;
  $('#cardBoot').textContent =
    `bootstrap ${card.boot.n_boot} 次 · α=${card.boot.alpha} · seed=${card.boot.seed}`;

  const rows = [`<thead><tr><th>分组</th><th class="right">n</th><th class="right">MAE</th><th>MAE 95% CI</th>
      <th class="right">R²</th><th>R² 95% CI</th><th class="right">ρ</th></tr></thead>`, '<tbody>'];

  rows.push(`<tr style="background:#f7fbfa">
      <td><b>总体</b></td><td class="right num">${o.n}</td>
      <td class="right num">${fmt(o.mae, 2)}</td><td>${ciTxt(o.mae_ci)}</td>
      <td class="right num">${fmt(o.r2, 2)}</td><td>${ciTxt(o.r2_ci)}</td>
      <td class="right num">${fmt(o.spearman, 2)}</td></tr>`);

  card.by_model.forEach(g => {
    const bad = !g.reliable;
    rows.push(`<tr${bad ? ' style="background:#fdf5f4"' : ''}>
      <td>${g.group}${bad ? '<div class="hint" style="color:var(--red)">不得单独引用</div>' : ''}</td>
      <td class="right num">${g.n}</td>
      <td class="right num">${fmt(g.mae, 2)}</td><td>${ciTxt(g.mae_ci)}</td>
      <td class="right num" style="color:${g.reliable && g.r2 < o.r2 - 0.3 ? 'var(--red)' : 'var(--ink)'}">${fmt(g.r2, 2)}</td>
      <td>${ciTxt(g.r2_ci)}</td>
      <td class="right num">${fmt(g.spearman, 2)}</td></tr>`);
  });
  $('#cardTable').innerHTML = rows.join('') + '</tbody>';

  const an = card.anomalies || [];
  $('#anomPill').textContent = an.length ? `${an.length} 项待归因` : '未检出';
  $('#anomPill').className = 'pill ' + (an.length ? 'r' : 't');
  $('#anomList').innerHTML = an.length ? an.map(a => `
    <div class="risk hi"><span class="dot"></span><div style="flex:1">
      <div><b>${a.group}</b> <span class="hint">n=${a.n}</span></div>
      <div class="act">R² ${a.r2} vs 总体 ${a.overall_r2}（${a.delta > 0 ? '+' : ''}${a.delta}）</div>
      <div class="act" style="color:var(--teal-ink)">→ 总体均值掩盖了该组差异，需按版本单独归因后再决定是否继续用</div>
    </div></div>`).join('')
    : '<div class="hint">各可信组 R² 与总体差值均 < 0.3，无需单独归因。</div>';

  const h = card.holdout;
  $('#holdoutBox').innerHTML = `
    <div class="hint">以 <b>${h.cutoff}</b> 为界（真实使用时应取模型冻结日）</div>
    ${[['回溯集', h.retro], ['前瞻集', h.prospective]].map(([k, b]) => `
      <div class="ba"><span class="ba-k">${k}（n=${b.n}）</span>
        <span class="ba-v"><span class="ba-from">MAE ${fmt(b.mae, 2)}</span>
        <span style="color:var(--faint)">·</span>
        <span class="ba-to">R² ${fmt(b.r2, 2)}</span></span></div>`).join('')}
    <div class="hint">${h.note}</div>`;

  $('#limitsBox').innerHTML = card.limitations.map(x => `
    <div style="display:flex;gap:8px;font-size:12.5px;line-height:1.6">
      <span style="color:var(--red);flex:0 0 auto">·</span><span>${x}</span></div>`).join('');

  drawSens(card.sensitivity);
}

/* ---------------- 总览 ---------------- */
const PIPELINE = [
  { p: 'ECD01', ind: '膀胱癌 NMIBC', stage: 'IND 准备', readout: '单周期给药抑瘤 99%（临床前）', ai: 82, note: 'CMC 中试' },
  { p: 'ECD02', ind: '肝细胞癌 HCC', stage: '临床前 PoC', readout: '待体内重复给药数据', ai: 64, note: '序列优化中' },
  { p: 'ECD03', ind: '前列腺癌 mCRPC', stage: '靶点评估', readout: 'miRNA 网络缺陷覆盖率 71%', ai: 41, note: '适应症排序' }
];

function renderDash() {
  const m = state.metrics || { n: 0, mae: 0, r2: 0, flagged: [], spearman: 0, sigma: 0 };
  $('#kpis').innerHTML = [
    { k: '在研项目', v: '3', u: '个', d: 'ECD01 临近 IND · 2 个临床前', cls: '' },
    { k: '设计→体内 PoC 周期', v: '6.8', u: '周', d: '基线 10 周 · ↓32%', cls: 'up' },
    { k: '本期无效实验压缩', v: '97.6', u: '%', d: '500 候选 → 12 个进湿实验', cls: 'up' },
    { k: '预测偏差超阈', v: String(m.flagged.length), u: '项', d: `共 ${m.n} 条记录`, cls: m.flagged.length ? 'down' : '' }
  ].map(x => `<div class="card kpi"><div class="k">${x.k}</div>
      <div class="v">${x.v}<small>${x.u}</small></div><div class="d ${x.cls}">${x.d}</div></div>`).join('');

  $('#pipeline').innerHTML = `
    <thead><tr><th>项目</th><th>适应症</th><th>阶段</th><th>关键读数</th><th style="width:130px">AI 支持度</th></tr></thead>
    <tbody>${PIPELINE.map(r => `<tr>
      <td><b>${r.p}</b></td>
      <td>${r.ind}<div class="hint">${r.note}</div></td>
      <td><span class="pill ${r.stage === 'IND 准备' ? 't' : r.stage === '临床前 PoC' ? 'a' : ''}">${r.stage}</span></td>
      <td>${r.readout}</td>
      <td><div style="display:flex;align-items:center;gap:8px"><div class="bar" style="flex:1"><i style="width:${r.ai}%"></i></div>
        <span class="num" style="font-size:12px;color:var(--muted)">${r.ai}</span></div></td></tr>`).join('')}</tbody>`;

  $('#events').innerHTML = [
    { d: '10-28', t: '<b>模型卡上线</b>', s: '分层指标 + bootstrap 区间；一分层就发现最新版 R²≈0' },
    { d: '10-28', t: '<b>后端上线</b>', s: 'SQLite 持久化 + 本地 API，指标实时重算' },
    { d: '10-27', t: '<b>同义优化求解器上线</b>', s: 'CpG-free + 去酶切位点，蛋白序列零改动' },
    { d: '10-24', t: '<b>靶点评分接入服务端</b>', s: '六维权重可调，排序由后端重算' },
    { d: '10-21', t: '<b>否决 AlphaFold3 进管线</b>', s: '许可分 25 < 门槛 60，精度最高也不放行' }
  ].map(e => `<div class="ev-row"><div class="ev-date">${e.d}</div>
      <div class="ev-txt">${e.t}<br><span>${e.s}</span></div></div>`).join('');

  const flaggedRows = state.records.filter(r => (m.flagged || []).includes(r.id));
  $('#biasPill').textContent = `${flaggedRows.length} 项超阈`;
  $('#biasPill').className = 'pill ' + (flaggedRows.length ? 'a' : 't');
  $('#biasList').innerHTML = flaggedRows.length ? flaggedRows.map(r => {
    const dev = Math.abs(r.pred - r.obs) / (m.sigma || 1);
    return `<div>
      <div style="display:flex;align-items:center;gap:8px;font-size:12.5px">
        <span>${r.id}</span><span class="pill r">${fmt(dev)}σ</span>
        <span style="margin-left:auto" class="mono">MAE ${fmt(Math.abs(r.pred - r.obs), 2)}</span></div>
      <div class="bar" style="margin-top:6px"><i style="width:${clamp(dev / 3 * 100)}%"></i></div>
      <div class="hint" style="margin-top:4px">${r.note || '待归因'}</div></div>`;
  }).join('') : '<div class="hint">当前无超阈记录。</div>';
}

/* ---------------- 模型 / 资产 ---------------- */
function renderModels(data) {
  const rows = data.rows;
  $('#modelThreshold').textContent = `许可 < ${data.veto_threshold} 分一票否决 · 最优 ${data.best}`;
  $('#modelTable').innerHTML = `
    <thead><tr><th style="width:28px">#</th><th>模型</th><th>任务</th><th>许可</th><th class="right">许可分</th><th>GitHub</th>
      <th style="width:130px">综合分</th><th>结论</th></tr></thead>
    <tbody>${rows.map(m => `<tr${m.vetoed ? ' style="background:#fdf5f4"' : ''}>
        <td class="num" style="color:var(--faint)">${m.rank}</td>
        <td><b>${m.n}</b>${m.vetoed ? `<div class="hint" style="color:var(--red)">${m.reason}</div>` : ''}</td>
        <td style="color:var(--ink-2)">${m.task}</td>
        <td><span class="pill ${m.vetoed ? 'r' : 't'}">${m.lic}</span></td>
        <td class="right num" style="color:${m.vetoed ? 'var(--red)' : 'var(--ink-2)'};font-weight:${m.vetoed ? 600 : 400}">${m.ls}</td>
        <td class="mono" style="color:var(--muted)">${m.stars}</td>
        <td><div style="display:flex;align-items:center;gap:8px"><div class="bar" style="flex:1"><i style="width:${m.total}%"></i></div>
          <span class="num" style="font-size:12px;width:26px;text-align:right">${fmt(m.total, 1)}</span></div></td>
        <td><span class="pill ${m.vetoed ? 'r' : m.verdict.includes('上线') ? 't' : 'a'}">${m.decision}</span></td></tr>`).join('')}</tbody>`;
  $('#modelNote').textContent = data.note;
}

const ASSETS = [
  { n: '文献与专利', c: 12480, unit: '篇', up: '每日增量', own: '生信组', lic: '混合（逐篇核）', train: false, note: '论文 12,480 篇 + 专利 318 件；PaperQA2 建索引' },
  { n: '内部组学', c: 386, unit: '样本', up: '随实验', own: '生信组', lic: '内部', train: true, note: 'scRNA-seq / miRNA-seq / bulk RNA' },
  { n: '临床与随访', c: 42, unit: '例', up: '月度', own: '临床组', lic: '内部 · 去标识', train: false, note: '需伦理批件与数据使用协议' },
  { n: '实验记录（ELN）', c: 2140, unit: '条', up: '实时', own: '实验组', lic: '内部', train: true, note: '含 617 条阴性记录，已结构化入库' }
];

async function loadAssets() {
  const q = $('#assetSearch').value.trim();
  const sort = $('#assetSort').value;
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (sort) params.set('sort', sort);
  const d = await api('/api/assets' + (params.toString() ? '?' + params.toString() : ''));
  renderAssets(d);
}

function renderAssets(d) {
  // 顶部汇总卡（按类别）
  $('#assets').innerHTML = d.summary.map(s => {
    const allTrain = s.train === s.total && s.total > 0;
    return `<div class="card"><div class="card-hd"><h2>${s.category}</h2><span class="sp"></span>
      <span class="pill ${allTrain ? 't' : s.train > 0 ? 'v' : 'a'}">${allTrain ? '全部可训练' : s.train ? '部分可训练' : '仅检索'}</span></div>
      <div class="card-bd">
        <div style="display:flex;align-items:baseline;gap:6px">
          <span style="font-size:24px;font-weight:640">${s.total}</span><span class="hint">项</span>
          <span class="hint" style="margin-left:6px">${s.train} 项可训练</span></div>
      </div></div>`;
  }).join('');

  $('#assetCount').textContent = d.matched < d.total ? `${d.matched} / ${d.total} 项` : `${d.total} 项`;
  $('#assetTag').textContent = `共 ${d.summary.length} 类 · ${d.total} 项`;

  $('#assetTable').innerHTML = `
    <thead><tr><th>资产</th><th>类别</th><th>规模</th><th>许可</th><th>训练可用性</th><th>责任人</th></tr></thead>
    <tbody>${d.rows.map(a => `<tr><td><b>${a.name}</b><div class="hint" style="color:var(--muted)">${a.note}</div></td>
      <td style="color:var(--muted)">${a.category}</td>
      <td class="num">${a.size}</td>
      <td class="mono" style="color:var(--muted)">${a.license}</td>
      <td><span class="pill ${a.pill}">${a.usage === '训练' ? '可训练' : a.usage === '评测' ? '仅评测' : '仅检索'}</span></td>
      <td style="color:var(--muted)">${a.owner}</td></tr>`).join('')}</tbody>`;
}

function renderProtein(p) {
  state.protein = p;
  const cards = [
    { k: '氨基酸数', v: String(p.n_aa), s: `CDS ${p.cds_nt} nt${p.truncated_nt ? ` · 尾部 ${p.truncated_nt} nt 未翻译` : ''}` },
    { k: '分子量', v: fmt(p.mw_kda, 2), s: 'kDa · 平均残基质量' },
    { k: 'GRAVY', v: fmt(p.gravy, 2), s: p.gravy > 0 ? '整体疏水' : '整体亲水', cls: p.gravy > 0.2 ? 'down' : '' },
    { k: '等电点 pI', v: fmt(p.pI, 2), s: `pH 7 净电荷 ${p.charge_ph7 > 0 ? '+' : ''}${fmt(p.charge_ph7, 2)}` },
    { k: '脂肪族指数', v: fmt(p.aliphatic_index, 1), s: 'Ikai (1980) · 越高越耐热' },
    { k: 'ε₂₈₀', v: String(p.ext_coeff_280), s: 'M⁻¹cm⁻¹ · 还原态' },
    { k: 'Cys / 电荷对', v: `${p.cys} / ${p.basic}·${p.acidic}`, s: 'Cys 可交联 · 碱性·酸性残基' },
    { k: 'N-糖基化', v: String(p.n_glyc), s: p.n_glyc ? (p.glyc_sites[0].motif + '@' + p.glyc_sites[0].pos) : '无 N-X-S/T 基序', cls: p.n_glyc ? 'down' : '' }
  ];
  $('#protMetrics').innerHTML = cards.map(c => `<div class="card metric" style="box-shadow:none">
      <span class="m-k">${c.k}</span><span class="m-v">${c.v}</span>
      <span class="m-s ${c.cls || ''}">${c.s}</span></div>`).join('');

  const lvMap = { hi: ['r', '高'], md: ['a', '中'], lo: ['', '低'] };
  $('#protRiskCount').textContent = p.risks.length + ' 条';
  $('#protRiskCount').className = 'pill ' + (p.risks.some(r => r.lv === 'hi') ? 'r' : p.risks.length ? 'a' : 't');
  $('#protRisks').innerHTML = p.risks.length ? p.risks.map(r => `
    <div class="risk ${r.lv}"><span class="dot"></span>
      <div style="flex:1">
        <div><b>${r.t}</b></div>
        <div class="act">${r.d}</div>
        <div class="act" style="color:var(--teal-ink)">→ ${r.a}</div>
      </div></div>`).join('') : '<div class="hint">未检出序列层面的风险项。</div>';

  const top = Object.entries(p.composition).slice(0, 9);
  const maxC = Math.max(...top.map(x => x[1]));
  $('#aaHelper').textContent = `共 ${Object.keys(p.composition).length} 种残基`;
  $('#aaComp').innerHTML = top.map(([aa, c]) => `
    <div style="display:flex;align-items:center;gap:8px;font-size:12px">
      <span class="mono" style="width:16px;color:var(--ink-2)">${aa}</span>
      <div class="bar" style="flex:1"><i style="width:${c / maxC * 100}%"></i></div>
      <span class="mono" style="width:44px;text-align:right;color:var(--muted)">${c} · ${fmt(c / p.n_aa * 100, 1)}%</span>
    </div>`).join('');

  const runs = p.hydrophobic_runs || [];
  $('#hydroNote').innerHTML = runs.length
    ? `检出 ${runs.length} 处连续疏水段：` + runs.slice(0, 3).map(r =>
        `<b>${r.start}–${r.end} aa</b>（跨 ${r.span} aa，峰值 ${r.peak}）`).join('，')
      + `。阈值 ${p.tm_threshold}，窗口 ${p.hydro_window} aa；跨 ≥15 aa 才怀疑跨膜，10–14 aa 多为球状蛋白疏水核。`
    : `无连续疏水段。整体 GRAVY ${fmt(p.gravy, 2)}。`;

  $('#boltzYaml').textContent =
`version: 1
sequences:
  - protein:
      id: A
      sequence: ${p.n_aa > 40 ? p.protein.slice(0, 20) + '…' + p.protein.slice(-8) : p.protein}
  - protein:
      id: B
      sequence: <hexon_aa>
properties:
  - affinity:
      binder: B`;
}

/* ---------------- 结构推理任务 ---------------- */
const STATUS_LABEL = { queued: '排队中', running: '运行中', done: '完成', failed: '失败' };
const STATUS_PILL = { queued: 'a', running: 'a', done: 't', failed: 'r' };

function renderInferTable(rows) {
  const tb = $('#inferTable tbody');
  if (!rows.length) {
    tb.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">暂无任务。</td></tr>';
    return;
  }
  tb.innerHTML = rows.map(t => `
    <tr data-tid="${t.id}" style="cursor:pointer">
      <td class="mono" style="font-size:12px">${t.id}</td>
      <td><span class="pill v">${t.model}</span></td>
      <td><span class="pill ${STATUS_PILL[t.status]}">${STATUS_LABEL[t.status] || t.status}</span></td>
      <td class="mono" style="font-size:12px;color:var(--muted)">${t.input_hash}</td>
      <td class="num" style="color:var(--muted)">${t.created}</td>
      <td class="right num">${t.result && t.result.mean_plddt != null ? t.result.mean_plddt : '—'}</td>
    </tr>`).join('');
  $$('#inferTable [data-tid]').forEach(tr => tr.onclick = () => {
    const tid = tr.dataset.tid;
    showInferResult(tid);
  });
}

function drawPlddtCurve(result) {
  const cv = $('#plddtCanvas');
  if (!cv) return;
  const { ctx, w, h } = fit(cv, 150);
  const padL = 30, padR = 10, padT = 10, padB = 18;
  const iw = w - padL - padR, ih = h - padT - padB;
  const N = result.n_res, vals = result.plddt;
  const X = i => padL + i / Math.max(1, N - 1) * iw;
  const Y = v => padT + ih - v / 100 * ih;
  [50, 70, 90].forEach(v => {
    const y = Y(v);
    ctx.strokeStyle = '#f0f3f3'; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    ctx.fillStyle = '#93a0a3'; ctx.font = '9px ui-monospace,monospace'; ctx.textAlign = 'right';
    ctx.fillText(v, padL - 5, y + 3);
  });
  vals.forEach((v, i) => {
    const x = X(i), y = Y(v);
    ctx.fillStyle = v > 90 ? '#12a58f' : v > 70 ? '#c98a1c' : '#b4392f';
    ctx.fillRect(x, y, Math.max(1.5, iw / N * 0.9), padT + ih - y);
  });
  ctx.fillStyle = '#6c797c'; ctx.font = '10px system-ui'; ctx.textAlign = 'left';
  ctx.fillText('1', padL, h - 4);
  ctx.textAlign = 'right'; ctx.fillText(N + ' 残基', w - padR, h - 4);
}

function showInferResult(tid) {
  const t = state.inferTasks.find(x => x.id === tid);
  if (!t) return;
  $('#inferResultState').textContent = STATUS_LABEL[t.status] || t.status;
  $('#inferResultState').className = 'tag';

  if (t.status === 'failed') {
    $('#inferResult').innerHTML = `<div class="risk hi"><span class="dot"></span>
      <div><b>推理失败</b><div class="act">${t.error || '未知错误'}</div></div></div>`;
    return;
  }
  if (t.status !== 'done' || !t.result) {
    $('#inferResult').innerHTML = `<div class="hint" style="color:var(--muted)">
      ${t.status === 'running' ? '<span class="loading"></span> 推理进行中…' : '任务排队中，等待执行…'}</div>`;
    return;
  }
  const r = t.result;
  const low = r.plddt.filter(v => v < 50).length;
  $('#inferResult').innerHTML = `
    <div class="grid g4" style="gap:8px">
      <div class="card metric" style="box-shadow:none"><span class="m-k">平均 pLDDT</span><span class="m-v">${r.mean_plddt}</span><span class="m-s">${r.n_res} 残基</span></div>
      <div class="card metric" style="box-shadow:none"><span class="m-k">pTM</span><span class="m-v">${fmt(r.ptm, 2)}</span><span class="m-s">${r.ptm >= 0.7 ? '可信折叠' : '需复核'}</span></div>
      <div class="card metric" style="box-shadow:none"><span class="m-k">结合概率</span><span class="m-v">${fmt(r.binder, 2)}</span><span class="m-s">binder 概率（0–1）</span></div>
      <div class="card metric" style="box-shadow:none"><span class="m-k">低置信残基</span><span class="m-v">${low}</span><span class="m-s">pLDDT &lt; 50 需实验补充</span></div>
    </div>
    <div class="card" style="margin-top:10px;box-shadow:none;border:1px solid var(--line)">
      <div class="card-hd"><h2>残基级 pLDDT</h2><span class="sp"></span>
        <span class="legend"><span><i style="background:#12a58f"></i>&gt;90</span><span><i style="background:#c98a1c"></i>70–90</span><span><i style="background:#b4392f"></i>&lt;50</span></span></div>
      <div class="card-bd"><canvas id="plddtCanvas" height="150" style="width:100%;display:block"></canvas></div>
    </div>`;
  requestAnimationFrame(() => drawPlddtCurve(r));

  // 三要素
  $('#reproState').textContent = '已落盘';
  $('#reproState').className = 'pill t';
  $('#reproBox').innerHTML = `
    <div><span style="color:var(--muted)">镜像 digest</span><div class="mono" style="word-break:break-all">${r.repro.image_digest}</div></div>
    <div><span style="color:var(--muted)">权重 hash</span><div class="mono" style="word-break:break-all">${r.repro.weight_hash}</div></div>
    <div><span style="color:var(--muted)">输入 hash</span><div class="mono" style="word-break:break-all">${r.repro.input_hash}</div></div>
    <div class="hint" style="margin-top:4px">三要素 + 输入 YAML 一起落盘，任何人在任何机器上都能复现这次推理。</div>`;
}

async function loadInferTasks() {
  try {
    const d = await api('/api/infer');
    state.inferTasks = d.rows;
    $('#inferBackend').textContent = d.backend;
    renderInferTable(d.rows);
    if (d.rows.length) showInferResult(d.rows[0].id);
  } catch (e) { console.error(e); }
}

async function submitInfer() {
  const payload = $('#inferPayload').value.trim();
  const hexon = $('#inferHexon').value.trim();
  if (!payload || !hexon) return alert('请填写 payload 与六邻体两条蛋白序列。');
  const btn = $('#submitInfer');
  btn.disabled = true; btn.innerHTML = '<span class="loading"></span> 提交中';
  try {
    const d = await api('/api/infer', { method: 'POST', body: JSON.stringify({ payload_aa: payload, hexon_aa: hexon }) });
    $('#inferHint').textContent = `任务 ${d.task.id} 已提交，排队执行中。`;
    // 先插入本地，再轮询到完成
    state.inferTasks.unshift(d.task);
    renderInferTable(state.inferTasks);
    await pollInfer(d.task.id);
  } catch (e) {
    alert('提交失败：' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = '提交推理';
  }
}

async function pollInfer(tid) {
  // 轮询直到 done/failed，更新本地状态
  for (let i = 0; i < 60; i++) {
    const d = await api('/api/infer/' + encodeURIComponent(tid));
    const t = d.task;
    const idx = state.inferTasks.findIndex(x => x.id === tid);
    if (idx >= 0) state.inferTasks[idx] = t; else state.inferTasks.unshift(t);
    renderInferTable(state.inferTasks);
    if (t.status === 'done' || t.status === 'failed') {
      showInferResult(tid);
      return;
    }
    await new Promise(r => setTimeout(r, 300));
  }
}

$('#runOpt').onclick = runOptimize;
$('#submitInfer').onclick = submitInfer;
$('#assetSearch').addEventListener('input', () => loadAssets());
$('#assetSort').onchange = () => loadAssets();
$('#exportCsv').onclick = () => { window.location.href = '/api/records/export.csv'; };
$('#loadDemo').onclick = async () => {
  const d = await api('/api/demo');
  $('#seqInput').value = d.sequence;
  $('#seqHint').innerHTML = '示例构建体已<b>人工注入 6 类风险位点</b>（同聚物 / 串联重复 / 免疫刺激 CpG / polyA / 酶切位点 / E2F 元件）。';
  await runAnalysis();
};
$('#exportSeq').onclick = () => {
  if (!state.analysis) return alert('请先分析序列。');
  const a = state.analysis;
  const blob = new Blob([JSON.stringify(a, null, 2)], { type: 'application/json' });
  const el = document.createElement('a');
  el.href = URL.createObjectURL(blob);
  el.download = `seq-analysis-${a.length}bp.json`; el.click();
  URL.revokeObjectURL(el.href);
};
$('#resetW').onclick = async () => {
  state.weights = null;
  const t = await loadTargets();
  renderWeights(t.dims, t.weights);
};
$('#exportTarget').onclick = async () => {
  const data = await loadTargets();
  const blob = new Blob([JSON.stringify({ exportedAt: new Date().toISOString(), weights: data.weights, ranking: data.rows }, null, 2)], { type: 'application/json' });
  const el = document.createElement('a');
  el.href = URL.createObjectURL(blob);
  el.download = 'target-evaluation-snapshot.json'; el.click();
  URL.revokeObjectURL(el.href);
};
const syncOutcome = () => {
  const fail = $('#fOutcome').value === 'fail';
  $('#fObs').disabled = fail;
  $('#fObs').style.opacity = fail ? .45 : 1;
  $('#fObs').title = fail ? '技术失败没有有效读数，实测值不计入指标' : '';
};
$('#fOutcome').onchange = syncOutcome;
syncOutcome();

$('#addRec').onclick = async () => {
  const outcome = $('#fOutcome').value, note = $('#fNote').value.trim();
  if (outcome === 'fail' && !note) {
    return alert('技术失败必须填归因。失败原因（包装滴度不足 / 转染效率过低 / 样本污染）\n比失败本身更值钱——它是构建体设计的信号，不是模型误差。');
  }
  const body = {
    id: $('#fId').value.trim(), pred: parseFloat($('#fPred').value),
    obs: outcome === 'fail' ? 0 : parseFloat($('#fObs').value),
    model: $('#fVer').value, note, outcome
  };
  try {
    const res = await api('/api/records', { method: 'POST', body: JSON.stringify(body) });
    state.records = res.rows; state.metrics = res.metrics;
    // 新编号取现有最大号 +1：按条数算会在删过记录后撞号
    const maxN = res.rows.reduce((mx, r) => {
      const m = /(\d+)$/.exec(r.id);
      return m ? Math.max(mx, +m[1]) : mx;
    }, 0);
    $('#fId').value = 'ECD-AI-' + String(maxN + 1).padStart(3, '0');
    $('#fNote').value = '';
    renderLoop(); renderDash();
    loadCard();                      // 新数据进分层表，指标随之重算
  } catch (e) { alert('写入失败：' + e.message); }
};

/* ---------------- 启动 ---------------- */
async function loadCard() {
  try {
    renderModelCard(await api('/api/model-card'));
  } catch (e) { console.warn('模型卡加载失败：' + e.message); }
}

$('#exportCard').onclick = () => {
  if (!state.card) return alert('模型卡尚未加载完成。');
  const blob = new Blob([state.card.markdown], { type: 'text/markdown;charset=utf-8' });
  const el = document.createElement('a');
  el.href = URL.createObjectURL(blob);
  el.download = 'model-card.md'; el.click();
  URL.revokeObjectURL(el.href);
};

(async function init() {
  try {
    const h = await api('/api/health');
    $('#health').textContent = '● 本地服务已连接';
    $('#connState').textContent = `SQLite · ${h.version}`;
  } catch {
    $('#health').textContent = '● 服务未连接';
    $('#health').className = 'tag warn';
    $('#connState').textContent = '请先运行 python app.py';
  }

  try {
    const rec = await api('/api/records');
    state.records = rec.rows; state.metrics = rec.metrics;
    renderLoop(); renderDash();
  } catch (e) { console.error(e); }

  try {
    const t = await loadTargets();
    renderWeights(t.dims, t.weights);
  } catch (e) { console.error(e); }

  try { renderModels(await api('/api/models')); } catch (e) { console.error(e); }

  await loadCard();

  loadAssets();

  loadInferTasks();

  try {
    const d = await api('/api/demo');
    $('#seqInput').value = d.sequence;
    await runAnalysis();
  } catch (e) { console.error(e); }
})();

window.addEventListener('resize', () => {
  if ($('#view-seq').classList.contains('active')) { drawGC(); drawRadar(state.analysis); }
  if ($('#view-loop').classList.contains('active')) drawScatter();
  if ($('#view-struct').classList.contains('active')) drawHydro();
});
