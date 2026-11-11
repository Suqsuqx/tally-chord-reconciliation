"""FastAPI host for two restricted MCP endpoints and a signed sandbox provider webhook."""
import os
import hmac
import hashlib
import json
import logging
import secrets
from datetime import datetime,timezone
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from .db import init_db
from contextlib import asynccontextmanager
from .business import seed, ingest_verified_payment, ToolFailure
from .mcp import process
from .paystack_connections import complete_paystack_setup
from .notion_connections import cancel_notion_oauth, complete_notion_oauth, start_notion_oauth

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
    seed()
    yield

app=FastAPI(title='Tally Reconciliation Sandbox',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)

@app.get('/healthz')
def health():
    return {'status':'ok','service':'tally-mcp','environment':os.getenv('TALLY_ENV','sandbox')}

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
        result=ingest_verified_payment(json.loads(raw))
        return JSONResponse(result)
    except (json.JSONDecodeError,ToolFailure) as ex:
        return JSONResponse({'error':getattr(ex,'code','INVALID_JSON'),'message':str(ex)},status_code=400)

PAYSTACK_SETUP_HTML="""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect Paystack to Tally</title>
<style>body{font:16px system-ui;max-width:34rem;margin:3rem auto;padding:0 1rem}label{display:block;margin:1rem 0}input{width:100%;padding:.7rem}button{padding:.8rem 1rem}</style>
<h1>Connect Paystack TEST</h1><p>Enter credentials from your Paystack dashboard. They are sent directly to Tally and are never placed in chat.</p>
<form id="setup"><label>Restricted TEST key<input id="key" type="password" autocomplete="off" required></label>
<label>Webhook signing secret<input id="secret" type="password" autocomplete="off" required></label>
<button>Connect</button></form><p id="result" role="status"></p>
<script>const token=new URLSearchParams(location.hash.slice(1)).get('token')||'';history.replaceState(null,'',location.pathname);
document.querySelector('#setup').addEventListener('submit',async e=>{e.preventDefault();const result=document.querySelector('#result');result.textContent='Connecting…';
const response=await fetch('/integrations/paystack/connect',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({setup_token:token,restricted_key:document.querySelector('#key').value,webhook_secret:document.querySelector('#secret').value})});
const body=await response.json();document.querySelector('#key').value='';document.querySelector('#secret').value='';result.textContent=response.ok?'Paystack TEST connected. You may close this page.':(body.message||'Connection failed. Request a new setup link.');});</script>"""

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
    except (json.JSONDecodeError,ValueError,ToolFailure):
        return JSONResponse({'error':'CONNECTION_FAILED','message':'Connection failed. Request a new setup link.'},status_code=400)

NOTION_SETUP_HTML="""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect Notion to Tally</title>
<style>body{font:16px system-ui;max-width:34rem;margin:3rem auto;padding:0 1rem}button{padding:.8rem 1rem}</style>
<h1>Connect Notion</h1>
<p>Notion will ask you to choose the ASYAN SHOP pages Tally may read. Nothing is imported until you approve a preview.</p>
<button id="connect">Choose pages in Notion</button><p id="result" role="status"></p>
<script>const token=new URLSearchParams(location.hash.slice(1)).get('token')||'';history.replaceState(null,'',location.pathname);
document.querySelector('#connect').addEventListener('click',async()=>{const result=document.querySelector('#result');result.textContent='Opening Notion…';
const response=await fetch('/integrations/notion/start',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({setup_token:token})});
const body=await response.json();if(response.ok&&body.authorize_url){location.assign(body.authorize_url);return;}result.textContent=body.message||'Connection failed. Request a new setup link.';});</script>"""

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
    except (json.JSONDecodeError,ValueError,ToolFailure):
        return JSONResponse({'error':'CONNECTION_FAILED','message':'Connection failed. Request a new setup link.'},
                            status_code=400,headers={'Cache-Control':'no-store'})

@app.get('/integrations/notion/callback')
async def notion_callback(request:Request):
    code=request.query_params.get('code')
    state=request.query_params.get('state')
    denied=request.query_params.get('error')
    if denied:
        cancel_notion_oauth(state)
        return HTMLResponse('<!doctype html><meta charset="utf-8"><title>Notion not connected</title><p>Notion access was not granted. Return to Tally and request a new setup link if you want to try again.</p>',
                            status_code=400,headers=NO_STORE_HEADERS)
    try:
        result=await complete_notion_oauth(code,state)
        count=len(result['authorized_resources'])
        readable=sum(item.get('read_status')=='readable' for item in result['authorized_resources'])
        body=f'<!doctype html><meta charset="utf-8"><title>Notion connected</title><p>Notion connected. Tally discovered {count} authorized resource(s) and verified content reads for {readable}. You may close this page and return to Tally for the import preview.</p>'
        return HTMLResponse(body,headers=NO_STORE_HEADERS)
    except (ValueError,ToolFailure):
        return HTMLResponse('<!doctype html><meta charset="utf-8"><title>Notion connection failed</title><p>Notion could not be connected. Return to Tally and request a new setup link.</p>',
                            status_code=400,headers=NO_STORE_HEADERS)

# Business-routed Paystack TEST webhook. Platform feature remains default-off.
from .paystack_webhook import router as paystack_webhook_router
app.include_router(paystack_webhook_router)
