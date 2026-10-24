'use strict';

const CFG = window.PSE9_CONFIG || {};
const DATA_URL = 'data/submissions.enc.json';
const TOKEN_PREFIX = 'pse9-sync:';
const CODE_KEY = 'pse9review:code';

// The review form. Keep in step with review_rubric.md and backend/Code.gs.
const FORM = {
  coi: {
    label: 'Conflict of interest',
    options: [
      ['coauthor', 'Yes, I am a co-author'],
      ['knows', 'Yes, I think I know the submitter'],
      ['none', 'No'],
    ],
  },
  criteria: [
    {
      key: 'fit', label: 'Fit with PSE',
      question: 'Is this about scientific error in the sense of the call?',
      anchors: ['Not about scientific error', 'Related; the link to error is indirect or left to infer', 'Squarely on topic'],
    },
    {
      key: 'accessibility', label: 'Interdisciplinary accessibility',
      question: 'Can someone from a different discipline understand the question, what was done or argued, and the main claim?',
      anchors: ['Only a specialist could follow it', 'Main idea comes across; parts need background the room will not have', 'Fully accessible to the whole room'],
    },
    {
      key: 'quality', label: 'Scientific quality',
      question: 'Does this work seem to be of high scientific quality?',
      anchors: ['Claim not supported, or a clear flaw', 'Plausible, with open questions', 'Convincing and careful'],
    },
    {
      key: 'novelty', label: 'Novelty and contribution',
      question: 'Does it add something: a new result, dataset, method, tool, argument or perspective?',
      anchors: ['Repeats what is known', 'Modest or incremental addition', 'Clearly new, or a fresh angle on a known problem'],
    },
  ],
  recommendation: {
    label: 'Recommendation',
    hint: 'Capacity: 12 contributed talks, up to 84 posters (42 per session, two sessions) and about 6 to 10 hackathon sessions. Poster space is not scarce, so recommend Reject only for lack of quality or fit, never for space.',
    options: [
      ['talk_top', 'Talk, top 5% of submissions'],
      ['talk', 'Talk'],
      ['poster', 'Poster'],
      ['hackathon', 'Ask to resubmit as a hackathon'],
      ['reject', 'Reject'],
    ],
  },
  confidence: {
    label: 'Confidence in this recommendation',
    options: [['low', 'Low'], ['medium', 'Medium'], ['high', 'High']],
  },
};
const SCORE_KEYS = [...FORM.criteria.map((c) => c.key), 'recommendation', 'confidence'];
const RECORD_KEYS = ['coi', ...SCORE_KEYS, 'note'];

const $ = (id) => document.getElementById(id);
function el(tag, attrs = {}, children = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else n.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c != null) n.append(c);
  return n;
}

const state = {
  reviewer: null, token: null, builtAt: null,
  fields: [], submissions: [], scores: {}, current: 0,
};

// ---------- unlocking the data ----------
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');

async function loadPackage() {
  const res = await fetch(DATA_URL, { cache: 'no-store' });
  if (!res.ok) throw new Error('Could not load the submissions file.');
  return res.json();
}

async function unlock(code, pkg) {
  const m = /^pse9-(r\d+)-/i.exec(code);
  const rid = m ? m[1].toUpperCase() : null;
  const entry = rid && pkg.keys.find((k) => k.reviewer === rid);
  if (!entry) throw new Error('Code not recognised.');
  const enc = new TextEncoder();
  const base = await crypto.subtle.importKey('raw', enc.encode(code), 'PBKDF2', false, ['deriveKey']);
  const kek = await crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: b64(entry.salt), iterations: pkg.kdf.iterations, hash: pkg.kdf.hash },
    base, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
  let raw;
  try {
    raw = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(entry.iv) }, kek, b64(entry.wrapped));
  } catch (e) {
    throw new Error('Code not recognised.');
  }
  const dataKey = await crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['decrypt']);
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(pkg.iv) }, dataKey, b64(pkg.ciphertext));
  const payload = JSON.parse(new TextDecoder().decode(plain));
  const token = hex(await crypto.subtle.digest('SHA-256', enc.encode(TOKEN_PREFIX + code)));
  return { reviewer: rid, token, payload };
}

