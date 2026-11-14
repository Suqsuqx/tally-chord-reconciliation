"""FastAPI host for two restricted MCP endpoints and a signed sandbox provider webhook."""
import os
import hmac
import hashlib
import json
import logging
import secrets
from datetime import datetime,timezone
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from .db import init_db
from contextlib import asynccontextmanager
from .business import ingest_verified_payment, resolve_shop_entry, ToolFailure
from .mcp import process
from .paystack_connections import complete_paystack_setup
from .notion_connections import (cancel_notion_oauth, complete_notion_oauth,
    initialize_notion_workspace_for_business, select_notion_workspace_parent,
    start_notion_oauth)

logger=logging.getLogger('uvicorn.error')

def session_fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()[:12] if value else None

def _key_names(value):
    """Return bounded JSON object key names without inspecting or logging values."""
    if not isinstance(value,dict):
        return []
    return sorted(str(key).replace('\r','\\r').replace('\n','\\n')[:80] for key in value)[:50]

def mcp_context_shape(data):
    """Describe possible MCP context containers using key names only."""
    params=data.get('params') if isinstance(data,dict) else None
    params=params if isinstance(params,dict) else {}
    arguments=params.get('arguments')
    arguments=arguments if isinstance(arguments,dict) else {}
    return {
        'body_keys':_key_names(data),
        'params_keys':_key_names(params),
        'top_meta_keys':_key_names(data.get('_meta')) if isinstance(data,dict) else [],
        'params_meta_keys':_key_names(params.get('_meta')),
        'argument_keys':_key_names(arguments),
        'arguments_meta_keys':_key_names(arguments.get('_meta')),
    }

@asynccontextmanager
async def lifespan(app):
    if os.getenv('TALLY_ENV','sandbox')!='sandbox':
        raise RuntimeError('This release is sandbox-only; production authentication and provider adapters are not implemented')
    init_db()
    yield

app=FastAPI(title='Tally Reconciliation Sandbox',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)

@app.get('/healthz')
def health():
    return {'status':'ok','service':'tally-mcp','environment':os.getenv('TALLY_ENV','sandbox')}

@app.get('/shop/{shop_slug}')
def shop_entry(shop_slug:str):
    try:
        entry=resolve_shop_entry(shop_slug,os.getenv('TALLY_SHOP_BOUND_SLUG'))
        return RedirectResponse(entry['agent_url'],status_code=307,headers={
            'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex'})
    except ToolFailure as exc:
        status=404 if exc.code in ('SHOP_UNAVAILABLE','SHOP_CONTEXT_MISMATCH') else 503
        return JSONResponse({'error':exc.code,'message':exc.message},status_code=status,
                            headers={'Cache-Control':'no-store','X-Robots-Tag':'noindex'})

async def mcp_endpoint(request:Request,channel:str):
    key=os.getenv('TALLY_SHOP_MCP_TOKEN' if channel=='shop' else 'TALLY_DESK_MCP_TOKEN','')
    if not key or key.startswith('CHANGE_'):
        return JSONResponse({'error':'Server MCP token not configured'},status_code=503)
    auth=request.headers.get('authorization','')
    expected='Bearer '+key
    if not hmac.compare_digest(auth,expected):
        return JSONResponse({'error':'Unauthorized'},status_code=401)
    try:
        data=await request.json()
        if isinstance(data,list):return JSONResponse({'error':'Batch JSON-RPC not implemented'},status_code=400)
        if not isinstance(data,dict):return JSONResponse({'error':'Invalid JSON-RPC request'},status_code=400)
        method=data.get('method')
        incoming_session=request.headers.get('mcp-session-id','')
        if method in ('initialize','tools/call'):
            shape=mcp_context_shape(data)
            params=data.get('params') if isinstance(data.get('params'),dict) else {}
            logger.info('tally_mcp_context channel=%s method=%s tool=%s session_present=%s session_fp=%s header_names=%s body_keys=%s params_keys=%s top_meta_keys=%s params_meta_keys=%s argument_keys=%s arguments_meta_keys=%s',
                        channel,method,params.get('name'),bool(incoming_session),
                        session_fingerprint(incoming_session),','.join(sorted(request.headers.keys())),
                        json.dumps(shape['body_keys'],separators=(',',':')),
                        json.dumps(shape['params_keys'],separators=(',',':')),
                        json.dumps(shape['top_meta_keys'],separators=(',',':')),
                        json.dumps(shape['params_meta_keys'],separators=(',',':')),
                        json.dumps(shape['argument_keys'],separators=(',',':')),
                        json.dumps(shape['arguments_meta_keys'],separators=(',',':')))
        result=process(channel,data)
        headers={'MCP-Protocol-Version':'2025-03-26'}
        if method=='initialize':
            issued_session=secrets.token_urlsafe(24)
            headers['Mcp-Session-Id']=issued_session
            logger.info('tally_mcp_session_issued channel=%s session_fp=%s',channel,session_fingerprint(issued_session))
        return Response(status_code=202) if result is None else JSONResponse(result,headers=headers)
    except json.JSONDecodeError:
        return JSONResponse({'error':'Invalid JSON'},status_code=400)

