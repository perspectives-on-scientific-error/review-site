// PSE9 review: score sink. Paste into a Google Apps Script bound to a new
// Google Sheet (Extensions > Apps Script), then Deploy > New deployment >
// Web app, "Execute as: Me", "Who has access: Anyone". Put the /exec URL in
// config.js. Re-deploy (new version) after any edit.
//
// The sheet gets two tabs: "scores" (one row per reviewer and submission,
// updated in place) and "log" (every save, append-only).

// From: uv run tools/make_codes.py --show
const TOKENS = {
  R1: 'paste-token-here',
  R2: 'paste-token-here',
  R3: 'paste-token-here',
  R4: 'paste-token-here',
  R5: 'paste-token-here',
};

const FIELDS = ['submission', 'coi', 'fit', 'accessibility', 'quality', 'novelty',
  'recommendation', 'confidence', 'note', 'complete', 'saved_at', 'saved_at_iso'];

function out(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function authorised(reviewer, token) {
  return !!reviewer && !!TOKENS[reviewer] && TOKENS[reviewer] === token;
}

function sheet(name) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    sh.appendRow(['reviewer'].concat(FIELDS, ['received_at']));
    sh.setFrozenRows(1);
  }
  return sh;
}

// Keep free text from being read as a formula.
function cell(v) {
  if (v === undefined || v === null) return '';
  if (typeof v === 'string' && /^[=+\-@]/.test(v)) return "'" + v;
  return v;
}

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out({ ok: false, error: 'bad json' }); }
  if (!authorised(body.reviewer, body.token)) return out({ ok: false, error: 'unauthorised' });
  const r = body.record || {};
  if (!r.submission) return out({ ok: false, error: 'no submission id' });
  const row = [body.reviewer].concat(FIELDS.map((f) => cell(r[f])), [new Date().toISOString()]);

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    sheet('log').appendRow(row);
    const sh = sheet('scores');
    const data = sh.getDataRange().getValues();
    let idx = -1;
    for (let i = 1; i < data.length; i++) {
      if (data[i][0] === body.reviewer && String(data[i][1]) === String(r.submission)) { idx = i; break; }
    }
    if (idx >= 0) sh.getRange(idx + 1, 1, 1, row.length).setValues([row]);
    else sh.appendRow(row);
  } finally {
    lock.releaseLock();
  }
  return out({ ok: true });
}

function doGet(e) {
  const p = (e && e.parameter) || {};
  if (!p.reviewer) return out({ ok: true, service: 'pse9-review' });
  if (!authorised(p.reviewer, p.token)) return out({ ok: false, error: 'unauthorised' });
  const sh = sheet('scores');
  const data = sh.getDataRange().getValues();
  const head = data[0];
  const records = [];
  for (let i = 1; i < data.length; i++) {
    if (data[i][0] !== p.reviewer) continue;
    const rec = {};
    head.forEach((h, j) => { rec[h] = data[i][j]; });
    records.push(rec);
  }
  return out({ ok: true, records: records });
}
