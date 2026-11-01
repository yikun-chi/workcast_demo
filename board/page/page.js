// Charts for the forecast board: plain SVG and HTML, no libraries. Every number comes from the JSON block in the page.
(function () {
  const D = JSON.parse(document.getElementById('board-data').textContent);
  const NS = 'http://www.w3.org/2000/svg';
  const $ = s => document.querySelector(s);
  const svg = (t, a, p) => { const e = document.createElementNS(NS, t); for (const k in a || {}) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; };
  const el = (t, c, txt, p) => { const e = document.createElement(t); if (c) e.className = c; if (txt != null) e.textContent = txt; if (p) p.appendChild(e); return e; };
  const COLOR = { combined: 'var(--c-combined)', astra: 'var(--c-astra)', workcast: 'var(--c-sim)', damped_trend: 'var(--c-damped)', damped_12w: 'var(--c-damped)', damped_full: 'var(--c-damped)' };
  const color = k => COLOR[k] || 'var(--c-other)';
  const L = D.labels;
  const pct = x => x == null ? '–' : x.toFixed(1) + '%';
  const tok = x => x >= 1e15 ? (x / 1e15).toFixed(1) + 'Q' : x >= 1e12 ? (x / 1e12).toFixed(x >= 1e13 ? 0 : 1) + 'T' : x >= 1e9 ? (x / 1e9).toFixed(x >= 1e10 ? 0 : 1) + 'B' : x >= 1e6 ? (x / 1e6).toFixed(0) + 'M' : String(Math.round(x));
  const axisTok = x => tok(x).replace('.0', '');
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const parts = s => s.split('-').map(Number);
  const dayMon = s => { const [, m, d] = parts(s); return d + ' ' + MONTHS[m - 1]; };
  const full = s => { const [y, m, d] = parts(s); return d + ' ' + MONTHS[m - 1] + ' ' + y; };
  const reduced = () => window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- theme: dark by default, as on the main site
  const themeBtn = $('#theme');
  if (themeBtn) themeBtn.addEventListener('click', () => {
    const dark = document.documentElement.classList.toggle('dark');
    try { localStorage.setItem('board-theme', dark ? 'dark' : 'light'); } catch (e) { /* storage may be blocked */ }
  });

  // ---- one tooltip for the whole page; labels always go in through textContent
  const tip = el('div', '', null, document.body); tip.id = 'tip'; tip.setAttribute('role', 'status');
  function showTip(x, y, head, rows, note) {
    tip.textContent = '';
    if (head) el('div', 'h', head, tip);
    (rows || []).forEach(r => {
      const row = el('div', 'r', null, tip);
      if (r.color) el('i', '', null, row).style.background = r.color;
      el('b', '', r.value, row); el('span', '', r.label, row);
    });
    if (note) el('div', 'n', note, tip);
    tip.classList.add('on');
    const b = tip.getBoundingClientRect();
    let left = x + 14, top = y + 14;
    if (left + b.width > innerWidth - 8) left = x - b.width - 14;
    if (top + b.height > innerHeight - 8) top = y - b.height - 14;
    tip.style.left = Math.max(8, left) + 'px'; tip.style.top = Math.max(8, top) + 'px';
  }
  const hideTip = () => tip.classList.remove('on');
  addEventListener('scroll', hideTip, { passive: true });

  function pills(host, opts, value, on) {
    const btns = opts.map(o => {
      const b = el('button', 'pill', o.label, host); b.type = 'button';
      b.addEventListener('click', () => { if (!b.disabled) on(o.v); });
      return { b, o };
    });
    const api = {
      set(v) { btns.forEach(x => x.b.setAttribute('aria-pressed', String(x.o.v === v))); },
      disable(f) { btns.forEach(x => { x.b.disabled = f(x.o.v); }); },
    };
    api.set(value);
    return api;
  }
  function watch(node, draw) {
    let w = 0;
    new ResizeObserver(es => { const n = Math.round(es[0].contentRect.width); if (n && n !== w) { w = n; draw(n); } }).observe(node);
  }
  function ticks(max, n) {
    const raw = max / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag;
    const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag;
    const out = []; for (let v = 0; v <= max + step * 0.001; v += step) out.push(v);
    if (out[out.length - 1] < max) out.push(out[out.length - 1] + step);
    return out;
  }
  function pathOf(xs, ys) {
    let d = '', pen = false;
    xs.forEach((x, i) => { const y = ys[i]; if (y == null) { pen = false; return; } d += (pen ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1); pen = true; });
    return d;
  }

  // ---- market: weekly tokens with the live forecast appended
  function market() {
    const host = $('#c-market'); if (!host || !D.market) return;
    const M = D.market, F = D.forecast;
    let drawn = false;
    watch(host, W => {
      host.textContent = '';
      const H = W < 560 ? 220 : 300, m = { t: 14, r: W < 560 ? 44 : 64, b: 26, l: 44 };
      const s = svg('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, height: H, tabindex: 0, role: 'img', 'aria-label': D.market_alt }, host);
      const n = M.tokens.length + (F ? F.tokens.length : 0);
      const all = M.tokens.concat(F ? F.tokens : []);
      const T = ticks(Math.max(...all), 4), top = T[T.length - 1];
      const X = i => m.l + i / (n - 1) * (W - m.l - m.r), Y = v => H - m.b - v / top * (H - m.t - m.b);
      const g = svg('g', { class: 'grid' }, s);
      T.forEach(v => { svg('line', { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v) }, g); svg('text', { x: m.l - 8, y: Y(v) + 4, 'text-anchor': 'end' }, s).textContent = v ? tok(v) : '0'; });
      const weeks = M.weeks.concat(F ? F.weeks : []);
      let last = -99;
      weeks.forEach((w, i) => { const [y, mo, d] = parts(w); if (d <= 7 && (mo - 1) % 3 === 0 && X(i) - last > 60) { last = X(i); svg('text', { x: X(i), y: H - 6, 'text-anchor': 'middle' }, s).textContent = MONTHS[mo - 1] + ' ' + String(y).slice(2); } });
      const xs = M.tokens.map((_, i) => X(i)), ys = M.tokens.map(Y), base = Y(0);
      svg('path', { d: pathOf(xs, ys) + `L${xs[xs.length - 1]} ${base}L${xs[0]} ${base}Z`, fill: 'var(--c-combined)', style: 'fill-opacity:var(--wash)' }, s);
      const line = svg('path', { d: pathOf(xs, ys), fill: 'none', stroke: 'var(--c-combined)', 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', pathLength: 1 }, s);
      if (!drawn && !reduced()) { line.style.strokeDasharray = '1'; line.style.strokeDashoffset = '1'; line.getBoundingClientRect(); line.style.transition = 'stroke-dashoffset 1.1s ease-out'; line.style.strokeDashoffset = '0'; drawn = true; }
      const k = M.tokens.length - 1;
      if (F) {
        const fx = F.tokens.map((_, i) => X(k + 1 + i)), fy = F.tokens.map(Y);
        svg('path', { d: `M${xs[k]} ${ys[k]}` + pathOf(fx, fy).replace('M', 'L'), fill: 'none', stroke: 'var(--c-combined)', 'stroke-width': 2, 'stroke-dasharray': '2 5', 'stroke-linecap': 'round' }, s);
        svg('circle', { cx: fx[fx.length - 1], cy: fy[fy.length - 1], r: 4, fill: 'var(--c-combined)', stroke: 'var(--panel)', 'stroke-width': 2 }, s);
        svg('text', { x: fx[fx.length - 1] - 10, y: fy[fy.length - 1] + 2, 'text-anchor': 'end', class: 'strong' }, s).textContent = 'Forecast';
      }
      svg('circle', { cx: xs[k], cy: ys[k], r: 4, fill: 'var(--c-combined)', stroke: 'var(--panel)', 'stroke-width': 2 }, s);
      if (!F) svg('text', { x: xs[k] + 8, y: ys[k] + 4, class: 'strong' }, s).textContent = tok(M.tokens[k]);
      const cross = svg('line', { y1: m.t, y2: H - m.b, stroke: 'var(--pill-hv)', 'stroke-width': 1, opacity: 0 }, s);
      const mark = svg('circle', { r: 4, fill: 'var(--c-combined)', stroke: 'var(--panel)', 'stroke-width': 2, opacity: 0 }, s);
      const at = (i, cx, cy) => {
        const isF = i >= M.tokens.length, v = all[i];
        cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('opacity', 1);
        mark.setAttribute('cx', X(i)); mark.setAttribute('cy', Y(v)); mark.setAttribute('opacity', 1);
        showTip(cx, cy, 'Week of ' + full(weeks[i]), [{ color: 'var(--c-combined)', value: tok(v), label: isF ? 'simulation forecast' : 'tokens, all apps' }]);
      };
      const clear = () => { cross.setAttribute('opacity', 0); mark.setAttribute('opacity', 0); hideTip(); };
      s.addEventListener('pointermove', e => {
        const r = s.getBoundingClientRect();
        const i = Math.max(0, Math.min(n - 1, Math.round((e.clientX - r.left - m.l) / (W - m.l - m.r) * (n - 1))));
        at(i, e.clientX, e.clientY);
      });
      s.addEventListener('pointerleave', clear);
      let ki = k;
      s.addEventListener('keydown', e => {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        e.preventDefault(); ki = Math.max(0, Math.min(n - 1, ki + (e.key === 'ArrowLeft' ? -1 : 1)));
        const r = s.getBoundingClientRect(); at(ki, r.left + X(ki), r.top + Y(all[ki]));
      });
      s.addEventListener('blur', clear);
    });
  }

  // ---- ranked error bars; the set and the horizon also switch the table and the text below
  function leaderboard() {
    const host = $('#c-rank'); if (!host) return;
    const state = { set: 'heldout', h: 'mean' };
    const SETS = D.retro.sets, ROW = () => (host.clientWidth < 560 ? 44 : 32), rows = {};
    const hz = [{ v: 'mean', label: 'Mean' }, { v: '1', label: '1 week' }, { v: '2', label: '2 weeks' }, { v: '4', label: '4 weeks' }, { v: '8', label: '8 weeks' }];
    const c = $('#ctl-rank');
    const ps = pills(c, D.set_labels.map(([v, label]) => ({ v, label })), state.set, v => { state.set = v; if (state.h === '8' && !has8()) state.h = 'mean'; draw(); });
    el('span', 'gap', null, c);
    const ph = pills(c, hz, state.h, v => { state.h = v; draw(); });
    const has8 = () => Object.values(SETS[state.set].mean).some(v => v['8'] != null);
    function draw() {
      ps.set(state.set); ph.set(state.h); ph.disable(v => v === '8' && !has8());
      document.querySelectorAll('[data-set]').forEach(n => n.classList.toggle('is-hidden', n.dataset.set !== state.set));
      const key = state.h === 'mean' ? 'mean' : state.h, mean = SETS[state.set].mean;
      const order = Object.keys(mean).filter(k => mean[k][key] != null).sort((a, b) => mean[a][key] - mean[b][key]);
      const max = Math.max(...order.map(k => mean[k][key])) || 1, rh = ROW();
      Object.keys(rows).forEach(k => { if (!mean[k]) { rows[k].root.remove(); delete rows[k]; } });
      order.forEach((k, i) => {
        if (!rows[k]) {
          const root = el('div', 'lb' + (k === 'combined' ? ' us' : ''), null, host); root.tabIndex = 0;
          el('div', 'nm', L[k] || k, root);
          const tr = el('div', 'tr', null, root), bar = el('div', 'bar', null, tr), val = el('span', '', '', tr);
          bar.style.background = color(k); bar.style.width = '0';
          const show = (x, y) => {
            const m = SETS[state.set].mean[k];
            showTip(x, y, L[k] || k, ['1', '2', '4', '8'].filter(h => m[h] != null).map(h => ({ value: pct(m[h]), label: h + (h === '1' ? ' week ahead' : ' weeks ahead') })).concat([{ value: pct(m.mean), label: 'mean of 1, 2 and 4 weeks' }]), D.inputs[k]);
          };
          root.addEventListener('pointermove', e => show(e.clientX, e.clientY));
          root.addEventListener('pointerleave', hideTip);
          root.addEventListener('focus', () => { const r = root.getBoundingClientRect(); show(r.left + 40, r.bottom); });
          root.addEventListener('blur', hideTip);
          rows[k] = { root, bar, val };
        }
        const r = rows[k];
        r.root.classList.remove('is-hidden');
        r.root.style.top = (i * rh) + 'px'; r.root.style.height = rh + 'px';
        r.val.textContent = pct(mean[k][key]);
        const room = host.clientWidth < 560 ? host.clientWidth - 60 : host.clientWidth - 240 - 12 - 60;
        requestAnimationFrame(() => { r.bar.style.width = (mean[k][key] / max * Math.max(room, 40)).toFixed(1) + 'px'; });
      });
      Object.keys(rows).forEach(k => { if (mean[k] && !order.includes(k)) rows[k].root.classList.add('is-hidden'); });
      host.style.height = (order.length * rh) + 'px';
    }
    watch(host, () => draw());
  }

  // ---- error at every weekly cutoff
  function weekly() {
    const host = $('#c-weekly'); if (!host) return;
    const W_ = D.retro.weekly, keys = Object.keys(W_.series);
    const on = {}; keys.forEach(k => { on[k] = k !== 'carry_forward'; });
    let h = '1', width = 0;
    const p = pills($('#ctl-weekly'), [{ v: '1', label: '1 week' }, { v: '2', label: '2 weeks' }, { v: '4', label: '4 weeks' }, { v: '8', label: '8 weeks' }], h, v => { h = v; p.set(v); draw(width); note(); });
    const leg = $('#leg-weekly');
    keys.forEach(k => {
      const b = el('button', 'lk', null, leg); b.type = 'button'; b.setAttribute('aria-pressed', String(on[k]));
      el('i', '', null, b).style.background = color(k); b.appendChild(document.createTextNode(L[k]));
      b.addEventListener('click', () => { on[k] = !on[k]; b.setAttribute('aria-pressed', String(on[k])); draw(width); });
    });
    const noteEl = $('#note-weekly');
    function note() {
      const v = W_.series.combined[h].filter(x => x != null);
      noteEl.textContent = `Across the ${v.length} scored weeks, the combined method's ${h}-week error ranged from ${Math.min(...v).toFixed(1)}% to ${Math.max(...v).toFixed(1)}%.`;
      const tb = $('#weekly-table'); tb.textContent = '';
      const t = el('table', '', null, tb), hd = el('tr', '', null, t);
      ['Cutoff'].concat(keys.map(k => L[k])).forEach(x => el('th', '', x, hd));
      W_.cutoffs.forEach((c, i) => { const r = el('tr', '', null, t); el('td', '', full(c) + (c >= W_.heldout_from ? ' (held out)' : ''), r); keys.forEach(k => el('td', '', pct(W_.series[k][h][i]), r)); });
    }
    note();
    function draw(W) {
      if (!W) return; width = W;
      host.textContent = '';
      const Ht = W < 560 ? 260 : 340, m = { t: 22, r: 12, b: 26, l: 38 };
      const s = svg('svg', { class: 'chart', viewBox: `0 0 ${W} ${Ht}`, height: Ht, tabindex: 0, role: 'img', 'aria-label': D.weekly_alt }, host);
      const n = W_.cutoffs.length, vals = keys.flatMap(k => W_.series[k][h]).filter(x => x != null);
      const T = ticks(Math.max(...vals), 4), top = T[T.length - 1];
      const X = i => m.l + i / (n - 1) * (W - m.l - m.r), Y = v => Ht - m.b - v / top * (Ht - m.t - m.b);
      const b0 = W_.cutoffs.indexOf(W_.heldout_from);
      svg('rect', { x: X(b0) - (X(1) - X(0)) / 2, y: m.t - 18, width: W - m.r - X(b0) + (X(1) - X(0)) / 2, height: Ht - m.b - m.t + 18, fill: 'var(--band)', rx: 6 }, s);
      svg('text', { x: X(b0) - (X(1) - X(0)) / 2 + 8, y: m.t - 5, class: 'strong' }, s).textContent = 'Held-out weeks';
      svg('text', { x: m.l + 4, y: m.t - 5 }, s).textContent = W < 560 ? 'Weights fitted here' : 'Earlier weeks: weights fitted here';
      const g = svg('g', { class: 'grid' }, s);
      T.forEach(v => { svg('line', { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v) }, g); svg('text', { x: m.l - 8, y: Y(v) + 4, 'text-anchor': 'end' }, s).textContent = v + '%'; });
      let seen = -1, lastX = -99;
      W_.cutoffs.forEach((c, i) => { const mo = parts(c)[1]; if (mo !== seen) { seen = mo; if (X(i) - lastX > 34) { lastX = X(i); svg('text', { x: X(i), y: Ht - 6, 'text-anchor': 'middle' }, s).textContent = MONTHS[mo - 1]; } } });
      const xs = W_.cutoffs.map((_, i) => X(i));
      keys.slice().reverse().forEach(k => {
        if (!on[k]) return;
        const ys = W_.series[k][h].map(v => v == null ? null : Y(v));
        svg('path', { d: pathOf(xs, ys), fill: 'none', stroke: color(k), 'stroke-width': k === 'combined' ? 2.5 : 1.75, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', opacity: k === 'combined' ? 1 : .85 }, s);
      });
      const cross = svg('line', { y1: m.t, y2: Ht - m.b, stroke: 'var(--pill-hv)', 'stroke-width': 1, opacity: 0 }, s);
      const marks = svg('g', {}, s);
      const at = (i, cx, cy) => {
        cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('opacity', 1);
        marks.textContent = '';
        const rows = keys.filter(k => on[k] && W_.series[k][h][i] != null).map(k => ({ k, v: W_.series[k][h][i] })).sort((a, b) => a.v - b.v);
        rows.forEach(r => svg('circle', { cx: X(i), cy: Y(r.v), r: 4, fill: color(r.k), stroke: 'var(--panel)', 'stroke-width': 2 }, marks));
        showTip(cx, cy, 'Cutoff ' + full(W_.cutoffs[i]) + (i >= b0 ? ' · held out' : ''), rows.length ? rows.map(r => ({ color: color(r.k), value: pct(r.v), label: L[r.k] })) : [], rows.length ? '' : `The ${h}-week result for this cutoff has not elapsed.`);
      };
      const clear = () => { cross.setAttribute('opacity', 0); marks.textContent = ''; hideTip(); };
      s.addEventListener('pointermove', e => {
        const r = s.getBoundingClientRect();
        at(Math.max(0, Math.min(n - 1, Math.round((e.clientX - r.left - m.l) / (W - m.l - m.r) * (n - 1)))), e.clientX, e.clientY);
      });
      s.addEventListener('pointerleave', clear);
      let ki = n - 1;
      s.addEventListener('keydown', e => {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        e.preventDefault(); ki = Math.max(0, Math.min(n - 1, ki + (e.key === 'ArrowLeft' ? -1 : 1)));
        const r = s.getBoundingClientRect(); at(ki, r.left + X(ki), r.top + m.t + 40);
      });
      s.addEventListener('blur', clear);
    }
    watch(host, draw);
  }

  // ---- forecast against actual, one dot per app
  function scatter() {
    const host = $('#c-scatter'); if (!host) return;
    const S = D.retro.scatter, keys = Object.keys(S[0].forecast);
    const st = { m: 'combined', h: '1', c: 0 };
    const dec = v => Math.pow(10, v / 1000);
    const cm = $('#ctl-scat-m'), ch = $('#ctl-scat-h'), cc = $('#ctl-scat-c');
    const pm = pills(cm, keys.map(k => ({ v: k, label: L[k] })), st.m, v => { st.m = v; update(); });
    const ph = pills(ch, ['1', '2', '4'].map(h => ({ v: h, label: h === '1' ? '1 week' : h + ' weeks' })), st.h, v => { st.h = v; update(); });
    const pc = pills(cc, S.map((e, i) => ({ v: i, label: dayMon(e.cutoff) })), st.c, v => { st.c = v; if (!S[v].actual[st.h]) st.h = '1'; update(); });
    const out = $('#scat-err'), tb = $('#scat-table');
    let parts_ = null;
    function points() {
      const e = S[st.c], act = e.actual[st.h], f = e.forecast[st.m][st.h];
      return e.apps.map((a, i) => ({ a, i, x: dec(f[i]), y: dec(act[i]) }));
    }
    function update() {
      pm.set(st.m); ph.set(st.h); pc.set(st.c);
      ph.disable(h => !S[st.c].actual[h]);
      const e = S[st.c];
      out.textContent = `${L[st.m]}, ${st.h}-week forecast from ${full(e.cutoff)}: ${pct(e.error[st.m][st.h])} token-weighted error.`;
      const pts = points();
      if (parts_) parts_.place(pts);
      tb.textContent = '';
      const t = el('table', '', null, tb), hd = el('tr', '', null, t);
      ['App', 'Forecast', 'Actual', 'Miss'].forEach(x => el('th', '', x, hd));
      pts.slice().sort((a, b) => b.y - a.y).forEach(p => {
        const r = el('tr', '', null, t);
        el('td', '', p.a, r); el('td', '', tok(p.x), r); el('td', '', tok(p.y), r); el('td', '', ((p.x / p.y - 1) * 100).toFixed(0) + '%', r);
      });
    }
    watch(host, W => {
      host.textContent = '';
      const Ht = Math.min(W, 560), m = { t: 12, r: 14, b: 42, l: 54 };
      const s = svg('svg', { class: 'chart', viewBox: `0 0 ${W} ${Ht}`, height: Ht, role: 'img', 'aria-label': D.scatter_alt, tabindex: 0 }, host);
      // one fixed scale across every view, so a switch moves the dots and nothing else
      const every = S.flatMap(e => Object.values(e.actual).flat().concat(keys.flatMap(k => Object.values(e.forecast[k]).flat()))).map(dec);
      const lo = Math.floor(Math.log10(Math.min(...every))), hi = Math.ceil(Math.log10(Math.max(...every)));
      const X = v => m.l + (Math.log10(v) - lo) / (hi - lo) * (W - m.l - m.r), Y = v => Ht - m.b - (Math.log10(v) - lo) / (hi - lo) * (Ht - m.t - m.b);
      const g = svg('g', { class: 'grid' }, s);
      for (let d = lo; d <= hi; d++) {
        const v = Math.pow(10, d);
        svg('line', { x1: X(v), x2: X(v), y1: m.t, y2: Ht - m.b }, g); svg('line', { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v) }, g);
        svg('text', { x: X(v), y: Ht - m.b + 16, 'text-anchor': 'middle' }, s).textContent = axisTok(v);
        svg('text', { x: m.l - 8, y: Y(v) + 4, 'text-anchor': 'end' }, s).textContent = axisTok(v);
      }
      svg('text', { x: (m.l + W - m.r) / 2, y: Ht - 6, 'text-anchor': 'middle' }, s).textContent = 'Forecast tokens';
      svg('text', { x: 12, y: (m.t + Ht - m.b) / 2, 'text-anchor': 'middle', transform: `rotate(-90 12 ${(m.t + Ht - m.b) / 2})` }, s).textContent = 'Actual tokens';
      const dv = [Math.pow(10, lo), Math.pow(10, hi)];
      svg('line', { x1: X(dv[0]), y1: Y(dv[0]), x2: X(dv[1]), y2: Y(dv[1]), stroke: 'var(--pill-hv)', 'stroke-width': 1 }, s);
      const lab = svg('text', { x: X(dv[1]) - 6, y: Y(dv[1]) + 34, 'text-anchor': 'end' }, s); lab.textContent = 'On this line, forecast = actual';
      const layer = svg('g', {}, s), dots = [];
      const hl = svg('circle', { r: 7, fill: 'none', stroke: 'var(--fg)', 'stroke-width': 2, opacity: 0 }, s);
      let cur = [];
      const api = {
        place(pts) {
          cur = pts;
          pts.forEach((p, i) => {
            if (!dots[i]) { dots[i] = svg('circle', { r: 4, class: 'dot', stroke: 'var(--panel)', 'stroke-width': 1.5, cx: 0, cy: 0 }, layer); }
            dots[i].style.fill = color(st.m);
            dots[i].style.transform = `translate(${X(p.x).toFixed(1)}px,${Y(p.y).toFixed(1)}px)`;
          });
          hl.setAttribute('opacity', 0);
        },
      };
      parts_ = api; api.place(points());
      const show = (p, cx, cy) => {
        hl.setAttribute('cx', X(p.x)); hl.setAttribute('cy', Y(p.y)); hl.setAttribute('opacity', 1);
        const miss = (p.x / p.y - 1) * 100;
        showTip(cx, cy, p.a, [{ value: tok(p.x), label: 'forecast' }, { value: tok(p.y), label: 'actual' }, { value: (miss >= 0 ? '+' : '') + miss.toFixed(0) + '%', label: miss >= 0 ? 'too high' : 'too low' }]);
      };
      const clear = () => { hl.setAttribute('opacity', 0); hideTip(); };
      s.addEventListener('pointermove', e => {
        const r = s.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
        let best = null, bd = 40 * 40;
        cur.forEach(p => { const d = (X(p.x) - px) ** 2 + (Y(p.y) - py) ** 2; if (d < bd) { bd = d; best = p; } });
        if (best) show(best, e.clientX, e.clientY); else clear();
      });
      s.addEventListener('pointerleave', clear);
      let ki = -1;
      s.addEventListener('keydown', e => {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        e.preventDefault();
        const o = cur.slice().sort((a, b) => b.y - a.y);
        ki = Math.max(0, Math.min(o.length - 1, ki + (e.key === 'ArrowLeft' ? -1 : 1)));
        const r = s.getBoundingClientRect(); show(o[ki], r.left + X(o[ki].x), r.top + Y(o[ki].y));
      });
      s.addEventListener('blur', clear);
    });
    update();
  }
  [market, leaderboard, weekly, scatter].forEach(f => { try { f(); } catch (e) { console.error(f.name, e); } });
})();
function cp(b) { navigator.clipboard && navigator.clipboard.writeText(b.dataset.t); b.textContent = 'Copied'; setTimeout(() => { b.textContent = 'Share'; }, 1400); }