@app.post('/mcp/shop')
async def shop(request:Request):return await mcp_endpoint(request,'shop')

@app.post('/mcp/desk')
async def desk(request:Request):return await mcp_endpoint(request,'desk')

@app.post('/sandbox/provider-event')
async def provider_event(request:Request):
    if os.getenv('TALLY_ENV','sandbox')!='sandbox':return JSONResponse({'error':'Not available'},status_code=404)
    secret=os.getenv('TALLY_WEBHOOK_SECRET','')
    if not secret or secret.startswith('CHANGE_'):return JSONResponse({'error':'Webhook secret not configured'},status_code=503)
    raw=await request.body()
    timestamp=request.headers.get('x-tally-timestamp','')
    supplied=request.headers.get('x-tally-signature','')
    try:ts=int(timestamp)
    except ValueError:return JSONResponse({'error':'Invalid timestamp'},status_code=401)
    if abs(datetime.now(timezone.utc).timestamp()-ts)>300:
        return JSONResponse({'error':'Expired timestamp'},status_code=401)
    expected='sha256='+hmac.new(secret.encode(),timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied,expected):return JSONResponse({'error':'Invalid signature'},status_code=401)
    try:
        event=json.loads(raw)
        if not isinstance(event,dict):
            raise ToolFailure('INVALID_INPUT','Provider event must be an object')
        result=ingest_verified_payment(event,business_id=event.get('business_id'))
        return JSONResponse(result)
    except (json.JSONDecodeError,ToolFailure) as ex:
        return JSONResponse({'error':getattr(ex,'code','INVALID_JSON'),'message':str(ex)},status_code=400)

