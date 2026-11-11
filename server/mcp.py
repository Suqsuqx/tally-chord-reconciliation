"""Minimal stateless MCP Streamable HTTP transport. Responses use JSON-RPC over HTTPS."""
import json
import os
from .business import invoke, ToolFailure

# Tools must use exact public names below; per-server allowlists are enforced twice.
S=lambda desc,props,required=[]:{'description':desc,'inputSchema':{'type':'object','properties':props,'required':required,'additionalProperties':False}}
P=lambda d,typ='string':{'type':typ,'description':d}
TOKEN=P('Opaque sandbox session from link_identity. Never send it to the end user.')
SHOP={
 'link_identity':S('Redeem a one-time sandbox CUSTOMER access code. Never display returned session token.',{'code':P('One-time code')},['code']),
 'get_catalog':S('Current prices and available quantities from merchant database, not knowledge files.',{}),
 'create_order':S('Create order for linked customer; server rechecks stock and calculates total. Reuse request_id on retries.',
       {'session_token':TOKEN,'items':{'type':'array','items':{'type':'object','properties':{'product_id':P('Catalog item ID'),'quantity':P('Positive quantity','integer')},'required':['product_id','quantity']}},'request_id':P('Unique idempotency key stable for retry')},['session_token','items','request_id']),
 'get_my_order':S('Get order only if owned by linked customer.',{'session_token':TOKEN,'order_id':P('Order reference')},['session_token','order_id']),
 'record_payment_claim':S('Record unverified customer claim; NEVER confirms payment.',{'session_token':TOKEN,'order_id':P('Order reference'),'note':P('Customer wording')},['session_token','order_id']),
 'create_support_case':S('Escalate complaint or uncertain question to staff queue.',{'session_token':TOKEN,'category':{'type':'string','enum':['complaint','inquiry']},'message':P('Customer issue'),'order_id':P('Optional customer order reference')},['session_token','category','message']),
 'get_my_support_case':S('Read one customer-owned case and recorded staff reply.',{'session_token':TOKEN,'case_id':P('Case reference')},['session_token','case_id']),
}
DESK={
 'link_identity':S('Redeem one-time sandbox STAFF access code. Never display session token.',{'code':P('One-time code')},['code']),
 'get_catalog':S('Read catalogue and available quantities for authenticated merchant.',{'session_token':TOKEN},['session_token']),
 'upsert_product':S('ADMIN ONLY. Create/update a product after merchant confirms preview. Price in kobo.',{
   'session_token':TOKEN,'name':P('Product name'),'price_minor':P('NGN amount in kobo (integer)','integer'),
   'stock_on_hand':P('Physical units on hand','integer'),'low_stock_threshold':P('Low stock warning threshold','integer')},
   ['session_token','name','price_minor','stock_on_hand']),
 'get_order_queue':S('Merchant-scoped order queue.',{'session_token':TOKEN},['session_token']),
 'update_order_status':S('Advance paid order preparing, dispatched, fulfilled, one step at a time.',{
    'session_token':TOKEN,'order_id':P('Order ID'),'new_status':{'type':'string','enum':['preparing','dispatched','fulfilled']}},['session_token','order_id','new_status']),
 'get_reconciliation_report':S('Compute matched verified transfers, payment mismatches, unmatched credits and unpaid orders from the ledger.',{'session_token':TOKEN},['session_token']),
 'get_merchant_catchup':S('Merchant catch-up since supplied timestamp or previous 24h: recent activity, reconciliation, inventory alerts, support exceptions.',{'session_token':TOKEN,'since':P('Optional ISO-8601 timestamp with timezone, e.g. 2026-11-04T08:00:00+01:00')},['session_token']),
 'get_inventory_alerts':S('Low stock and sold-out items from real on-hand minus reserved quantity.',{'session_token':TOKEN},['session_token']),
 'record_stock_adjustment':S('ADMIN ONLY. Record physical count adjustment with reason and audit entry.',{
    'session_token':TOKEN,'product_id':P('Product ID'),'new_stock_on_hand':P('Physical units on hand','integer'),
    'reason':P('Reason for stock discrepancy')},['session_token','product_id','new_stock_on_hand','reason']),
 'list_support_cases':S('Merchant scoped support queue.',{'session_token':TOKEN},['session_token']),
 'reply_support_case':S('Store merchant answer in case history; delivery remains unverified unless a messaging integration succeeds.',{
    'session_token':TOKEN,'case_id':P('Case ID'),'message':P('Merchant-approved answer')},['session_token','case_id','message']),
}
ALL={'shop':SHOP,'desk':DESK}

def _attach_admin_setup_links(channel,name,result):
    """Attach enabled provider setup links to the initial Admin link without adding MCP tools."""
    if channel!='desk' or name!='link_identity' or not isinstance(result,dict) or result.get('role')!='admin':
        return result
    session_token=result.get('session_token')
    links={}
    if os.getenv('TALLY_PAYSTACK_CONNECTIONS_ENABLED','false').lower()=='true':
        from .paystack_connections import issue_paystack_setup_link
        try:
            links['paystack']=issue_paystack_setup_link(session_token)
        except ToolFailure as ex:
            links['paystack']={'status':'unavailable','error':ex.code}
    if os.getenv('TALLY_NOTION_CONNECTIONS_ENABLED','false').lower()=='true':
        from .notion_connections import issue_notion_setup_link
        try:
            links['notion']=issue_notion_setup_link(session_token)
        except ToolFailure as ex:
            links['notion']={'status':'unavailable','error':ex.code}
    if links:
        result=dict(result)
        result['provider_setup']=links
    return result

def process(channel,body):
    request_id=body.get('id')
    method=body.get('method')
    if method=='initialize':
        return {'jsonrpc':'2.0','id':request_id,'result':{
            'protocolVersion':'2025-03-26','capabilities':{'tools':{'listChanged':False}},
            'serverInfo':{'name':'tally-'+channel,'version':'1.2.0'},
            'instructions':'Tally sandbox. Only tool results are authoritative. Identity links are sandbox codes, not verified WhatsApp senders.'}}
    if method=='ping':return {'jsonrpc':'2.0','id':request_id,'result':{}}
    if method=='notifications/initialized':return None
    if method=='tools/list':
        return {'jsonrpc':'2.0','id':request_id,'result':{'tools':[
            {'name':name,**data} for name,data in ALL[channel].items()]}}
    if method=='tools/call':
        name=body.get('params',{}).get('name')
        args=body.get('params',{}).get('arguments',{})
        if name not in ALL[channel]:
            return {'jsonrpc':'2.0','id':request_id,'result':{'isError':True,'content':[{'type':'text','text':json.dumps({'error':'FORBIDDEN','message':'Tool not enabled'})}]}}
        try:
            result=invoke(channel,name,args)
            result=_attach_admin_setup_links(channel,name,result)
            return {'jsonrpc':'2.0','id':request_id,'result':{'content':[{'type':'text','text':json.dumps(result,ensure_ascii=False)}]}}
        except ToolFailure as ex:
            return {'jsonrpc':'2.0','id':request_id,'result':{'isError':True,'content':[{'type':'text','text':json.dumps({'error':ex.code,'message':ex.message})}]}}
        except Exception as ex:
            return {'jsonrpc':'2.0','id':request_id,'result':{'isError':True,'content':[{'type':'text','text':json.dumps({'error':'SERVER_ERROR','message':'Unexpected server error'})}]}}
    return {'jsonrpc':'2.0','id':request_id,'error':{'code':-32601,'message':'Method not found'}}