// ---------- local storage ----------
const storeKey = () => `pse9review:${state.reviewer}:scores`;
function loadScores() {
  try { return JSON.parse(localStorage.getItem(storeKey()) || '{}'); } catch (e) { return {}; }
}
function persist() {
  try { localStorage.setItem(storeKey(), JSON.stringify(state.scores)); } catch (e) { /* storage blocked */ }
}
function remember(code) { try { localStorage.setItem(CODE_KEY, code); } catch (e) { /* ignore */ } }
function forget() { try { localStorage.removeItem(CODE_KEY); } catch (e) { /* ignore */ } }

function isComplete(rec) {
  if (!rec || !rec.coi) return false;
  if (rec.coi === 'coauthor') return true;
  return SCORE_KEYS.every((k) => rec[k]);
}

// ---------- submissions ----------
// Each reviewer has their own order (tools/build_data.py), so that every
// submission gets reviews early even if not everyone finishes.
function orderFor(payload, rid) {
  const order = payload.order && payload.order[rid];
  if (!order) return payload.submissions;
  const byId = new Map(payload.submissions.map((s) => [s.id, s]));
  const listed = new Set(order);
  return order.map((id) => byId.get(id)).filter(Boolean)
    .concat(payload.submissions.filter((s) => !listed.has(s.id)));
}

const currentSub = () => state.submissions[state.current];
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '');

function renderSubmission() {
  const s = currentSub();
  if (!s) return;
  $('sub-id').textContent = s.id;
  const dl = $('sub-fields');
  const long = $('sub-long');
  dl.innerHTML = '';
  long.innerHTML = '';
  for (const f of state.fields) {
    const v = (s[f.key] == null ? '' : String(s[f.key])).trim();
    if (f.long) {
      const box = el('div', { class: 'longfield' }, [el('h3', { text: f.label })]);
      const paras = v ? v.split(/\n\s*\n/) : ['(empty)'];
      for (const p of paras) box.append(el('p', { text: p }));
      long.append(box);
    } else {
      dl.append(el('dt', { text: f.label }), el('dd', { text: v || 'not given' }));
    }
  }
  fillForm(state.scores[s.id]);
  $('jump').value = String(state.current);
  $('prev').disabled = state.current === 0;
  $('next').disabled = state.current >= state.submissions.length - 1;
  window.scrollTo({ top: 0 });
}

function refreshList() {
  const sel = $('jump');
  sel.innerHTML = '';
  let done = 0;
  state.submissions.forEach((s, i) => {
    const rec = state.scores[s.id];
    const complete = rec && rec.complete;
    if (complete) done++;
    const mark = complete ? '✓ ' : rec ? '… ' : '';
    sel.append(el('option', { value: String(i), text: `${mark}${s.id}` }));
  });
  sel.value = String(state.current);
  $('progress').textContent = `${done} of ${state.submissions.length} scored`;
}

function goTo(i) {
  if (i < 0 || i >= state.submissions.length) return;
  state.current = i;
  renderSubmission();
}

function goNextUnscored() {
  const n = state.submissions.length;
  for (let k = 1; k <= n; k++) {
    const i = (state.current + k) % n;
    const rec = state.scores[state.submissions[i].id];
    if (!rec || !rec.complete) { goTo(i); return; }
  }
  setSaveStatus('All submissions scored.');
}

// ---------- the form ----------
function radioGroup(key, label, options, hint) {
  const fs = el('fieldset', { class: 'choices' }, [el('legend', { text: label })]);
  if (hint) fs.append(el('p', { class: 'q', text: hint }));
  for (const [val, text] of options) {
    fs.append(el('label', {}, [el('input', { type: 'radio', name: key, value: val }), el('span', { text })]));
  }
  return fs;
}