SETUP_PAGE_CSS="""
:root{color-scheme:light;--ink:#17352f;--muted:#5f716d;--green:#078a70;--green-dark:#056c59;--mint:#e9f8f3;--cream:#f7f5ef;--line:#dce8e3;--danger:#a53b31;--danger-bg:#fff1ef;--success:#066a56;--success-bg:#e8f8f1}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 15% 0,#dff5ed 0,transparent 34rem),var(--cream);color:var(--ink);font:16px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.page{width:min(100% - 2rem,42rem);margin:0 auto;padding:2rem 0 3rem}.brand{display:flex;align-items:center;gap:.75rem;margin:0 0 1.25rem}.mark{display:grid;place-items:center;width:2.75rem;height:2.75rem;border-radius:14px;background:var(--green);color:#fff;font-size:1.25rem;font-weight:800;box-shadow:0 8px 22px rgba(7,138,112,.2)}.brand-name{font-weight:800;font-size:1.1rem;letter-spacing:-.02em}.brand-note{display:block;color:var(--muted);font-size:.82rem;font-weight:500}
.card{overflow:hidden;background:rgba(255,255,255,.96);border:1px solid rgba(220,232,227,.95);border-radius:24px;box-shadow:0 22px 55px rgba(30,62,54,.1)}.content{padding:clamp(1.4rem,5vw,2.35rem)}.eyebrow{display:inline-flex;align-items:center;gap:.45rem;margin-bottom:1rem;padding:.34rem .68rem;border-radius:999px;background:var(--mint);color:var(--green-dark);font-size:.75rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase}.eyebrow:before{content:"";width:.45rem;height:.45rem;border-radius:50%;background:var(--green)}h1{margin:0;font-size:clamp(1.9rem,7vw,2.65rem);line-height:1.08;letter-spacing:-.045em}p{margin:.75rem 0;color:var(--muted)}.lede{font-size:1.06rem;max-width:35rem}.trust{display:flex;gap:.75rem;margin:1.4rem 0;padding:1rem;border:1px solid var(--line);border-radius:16px;background:#fbfdfc}.trust-icon{display:grid;flex:0 0 auto;place-items:center;width:2rem;height:2rem;border-radius:10px;background:var(--mint);color:var(--green-dark);font-weight:900}.trust strong{display:block;margin-bottom:.1rem;font-size:.92rem}.trust p{margin:0;font-size:.86rem}
.checklist{display:grid;gap:.7rem;margin:1.4rem 0;padding:0;list-style:none}.checklist li{display:flex;gap:.65rem;color:var(--muted);font-size:.92rem}.checklist li:before{content:"✓";display:grid;flex:0 0 auto;place-items:center;width:1.35rem;height:1.35rem;margin-top:.05rem;border-radius:50%;background:var(--mint);color:var(--green-dark);font-size:.76rem;font-weight:900}
form{margin-top:1.65rem}.field{display:block;margin:0 0 1.15rem}.field-label{display:flex;justify-content:space-between;gap:1rem;margin-bottom:.45rem;color:var(--ink);font-size:.92rem;font-weight:750}.optional{color:var(--muted);font-size:.78rem;font-weight:600}input{display:block;width:100%;min-height:3.25rem;padding:.72rem .9rem;border:1px solid #bdcdc7;border-radius:12px;background:#fff;color:var(--ink);font:inherit;outline:0;transition:border-color .15s,box-shadow .15s}input:focus{border-color:var(--green);box-shadow:0 0 0 4px rgba(7,138,112,.12)}.hint{display:block;margin-top:.4rem;color:var(--muted);font-size:.8rem}code{padding:.1rem .32rem;border-radius:5px;background:#edf3f0;color:#31534b;font:600 .88em ui-monospace,SFMono-Regular,Consolas,monospace}details{margin:.8rem 0 1.35rem;border:1px solid var(--line);border-radius:14px;background:#fbfdfc}summary{padding:.85rem 1rem;cursor:pointer;color:var(--ink);font-size:.9rem;font-weight:750}details .details-body{padding:0 1rem 1rem}.button{display:flex;align-items:center;justify-content:center;width:100%;min-height:3.25rem;padding:.78rem 1.1rem;border:0;border-radius:13px;background:var(--green);color:#fff;font:800 .97rem/1 system-ui;cursor:pointer;box-shadow:0 9px 22px rgba(7,138,112,.2);transition:background .15s,transform .15s}.button:hover{background:var(--green-dark);transform:translateY(-1px)}.button:focus-visible{outline:3px solid rgba(7,138,112,.25);outline-offset:3px}.button:disabled{cursor:not-allowed;box-shadow:none;opacity:.55;transform:none}
.status{margin:1rem 0 0;padding:.85rem 1rem;border-radius:12px;font-size:.9rem;font-weight:650}.status:empty{display:none}.status[data-state="working"]{background:#f1f5f3;color:#44635b}.status[data-state="success"]{background:var(--success-bg);color:var(--success)}.status[data-state="error"]{background:var(--danger-bg);color:var(--danger)}.footer{padding:1rem 1.4rem;border-top:1px solid var(--line);background:#fbfdfc;color:var(--muted);text-align:center;font-size:.78rem}.result-icon{display:grid;place-items:center;width:3.5rem;height:3.5rem;margin-bottom:1.25rem;border-radius:18px;background:var(--success-bg);color:var(--success);font-size:1.5rem;font-weight:900}.result-icon.error{background:var(--danger-bg);color:var(--danger)}
@media(max-width:32rem){.page{width:min(100% - 1rem,42rem);padding:.5rem 0 1rem}.brand{margin:.75rem .5rem 1rem}.card{border-radius:20px}.content{padding:1.35rem}.trust{padding:.85rem}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}.button{transition:none}}
"""

