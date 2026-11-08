"""Local web UI for ShieldAI - stdlib http.server only, no external deps.

Serves a single-page dashboard + JSON API on 127.0.0.1. All assets are
embedded (no CDN/fonts/frameworks) so the local-only claim holds:
nothing leaves the machine and nothing is fetched from the network.

UX contract (first principles):
  - The user's goal is "type request -> get answer". Everything else is
    secondary. Primary surface shows at most 3 things: input, result,
    health.
  - One keystroke submits; stages animate as the pipeline advances;
    every state (pending/done/blocked/error) is visible - no silent
    waiting.
  - Honest by design: LLM output is labelled "unverified"; integrity
    status is computed, never decorative.
"""
import json
import queue
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from guardian_ai.compliance import redact
from guardian_ai.db import (init_database, audit_log, export_audit,
                            record_tasks, verify_audit_chain)
from guardian_ai.executor import Executor
from guardian_ai.router import Router

HOST, PORT = "127.0.0.1", 8765

# ThreadingHTTPServer runs each request in a NEW thread, but a sqlite3
# connection is bound to its creating thread - so per-thread storage
# would re-run init_database() (~200ms: schema+migrations+seed) on every
# single request. Pool the connections instead: check one out, hand it
# back when done. init cost is paid once per concurrent slot, not per
# request.
_POOL_SIZE = 4
_pool: "queue.Queue[sqlite3.Connection]" = queue.Queue(
    maxsize=_POOL_SIZE)
_pool_init = threading.Lock()


def _conn():
    """Check out a pooled connection. sqlite3 starts an implicit
    transaction on DML, so a conn released mid-exception could carry an
    open transaction + write lock into the next request - rollback on
    checkout guarantees a clean state."""
    try:
        conn = _pool.get_nowait()
    except queue.Empty:
        with _pool_init:
            try:
                conn = _pool.get_nowait()
            except queue.Empty:
                return init_database()
    conn.rollback()
    return conn


def _release(conn) -> None:
    try:
        _pool.put_nowait(conn)
    except queue.Full:
        conn.close()


# forged-task check cached on row count - recomputing every signature
# each 10s poll is O(#signed rows) and wasteful when nothing changed.
_forged_cache = {"count": -1, "forged": 0}


def _log_error(msg: str) -> None:
    """Persist request-handling errors - stderr alone is lost once the
    server's terminal closes, so a file log keeps failures debuggable.
    The log is bounded (last 200 lines) so it cannot fill the disk over
    time - an unbounded error log would repeat the audit-growth problem."""
    try:
        from guardian_ai.paths import data_dir
        from datetime import datetime
        log = data_dir() / "webui-errors.log"
        lines = []
        if log.exists():
            lines = log.read_text(encoding="utf-8").splitlines()[-199:]
        lines.append(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}")
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass  # logging must never break the request path