function criterion(c) {
  const fs = el('fieldset', { class: 'criterion' }, [el('legend', { text: c.label }), el('p', { class: 'q', text: c.question })]);
  const scale = el('div', { class: 'scale' });
  for (let v = 1; v <= 5; v++) {
    scale.append(el('label', {}, [el('input', { type: 'radio', name: c.key, value: String(v) }), el('span', { text: String(v) })]));
  }
  fs.append(scale);
  fs.append(el('div', { class: 'anchors' }, c.anchors.map((a, i) => el('span', { text: `${[1, 3, 5][i]} · ${a}` }))));
  return fs;
}

function buildForm() {
  const f = $('review');
  f.innerHTML = '';
  f.append(radioGroup('coi', FORM.coi.label, FORM.coi.options));
  f.append(el('p', { id: 'coi-flag', class: 'flag', hidden: '' }));
  const scoring = el('div', { id: 'scoring' });
  for (const c of FORM.criteria) scoring.append(criterion(c));
  scoring.append(radioGroup('recommendation', FORM.recommendation.label, FORM.recommendation.options, FORM.recommendation.hint));
  scoring.append(radioGroup('confidence', FORM.confidence.label, FORM.confidence.options));
  scoring.append(el('fieldset', {}, [
    el('legend', { text: 'Notes for discussion (optional)' }),
    el('textarea', { id: 'note', name: 'note', rows: '3', placeholder: 'Anything the scores do not capture.' }),
  ]));
  f.append(scoring);
  f.append(el('div', { class: 'actions' }, [
    el('button', { type: 'button', class: 'primary', id: 'save', text: 'Save' }),
    el('button', { type: 'button', id: 'save-next', text: 'Save and next unscored' }),
    el('span', { id: 'save-status' }),
  ]));
  f.addEventListener('change', onFormChange);
  f.addEventListener('submit', (e) => e.preventDefault());
  $('note').addEventListener('input', onFormChange);
  $('save').addEventListener('click', () => save(false));
  $('save-next').addEventListener('click', () => save(true));
}

function readForm() {
  const f = $('review');
  const rec = {};
  for (const k of RECORD_KEYS) {
    if (k === 'note') rec.note = $('note').value.trim();
    else {
      const r = f.querySelector(`input[name="${k}"]:checked`);
      rec[k] = r ? r.value : '';
    }
  }
  if (rec.coi === 'coauthor') for (const k of SCORE_KEYS) rec[k] = '';
  return rec;
}

function fillForm(rec) {
  const f = $('review');
  f.reset();
  if (rec) {
    for (const k of RECORD_KEYS) {
      if (k === 'note') $('note').value = rec.note || '';
      else if (rec[k]) {
        const r = f.querySelector(`input[name="${k}"][value="${rec[k]}"]`);
        if (r) r.checked = true;
      }
    }
  }
  applyCoi(rec ? rec.coi : '');
  markScale();
  setSaveStatus(rec ? statusText(rec) : '');
}

function applyCoi(coi) {
  const flag = $('coi-flag');
  $('scoring').hidden = coi === 'coauthor';
  if (coi === 'coauthor') {
    flag.hidden = false;
    flag.textContent = 'Thank you. As a co-author you do not score this submission. Press Save and move on.';
  } else if (coi === 'knows') {
    flag.hidden = false;
    flag.textContent = 'Noted. Please score anyway; we will consider the flag.';
  } else {
    flag.hidden = true;
  }
}

function markScale() {
  for (const l of document.querySelectorAll('.scale label')) l.classList.toggle('on', l.querySelector('input').checked);
}

function setSaveStatus(text) { $('save-status').textContent = text; }