PAYSTACK_SETUP_HTML="""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#078a70"><title>Connect Paystack · Tally</title><style>"""+SETUP_PAGE_CSS+"""</style></head>
<body><main class="page"><header class="brand"><span class="mark" aria-hidden="true">T</span><span class="brand-name">Tally<span class="brand-note">Merchant setup</span></span></header>
<section class="card"><div class="content"><span class="eyebrow">Paystack test connection</span><h1>Connect payments securely</h1>
<p class="lede">Link your Paystack account so Tally can create test checkouts and verify customer payments for your business.</p>
<div class="trust"><span class="trust-icon" aria-hidden="true">⌁</span><div><strong>Your key stays private</strong><p>It travels directly to Tally, is encrypted for this business and is never placed in chat.</p></div></div>
<form id="setup"><label class="field"><span class="field-label">Restricted test key</span><input id="key" type="password" autocomplete="off" placeholder="rk_test_…" pattern="rk_test_.+" spellcheck="false" required aria-describedby="key-help"><small class="hint" id="key-help">Use a key beginning <code>rk_test_</code> with <code>transactions:write</code>. Never enter a <code>pk_test_</code> or account-wide <code>sk_test_</code> key.</small></label>
<details><summary>Optional: instant webhook updates</summary><div class="details-body"><label class="field"><span class="field-label">Webhook signing secret <span class="optional">Optional</span></span><input id="secret" type="password" autocomplete="off" placeholder="whsec_…" spellcheck="false"><small class="hint">You can skip this. Tally can verify payment claims directly; add a <code>whsec_</code> secret only for instant event updates.</small></label></div></details>
<button class="button" id="submit" type="submit">Connect Paystack</button></form><p class="status" id="result" role="status" aria-live="polite"></p></div>
<footer class="footer">Secure setup link · Test payments only · You can revoke access from Paystack</footer></section></main>
<script>const token=new URLSearchParams(location.hash.slice(1)).get('token')||'';history.replaceState(null,'',location.pathname);
const form=document.querySelector('#setup'),button=document.querySelector('#submit'),result=document.querySelector('#result');
const status=(message,state)=>{result.textContent=message;result.dataset.state=state};
if(!token){button.disabled=true;status('This setup link is incomplete or expired. Request a fresh Paystack link from Tally.','error')}
form.addEventListener('submit',async e=>{e.preventDefault();if(!token)return;button.disabled=true;button.textContent='Connecting…';status('Verifying your restricted key securely…','working');
try{const response=await fetch('/integrations/paystack/connect',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({setup_token:token,restricted_key:document.querySelector('#key').value,webhook_secret:document.querySelector('#secret').value})});
const body=await response.json();document.querySelector('#key').value='';document.querySelector('#secret').value='';if(response.ok){form.hidden=true;status('Paystack is connected. You can close this page and return to Tally.','success')}else{status(body.message||'Connection failed. Request a new setup link.','error');button.disabled=false;button.textContent='Try again'}}catch(_){status('Tally could not be reached. Check your connection and request a new setup link if this continues.','error');button.disabled=false;button.textContent='Try again'}});</script></body></html>"""

@app.get('/integrations/paystack/setup')
async def paystack_setup_page():
    headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer',
             'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"}
    return HTMLResponse(PAYSTACK_SETUP_HTML,headers=headers)

@app.post('/integrations/paystack/connect')
async def paystack_connect(request:Request):
    try:
        raw=await request.body()
        if not raw or len(raw)>16*1024:raise ValueError('Invalid setup request')
        data=json.loads(raw)
        if not isinstance(data,dict):raise ValueError('Invalid setup request')
        result=await complete_paystack_setup(data.get('setup_token'),data.get('restricted_key'),data.get('webhook_secret'))
        return JSONResponse(result)
    except ToolFailure as exc:
        logger.info('paystack_setup_failed code=%s',exc.code)
        return JSONResponse({'error':exc.code,'message':exc.message},status_code=400,
                            headers={'Cache-Control':'no-store'})
    except (json.JSONDecodeError,ValueError):
        logger.info('paystack_setup_failed code=INVALID_REQUEST')
        return JSONResponse({'error':'INVALID_REQUEST',
                             'message':'The Paystack setup request was invalid. Request a fresh link and try again.'},
                            status_code=400,headers={'Cache-Control':'no-store'})

NOTION_SETUP_HTML="""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#078a70"><title>Connect Notion · Tally</title><style>"""+SETUP_PAGE_CSS+"""</style></head>
<body><main class="page"><header class="brand"><span class="mark" aria-hidden="true">T</span><span class="brand-name">Tally<span class="brand-note">Merchant setup</span></span></header>
<section class="card"><div class="content"><span class="eyebrow">Notion connection</span><h1>Bring your business into Tally</h1>
<p class="lede">Choose one business workspace page. Tally will use only that authorized content and keep readable business records there.</p>
<ul class="checklist"><li>Read the selected business page and its shared content</li><li>Create managed Profile, Catalogue, Policies, Orders and Activity sections inside it</li><li>Keep approved catalogue, order, payment and support updates synchronized automatically</li></ul>
<div class="trust"><span class="trust-icon" aria-hidden="true">✓</span><div><strong>Your authorization is the approval</strong><p>By continuing, you authorize Tally to read the page you select and create or update its managed sections. SQL remains the authoritative transaction record.</p></div></div>
<button class="button" id="connect" type="button">Authorize and set up Notion</button><p class="status" id="result" role="status" aria-live="polite"></p></div>
<footer class="footer">Notion controls page access · Tally stores transactional state securely</footer></section></main>
<script>const token=new URLSearchParams(location.hash.slice(1)).get('token')||'';history.replaceState(null,'',location.pathname);
const button=document.querySelector('#connect'),result=document.querySelector('#result');const status=(message,state)=>{result.textContent=message;result.dataset.state=state};
if(!token){button.disabled=true;status('This setup link is incomplete or expired. Request a fresh Notion link from Tally.','error')}
button.addEventListener('click',async()=>{if(!token)return;button.disabled=true;button.textContent='Opening Notion…';status('Preparing your secure Notion authorization…','working');
try{const response=await fetch('/integrations/notion/start',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({setup_token:token})});const body=await response.json();if(response.ok&&body.authorize_url){location.assign(body.authorize_url);return;}status(body.message||'Connection failed. Request a new setup link.','error')}catch(_){status('Tally could not be reached. Check your connection and request a new setup link if this continues.','error')}button.disabled=false;button.textContent='Try again'});</script></body></html>"""