_HTML = r"""<!doctype html>
<html lang="ja" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>ShieldAI - Local AI Control Plane</title>
<style>
/* ---------- design tokens (single source of truth) ---------- */
:root{
  --bg:#0b0f14; --surface:#12171f; --surface-2:#1a212b;
  --border:#242d39; --fg:#e6edf3; --dim:#8b949e; --faint:#6b7683;
  --ok:#3fb950; --warn:#d29922; --err:#f85149; --acc:#4c9aff;
  --radius:10px; --radius-s:6px;
  --space:16px; --space-s:8px;
  --shadow:0 8px 24px rgba(0,0,0,.35);
}
@media (prefers-color-scheme: light){ :root{
  --bg:#f6f8fa; --surface:#ffffff; --surface-2:#f0f2f5;
  --border:#d8dee4; --fg:#1f2328; --dim:#59636e; --faint:#818b98;
}}
@media (prefers-reduced-motion: reduce){
  *{animation:none!important;transition:none!important}
}
/* ---------- base ---------- */
*{box-sizing:border-box;margin:0}
html{-webkit-text-size-adjust:100%}
body{
  background:var(--bg);color:var(--fg);
  font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;
  min-height:100vh;
}
.wrap{max-width:880px;margin:0 auto;padding:24px 16px 64px}
:focus-visible{outline:2px solid var(--acc);outline-offset:2px;
  border-radius:var(--radius-s)}
/* ---------- header: at most 3 things the eye lands on ---------- */
header{display:flex;align-items:center;gap:10px;margin-bottom:24px}
.logo{font-weight:700;font-size:18px;letter-spacing:-.02em}
.health{display:flex;gap:6px;margin-left:auto}
.dot{display:inline-flex;align-items:center;gap:5px;
  font-size:12px;color:var(--dim);background:var(--surface);
  border:1px solid var(--border);border-radius:20px;padding:4px 10px}
.dot i{width:7px;height:7px;border-radius:50%;background:var(--faint)}
.dot.ok i{background:var(--ok)}.dot.bad i{background:var(--err)}
.dot.warn i{background:var(--warn)}
/* ---------- hero: the one action ---------- */
.hero{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:20px;margin-bottom:16px;
  box-shadow:var(--shadow)}
.hero label{display:block;font-size:13px;color:var(--dim);
  margin-bottom:8px}
.req-row{display:flex;gap:8px}
#req{flex:1;padding:12px 14px;font-size:15px;color:var(--fg);
  background:var(--bg);border:1px solid var(--border);
  border-radius:var(--radius-s)}
#req::placeholder{color:var(--faint)}
.btn{padding:12px 20px;font-size:14px;font-weight:600;color:#fff;
  background:var(--acc);border:0;border-radius:var(--radius-s);
  cursor:pointer;transition:opacity .15s}
.btn:hover{opacity:.85}
.btn:disabled{opacity:.4;cursor:wait}
.btn.ghost{background:transparent;color:var(--dim);
  border:1px solid var(--border);font-weight:500}
.btn.ghost:hover{color:var(--fg);border-color:var(--dim)}
.actions{display:flex;gap:8px;margin-top:12px}
/* ---------- pipeline stages: state always visible ---------- */
.stages{display:flex;gap:6px;flex-wrap:wrap;margin-top:14px;
  min-height:28px}
.stage{display:inline-flex;align-items:center;gap:6px;font-size:12px;
  color:var(--faint);border:1px solid var(--border);
  border-radius:var(--radius-s);padding:4px 10px}
.stage::before{content:"";width:6px;height:6px;border-radius:50%;
  background:var(--faint)}
.stage.run{color:var(--acc);border-color:var(--acc)}
.stage.run::before{background:var(--acc);
  animation:pulse 1s infinite}
.stage.done{color:var(--ok);border-color:#2a3d30}
.stage.done::before{background:var(--ok)}
.stage.blocked{color:var(--err);border-color:#4a2629}
.stage.blocked::before{background:var(--err)}
.stage.skip{color:var(--faint)}
@keyframes pulse{50%{opacity:.3}}
/* ---------- result ---------- */
.result{display:none;margin-top:16px;border-top:1px solid var(--border);
  padding-top:16px}
.result.show{display:block}
.result-head{display:flex;align-items:center;gap:8px;
  margin-bottom:10px;flex-wrap:wrap}
.badge{display:inline-block;padding:2px 10px;border-radius:12px;
  font-size:12px;font-weight:600}
.b-ok{background:#12291a;color:var(--ok)}
.b-warn{background:#2e2610;color:var(--warn)}
.b-bad{background:#35161a;color:var(--err)}
.b-acc{background:#152238;color:var(--acc)}
.result-body{font-size:14px;white-space:pre-wrap}
.llm-note{margin-top:12px;font-size:12px;color:var(--warn);
  border-left:3px solid var(--warn);padding:4px 10px;
  background:rgba(210,153,34,.06)}
/* ---------- activity ---------- */
.tabs{display:flex;gap:4px;margin:24px 0 10px;border-bottom:
  1px solid var(--border)}
.tab{padding:8px 14px;font-size:13px;color:var(--dim);
  border:0;background:none;cursor:pointer;
  border-bottom:2px solid transparent}
.tab.on{color:var(--fg);border-bottom-color:var(--acc);
  font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--faint);font-weight:600;
  padding:6px 10px;font-size:11px;text-transform:uppercase;
  letter-spacing:.04em}
td{padding:8px 10px;border-top:1px solid var(--border);
  vertical-align:top}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px}
.dim{color:var(--dim)}
.empty{color:var(--faint);padding:20px;text-align:center;font-size:13px}
/* ---------- toast: feedback, never silence ---------- */
.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%)
  translateY(80px);background:var(--surface-2);border:1px solid
  var(--border);border-radius:var(--radius);padding:12px 18px;
  font-size:13px;box-shadow:var(--shadow);transition:transform .25s;
  max-width:90vw;z-index:10}
.toast.show{transform:translateX(-50%) translateY(0)}
.toast .cause{color:var(--dim);font-size:12px;margin-top:2px}
.btn:focus-visible,input:focus-visible,.tab:focus-visible{
  outline:2px solid var(--acc);outline-offset:2px}
@media(max-width:560px){
  .req-row{flex-direction:column}
  .health{flex-wrap:wrap}
}
</style></head>
<body>
<div class="wrap">

<header>
  <div class="logo">ShieldAI</div>
  <select id="lang" aria-label="Language" onchange="setLang(this.value)"
    style="background:var(--card);color:var(--text);border:1px solid
      var(--border);border-radius:6px;padding:4px 8px;font-size:13px">
    <option value="ja">日本語</option>
    <option value="en">English</option>
  </select>
  <div class="health" id="health" role="status" aria-live="polite">
    <span class="dot"><i></i><span data-i18n="checking">checking…</span></span>
  </div>
</header>

<main>
  <section class="hero" aria-label="Request">
    <label for="req" data-i18n="what">何を処理しますか?</label>
    <div class="req-row">
      <input id="req" type="text" autocomplete="off" autofocus
        data-i18n-ph="ph"
        placeholder="例: サーバー障害 ERROR 10.0.0.1 ログを確認して"
        aria-describedby="hint">
      <button class="btn" id="run" onclick="submit()">実行</button>
    </div>
    <div id="hint" class="dim" style="font-size:12px;margin-top:8px"
      data-i18n="hint">
      Enter で送信 &middot; 分類→計画→決定論的実行→監査 (100% ローカル)
    </div>
    <div class="actions">
      <button class="btn ghost" onclick="doVerify()" data-i18n="actVerify">Verify chain</button>
      <button class="btn ghost" onclick="doExport()" data-i18n="actExport">Export audit</button>
      <button class="btn ghost" onclick="doDecrypt()" data-i18n="actDecrypt">Decrypt</button>
      <button class="btn ghost" onclick="doUpdate()" data-i18n="actUpdate">Check updates</button>
      <button class="btn ghost" onclick="doDoctor()" data-i18n="actDoctor">Doctor</button>
    </div>
    <div class="stages" id="stages" aria-live="polite"></div>
    <div class="result" id="result" aria-live="polite">
      <div class="result-head" id="result-head"></div>
      <div class="result-body" id="result-body"></div>
      <div class="llm-note" id="llm-note" style="display:none"></div>
    </div>
  </section>

  <section aria-label="Activity">
    <div class="tabs" role="tablist">
      <button class="tab on" role="tab" aria-selected="true"
        onclick="showTab('audit',this)" data-i18n="tabAudit">Audit log</button>
      <button class="tab" role="tab" aria-selected="false"
        onclick="showTab('tasks',this)" data-i18n="tabTasks">Work record</button>
    </div>
    <table id="audit" role="tabpanel" aria-label="Audit log" data-i18n-aria="tabAudit"></table>
    <table id="tasks" role="tabpanel" aria-label="Work record" style="display:none" data-i18n-aria="tabTasks"></table>
  </section>
</main>
</div>
<div class="toast" id="toast" role="alert"></div>

<script>
const $=id=>document.getElementById(id);
// i18n: ?lang= -> sessionStorage -> navigator.language. A global product
// can't hardcode one language - strings live in a dict so new locales
// are added as data, not code.
const STR={
 ja:{what:'何を処理しますか?',ph:'例: サーバー障害 ERROR 10.0.0.1 ログを確認して',
     run:'実行',running:'実行中…',
     hint:'Enter で送信 · 分類→計画→決定論的実行→監査 (100% ローカル)',
     cancelled:'中止しました',
     cancelledWhy:'破損した監査チェーンへの書き込みを拒否',
     failed:'実行に失敗しました',
     failedWhy:'再実行するか status で健全性を確認してください',
     checking:'確認中…',
     tabAudit:'監査ログ',tabTasks:'作業記録',
     actVerify:'チェーン検証',actExport:'監査エクスポート',
     actDecrypt:'復号',actUpdate:'更新確認',
     tipOk:'先端一致',tipBroken:'先端破損',forged:'件 偽造',
     keyOk:'鍵 ok',keyMissing:'鍵なし',
     licensed:'ライセンス',community:'コミュニティ',
     deterministic:'決定論',entries:'件',
     triggersMissing:'件 トリガー欠落',offline:'オフライン',
     thAgent:'エージェント',thReq:'リクエスト',thMs:'ms',
     thTime:'時刻',thStatus:'状態',thDesc:'説明',
     noEntries:'まだエントリがありません',
     noTasks:'まだ作業がありません',
     confirmBroken:'監査チェーンが #{n} で破損: {reason}\n\n改竄の可能性があります。続行しますか?',
     noAnswer:'(回答なし)',
     llmNote:'LLM 推論 ({model}) - モデル生成・未検証',
     chainOk:'チェーン正常 - {n} 件を検証 (HMAC + chain_state)',
     chainBroken:'チェーン破損{at}',
     verifyFailed:'検証に失敗しました',
     updateCheck:'更新チェック',
     newVer:'新版 {latest} (現在 {current})',
     upToDate:'最新です ({current})',
     updateFailed:'更新チェックに失敗しました',
     exported:'監査をエクスポートしました',
     exportBroken:'警告: 監査チェーンが破損 - このエクスポートは侵害されたデータを含みます',
     exportFailed:'エクスポートに失敗しました',
     decPath:'復号するファイルのパス (.enc):',
     decNonJson:'復号しました (JSON ではありません)',
     decOk:'検証済み: {n} 件が署名済み先端に到達',
     decInvalid:'無効: {reason}',
     decFailed:'復号に失敗しました',
     stg_ingestion:'取込',stg_extraction:'抽出',
     stg_verification:'検証',stg_synthesis:'合成',stg_audit:'監査',
     actDoctor:'環境診断',doctorOk:'全チェック通過',
     doctorFail:'{n} 件のチェックが失敗',
     doctorFailed:'診断に失敗しました'},
 en:{what:'What should we process?',ph:'e.g. check the log: server failure ERROR 10.0.0.1',
     run:'Run',running:'Running…',
     hint:'Enter to send · classify → plan → deterministic execute → audit (100% local)',
     cancelled:'Cancelled',
     cancelledWhy:'Refused to write to a broken audit chain',
     failed:'Run failed',
     failedWhy:'Retry, or check health with status',
     checking:'checking…',
     tabAudit:'Audit log',tabTasks:'Work record',
     actVerify:'Verify chain',actExport:'Export audit',
     actDecrypt:'Decrypt',actUpdate:'Check updates',
     tipOk:'tip ok',tipBroken:'tip broken',forged:'forged',
     keyOk:'key ok',keyMissing:'key missing',
     licensed:'licensed',community:'community',
     deterministic:'deterministic',entries:'entries',
     triggersMissing:'triggers missing',offline:'offline',
     thAgent:'agent',thReq:'request',thMs:'ms',
     thTime:'time',thStatus:'status',thDesc:'description',
     noEntries:'no entries yet',
     noTasks:'no tasks yet',
     confirmBroken:'Audit chain is broken at #{n}: {reason}\n\nThe trail may be tampered. Continue anyway?',
     noAnswer:'(no answer)',
     llmNote:'LLM inference ({model}) - model-generated, unverified',
     chainOk:'chain ok - {n} entries verified (HMAC + chain_state)',
     chainBroken:'chain BROKEN{at}',
     verifyFailed:'verify failed',
     updateCheck:'update check',
     newVer:'new version {latest} (current {current})',
     upToDate:'up to date ({current})',
     updateFailed:'update check failed',
     exported:'audit exported',
     exportBroken:'WARNING: audit chain is broken - this export captures compromised data',
     exportFailed:'export failed',
     decPath:'decrypt file path (.enc):',
     decNonJson:'decrypted (not JSON)',
     decOk:'verified: {n} entries reach signed head',
     decInvalid:'INVALID: {reason}',
     decFailed:'decrypt failed',
     stg_ingestion:'ingestion',stg_extraction:'extraction',
     stg_verification:'verification',stg_synthesis:'synthesis',
     stg_audit:'audit',
     actDoctor:'Doctor',doctorOk:'all checks passed',
     doctorFail:'{n} check(s) failed',
     doctorFailed:'doctor failed'}};
const _Q=new URLSearchParams(location.search);
const _LANG=_Q.get('lang')||sessionStorage.getItem('sl')||
  (navigator.language||'').slice(0,2);
const LANG=STR[_LANG]?_LANG:'en';
sessionStorage.setItem('sl',LANG);
document.documentElement.lang=LANG;
const t=k=>(STR[LANG]||STR.en)[k]||k;
const tf=(k,o)=>t(k).replace(/\{(\w+)\}/g,(_,x)=>o?.[x]??x);
function setLang(l){
  sessionStorage.setItem('sl',l);
  const u=new URL(location.href);u.searchParams.set('lang',l);
  location.href=u;}
document.addEventListener('DOMContentLoaded',()=>{
  const sel=document.getElementById('lang');if(sel)sel.value=LANG;
  document.querySelectorAll('[data-i18n]').forEach(
    e=>e.textContent=t(e.dataset.i18n));
  document.querySelectorAll('[data-i18n-ph]').forEach(
    e=>e.placeholder=t(e.dataset.i18nPh));
  document.querySelectorAll('[data-i18n-aria]').forEach(
    e=>e.setAttribute('aria-label',t(e.dataset.i18nAria)));
  $('run').textContent=t('run');
  $('health').innerHTML=`<span class="dot"><i></i>${t('checking')}</span>`;});
const _T=_Q.get('t')||sessionStorage.getItem('st')||'';
sessionStorage.setItem('st',_T);
const H=o=>({...(o||{}),headers:{...((o&&o.headers)||{}),'X-Token':_T}});
const J=u=>fetch(u,H()).then(r=>{if(!r.ok)throw new Error(r.status);return r.json()});
const badge=(t,c)=>`<span class="badge b-${c}">${t}</span>`;
const esc=s=>String(s??'').replace(/[&<>"']/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let toastT;
function toast(msg,cause){
  $('toast').innerHTML=esc(msg)+
    (cause?`<div class="cause">${esc(cause)}</div>`:'');
  $('toast').classList.add('show');
  clearTimeout(toastT);
  toastT=setTimeout(()=>$('toast').classList.remove('show'),5000);
}
/* ---------- health: 3 ambient indicators, no noise ---------- */
async function refresh(){
  try{
    const s=await J('/api/status');
    const chain=s.chain||{};
    $('health').innerHTML=
      // the ambient check only verifies the tip (head/count match) -
      // 'chain ok' would overclaim full verification (verify runs it).
      `<span class="dot ${chain.ok?'ok':'bad'}"><i></i>${
        chain.ok?t('tipOk'):t('tipBroken')}</span>`+
      (chain.forged_tasks?`<span class="dot bad"><i></i>${
        chain.forged_tasks} ${t('forged')}</span>`:'')+
      `<span class="dot ${s.kms_ok===false?'bad':'ok'}"><i></i>${
        s.kms_ok===false?t('keyMissing'):t('keyOk')}</span>`+
      `<span class="dot ${(s.license||{}).valid?'ok':''}"><i></i>${
        (s.license||{}).valid?t('licensed'):t('community')}</span>`+
      `<span class="dot ${s.ollama_up?'ok':'warn'}"><i></i>${
        s.ollama_up?(s.models[0]||'model'):t('deterministic')}</span>`+
      `<span class="dot"><i></i>${s.audit_entries} ${t('entries')}</span>`+
      `<span class="dot"><i></i>v${s.version}</span>`+
      ((s.triggers_missing||[]).length?
       `<span class="dot warn"><i></i>${
         s.triggers_missing.length} ${t('triggersMissing')}</span>`:'');
  }catch(e){
    $('health').innerHTML=
      `<span class="dot bad"><i></i>${t('offline')}</span>`;
  }
  loadTables();
}
/* ---------- tables ---------- */
async function loadTables(){
  const h=await J('/api/history?n=15');
  $('audit').innerHTML=`<tr><th scope="col">#</th><th scope="col">${t('thAgent')}</th><th scope="col">${t('thReq')}</th><th scope="col">${t('thMs')}</th><th scope="col">${t('thTime')}</th></tr>`+
    (h.length?h.map(r=>`<tr><td class="mono">${r.id}</td><td>${esc(r.agent)}</td>
     <td class="dim">${esc((r.request||'').slice(0,48))}</td>
     <td class="mono">${r.latency_ms??'-'}</td>
     <td class="dim mono">${esc((r.timestamp||'').slice(5,19))}</td></tr>`).join('')
     :`<tr><td colspan="5" class="empty">${t('noEntries')}</td></tr>`);
  const tk=await J('/api/tasks');
  const sc={done:'ok',blocked:'bad',failed:'bad',skipped:'warn',pending:'warn'};
  // parity with the CLI 'forged' command - the UI needs to see WHICH
  // rows are fabricated, not just 'tip broken' (was /api/forged dead code).
  const fg=await J('/api/forged');
  const forgedRows=fg.length?'<tr><td colspan="3" class="dim" '+
    'style="color:var(--bad)">'+fg.map(r=>
      `[${esc(r.table)}] #${r.id} ${esc(r.agent)} `+
      `(${esc(r.reason||'')})`).join('<br>')+'</td></tr>':'';
  $('tasks').innerHTML=`<tr><th scope="col">${t('thAgent')}</th><th scope="col">${t('thStatus')}</th><th scope="col">${t('thDesc')}</th></tr>`+
    forgedRows+
    (tk.length?tk.map(r=>`<tr><td>${esc(r.agent)}</td>
     <td>${badge(r.status,sc[r.status]||'warn')}</td>
     <td class="dim">${esc(r.description||'')}</td></tr>`).join('')
     :`<tr><td colspan="3" class="empty">${t('noTasks')}</td></tr>`);
}
function showTab(id,el){
  document.querySelectorAll('.tab').forEach(t=>{
    t.classList.remove('on');t.setAttribute('aria-selected','false')});
  el.classList.add('on');el.setAttribute('aria-selected','true');
  $('audit').style.display=id==='audit'?'':'none';
  $('tasks').style.display=id==='tasks'?'':'none';
}
// ARIA tablist keyboard pattern: arrow keys move between tabs, not
// just Tab - without it screen-reader users can't switch panels.
document.querySelectorAll('.tab').forEach(el=>{
  el.addEventListener('keydown',e=>{
    if(e.key!=='ArrowRight'&&e.key!=='ArrowLeft')return;
    const tabs=[...document.querySelectorAll('.tab')];
    const i=(tabs.indexOf(el)+(e.key==='ArrowRight'?1:-1)+tabs.length)
      %tabs.length;
    tabs[i].focus();tabs[i].click();});
});
/* ---------- pipeline run: every state visible ---------- */
const PIPE=['ingestion','extraction','verification','synthesis','audit'];
function paintStages(done=[]){
  $('stages').innerHTML=PIPE.map(st=>{
    const s=done.find(x=>(x.step||x.type)===st);
    const cls=s?(s.status==='ok'||s.status==='done'?'done':
      s.status==='blocked'?'blocked':'skip'):'run';
    return `<div class="stage ${cls}">${t('stg_'+st)}</div>`;
  }).join('');
}
let busy=false;
async function submit(){
  const text=$('req').value.trim();
  if(!text||busy)return;
  busy=true;$('run').disabled=true;$('run').textContent=t('running');
  $('result').classList.remove('show');
  paintStages();
  const t0=Date.now();
  try{
    let body={text};
    let r=await fetch('/api/request',H({method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)})).then(r=>r.json());
    if(r.error==='chain_broken'){
      // same explicit-ack gate as the CLI - never write silently
      if(confirm(tf('confirmBroken',
                    {n:r.broken_at,reason:r.reason}))){
        r=await fetch('/api/request',H({method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({text,ack_broken:true})})).then(r=>r.json());
      }else{
        paintStages([]);
        toast(t('cancelled'),t('cancelledWhy'));
        busy=false;$('run').disabled=false;$('run').textContent=t('run');
        return;
      }
    }
    if(r.error)throw new Error(r.error);
    paintStages(r.tasks||[]);
    $('result').classList.add('show');
    const blocked=r.status==='blocked';
    $('result-head').innerHTML=
      badge(blocked?'BLOCKED':'OK',blocked?'bad':'ok')+
      badge(r.agent,'acc')+
      `<span class="dim" style="font-size:12px">`+
      `model: ${esc(r.model)} · ${esc(r.complexity)} · `+
      `${((Date.now()-t0)/1000).toFixed(1)}s · audit #${r.entry_id}</span>`;
    $('result-body').textContent=r.answer||t('noAnswer');
    const llm=$('llm-note');
    if(r.llm_model){
      llm.style.display='block';
      llm.textContent=tf('llmNote',{model:r.llm_model});
    }else llm.style.display='none';
    $('req').value='';
    refresh();
  }catch(e){
    paintStages(PIPE.map(t=>({step:t,status:'blocked'})));
    toast(t('failed'),`${e.message} - ${t('failedWhy')}`);
  }finally{
    busy=false;$('run').disabled=false;$('run').textContent=t('run');
  }
}
/* ---------- secondary actions ---------- */
async function doVerify(){
  try{
    const v=await J('/api/verify');
    // forged tasks / missing chain_state have broken_at=null - '#null'
    // would be a wrong display, so the reason alone carries those.
    toast(v.ok?tf('chainOk',{n:v.entries})
             :tf('chainBroken',
                 {at:v.broken_at!=null?' at #'+v.broken_at:''}),
          v.ok?'':v.reason||'');
  }catch(e){toast(t('verifyFailed'),e.message)}
}
async function doUpdate(){
  try{
    const r=await fetch('/api/update',H({method:'POST',
      headers:{'Content-Type':'application/json'},
      body:'{}'})).then(r=>r.json());
    toast(t('updateCheck'),
      r.update_available?tf('newVer',r)
        :r.error||tf('upToDate',r));
  }catch(e){toast(t('updateFailed'),e.message)}
}
async function doDoctor(){
  try{
    const r=await J('/api/doctor');
    const bad=(r.checks||[]).filter(c=>!c.ok);
    toast(t('actDoctor'),
      r.all_ok?t('doctorOk')
        :tf('doctorFail',{n:bad.length})+' - '+
         bad.map(c=>`${c.name}: ${c.detail}`).join('; '));
  }catch(e){toast(t('doctorFailed'),e.message)}
}
async function doExport(){
  try{
    const r=await fetch('/api/export',H({method:'POST',
      headers:{'Content-Type':'application/json'},
      body:'{}'})).then(r=>r.json());
    window._lastExport=r.path;
    toast(t('exported'),
      r.chain_broken?t('exportBroken'):r.path);
  }catch(e){toast(t('exportFailed'),e.message)}
}
async function doDecrypt(){
  // export already returned the path - offer it so the user is not
  // expected to memorise a filesystem path (export->decrypt flow).
  const path=prompt(t('decPath'),window._lastExport||'');
  if(!path)return;
  try{
    const r=await fetch('/api/decrypt',H({method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path})})).then(r=>r.json());
    // non-JSON payloads return {decrypted} with no entries - show the
    // text (esc via textContent) instead of 'undefined entries'.
    if(r.decrypted!=null){
      $('result').classList.add('show');
      $('result-head').innerHTML=badge('DECRYPTED','acc');
      $('result-body').textContent=r.decrypted;
      toast(t('decNonJson'),r.reason||'');
      return;
    }
    toast(r.ok?tf('decOk',{n:r.entries})
             :tf('decInvalid',{reason:r.reason}),r.anchor||'');
  }catch(e){toast(t('decFailed'),e.message)}
}
/* ---------- keys ---------- */
$('req').addEventListener('keydown',e=>{if(e.key==='Enter')submit()});
/* refresh stacking: skip a poll while one is still in flight - a slow
   status call (>10s) would otherwise queue overlapping refreshes. A
   hidden tab also skips polls - background polling wastes cycles. */
let _refreshing=false;
const refreshOnce=()=>{
  if(_refreshing||document.hidden)return;
  _refreshing=true;
  refresh().finally(()=>_refreshing=false);};
// catch up immediately when the user returns to the tab
document.addEventListener('visibilitychange',()=>{
  if(!document.hidden)refreshOnce();});
refreshOnce();setInterval(refreshOnce,10000);
</script>
</body></html>"""