function statusText(rec) {
  if (!rec.saved_at) return '';
  const parts = [rec.complete ? 'Complete' : 'Incomplete'];
  if (rec.synced_at === rec.saved_at) parts.push('synced');
  else parts.push(CFG.syncUrl ? 'saved on this device, not synced yet' : 'saved on this device');
  return parts.join(' · ');
}

function onFormChange() {
  const s = currentSub();
  if (!s) return;
  const rec = readForm();
  const prev = state.scores[s.id] || {};
  const changed = RECORD_KEYS.some((k) => (prev[k] || '') !== (rec[k] || ''));
  if (!changed) return;
  rec.submission = s.id;
  rec.saved_at = Date.now();
  rec.synced_at = prev.synced_at || null;
  rec.complete = isComplete(rec);
  state.scores[s.id] = rec;
  persist();
  applyCoi(rec.coi);
  markScale();
  refreshList();
  setSaveStatus(statusText(rec));
}

// ---------- sync with the chair's sheet ----------
function setSync(text, cls) {
  const n = $('sync-status');
  n.textContent = text;
  n.className = 'muted small ' + (cls || '');
}

function pending() {
  return Object.values(state.scores).filter((r) => r.saved_at && r.synced_at !== r.saved_at);
}

function toWire(rec) {
  const w = { submission: rec.submission };
  for (const k of RECORD_KEYS) w[k] = rec[k] == null ? '' : rec[k];
  w.complete = !!rec.complete;
  w.saved_at = rec.saved_at;
  w.saved_at_iso = new Date(rec.saved_at).toISOString();
  return w;
}

async function pushRecord(rec) {
  const res = await fetch(CFG.syncUrl, {
    method: 'POST',
    body: JSON.stringify({ reviewer: state.reviewer, token: state.token, record: toWire(rec) }),
  });
  const j = await res.json();
  if (!j.ok) throw new Error(j.error || 'rejected');
}

async function syncAll() {
  if (!CFG.syncUrl) {
    setSync('No sync configured. Scores stay on this device; use the CSV download.');
    return;
  }
  const todo = pending();
  if (!todo.length) { setSync('All scores synced.', 'status-ok'); return; }
  setSync(`Syncing ${todo.length}…`);
  let failed = 0;
  for (const rec of todo) {
    const stamp = rec.saved_at;
    try {
      await pushRecord(rec);
      const live = state.scores[rec.submission];
      if (live && live.saved_at === stamp) live.synced_at = stamp;
    } catch (e) {
      failed++;
      console.warn('sync failed', e);
    }
  }
  persist();
  if (failed) setSync(`${failed} not synced (kept on this device). Check your connection and press Sync now.`, 'status-err');
  else setSync('All scores synced.', 'status-ok');
  const s = currentSub();
  if (s && state.scores[s.id]) setSaveStatus(statusText(state.scores[s.id]));
}

async function pullRemote() {
  if (!CFG.syncUrl) return;
  try {
    const url = `${CFG.syncUrl}?reviewer=${encodeURIComponent(state.reviewer)}&token=${encodeURIComponent(state.token)}`;
    const res = await fetch(url);
    const j = await res.json();
    if (!j.ok) throw new Error(j.error || 'rejected');
    let merged = 0;
    for (const r of j.records || []) {
      const id = r.submission;
      if (!id) continue;
      const remoteAt = Number(r.saved_at) || 0;
      const local = state.scores[id];
      if (!local || remoteAt > (local.saved_at || 0)) {
        const rec = { submission: id };
        for (const k of RECORD_KEYS) rec[k] = r[k] == null ? '' : String(r[k]);
        rec.saved_at = remoteAt;
        rec.synced_at = remoteAt;
        rec.complete = isComplete(rec);
        state.scores[id] = rec;
        merged++;
      }
    }
    if (merged) persist();
  } catch (e) {
    console.warn('pull failed', e);
    setSync('Could not reach the score sheet; working from this device.', 'status-warn');
  }
}

