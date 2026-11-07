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
@media(max-width:560px){
  .req-row{flex-direction:column}
  .health{flex-wrap:wrap}
}
</style></head>
<body>
<div class="wrap">

<header>
  <div class="logo">ShieldAI</div>
  <div class="health" id="health" role="status" aria-live="polite">
    <span class="dot"><i></i>checking&hellip;</span>
  </div>
</header>

<main>
  <section class="hero" aria-label="Request">
    <label for="req">何を処理しますか?</label>
    <div class="req-row">
      <input id="req" type="text" autocomplete="off" autofocus
        placeholder="例: サーバー障害 ERROR 10.0.0.1 ログを確認して"
        aria-describedby="hint">
      <button class="btn" id="run" onclick="submit()">実行</button>
    </div>
    <div id="hint" class="dim" style="font-size:12px;margin-top:8px">
      Enter で送信 &middot; 分類→計画→決定論的実行→監査 (100% ローカル)
    </div>
    <div class="actions">
      <button class="btn ghost" onclick="doVerify()">Verify chain</button>
      <button class="btn ghost" onclick="doExport()">Export audit</button>
      <button class="btn ghost" onclick="doDecrypt()">Decrypt</button>
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
        onclick="showTab('audit',this)">Audit log</button>
      <button class="tab" role="tab" aria-selected="false"
        onclick="showTab('tasks',this)">Work record</button>
    </div>
    <table id="audit" aria-label="Audit log"></table>
    <table id="tasks" aria-label="Work record" style="display:none"></table>
  </section>
</main>
</div>
<div class="toast" id="toast" role="alert"></div>

