"""FastAPI host for two restricted MCP endpoints and a signed sandbox provider webhook."""
import os
import hmac
import hashlib
import json
from datetime import datetime,timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from .db import init_db
from contextlib import asynccontextmanager
from .business import seed, ingest_verified_payment, ToolFailure
from .mcp import process

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
        result=process(channel,data)
        return Response(status_code=202) if result is None else JSONResponse(result,headers={'MCP-Protocol-Version':'2025-03-26'})
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