async function save(thenNext) {
  const s = currentSub();
  if (!s) return;
  onFormChange();
  if (!state.scores[s.id]) { setSaveStatus('Nothing to save yet.'); return; }
  await syncAll();
  if (thenNext) goNextUnscored();
}

function exportCsv() {
  const cols = ['reviewer', 'submission', ...RECORD_KEYS, 'complete', 'saved_at', 'saved_at_iso'];
  const q = (v) => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
  const rows = Object.values(state.scores)
    .sort((a, b) => a.submission.localeCompare(b.submission))
    .map((r) => { const w = toWire(r); w.reviewer = state.reviewer; return cols.map((c) => q(w[c])).join(','); });
  const csv = [cols.join(','), ...rows].join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = el('a', { href: URL.createObjectURL(blob), download: `pse9-scores-${state.reviewer}-${new Date().toISOString().slice(0, 10)}.csv` });
  document.body.append(a);
  a.click();
  a.remove();
}

// ---------- sign-in ----------
async function signIn(code, { remembered = false } = {}) {
  const btn = $('login-btn');
  const err = $('login-error');
  err.hidden = true;
  btn.disabled = true;
  btn.textContent = 'Opening…';
  try {
    const pkg = await loadPackage();
    const { reviewer, token, payload } = await unlock(code.trim(), pkg);
    state.reviewer = reviewer;
    state.token = token;
    state.builtAt = pkg.built_at;
    state.fields = payload.fields;
    state.submissions = orderFor(payload, reviewer);
    state.scores = loadScores();
    remember(code.trim());
    await pullRemote();
    showApp();
  } catch (e) {
    if (remembered) forget();
    err.textContent = e.message || 'Could not open.';
    err.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Open';
  }
}

function showApp() {
  $('login').hidden = true;
  $('app').hidden = false;
  $('who').hidden = false;
  $('who-name').textContent = `Reviewer ${state.reviewer}`;
  $('data-meta').textContent = `${state.submissions.length} submissions · data updated ${fmtDate(state.builtAt)}`;
  buildForm();
  const first = state.submissions.findIndex((s) => !(state.scores[s.id] && state.scores[s.id].complete));
  state.current = first >= 0 ? first : 0;
  refreshList();
  renderSubmission();
  if (CFG.syncUrl) {
    const n = pending().length;
    setSync(n ? `${n} saved on this device, not synced yet.` : 'All scores synced.', n ? 'status-warn' : 'status-ok');
  } else {
    setSync('No sync configured. Scores stay on this device; use the CSV download.');
  }
}

function init() {
  $('login-form').addEventListener('submit', (e) => { e.preventDefault(); signIn($('code').value); });
  $('signout').addEventListener('click', () => { forget(); location.reload(); });
  $('guide-btn').addEventListener('click', () => $('guide').showModal());
  $('jump').addEventListener('change', (e) => goTo(Number(e.target.value)));
  $('prev').addEventListener('click', () => goTo(state.current - 1));
  $('next').addEventListener('click', () => goTo(state.current + 1));
  $('next-unscored').addEventListener('click', goNextUnscored);
  $('sync-now').addEventListener('click', syncAll);
  $('export').addEventListener('click', exportCsv);
  if (!window.isSecureContext) {
    $('login-error').textContent = 'Open this page over https (or localhost); the browser will not decrypt otherwise.';
    $('login-error').hidden = false;
    return;
  }
  loadPackage()
    .then((pkg) => { $('login-meta').textContent = `${pkg.count} submissions · data updated ${fmtDate(pkg.built_at)}`; })
    .catch(() => {});
  let code = null;
  try { code = localStorage.getItem(CODE_KEY); } catch (e) { /* ignore */ }
  if (code) { $('code').value = code; signIn(code, { remembered: true }); }
}

document.addEventListener('DOMContentLoaded', init);
