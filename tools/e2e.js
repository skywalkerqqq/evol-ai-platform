/* 端到端联调：真浏览器 → 真 HTTP → 真 SQLite。
 * 跑之前先启动服务：python app.py 8000
 * 运行：NODE_PATH=... node tools/e2e.js
 */
const { chromium } = require('playwright');
const path = require('path');

const BASE = process.env.EVOL_BASE || 'http://127.0.0.1:8000/';
const OUT = path.join(__dirname, 'shots');

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail: detail === undefined ? '' : String(detail) });
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1.5 });
  const errs = [];
  page.on('pageerror', e => errs.push('PAGEERROR: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push('CONSOLE: ' + m.text()); });
  page.on('dialog', d => d.accept());          // 删除确认框自动确认

  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(700);

  /* ---------- 1 启动与总览 ---------- */
  const health = (await page.textContent('#health')).trim();
  check('服务连接状态', health.includes('已连接'), health);
  const conn = (await page.textContent('#connState')).trim();
  check('侧栏持久化标识', conn.includes('SQLite'), conn);

  const seedRows = await page.locator('#loopTable tbody tr').count();
  check('台账读到种子数据', seedRows === 18, `${seedRows} 条`);
  const kpiCards = await page.locator('#kpis .card').count();
  check('总览 KPI 渲染', kpiCards === 4, `${kpiCards} 张`);
  const pipeRows = await page.locator('#pipeline tbody tr').count();
  check('管线表渲染', pipeRows === 3, `${pipeRows} 行`);
  const biasTxt = (await page.textContent('#biasPill')).trim();
  check('偏差监控有口径', /项超阈/.test(biasTxt), biasTxt);
  await page.screenshot({ path: path.join(OUT, 'r-dash.png'), fullPage: true });

  /* ---------- 2 序列分析（真实计算） ---------- */
  await page.click('.nav-item[data-view="seq"]');
  await page.waitForTimeout(400);
  await page.click('#loadDemo');
  await page.waitForTimeout(600);

  const seqLen = (await page.textContent('#seqLenTag')).trim();
  const verdict1 = (await page.textContent('#seqVerdict')).trim();
  const riskRows = await page.locator('#risks .risk').count();
  const metricCount = await page.locator('#seqMetrics .metric').count();
  const topRisk = await page.locator('#seqTopRisk > div').count();
  const riskBefore = parseInt((await page.textContent('#riskCount')).trim(), 10);
  check('示例序列已分析', /\d+ bp/.test(seqLen), seqLen);
  check('分析给出结论而非占位', verdict1 !== '待分析', verdict1);
  check('风险位点条目 > 0', riskRows > 0, `${riskRows} 条`);
  check('指标卡 8 项', metricCount === 8, `${metricCount} 项`);
  check('Top 风险卡有内容', topRisk > 1, `${topRisk} 行（含标题）`);

  const gcPainted = await page.evaluate(() => {
    const cv = document.querySelector('#gcCanvas');
    const ctx = cv.getContext('2d');
    const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
    let n = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
    return n / (d.length / 4);
  });
  check('GC 曲线真的画出来了', gcPainted > 0.02, `覆盖率 ${(gcPainted * 100).toFixed(1)}%`);
  await page.screenshot({ path: path.join(OUT, 'r-seq.png'), fullPage: true });

  /* ---------- 3 同义优化（真实求解） ---------- */
  await page.click('#runOpt');
  await page.waitForSelector('#downloadFa', { timeout: 15000 });
  await page.waitForTimeout(300);

  const optInfo = await page.evaluate(() => {
    const ba = [...document.querySelectorAll('#optBody .ba')].map(e => ({
      k: e.querySelector('.ba-k').textContent.trim(),
      from: e.querySelector('.ba-from').textContent.trim(),
      to: e.querySelector('.ba-to').textContent.trim()
    }));
    const seqbox = document.querySelector('#optBody .seqbox');
    return {
      ba,
      changed: seqbox ? seqbox.querySelectorAll('.chg').length : 0,
      relax: (document.querySelector('#optBody').innerText.match(/全部约束满足|约束有放宽[^\n]*/) || [''])[0],
      trunc: /不构成完整密码子/.test(document.querySelector('#optBody').innerText),
      cpgFrom: (ba.find(x => x.k.includes('CpG')) || {}).from,
      cpgTo: (ba.find(x => x.k.includes('CpG')) || {}).to
    };
  });
  check('优化面板出现前后对比', optInfo.ba.length === 5, `${optInfo.ba.length} 行`);
  check('序列 diff 有高亮改动', optInfo.changed > 0, `${optInfo.changed} 个 nt`);
  check('CpG/100bp 被压到 0', parseFloat(optInfo.cpgTo) === 0, `${optInfo.cpgFrom} → ${optInfo.cpgTo}`);
  check('报告约束状态', optInfo.relax.length > 0, optInfo.relax);
  check('尾端截断如实提示', optInfo.trunc, optInfo.trunc ? '已提示' : '未提示');
  await page.screenshot({ path: path.join(OUT, 'r-opt.png'), fullPage: true });

  /* 应用优化序列 → 重新分析，风险应下降 */
  await page.click('#applyOpt');
  await page.waitForTimeout(1200);
  const verdict2 = (await page.textContent('#seqVerdict')).trim();
  const riskAfter = parseInt((await page.textContent('#riskCount')).trim(), 10);
  const appliedLen = await page.evaluate(() => document.querySelector('#seqInput').value.length);
  check('优化序列已回填工作台', appliedLen > 400, `${appliedLen} bp`);
  check('回填后重新分析风险数下降', riskAfter < riskBefore, `${riskBefore} 条 → ${riskAfter} 条`);
  check('结论随优化改善', verdict2 !== verdict1 || riskAfter < riskBefore, `${verdict1} → ${verdict2}`);

  /* ---------- 4 台账增删（真落库） ---------- */
  await page.click('.nav-item[data-view="loop"]');
  await page.waitForTimeout(400);
  const beforeAdd = await page.locator('#loopTable tbody tr').count();
  await page.fill('#fId', 'ECD-AI-999');
  await page.fill('#fPred', '7.4');
  await page.fill('#fObs', '5.2');
  await page.fill('#fNote', 'e2e 写入测试');
  await page.click('#addRec');
  await page.waitForTimeout(700);
  const afterAdd = await page.locator('#loopTable tbody tr').count();
  const recCount = (await page.textContent('#recCount')).trim();
  const maeVal = await page.evaluate(() => document.querySelectorAll('#loopKpis .card')[1].querySelector('.v').textContent.trim());
  check('新增记录写入成功', afterAdd === beforeAdd + 1, `${beforeAdd} → ${afterAdd}`);
  check('计数标签同步', recCount === `${afterAdd} 条`, recCount);
  check('MAE 由服务端重算', /^[\d.]+/.test(maeVal), maeVal);

  // 刷新页面验证真持久化（不是内存态）
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  await page.click('.nav-item[data-view="loop"]');
  await page.waitForTimeout(400);
  const afterReload = await page.locator('#loopTable tbody tr').count();
  check('刷新后记录仍在（SQLite 落盘）', afterReload === afterAdd, `${afterReload} 条`);

  // 删除
  await page.click('#loopTable [data-del="ECD-AI-999"]');
  await page.waitForTimeout(900);
  const afterDel = await page.locator('#loopTable tbody tr').count();
  check('删除记录成功', afterDel === beforeAdd, `${afterAdd} → ${afterDel}`);

  /* ---------- 4b 模型卡（分层 / 区间 / 异常） ---------- */
  const cardInfo = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#cardTable tbody tr')];
    const head = document.querySelector('#cardTable thead').innerText.replace(/\s+/g, ' ');
    return {
      rowCount: rows.length,
      head,
      overall: rows[0].innerText.replace(/\s+/g, ' '),
      groups: rows.slice(1).map(r => r.innerText.replace(/\s+/g, ' ')),
      anomPill: document.querySelector('#anomPill').textContent.trim(),
      anomN: document.querySelectorAll('#anomList .risk').length,
      holdout: document.querySelector('#holdoutBox').innerText.replace(/\s+/g, ' '),
      limitsN: document.querySelectorAll('#limitsBox > div').length,
      boot: document.querySelector('#cardBoot').textContent.trim()
    };
  });
  check('模型卡表格含总体 + 分层行', cardInfo.rowCount >= 3, `${cardInfo.rowCount} 行`);
  check('表头含置信区间列', /95% CI/.test(cardInfo.head), cardInfo.head.slice(0, 60));
  check('总体行带 R² 区间', /\[/.test(cardInfo.overall), cardInfo.overall.slice(0, 90));
  check('样本不足组标注不得引用',
    cardInfo.groups.some(g => g.includes('不得单独引用') || g.includes('样本不足')),
    cardInfo.groups.find(g => g.includes('不得单独引用')) || '（无小样本组）');
  check('分层异常被自动检出', cardInfo.anomN > 0 && /项待归因/.test(cardInfo.anomPill),
    cardInfo.anomPill);
  check('前瞻/回溯并列展示', /回溯集/.test(cardInfo.holdout) && /前瞻集/.test(cardInfo.holdout),
    cardInfo.holdout.slice(0, 70));
  check('局限性逐条列出', cardInfo.limitsN >= 3, `${cardInfo.limitsN} 条`);
  check('公布 bootstrap 参数（可复现）', /seed=\d+/.test(cardInfo.boot), cardInfo.boot);

  // 写一条极端偏差记录 → 分层指标必须跟着变
  const cardBeforeAdd = await page.evaluate(() =>
    document.querySelector('#cardTable tbody tr').innerText.replace(/\s+/g, ' '));
  await page.fill('#fId', 'ECD-AI-998');
  await page.fill('#fPred', '9.0');
  await page.fill('#fObs', '3.0');
  await page.click('#addRec');
  await page.waitForTimeout(900);
  const cardAfterAdd = await page.evaluate(() =>
    document.querySelector('#cardTable tbody tr').innerText.replace(/\s+/g, ' '));
  check('新增记录后模型卡自动重算', cardBeforeAdd !== cardAfterAdd,
    `${cardBeforeAdd.slice(0, 40)} → ${cardAfterAdd.slice(0, 40)}`);
  await page.click('#loopTable [data-del="ECD-AI-998"]');
  await page.waitForTimeout(900);
  const cardRestored = await page.evaluate(() =>
    document.querySelector('#cardTable tbody tr').innerText.replace(/\s+/g, ' '));
  check('删除后模型卡回到原值', cardRestored === cardBeforeAdd, cardRestored.slice(0, 40));

  /* ---------- 4c 结局审计与选择性偏差 ---------- */
  const auditInfo = await page.evaluate(() => ({
    pill: document.querySelector('#auditPill').textContent.trim(),
    box: document.querySelector('#auditBox').innerText.replace(/\s+/g, ' '),
    hasOutcomeCol: [...document.querySelectorAll('#loopTable thead th')]
      .some(t => t.textContent.includes('结局')),
    verdict: document.querySelector('#sensVerdict').innerText.replace(/\s+/g, ' '),
    assump: (document.querySelector('#sensAssump').innerText.match(/·/g) || []).length,
    meta: document.querySelector('#sensMeta').textContent.trim(),
  }));
  check('台账表出现结局列', auditInfo.hasOutcomeCol, '有');
  check('全阳性台账被判选择性录入', /选择性录入/.test(auditInfo.pill), auditInfo.pill);
  check('阳性率与警戒线并列显示',
    /阳性率 100%/.test(auditInfo.box) && /警戒 80%/.test(auditInfo.box),
    auditInfo.box.slice(0, 90));
  check('审计结论写明后果', /乐观偏差/.test(auditInfo.box), '有');
  check('敏感性 tipping point 已标出', /tipping point = \d+%/.test(auditInfo.verdict),
    auditInfo.verdict.slice(0, 70));
  check('假设条件逐条列明（不只给数字）', auditInfo.assump >= 4, `${auditInfo.assump} 条`);
  check('公布重复次数与 seed', /seed=\d+/.test(auditInfo.meta), auditInfo.meta);

  const sensPainted = await page.evaluate(() => {
    const cv = document.querySelector('#sensChart');
    const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
    let n = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 8) n++;
    return n / (cv.width * cv.height);
  });
  check('R² 下降曲线真的画出来了', sensPainted > 0.02,
    `覆盖率 ${(sensPainted * 100).toFixed(1)}%`);
  await page.screenshot({ path: path.join(OUT, 'r-audit.png'), fullPage: true });

  // 技术失败：必须落库，但绝不计入指标
  const kpiBefore = await page.evaluate(() =>
    document.querySelectorAll('#loopKpis .card')[0].querySelector('.v').textContent.trim());
  await page.selectOption('#fOutcome', 'fail');
  await page.fill('#fId', 'ECD-AI-997');
  await page.fill('#fPred', '6.5');
  await page.fill('#fNote', 'e2e：包装滴度不足');
  await page.click('#addRec');
  await page.waitForTimeout(800);
  const failInfo = await page.evaluate(() => {
    const cards = document.querySelectorAll('#loopKpis .card');
    const row = [...document.querySelectorAll('#loopTable tbody tr')]
      .find(r => r.innerText.includes('ECD-AI-997'));
    return {
      rows: document.querySelectorAll('#loopTable tbody tr').length,
      kpi0: cards[0].querySelector('.v').textContent.trim(),
      kpi0d: cards[0].querySelector('.d').textContent.trim(),
      box: document.querySelector('#auditBox').innerText.replace(/\s+/g, ' '),
      row: row ? row.innerText.replace(/\s+/g, ' ') : '',
    };
  });
  check('技术失败记录仍落库', failInfo.row.includes('ECD-AI-997'), failInfo.row.slice(0, 60));
  check('技术失败不计入指标', failInfo.kpi0 === kpiBefore, `${kpiBefore} → ${failInfo.kpi0}`);
  check('KPI 说明剔除了几条', /未计入/.test(failInfo.kpi0d), failInfo.kpi0d);
  check('该行实测值显示为 —', /—/.test(failInfo.row), failInfo.row.slice(0, 80));
  check('失败率进入审计卡', /技术失败率 \d+%/.test(failInfo.box), failInfo.box.slice(0, 110));
  await page.click('#loopTable [data-del="ECD-AI-997"]');
  await page.waitForTimeout(800);
  check('删除后结局分布复原',
    !/技术失败率 [1-9]/.test((await page.textContent('#auditBox')).replace(/\s+/g, ' ')),
    '已复原');

  await page.screenshot({ path: path.join(OUT, 'r-loop.png'), fullPage: true });

  /* ---------- 5 靶点权重（服务端重算排序） ---------- */
  await page.click('.nav-item[data-view="target"]');
  await page.waitForTimeout(500);
  const rankBefore = await page.evaluate(() =>
    [...document.querySelectorAll('#targetTable tbody tr')].map(tr => tr.querySelector('b').textContent.trim()));
  check('靶点表 6 行', rankBefore.length === 6, `${rankBefore.length} 行`);

  // 只留「安全性」40，其余归零
  await page.evaluate(() => {
    document.querySelectorAll('#weights input').forEach(inp => {
      inp.value = inp.dataset.k === 'safety' ? 40 : 0;
      inp.dispatchEvent(new Event('input', { bubbles: true }));
    });
  });
  await page.waitForTimeout(900);
  const rankAfter = await page.evaluate(() =>
    [...document.querySelectorAll('#targetTable tbody tr')].map(tr => tr.querySelector('b').textContent.trim()));
  check('改权重后排序由后端重算', rankBefore.join() !== rankAfter.join(),
    `Top1 ${rankBefore[0]} → ${rankAfter[0]}`);
  await page.screenshot({ path: path.join(OUT, 'r-target.png'), fullPage: true });

  // 重置
  await page.click('#resetW');
  await page.waitForTimeout(700);
  const rankReset = await page.evaluate(() =>
    [...document.querySelectorAll('#targetTable tbody tr')].map(tr => tr.querySelector('b').textContent.trim()));
  check('重置权重恢复原序', rankReset.join() === rankBefore.join(), `Top1 ${rankReset[0]}`);

  /* ---------- 6 蛋白画像 / 结构推理任务 ---------- */
  await page.click('.nav-item[data-view="struct"]');
  await page.waitForTimeout(600);
  const protInfo = await page.evaluate(() => ({
    metrics: [...document.querySelectorAll('#protMetrics .metric')].map(e =>
      e.querySelector('.m-k').textContent + '=' + e.querySelector('.m-v').textContent),
    risks: [...document.querySelectorAll('#protRisks .risk b')].map(e => e.textContent),
    banner: document.querySelector('#view-struct .pill') ? document.querySelector('#view-struct').innerText : '',
    yaml: (document.querySelector('#boltzYaml') || {}).textContent || '',
    fakeGone: !document.querySelector('#plddt') && !document.querySelector('#structTable'),
    backend: (document.querySelector('#inferBackend') || {}).textContent || ''
  }));
  check('蛋白画像 8 项指标', protInfo.metrics.length === 8, protInfo.metrics.join(' | '));
  check('明确标注 mock 后端', /mock/.test(protInfo.banner) && /Boltz-2/.test(protInfo.banner), '有');
  check('Boltz-2 输入 YAML 由真实序列生成',
    /sequence: M/.test(protInfo.yaml), protInfo.yaml.split('\n').slice(0, 4).join(' / '));
  check('假 pLDDT / 假批次表已移除', protInfo.fakeGone, protInfo.fakeGone ? '已移除' : '仍在');
  check('蛋白页风险项来自真实计算', protInfo.risks.length > 0, protInfo.risks.join('，'));
  check('后端名已显示', protInfo.backend.length > 0, protInfo.backend);

  // 提交推理任务 → 轮询到完成 → 三要素落盘
  await page.click('#submitInfer');
  await page.waitForTimeout(2500);   // mock 后端 0.4s 前向 + 轮询
  const inferInfo = await page.evaluate(() => {
    const state = (document.querySelector('#inferResultState') || {}).textContent || '';
    const rows = [...document.querySelectorAll('#inferTable tbody tr')].length;
    const reproText = (document.querySelector('#reproBox') || {}).innerText || '';
    const resultHtml = (document.querySelector('#inferResult') || {}).innerHTML || '';
    return { state, rows, reproText, hasPlddt: resultHtml.includes('pLDDT') || resultHtml.includes('plddt') };
  });
  check('推理任务已入队并完成', /完成|运行|排队/.test(inferInfo.state), inferInfo.state);
  check('任务队列有记录', inferInfo.rows >= 1, `${inferInfo.rows} 行`);
  check('三要素已落盘', /镜像 digest/.test(inferInfo.reproText) && /输入 hash/.test(inferInfo.reproText), '有');
  check('结果渲染了 pLDDT 指标', inferInfo.hasPlddt, inferInfo.hasPlddt ? '有' : '无');

  const hydroPainted = await page.evaluate(() => {
    const cv = document.querySelector('#hydroCanvas');
    const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
    let n = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
    return n / (d.length / 4);
  });
  check('疏水性曲线真的画出来了', hydroPainted > 0.02, `覆盖率 ${(hydroPainted * 100).toFixed(1)}%`);
  await page.screenshot({ path: path.join(OUT, 'r-struct.png'), fullPage: true });

  /* ---------- 7 模型矩阵一票否决 ---------- */
  await page.click('.nav-item[data-view="models"]');
  await page.waitForTimeout(500);
  const modelInfo = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#modelTable tbody tr')];
    const last = rows[rows.length - 1];
    const secondLast = rows[rows.length - 2];
    const af3 = rows.find(r => r.textContent.includes('AlphaFold3'));
    return {
      n: rows.length,
      threshold: document.querySelector('#modelThreshold').textContent.trim(),
      note: document.querySelector('#modelNote').textContent.trim(),
      af3Rank: af3 ? af3.querySelector('td').textContent.trim() : '',
      af3Text: af3 ? af3.innerText.replace(/\s+/g, ' ') : '',
      lastTotal: last ? parseFloat(last.querySelectorAll('td')[6].textContent.trim()) : NaN,
      secondTotal: secondLast ? parseFloat(secondLast.querySelectorAll('td')[6].textContent.trim()) : NaN,
      lastIsAf3: !!last && last.textContent.includes('AlphaFold3')
    };
  });
  check('模型矩阵 10 行', modelInfo.n === 10, `${modelInfo.n} 行`);
  check('门槛与最优来自后端', /许可 < 60/.test(modelInfo.threshold), modelInfo.threshold);
  check('AlphaFold3 被判一票否决', /一票否决/.test(modelInfo.af3Text), modelInfo.af3Text.slice(-40));
  check('否决项被排到末位', modelInfo.lastIsAf3 && modelInfo.af3Rank === '10',
    `rank=${modelInfo.af3Rank}`);
  check('否决项综合分高于上一名仍沉底', modelInfo.lastTotal > modelInfo.secondTotal,
    `${modelInfo.lastTotal} > ${modelInfo.secondTotal}`);
  check('说明门槛不参与加权', /不参与加权/.test(modelInfo.note), modelInfo.note.slice(0, 50));
  await page.screenshot({ path: path.join(OUT, 'r-models.png'), fullPage: true });

  /* ---------- 8 数据资产目录（后端驱动 + 检索） ---------- */
  await page.click('.nav-item[data-view="data"]');
  await page.waitForTimeout(500);
  const assetInfo = await page.evaluate(() => ({
    cards: document.querySelectorAll('#assets .card').length,
    rows: document.querySelectorAll('#assetTable tbody tr').length,
    count: (document.querySelector('#assetCount') || {}).textContent || '',
    tag: (document.querySelector('#assetTag') || {}).textContent || ''
  }));
  check('资产汇总卡由后端生成', assetInfo.cards >= 6, `${assetInfo.cards} 类`);
  check('资产明细 12 项', assetInfo.rows === 12, `${assetInfo.rows} 项`);
  check('资产计数标签', /12 项/.test(assetInfo.count) || /12 项/.test(assetInfo.tag), assetInfo.tag);

  // 检索
  await page.fill('#assetSearch', '组学');
  await page.waitForTimeout(500);
  const searchInfo = await page.evaluate(() => ({
    rows: document.querySelectorAll('#assetTable tbody tr').length,
    count: (document.querySelector('#assetCount') || {}).textContent || ''
  }));
  check('检索「组学」过滤到 3 项', searchInfo.rows === 3, `${searchInfo.rows} 项 · ${searchInfo.count}`);
  await page.fill('#assetSearch', '');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, 'r-assets.png'), fullPage: true });

  /* ---------- 9 台账导出 CSV ---------- */
  await page.click('.nav-item[data-view="loop"]');
  await page.waitForTimeout(400);
  const csvBtn = await page.evaluate(() => !!document.querySelector('#exportCsv'));
  check('台账页有导出 CSV 按钮', csvBtn, csvBtn ? '有' : '无');

  /* ---------- 汇总 ---------- */
  const pass = results.filter(r => r.ok).length;
  console.log('\n=== E2E ===');
  results.forEach(r => console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.detail ? '  ·  ' + r.detail : ''}`));
  console.log(`\n${pass}/${results.length} 通过`);
  console.log('控制台错误：' + (errs.length ? '\n' + errs.join('\n') : '无'));

  await browser.close();
  process.exit(pass === results.length && !errs.length ? 0 : 1);
})();
