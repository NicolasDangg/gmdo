/* gmdo landing: every number below comes from window.GMDO (site/data.js), built from a redacted export. */
(() => {
  const D = window.GMDO;
  const $ = (s, r = document) => r.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/\p{Extended_Pictographic}\uFE0F?/gu, '').trim().replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmt = (n) => Number(n).toLocaleString('en-US');
  const usd = (n) => '$' + Number(n).toFixed(2);
  const STEP = 0.016;
  const estSteps = (rows) => 9 + Math.floor(rows / 20) * 2;          // same formula as extract.py
  const termKey = (t) => (t || '').replace(/\s+/g, '');

  if (!D) return;

  /* ---------- hero: the agent reads a course row by row; rows stream into records.csv ---------- */
  (() => {
    const stage = $('.stage');
    if (!stage) return;
    const rowsEl = $('#st-rows'), csv = $('#st-csv'), docs = $('#st-docs'), status = $('#st-status');
    const url = $('#st-url'), title = $('#st-course'), cursor = $('#st-cursor'), browser = $('.pane.browser');
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const tick = '<svg class="ok-ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3 3 7-7" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
    const fileIco = '<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 1.5h6.5L13 5v9.5H3z M9.5 1.5V5H13" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>';
    const sleep = (ms) => new Promise((r) => setTimeout(r, reduce ? 0 : ms));
    const courses = (D.stage && D.stage.length) ? D.stage : [{
      id: '', label: D.sample.course, listed: D.sample.rows.length,
      rows: D.sample.rows.map((r) => ({ key: r.record_key, name: r.assignment_name, score: r.score, out_of: r.out_of })) }];
    const docNames = D.doc_names && D.doc_names.length ? D.doc_names : ['handout.pdf', 'essay-final.docx', 'practical-notes.pdf'];
    let lines = 0, docN = 0;
    const shortKey = (k) => String(k || '').replace(/^canvas:/, '');
    const scoreText = (r) => (r.score ?? '–') + (r.out_of ? ' / ' + r.out_of : '');

    csv.innerHTML = '<div class="l h"><span>record_key, assignment_name, score, out_of</span><span>check</span></div>';

    function moveCursor(el) {
      cursor.style.transform = `translate(${el.offsetLeft + el.offsetWidth - 34}px, ${el.offsetTop + el.offsetHeight / 2 - 4}px)`;
    }
    function rel(el) {
      const a = el.getBoundingClientRect(), s = stage.getBoundingClientRect();
      return { x: a.left - s.left, y: a.top - s.top, w: a.width, h: a.height };
    }
    async function fly(el, r) {
      if (reduce) return;
      const p = document.createElement('div');
      p.className = 'packet';
      p.textContent = scoreText(r) + '  ' + String(r.name || '').slice(0, 18);
      stage.appendChild(p);
      const from = rel(el), to = rel(csv);
      const x0 = from.x + from.w - 140, y0 = from.y + 2;
      const x1 = to.x + 12, y1 = to.y + Math.min(to.h - 30, 26 + Math.min(lines, 9) * 18);
      await p.animate([
        { transform: `translate(${x0}px, ${y0}px) scale(.9)`, opacity: 0 },
        { transform: `translate(${x0 + 20}px, ${y0}px) scale(1)`, opacity: 1, offset: 0.15 },
        { transform: `translate(${x1}px, ${y1}px) scale(1)`, opacity: 1, offset: 0.85 },
        { transform: `translate(${x1}px, ${y1}px) scale(.96)`, opacity: 0 },
      ], { duration: 760, easing: 'cubic-bezier(.22,1,.36,1)' }).finished.catch(() => {});
      p.remove();
    }
    function appendLine(r) {
      const l = document.createElement('div');
      l.className = 'l';
      l.innerHTML = `<span>${esc(shortKey(r.key))}, ${esc(r.name)}, ${esc(r.score ?? '')}, ${esc(r.out_of ?? '')}</span><span>${tick}</span>`;
      csv.appendChild(l);
      lines++;
      while (csv.children.length > 11) csv.children[1].remove();      // keep the header row
    }
    function addDoc() {
      const d = document.createElement('span');
      d.className = 'doc';
      d.innerHTML = fileIco + esc(String(docNames[docN++ % docNames.length]).slice(0, 26));
      docs.appendChild(d);
      while (docs.querySelectorAll('.doc').length > 3) docs.querySelector('.doc').remove();
    }
    async function play(c, n) {
      url.textContent = `canvas.your-school.edu/courses/${c.id || '…'}/grades`;
      title.textContent = `Grades · ${c.label}`;
      const rows = c.rows.slice(0, 8);
      rowsEl.innerHTML = rows.map((r) => `<div class="g-row"><span>${esc(r.name)}</span><span>${esc(scoreText(r))}</span></div>`).join('');
      const els = [...rowsEl.children];
      for (let i = 0; i < els.length; i++) {
        const done = Math.round((i + 1) / els.length * c.listed);
        els[i].classList.add('reading');
        moveCursor(els[i]);
        status.innerHTML = `<span>Run ${n} · ${esc(c.label)}</span><b>${done} / ${c.listed} rows</b>`;
        await sleep(420);
        await fly(els[i], rows[i]);
        appendLine(rows[i]);
        els[i].classList.replace('reading', 'done');
      }
      addDoc();
      status.innerHTML = `<span>${esc(c.label)}: ${c.listed} of ${c.listed} rows</span><b>${tick} matches Canvas</b>`;
      await sleep(1600);
    }
    async function loop() {
      let n = 1;
      do {
        for (const c of courses) {
          while (document.hidden || !visible) await new Promise((r) => setTimeout(r, 400));
          await play(c, n++);
          if (reduce) return;
        }
      } while (!reduce);
    }
    let visible = true;
    if ('IntersectionObserver' in window) new IntersectionObserver(([e]) => (visible = e.isIntersecting)).observe(stage);
    document.fonts?.ready.then(loop) ?? loop();
  })();
  const inScope = D.courses.filter((c) => c.note !== 'term not selected' && c.listed > 0);

  /* ---------- the live thing: a gmdo command and what it would do ---------- */
  const input = $('#cmd'), out = $('#answer'), caret = $('.typed-line .caret');
  const portalLine = `Portal: ${D.totals.courses} courses, ${fmt(D.courses.reduce((a, c) => a + (c.listed || 0), 0))} assignments, ${D.totals.docs} documents (${D.totals.doc_mb} MB)`;

  function answer(raw) {
    const words = raw.trim().split(/\s+/).filter(Boolean);
    if (!words.length) return '<span class="p">Type a command, for example gmdo export</span>';
    if (words[0] !== 'gmdo') return `<span class="warn">${esc(words[0])}: not gmdo. Try gmdo export</span>`;
    const cmd = words[1] || '';
    const flag = (f) => words.includes(f);
    const val = (f) => { const i = words.indexOf(f); return i > -1 ? (words[i + 1] || '').replace(/"/g, '') : null; };
    if (!cmd || cmd === '--help') return 'Commands: setup, export, showcase, status, runs';
    if (cmd === 'setup') return 'Opening a TinyFish browser on your school’s Canvas sign-in page …\nSign in there yourself. Nothing you type passes through gmdo.\n<span class="ok">Saved 55 cookies to profile gmdo-canvas. No password was stored.</span>';
    if (cmd === 'status') return `last export ${D.rerun ? 'rerun' : 'first run'} · ${fmt(D.totals.records)} records · ${D.totals.docs} documents · courses complete ${inScope.filter((c) => c.complete).length}/${inScope.length}`;
    if (cmd === 'runs') return inScope.slice(0, 4).map((c) => `COMPLETED  steps ${String(c.steps ?? '-').padStart(3)}  agent.tinyfish.ai/runs/${c.run || '…'}…`).join('\n');
    if (cmd === 'showcase') return `Showcase written to showcase/ (${fmt(D.totals.records)} records, ${D.totals.courses} courses, ${D.totals.docs} documents)\n<span class="ok">${D.terms_checked ? fmt(D.terms_checked) + ' personal terms checked, none left.' : 'Every personal term checked, none left.'}</span>`;
    if (cmd !== 'export') return `<span class="warn">gmdo: no command “${esc(cmd)}”. Try export, showcase, status, runs, setup.</span>`;

    const terms = val('--terms');
    const wanted = terms ? new Set(terms.split(',').map(termKey)) : null;
    const pool = D.courses.filter((c) => c.listed > 0 && (!wanted || wanted.has(termKey(c.term))));
    const full = flag('--full');
    const changed = full ? pool : pool.filter((c) => !c.complete);    // after the first export nothing has changed
    const est = changed.reduce((a, c) => a + estSteps(c.listed), 0) * STEP;
    const lines = [portalLine, `Changed since last export: ${changed.length} course(s) → agent runs (est. ~${usd(est)})`];
    if (flag('--dry-run')) return lines.join('\n');
    if (!changed.length) {
      lines.push('', `${fmt(D.totals.records)} records · courses complete ${pool.filter((c) => c.complete).length}/${pool.length} · added 0 · changed 0 · removed 0`,
        `documents: ${D.totals.docs} unchanged`, '<span class="ok">agent: 0 runs, 0 steps (~$0.00)</span>');
    } else {
      const steps = changed.reduce((a, c) => a + (c.steps || estSteps(c.listed)), 0);
      lines.push(`Agent: ${changed.length} run(s) submitted as a batch`, '',
        `${fmt(pool.reduce((a, c) => a + (c.read || 0), 0))} records · courses complete ${changed.length}/${pool.length}`,
        `<span class="ok">agent: ${changed.length} runs, ~${steps} steps (~${usd(steps * STEP)})</span>`);
    }
    return lines.join('\n');
  }
  function render() {
    out.innerHTML = '<code>' + answer(input.value) + '</code>';
    // the caret block follows the text
    const m = document.createElement('span');
    m.style.cssText = 'position:absolute;visibility:hidden;white-space:pre;font:inherit;letter-spacing:inherit';
    m.textContent = input.value.slice(0, input.selectionStart ?? input.value.length);
    input.parentNode.appendChild(m);
    caret.style.left = Math.min(m.offsetWidth - input.scrollLeft, input.clientWidth) + 'px';
    m.remove();
    document.querySelectorAll('.examples button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.cmd === input.value.trim())));
  }
  if (input) {
    ['input', 'keyup', 'click', 'focus'].forEach((e) => input.addEventListener(e, render));
    document.querySelectorAll('.examples button').forEach((b) => b.addEventListener('click', () => { input.value = b.dataset.cmd; render(); input.focus(); }));
    document.fonts?.ready.then(render); render();
  }

  /* ---------- mockups ---------- */
  const tiles = $('#tiles');
  if (tiles) tiles.innerHTML = inScope.filter((c) => /2026/.test(c.term)).slice(0, 6).map((c) => `<span>${esc(c.label)}</span>`).join('');

  const runs = $('#runs tbody');
  if (runs) {
    const rows = inScope.slice(0, 7);
    runs.innerHTML = rows.map((c, i) => `<tr${i === 1 ? ' class="sel"' : ''}><td>${esc(c.label)}</td><td class="r">${c.read ?? '–'}</td><td class="r">${c.listed}</td><td class="r">${c.steps ?? '–'}</td><td class="key">${c.run ? esc(c.run) + '…' : '–'}</td></tr>`).join('');
    const steps = inScope.reduce((a, c) => a + (c.steps || 0), 0);
    $('#runs-sum').textContent = `${inScope.length} runs · ${fmt(steps)} steps · ${usd(steps * STEP)}`;
  }

  const recs = $('#records tbody');
  if (recs) {
    recs.innerHTML = D.sample.rows.map((r, i) => `<tr${i === 2 ? ' class="sel"' : ''}><td class="key">${esc(r.record_key)}</td><td>${esc(r.assignment_name)}</td><td class="r">${esc((r.submitted_at || '').slice(0, 10)) || '–'}</td><td class="r">${r.score ?? '–'}</td><td class="r">${r.out_of ?? '–'}</td><td>${r.score_verified === true ? 'yes' : r.score_verified === false ? 'no' : '–'}</td></tr>`).join('');
    $('#rec-title').textContent = `records.csv · ${D.sample.course}`;
    $('#rec-sum').textContent = `${fmt(D.totals.records)} rows · ${fmt(D.totals.verified)} scores matched Canvas`;
  }

  const check = $('#checktable tbody');
  if (check) {
    const byYear = {};
    D.courses.filter((c) => c.listed > 0).forEach((c) => (byYear[c.term] ||= []).push(c));
    const years = Object.keys(byYear).sort().reverse();
    check.innerHTML = years.map((y, yi) => (yi ? '<tr class="gap"><td colspan="4"></td></tr>' : '') + byYear[y].map((c, i) => {
      const skipped = c.note === 'term not selected';
      const result = skipped ? 'Not in this export' : c.complete ? 'Complete' : 'Read again';
      const rows = skipped ? `– / ${c.listed}` : `${c.read ?? '–'} / ${c.listed}`;
      return `<tr><td class="yr">${i ? '' : esc(y)}</td><td class="subj">${esc(c.label)}</td><td class="r rows">${rows}</td><td class="r">${result}</td></tr>`;
    }).join('')).join('');
  }

  const docsLine = $('#sw-docs');
  if (docsLine) docsLine.firstChild.textContent = `${D.totals.docs} files, ${D.totals.doc_mb} MB: your own uploads and every attachment on your submissions, checked byte for byte. `;
  const rerunLine = $('#sw-rerun');
  if (rerunLine && D.rerun) rerunLine.textContent = `The second run sent ${D.rerun.sent} of ${inScope.length} courses to the agent and cost ${usd(D.rerun.cost)}.`;
  const fullLine = $('#sw-full');
  if (fullLine) fullLine.firstChild.textContent = `Every course goes back to the agent: ${inScope.length} runs, about ${usd(inScope.reduce((a, c) => a + estSteps(c.listed), 0) * STEP)}. `;
})();

/* ---------- switches ---------- */
document.querySelectorAll('.sw').forEach((band) => {
  const t = band.querySelector('.toggle');
  const set = (on) => { band.dataset.on = String(on); t.setAttribute('aria-checked', String(on)); };
  band.addEventListener('click', (e) => { if (e.target.closest('a')) return; set(band.dataset.on !== 'true'); });
  t.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); set(band.dataset.on !== 'true'); } });
});