<script>
const $=id=>document.getElementById(id);
const J=u=>fetch(u).then(r=>{if(!r.ok)throw new Error(r.status);return r.json()});
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
        chain.ok?'tip ok':'tip broken'}</span>`+
      (chain.forged_tasks?`<span class="dot bad"><i></i>${
        chain.forged_tasks} forged</span>`:'')+
      `<span class="dot ${s.kms_ok===false?'bad':'ok'}"><i></i>${
        s.kms_ok===false?'key missing':'key ok'}</span>`+
      `<span class="dot ${s.ollama_up?'ok':'warn'}"><i></i>${
        s.ollama_up?(s.models[0]||'model'):'deterministic'}</span>`+
      `<span class="dot"><i></i>${s.audit_entries} entries</span>`+
      ((s.triggers_missing||[]).length?
       `<span class="dot warn"><i></i>${s.triggers_missing.length} triggers missing</span>`:'');
  }catch(e){
    $('health').innerHTML='<span class="dot bad"><i></i>offline</span>';
  }
  loadTables();
}
/* ---------- tables ---------- */
async function loadTables(){
  const h=await J('/api/history?n=15');
  $('audit').innerHTML='<tr><th>#</th><th>agent</th><th>request</th><th>ms</th><th>time</th></tr>'+
    (h.length?h.map(r=>`<tr><td class="mono">${r.id}</td><td>${esc(r.agent)}</td>
     <td class="dim">${esc((r.request||'').slice(0,48))}</td>
     <td class="mono">${r.latency_ms??'-'}</td>
     <td class="dim mono">${esc((r.timestamp||'').slice(5,19))}</td></tr>`).join('')
     :'<tr><td colspan="5" class="empty">no entries yet</td></tr>');
  const t=await J('/api/tasks');
  const sc={done:'ok',blocked:'bad',failed:'bad',skipped:'warn',pending:'warn'};
  $('tasks').innerHTML='<tr><th>agent</th><th>status</th><th>description</th></tr>'+
    (t.length?t.map(r=>`<tr><td>${esc(r.agent)}</td>
     <td>${badge(r.status,sc[r.status]||'warn')}</td>
     <td class="dim">${esc(r.description||'')}</td></tr>`).join('')
     :'<tr><td colspan="3" class="empty">no tasks yet</td></tr>');
}
function showTab(id,el){
  document.querySelectorAll('.tab').forEach(t=>{
    t.classList.remove('on');t.setAttribute('aria-selected','false')});
  el.classList.add('on');el.setAttribute('aria-selected','true');
  $('audit').style.display=id==='audit'?'':'none';
  $('tasks').style.display=id==='tasks'?'':'none';
}
/* ---------- pipeline run: every state visible ---------- */
const PIPE=['ingestion','extraction','verification','synthesis','audit'];
function paintStages(done=[]){
  $('stages').innerHTML=PIPE.map(t=>{
    const s=done.find(x=>(x.step||x.type)===t);
    const cls=s?(s.status==='ok'||s.status==='done'?'done':
      s.status==='blocked'?'blocked':'skip'):'run';
    return `<div class="stage ${cls}">${t}</div>`;
  }).join('');
}
let busy=false;
async function submit(){
  const text=$('req').value.trim();
  if(!text||busy)return;
  busy=true;$('run').disabled=true;$('run').textContent='実行中…';
  $('result').classList.remove('show');
  paintStages();
  const t0=Date.now();
  try{
    let body={text};
    let r=await fetch('/api/request',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)}).then(r=>r.json());
    if(r.error==='chain_broken'){
      // same explicit-ack gate as the CLI - never write silently
      if(confirm(`Audit chain is broken at #${r.broken_at}: ${r.reason}\n\n`+
                 `The trail may be tampered. Continue anyway?`)){
        r=await fetch('/api/request',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({text,ack_broken:true})}).then(r=>r.json());
      }else{
        paintStages([]);
        toast('中止しました','破損した監査チェーンへの書き込みを拒否');
        busy=false;$('run').disabled=false;$('run').textContent='実行';
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
    $('result-body').textContent=r.answer||'(no answer)';
    const llm=$('llm-note');
    if(r.llm_model){
      llm.style.display='block';
      llm.textContent=`LLM inference (${r.llm_model}) - model-generated, unverified`;
    }else llm.style.display='none';
    $('req').value='';
    refresh();
  }catch(e){
    paintStages(PIPE.map(t=>({step:t,status:'blocked'})));
    toast('実行に失敗しました',
      `${e.message} - 再試行するか status で原因を確認してください`);
  }finally{
    busy=false;$('run').disabled=false;$('run').textContent='実行';
  }
}
/* ---------- secondary actions ---------- */
async function doVerify(){
  try{
    const v=await J('/api/verify');
    // forged tasks / missing chain_state have broken_at=null - '#null'
    // would be a wrong display, so the reason alone carries those.
    toast(v.ok?`chain ok - ${v.entries} entries verified (HMAC + chain_state)`
             :`chain BROKEN${v.broken_at!=null?' at #'+v.broken_at:''}`,
          v.ok?'':v.reason||'');
  }catch(e){toast('verify failed',e.message)}
}
async function doExport(){
  try{
    const r=await fetch('/api/export',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:'{}'}).then(r=>r.json());
    window._lastExport=r.path;
    toast('audit exported',
      r.chain_broken?'WARNING: audit chain is broken - this export '
                    'captures compromised data':r.path);
  }catch(e){toast('export failed',e.message)}
}
async function doDecrypt(){
  // export already returned the path - offer it so the user is not
  // expected to memorise a filesystem path (export->decrypt flow).
  const path=prompt('decrypt file path (.enc):',window._lastExport||'');
  if(!path)return;
  try{
    const r=await fetch('/api/decrypt',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path})}).then(r=>r.json());
    // non-JSON payloads return {decrypted} with no entries - show the
    // text (esc via textContent) instead of 'undefined entries'.
    if(r.decrypted!=null){
      $('result').classList.add('show');
      $('result-head').innerHTML=badge('DECRYPTED','acc');
      $('result-body').textContent=r.decrypted;
      toast('decrypted (not JSON)',r.reason||'');
      return;
    }
    toast(r.ok?`verified: ${r.entries} entries reach signed head`
             :`INVALID: ${r.reason}`,r.anchor||'');
  }catch(e){toast('decrypt failed',e.message)}
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
        from guardian_ai.db import _forged_work_records
        forged = _forged_work_records(conn)
        _forged_cache = {"count": task_count, "forged": forged}
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
    return {"audit_entries": count, "kms_ok": kms_ok,
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

    def do_GET(self):
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
            # parity with the CLI 'forged' command - the UI needs to see
            # WHICH rows are fabricated, not just 'tip broken'.
            from guardian_ai.db import _forged_rows
            self._send(200, json.dumps(
                _forged_rows(conn), ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
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


def serve(port: int = PORT, open_browser: bool = True) -> None:
    """Start the local UI server. Binds 127.0.0.1 only - nothing
    is exposed beyond the loopback interface."""
    httpd = ThreadingHTTPServer((HOST, port), _Handler)
    httpd.router = Router()
    httpd.executor = Executor()
    url = f"http://{HOST}:{port}"
    print(f"ShieldAI UI: {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