def _connection_result_html(title,message,success=True):
    icon='✓' if success else '!'
    icon_class='result-icon' if success else 'result-icon error'
    eyebrow='Connection complete' if success else 'Connection not completed'
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#078a70"><title>{title} · Tally</title><style>{SETUP_PAGE_CSS}</style></head>
<body><main class="page"><header class="brand"><span class="mark" aria-hidden="true">T</span><span class="brand-name">Tally<span class="brand-note">Merchant setup</span></span></header><section class="card"><div class="content"><span class="{icon_class}" aria-hidden="true">{icon}</span><span class="eyebrow">{eyebrow}</span><h1>{title}</h1><p class="lede">{message}</p></div><footer class="footer">You can close this page and return to your conversation with Tally</footer></section></main></body></html>'''

NO_STORE_HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer',
                  'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"}

@app.get('/integrations/notion/setup')
async def notion_setup_page():
    return HTMLResponse(NOTION_SETUP_HTML,headers=NO_STORE_HEADERS)

@app.post('/integrations/notion/start')
async def notion_start(request:Request):
    try:
        raw=await request.body()
        if not raw or len(raw)>4*1024:raise ValueError('Invalid setup request')
        data=json.loads(raw)
        if not isinstance(data,dict):raise ValueError('Invalid setup request')
        return JSONResponse(start_notion_oauth(data.get('setup_token')),headers={'Cache-Control':'no-store'})
    except ToolFailure as exc:
        logger.info('notion_oauth_start_failed code=%s',exc.code)
        return JSONResponse({'error':exc.code,'message':exc.message},status_code=400,
                            headers={'Cache-Control':'no-store'})
    except (json.JSONDecodeError,ValueError):
        logger.info('notion_oauth_start_failed code=INVALID_REQUEST')
        return JSONResponse({'error':'INVALID_REQUEST',
                             'message':'This Notion setup request is invalid. Request a fresh Notion link from Tally.'},
                            status_code=400,headers={'Cache-Control':'no-store'})

@app.get('/integrations/notion/callback')
async def notion_callback(request:Request):
    code=request.query_params.get('code')
    state=request.query_params.get('state')
    denied=request.query_params.get('error')
    if denied:
        cancel_notion_oauth(state)
        return HTMLResponse(_connection_result_html('Notion was not connected','No access was granted. Return to Tally and request a fresh setup link whenever you are ready to try again.',False),
                            status_code=400,headers=NO_STORE_HEADERS)
    try:
        result=await complete_notion_oauth(code,state)
        count=len(result['authorized_resources'])
        readable=sum(item.get('read_status')=='readable' for item in result['authorized_resources'])
        parent_page_id=select_notion_workspace_parent(result['business_id'])
        workspace=initialize_notion_workspace_for_business(
            result['business_id'],parent_page_id,backfill=True)
        backfill=workspace.get('backfill') or {}
        action=('created the managed business sections and synchronized' if workspace.get('created')
                else 'confirmed the managed sections and refreshed')
        message=(f'Tally verified {readable} of {count} authorized resource(s), {action} '
                 f'{backfill.get("products",0)} product(s), {backfill.get("orders",0)} order(s) '
                 f'and {backfill.get("support_cases",0)} support case(s). Future approved updates '
                 'will be added automatically.')
        body=_connection_result_html('Notion connected',message)
        return HTMLResponse(body,headers=NO_STORE_HEADERS)
    except (ValueError,ToolFailure) as exc:
        reference='tly-'+secrets.token_hex(5)
        logger.warning('notion_oauth_or_workspace_failed reference=%s code=%s',
                       reference,getattr(exc,'code','NOTION_CONNECTION_FAILED'))
        return HTMLResponse(_connection_result_html('Notion connection failed','Tally could not complete the connection. Return to Tally and request a fresh setup link.',False),
                            status_code=400,headers=NO_STORE_HEADERS)

# Business-routed Paystack TEST webhook. Platform feature remains default-off.
from .paystack_webhook import router as paystack_webhook_router
app.include_router(paystack_webhook_router)