def _status_payload(conn, executor):
    """Ambient health for the polling badge. The full chain walk is O(n)
    in entries, so running it every 10s poll gets expensive as the chain
    grows - the badge only needs a cheap tip check (last row's chain_hash
    must equal the signed chain_state head + count). /api/verify still
    does the full re-verification on demand."""
    state = conn.execute(
        "SELECT row_count, head, state_hmac FROM chain_state "
        "WHERE id = 1").fetchone()
    last = conn.execute(
        "SELECT COUNT(*), MAX(chain_hash) FROM "
        "(SELECT chain_hash FROM audit_logs ORDER BY id DESC LIMIT 1)"
    ).fetchone()
    count = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    tip_ok = (bool(state) and count == state[0]
              and (last[1] or "") == (state[1] or ""))
    # the badge must also surface work-record forgery - an intact audit
    # chain does not prove tasks/task_queue were not fabricated, and
    # 'tip ok' beside forged rows would mislead. The check is O(#signed
    # rows), so cache it on row count - a new row re-verifies, no change
    # reuses the result (signatures cannot change without a row change).
    global _forged_cache
    task_count = conn.execute(
        "SELECT (SELECT COUNT(*) FROM tasks)+"
        "(SELECT COUNT(*) FROM task_queue)").fetchone()[0]
    if _forged_cache.get("count") != task_count:
        from guardian_ai.db import _forged_work_records, _forged_rows
        _forged_cache = {"count": task_count,
                         "forged": _forged_work_records(conn),
                         "rows": _forged_rows(conn)}
    forged = _forged_cache["forged"]
    chain = {"ok": tip_ok and forged == 0, "entries": count,
             "forged_tasks": forged,
             "tip": ("chain_state head matches last row" if tip_ok
                     else "tip/state mismatch - run verify") +
                  (f"; {forged} forged work-record row(s)"
                   if forged else "")}
    # surface KMS key health too - if the key is lost, chain verification
    # fails cryptically instead of a clear 'key missing' signal.
    try:
        from guardian_ai.kms import get_key
        kms_ok = bool(get_key("audit_chain"))
    except Exception:
        kms_ok = False
    ollama = executor.llm
    # license state belongs in the ambient health - a commercial product
    # shows its own entitlement, not just on a forgotten CLI command.
    try:
        from guardian_ai.licensing import license_status
        lic = license_status()
        license_info = {"valid": lic["valid"],
                        "licensee": lic.get("licensee"),
                        "reason": lic.get("reason")}
    except Exception:
        license_info = {"valid": False, "reason": "check failed"}
    from guardian_ai import __version__
    return {"audit_entries": count, "kms_ok": kms_ok,
            "version": __version__,
            "license": license_info,
            "quick_check": conn.execute("PRAGMA quick_check").fetchone()[0],
            "chain": chain,
            "triggers_missing": [t for t in (
                "audit_no_update", "audit_no_delete",
                "queue_no_update", "queue_no_delete",
                "tasks_no_update", "tasks_no_delete")
                if t not in {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='trigger'")}],
            "agents": conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0],
            "ollama_up": bool(ollama and ollama.available()),
            "models": (ollama.models() if ollama and ollama.available()
                       else [])}


class _Handler(BaseHTTPRequestHandler):
    """Handlers share router/executor/conn via server attributes."""

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # keep the console quiet
        pass

    def _authorized(self) -> bool:
        """Every /api/ request needs the session token - on a customer's
        machine, any local process could otherwise read the audit trail
        (GETs) or pollute it (POST /api/request). The token is generated
        per-server-run and delivered only via the browser URL."""
        if not self.path.startswith("/api/"):
            return True
        return self.headers.get("X-Token") == getattr(
            self.server, "token", None)

    def do_GET(self):
        if not self._authorized():
            self._send(401, json.dumps({"error": "unauthorized"}))
            return
        # A failed pool acquire (DB locked, disk full) must not drop the
        # connection silently - report it so the UI can show a real state.
        try:
            conn = _conn()
        except Exception as e:
            _log_error(f"503 db unavailable: {e}")
            self._send(503, json.dumps({"error": f"db unavailable: {e}"}))
            return
        try:
            self._route_get(conn)
        finally:
            _release(conn)

    def _route_get(self, conn):
        if self.path in ("/", "/index.html"):
            self._send(200, _HTML, "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._send(200, json.dumps(
                _status_payload(conn, self.server.executor),
                ensure_ascii=False))
        elif self.path.startswith("/api/history"):
            try:
                n = int(self.path.split("n=")[1].split("&")[0])
            except (IndexError, ValueError):
                n = 15
            rows = conn.execute(
                "SELECT id, agent, request, timestamp, latency_ms "
                "FROM audit_logs ORDER BY id DESC LIMIT ?",
                (min(200, max(1, n)),)).fetchall()
            self._send(200, json.dumps(
                [{"id": r[0], "agent": r[1], "request": r[2],
                  "timestamp": r[3], "latency_ms": r[4]}
                 for r in rows], ensure_ascii=False))
        elif self.path == "/api/tasks":
            rows = conn.execute(
                "SELECT q.agent, q.status, t.description "
                "FROM task_queue q JOIN tasks t ON q.task_id = t.id "
                "ORDER BY q.id DESC LIMIT 15").fetchall()
            self._send(200, json.dumps(
                [{"agent": r[0], "status": r[1], "description": r[2]}
                 for r in rows], ensure_ascii=False))
        elif self.path == "/api/verify":
            self._send(200, json.dumps(
                verify_audit_chain(conn), ensure_ascii=False))
        elif self.path == "/api/forged":
            # reuse the forged cache - recomputing every signature on
            # every poll duplicates the status check's O(#signed rows)
            # cost; the rows are only stale until the next count change.
            global _forged_cache
            task_count = conn.execute(
                "SELECT (SELECT COUNT(*) FROM tasks)+"
                "(SELECT COUNT(*) FROM task_queue)").fetchone()[0]
            if _forged_cache.get("count") != task_count:
                from guardian_ai.db import _forged_work_records, \
                    _forged_rows
                _forged_cache = {"count": task_count,
                                 "forged": _forged_work_records(conn),
                                 "rows": _forged_rows(conn)}
            self._send(200, json.dumps(
                _forged_cache.get("rows", []), ensure_ascii=False))
        elif self.path == "/api/doctor":
            # environment self-check - same shared logic as `doctor`;
            # read-only so it belongs in GET, not POST.
            try:
                from guardian_ai.compliance import doctor_checks
                conn = _conn()
                try:
                    checks = doctor_checks(conn, self.server.executor)
                finally:
                    _release(conn)
                self._send(200, json.dumps(
                    {"checks": checks,
                     "all_ok": all(c["ok"] for c in checks)},
                    ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if not self._authorized():
            self._send(401, json.dumps({"error": "unauthorized"}))
            return
        # CSRF: apply to EVERY POST, not just /api/request - routing a
        # path before this check would let a foreign website bypass the
        # protection (the JSON preflight blocks reads, not the request
        # itself). Reject any non-localhost Origin.
        origin = self.headers.get("Origin", "")
        if origin and not origin.startswith(("http://127.0.0.1",
                                             "http://localhost")):
            self._send(403, json.dumps({"error": "foreign origin"}))
            return
        # Same reasoning as Origin: the body cap applies to EVERY POST,
        # not just /api/request - an unchecked rfile.read() on any path
        # is the same memory-exhaustion vector.
        length = int(self.headers.get("Content-Length", 0))
        if length > 65536:
            self._send(413, json.dumps({"error": "body too large"}))
            return
        if self.path == "/api/decrypt":
            self._decrypt()
            return
        # export writes a file - it is a side-effecting operation, so it
        # belongs behind POST (a GET <img> from any site could otherwise
        # trigger exports at will).
        if self.path == "/api/export":
            try:
                conn = _conn()
                try:
                    # same gate as the CLI export - never silently snapshot
                    # a compromised trail (warn that the export is suspect).
                    broken = not verify_audit_chain(conn).get("ok")
                    path = export_audit(conn)
                finally:
                    _release(conn)
                self._send(200, json.dumps(
                    {"path": path, "chain_broken": broken}))
            except RuntimeError as e:
                self._send(500, json.dumps({"error": str(e)}))
            return
        if self.path == "/api/update":
            # same check as the CLI 'update' command - the product's
            # ONLY outbound call: user-invoked (button), read-only,
            # sends nothing. No auto-update without signature checks.
            try:
                import urllib.request
                from guardian_ai import __version__
                req = urllib.request.Request(
                    "https://api.github.com/repos/shizukutanaka/"
                    "GuardianAI/releases/latest",
                    headers={"User-Agent": "shieldai-update-check",
                             "Accept": "application/vnd.github+json"})
                rel = json.loads(
                    urllib.request.urlopen(req, timeout=10).read())
                latest = str(rel.get("tag_name", "")).lstrip("v")

                def _v(s):
                    s = str(s).lstrip("v").split("-")[0]
                    return tuple(int(x) for x in s.split(".")
                                 if x.isdigit())
                self._send(200, json.dumps(
                    {"current": __version__, "latest": latest,
                     "update_available":
                         _v(latest) > _v(__version__)}))
            except Exception as e:
                self._send(502, json.dumps(
                    {"error": ("no releases published yet"
                               if "404" in str(e) else str(e))}))
            return
        if self.path != "/api/request":
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            payload = json.loads(
                self.rfile.read(length).decode("utf-8") or "{}")
            text = str(payload.get("text", "")).strip()
            if not text:
                self._send(400, json.dumps({"error": "empty request"}))
                return
            conn = _conn()  # raises are caught by the outer boundary
            try:
                # Same gate as the CLI (Socratic): never silently write to
                # a compromised audit trail - require explicit client ack.
                chain = verify_audit_chain(conn)
                if not chain.get("ok") and not payload.get("ack_broken"):
                    self._send(409, json.dumps({
                        "error": "chain_broken",
                        "broken_at": chain.get("broken_at"),
                        "reason": chain.get("reason", "")}))
                    return
                result = self.server.router.analyze(text)
                t0 = time.monotonic()
                result["execution"] = self.server.executor.execute(
                    text, result)
                latency_ms = int((time.monotonic() - t0) * 1000)
                # audit first so tasks link to their entry; secrets are
                # redacted before storage (deleted, not processed).
                entry_id = audit_log(conn, result["agent"],
                                     redact(text), redact(str(result)),
                                     latency_ms=latency_ms)
                record_tasks(conn, result["agent"], result["complexity"],
                             result["tasks"],
                             result["execution"].get("steps"),
                             audit_entry_id=entry_id)
            finally:
                _release(conn)  # returned to the pool on every path
            self._send(200, json.dumps({
                "entry_id": entry_id,
                "agent": result["agent"],
                "model": result["model"],
                "complexity": result["complexity"],
                "status": result["execution"].get("status"),
                "answer": result["execution"].get("answer"),
                "llm_model": result["execution"].get("llm_model"),
                "tasks": result["execution"].get("steps", []),
            }, ensure_ascii=False))
        except Exception as e:  # one boundary for the whole POST
            _log_error(f"500 POST {self.path}: {e}")
            self._send(500, json.dumps({"error": str(e)}))

    def _decrypt(self):
        """Decrypt an .enc export and verify the embedded anchor +
        that the exported entries form a chain reaching the signed head
        - same checks as the CLI `decrypt` command."""
        try:
            from pathlib import Path
            from guardian_ai.db import _chain_hash, _state_hmac
            from guardian_ai.encryption import Encryption
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(
                self.rfile.read(length).decode("utf-8") or "{}")
            path = Path(str(payload.get("path", "")).strip())
            raw = Encryption().decrypt(path.read_text(encoding="utf-8"))
            try:
                data = json.loads(raw)
            except ValueError:
                # same as the CLI: a non-JSON payload is just shown, not
                # a 500 - the decrypt itself still worked.
                self._send(200, json.dumps(
                    {"ok": True, "decrypted": raw[:2000],
                     "reason": "not JSON - raw payload returned"},
                    ensure_ascii=False))
                return
            st = data.get("chain_state")
            out = {"ok": False, "reason": "no chain_state in export"}
            if st and st.get("state_hmac") == _state_hmac(
                    st.get("row_count"), st.get("head")):
                prev = ""
                for e in sorted(data["entries"], key=lambda x: x["id"]):
                    prev = _chain_hash(prev, e["agent"], e["request"],
                                       e["result"], e["timestamp"])
                out = ({"ok": True, "entries": st["row_count"],
                        "anchor": f"head {st['head'][:16]}..."}
                       if prev == st["head"]
                       else {"ok": False, "entries": st["row_count"],
                             "anchor": f"head {st['head'][:16]}...",
                             "reason": "entries do not reach signed head"})
            elif st:
                out = {"ok": False, "reason": "anchor signature invalid"}
            self._send(200, json.dumps(out, ensure_ascii=False))
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}))


def serve(port: int = PORT, open_browser: bool = True,
          lang: str = None) -> None:
    """Start the local UI server. Binds 127.0.0.1 only - nothing
    is exposed beyond the loopback interface. `lang` presets the UI
    locale via ?lang= (same mechanism the header selector writes)."""
    try:
        httpd = ThreadingHTTPServer((HOST, port), _Handler)
    except OSError as e:
        # a second instance can't bind - the first is already serving.
        # Report it honestly instead of dropping a traceback into
        # crash.log (double-clicking the exe twice IS a product path).
        if getattr(e, "errno", None) in (98, 48, 10048):
            print(f"ShieldAI is already running on "
                  f"http://{HOST}:{port} - use the URL printed by the "
                  f"first instance (it holds the session token).")
            return
        raise
    httpd.router = Router()
    httpd.executor = Executor()
    # per-run session token - the URL is the credential. A local process
    # that can't see the URL can't reach the API.
    httpd.token = secrets.token_urlsafe(24)
    url = f"http://{HOST}:{port}/?t={httpd.token}"
    if lang:
        url += f"&lang={lang}"
    print(f"ShieldAI UI: {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