/* ---------- copy buttons ---------- */
document.querySelectorAll('[data-copy]').forEach((b) => b.addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = 'Copied'; setTimeout(() => (b.textContent = 'Copy'), 1400); } catch { b.textContent = 'Select and copy'; }
}));

/* ---------- reveal once; never leaves content hidden ---------- */
(() => {
  const els = document.querySelectorAll('[data-reveal]');
  els.forEach((el) => [...el.children].forEach((c, i) => c.style.setProperty('--i', i)));
  if (!('IntersectionObserver' in window)) { els.forEach((el) => el.classList.add('is-in')); return; }
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); } }), { rootMargin: '0px 0px -10% 0px' });
  els.forEach((el) => io.observe(el));
  addEventListener('load', () => setTimeout(() => els.forEach((el) => el.classList.add('is-in')), 4000));
})();

/* ---------- colour by chapter: the header takes the ground and ink of what is under it ---------- */
(() => {
  const chapters = document.querySelectorAll('[data-ground]');
  const root = document.documentElement.style;
  const head = document.querySelector('.top');
  function update() {
    const y = head.offsetHeight / 2;
    for (const c of chapters) {
      const r = c.getBoundingClientRect();
      if (r.top <= y && r.bottom > y) {
        root.setProperty('--header-ground', c.dataset.ground);
        root.setProperty('--header-ink', c.dataset.ink);
        return;
      }
    }
  }
  addEventListener('scroll', update, { passive: true }); addEventListener('resize', update); update();
})();

/* ---------- mobile menu ---------- */
(() => {
  const btn = document.querySelector('.menu-word'), menu = document.getElementById('menu');
  if (!btn || !menu) return;
  const close = () => { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
  btn.addEventListener('click', () => { const open = menu.hidden; menu.hidden = !open; btn.setAttribute('aria-expanded', String(open)); if (open) menu.querySelector('a').focus(); });
  menu.addEventListener('click', (e) => { if (e.target.closest('a')) close(); });
  addEventListener('keydown', (e) => { if (e.key === 'Escape' && !menu.hidden) { close(); btn.focus(); } });
})();
