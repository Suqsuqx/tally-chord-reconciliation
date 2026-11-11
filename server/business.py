"""Business tools: all private operations require validated sandbox session tokens."""
import hashlib
import os
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from .db import tx, rowdict

BUSINESS_ID = 'sandbox-cedar-bakes'

class ToolFailure(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def new_id(prefix):
    return f'{prefix}-{uuid4().hex[:12]}'

def digest(s):
    return hashlib.sha256(s.encode('utf8')).hexdigest()

def audit(conn, actor, action, target=None, detail=None):
    conn.execute('INSERT INTO audit VALUES(?,?,?,?,?,?,?)',
                 (new_id('aud'), actor['business_id'], actor['id'], action, target, json.dumps(detail or {}), now()))

def require(cond, code, message):
    if not cond:
        raise ToolFailure(code, message)

def seed():
    with tx() as c:
        c.execute('INSERT OR IGNORE INTO businesses VALUES(?,?,?)', (BUSINESS_ID, 'Cedar Bakes (sandbox)', 'NGN'))
        for a in [
            ('cust-ada','customer','customer','Ada (test customer)'),
            ('cust-bola','customer','customer','Bola (test customer)'),
            ('staff-eni','staff','admin','Eni (test Admin)'),
            ('staff-tola','staff','operator','Tola (test Operator)'),
            ('staff-femi','staff','operator','Femi (test Operator)'),
        ]:
            c.execute('INSERT OR IGNORE INTO actors (id,business_id,kind,role,display_name) VALUES(?,?,?,?,?)',
                      (a[0],BUSINESS_ID,a[1],a[2],a[3]))
        for item in [
            ('cup-choc','Chocolate cupcake',250000,14,3),
            ('cup-vanilla','Vanilla cupcake',200000,0,3),
            ('brownie','Brownie box',650000,5,2),
        ]:
            c.execute('''INSERT OR IGNORE INTO products
                    (id,business_id,name,price_minor,stock_on_hand,stock_reserved,low_stock_threshold,active,updated_at)
                    VALUES(?,?,?,?,?,0,?,1,?)''',
                    (item[0],BUSINESS_ID,item[1],item[2],item[3],item[4],now()))

def issue_link_code(actor_id, ttl_minutes=10):
    require(os.getenv('TALLY_ENV','sandbox')=='sandbox','SANDBOX_ONLY','Demo codes are disabled outside sandbox')
    with tx() as c:
        a=c.execute('SELECT * FROM actors WHERE id=? AND active=1',(actor_id,)).fetchone()
        require(a is not None, 'NOT_FOUND', 'Unknown active actor')
        code=secrets.token_urlsafe(24)
        exp=(datetime.now(timezone.utc)+timedelta(minutes=ttl_minutes)).isoformat()
        c.execute('INSERT INTO access_codes VALUES(?,?,?,NULL)',(digest(code),actor_id,exp))
        return code

def link_identity(code, channel):
    require(os.getenv('TALLY_ENV','sandbox')=='sandbox','SANDBOX_ONLY','Demo linking is disabled outside sandbox')
    with tx() as c:
        rec=c.execute('SELECT * FROM access_codes WHERE code_hash=?',(digest(code),)).fetchone()
        require(rec is not None and rec['used_at'] is None and rec['expires_at']>now(),
                'INVALID_CODE', 'This access code is invalid or expired')
        a=c.execute('SELECT * FROM actors WHERE id=? AND active=1',(rec['actor_id'],)).fetchone()
        require(a is not None, 'FORBIDDEN', 'Actor inactive')
        require((channel=='shop' and a['kind']=='customer') or (channel=='desk' and a['kind']=='staff'),
                'FORBIDDEN','Access code does not belong to this channel')
        c.execute('UPDATE access_codes SET used_at=? WHERE code_hash=?',(now(),digest(code)))
        session=secrets.token_urlsafe(32)
        expires=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
        c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(digest(session),a['id'],expires,now()))
        return {'session_token':session,'role':a['role'],'business_name':'Cedar Bakes (sandbox)',
                'expires_at':expires,'note':'Sandbox access only; not verified WhatsApp channel identity.'}

def actor_from_token(conn, token, channel):
    require(isinstance(token,str) and len(token)>20,'UNAUTHORIZED','Please link your sandbox identity first')
    a=conn.execute('''SELECT a.* FROM sessions s JOIN actors a ON a.id=s.actor_id
                      WHERE s.token_hash=? AND s.expires_at>? AND a.active=1''',(digest(token),now())).fetchone()
    require(a is not None,'UNAUTHORIZED','Session expired or invalid. Link your identity again')
    require((channel=='shop' and a['kind']=='customer') or (channel=='desk' and a['kind']=='staff'),
            'FORBIDDEN','This session cannot use these tools')
    return a

def require_role(actor,role):
    require(actor['role']==role,'FORBIDDEN',f'Only a {role} may perform this action')

def get_catalog(channel='shop',session_token=None):
    with tx() as c:
        if channel=='desk':actor_from_token(c,session_token,channel)
        products=c.execute('SELECT * FROM products WHERE business_id=? AND active=1 ORDER BY name',(BUSINESS_ID,)).fetchall()
        return {'business':'Cedar Bakes (sandbox)','currency':'NGN','products':[
            {'id':p['id'],'name':p['name'],'price_minor':p['price_minor'],
             'available_qty':max(0,p['stock_on_hand']-p['stock_reserved']),
             'available':p['stock_on_hand']-p['stock_reserved']>0} for p in products]}

def upsert_product(session_token,name,price_minor,stock_on_hand,low_stock_threshold=3):
    require(isinstance(name,str) and name.strip(),'INVALID_INPUT','Product name required')
    require(isinstance(price_minor,int) and price_minor>=0,'INVALID_INPUT','Price must be nonnegative integer minor units')
    require(isinstance(stock_on_hand,int) and stock_on_hand>=0,'INVALID_INPUT','Stock must be nonnegative integer')
    require(isinstance(low_stock_threshold,int) and low_stock_threshold>=0,'INVALID_INPUT','Threshold must be nonnegative integer')
    with tx() as c:
        a=actor_from_token(c,session_token,'desk');require_role(a,'admin')
        prior=c.execute('SELECT * FROM products WHERE business_id=? AND name=? COLLATE NOCASE',(a['business_id'],name.strip())).fetchone()
        if prior:
            require(stock_on_hand>=prior['stock_reserved'],'STOCK_RESERVED','Cannot set physical stock lower than outstanding reservations')
            pid=prior['id']
            c.execute('UPDATE products SET price_minor=?,stock_on_hand=?,low_stock_threshold=?,active=1,updated_at=? WHERE id=?',
                      (price_minor,stock_on_hand,low_stock_threshold,now(),pid))
        else:
            pid=new_id('prd')
            c.execute('''INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?,?)''',
                      (pid,a['business_id'],name.strip(),price_minor,'NGN',stock_on_hand,0,low_stock_threshold,1,now()))
        audit(c,a,'product.upserted',pid,{'price_minor':price_minor,'stock_on_hand':stock_on_hand})
        return {'product_id':pid,'name':name.strip(),'price_minor':price_minor,'stock_on_hand':stock_on_hand}

def create_order(session_token,items,request_id):
    require(isinstance(request_id,str) and len(request_id)>=4,'INVALID_INPUT','Stable request_id required for safe retries')
    require(isinstance(items,list) and len(items)>0 and len(items)<=20,'INVALID_INPUT','At least one item required')
    with tx() as c:
        a=actor_from_token(c,session_token,'shop')
        parsed={}
        for item in items:
            require(isinstance(item,dict),'INVALID_INPUT','Each item must be an object')
            pid=item.get('product_id');qty=item.get('quantity')
            require(isinstance(pid,str) and isinstance(qty,int) and 0<qty<=100,'INVALID_INPUT','Valid product_id and quantity required')
            parsed[pid]=parsed.get(pid,0)+qty
        prior=c.execute('SELECT * FROM orders WHERE business_id=? AND customer_id=? AND idempotency_key=?',
                        (a['business_id'],a['id'],request_id)).fetchone()
        if prior:
            old={r['product_id']:r['qty'] for r in c.execute('SELECT product_id,qty FROM order_items WHERE order_id=?',(prior['id'],)).fetchall()}
            require(old==parsed,'IDEMPOTENCY_CONFLICT','This request ID was previously used for different items')
            return {'order_id':prior['id'],'total_minor':prior['total_minor'],'currency':prior['currency'],'status':prior['status'],'duplicate':True}
        total=0;rows=[]
        for pid,qty in parsed.items():
            p=c.execute('SELECT * FROM products WHERE business_id=? AND id=? AND active=1',(a['business_id'],pid)).fetchone()
            require(p is not None,'UNAVAILABLE',f'Product {pid} not available')
            available=p['stock_on_hand']-p['stock_reserved']
            require(available>=qty,'OUT_OF_STOCK',f'{p["name"]} is unavailable in the requested quantity (available: {available})')
            total+=p['price_minor']*qty;rows.append((p,qty))
        oid=new_id('TLY')
        c.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?)',(oid,a['business_id'],a['id'],total,'NGN','awaiting_payment',request_id,now(),now()))
        for p,qty in rows:
            c.execute('INSERT INTO order_items VALUES(?,?,?,?,?)',(oid,p['id'],p['name'],qty,p['price_minor']))
            c.execute('UPDATE products SET stock_reserved=stock_reserved+?,updated_at=? WHERE id=?',(qty,now(),p['id']))
        audit(c,a,'order.created',oid,{'total_minor':total})
        return {'order_id':oid,'total_minor':total,'currency':'NGN','status':'awaiting_payment','duplicate':False}

def get_my_order(session_token,order_id):
    with tx() as c:
        a=actor_from_token(c,session_token,'shop')
        o=c.execute('SELECT * FROM orders WHERE id=? AND business_id=? AND customer_id=?',(order_id,a['business_id'],a['id'])).fetchone()
        require(o is not None,'NOT_FOUND','Order not found for this customer')
        items=c.execute('SELECT name,qty,price_minor FROM order_items WHERE order_id=?',(order_id,)).fetchall()
        return {'order_id':o['id'],'total_minor':o['total_minor'],'currency':o['currency'],'status':o['status'],
                'items':[rowdict(i) for i in items]}

def record_payment_claim(session_token,order_id,note='Customer reports transfer'):
    with tx() as c:
        a=actor_from_token(c,session_token,'shop')
        o=c.execute('SELECT * FROM orders WHERE id=? AND business_id=? AND customer_id=?',(order_id,a['business_id'],a['id'])).fetchone()
        require(o is not None,'NOT_FOUND','Order not found for this customer')
        cid=new_id('clm')
        c.execute('INSERT INTO payment_claims VALUES(?,?,?,?,?)',(cid,order_id,a['id'],str(note)[:500],now()))
        audit(c,a,'payment.claimed',order_id)
        return {'claim_id':cid,'order_id':order_id,'status':o['status'],'verified':False}

def ingest_verified_payment(event,business_id=BUSINESS_ID):
    require(event.get('event_status')=='success','INVALID_PAYMENT','Only successful provider events may settle orders')
    require(isinstance(event.get('event_id'),str) and isinstance(event.get('reference'),str),'INVALID_INPUT','Missing event id or reference')
    require(isinstance(event.get('amount_minor'),int) and event['amount_minor']>0,'INVALID_INPUT','Invalid amount')
    require(isinstance(event.get('currency'),str) and len(event['currency'])==3,'INVALID_INPUT','Invalid currency')
    with tx() as c:
        prior=c.execute('SELECT * FROM payment_events WHERE event_id=?',(event['event_id'],)).fetchone()
        if prior:
            require(prior['reference']==event['reference'] and prior['amount_minor']==event['amount_minor'] and prior['currency']==event['currency'],'EVENT_ID_CONFLICT','The event ID was already used for different payment details')
            return {'event_id':event['event_id'],'match_status':prior['match_status'],'duplicate':True}
        o=c.execute('SELECT * FROM orders WHERE id=? AND business_id=?',(event['reference'],business_id)).fetchone()
        if o is None:status='unmatched_reference';order_id=None
        elif o['total_minor']!=event['amount_minor']:status='amount_mismatch';order_id=o['id']
        elif o['currency']!=event['currency']:status='currency_mismatch';order_id=o['id']
        elif o['status']!='awaiting_payment':status='already_processed';order_id=o['id']
        else:
            status='matched';order_id=o['id']
            c.execute('UPDATE orders SET status=?,updated_at=? WHERE id=?',('confirmed',now(),o['id']))
        c.execute('INSERT INTO payment_events VALUES(?,?,?,?,?,?,?,?,?)',(event['event_id'],business_id,event['reference'],
                         event['amount_minor'],event['currency'],event['event_status'],status,order_id,now()))
        a={'business_id':business_id,'id':'sandbox-payment-provider'}
        audit(c,a,'payment.event_recorded',order_id,{'event_id':event['event_id'],'match_status':status})
        return {'event_id':event['event_id'],'order_id':order_id,'match_status':status,'duplicate':False}

def get_order_queue(session_token):
    with tx() as c:
        a=actor_from_token(c,session_token,'desk')
        orders=c.execute('SELECT id,customer_id,total_minor,status,created_at FROM orders WHERE business_id=? ORDER BY created_at DESC LIMIT 40',(a['business_id'],)).fetchall()
        return {'orders':[rowdict(x) for x in orders]}

def update_order_status(session_token,order_id,new_status):
    next_status={'confirmed':'preparing','preparing':'dispatched','dispatched':'fulfilled'}
    with tx() as c:
        a=actor_from_token(c,session_token,'desk')
        o=c.execute('SELECT * FROM orders WHERE id=? AND business_id=?',(order_id,a['business_id'])).fetchone()
        require(o is not None,'NOT_FOUND','Order not found')
        require(next_status.get(o['status'])==new_status,'INVALID_TRANSITION',f'Cannot move {o["status"]} to {new_status}')
        c.execute('UPDATE orders SET status=?,updated_at=? WHERE id=?',(new_status,now(),order_id))
        if new_status=='fulfilled':
            for item in c.execute('SELECT * FROM order_items WHERE order_id=?',(order_id,)).fetchall():
                c.execute('UPDATE products SET stock_on_hand=stock_on_hand-?,stock_reserved=stock_reserved-?,updated_at=? WHERE id=?',
                          (item['qty'],item['qty'],now(),item['product_id']))
        audit(c,a,'order.status_changed',order_id,{'from':o['status'],'to':new_status})
        return {'order_id':order_id,'previous_status':o['status'],'status':new_status}

def get_reconciliation_report(session_token):
    with tx() as c:
        a=actor_from_token(c,session_token,'desk')
        events=c.execute('SELECT event_id,reference,amount_minor,match_status FROM payment_events WHERE business_id=? ORDER BY created_at DESC',(a['business_id'],)).fetchall()
        verified_receipts=sum(e['amount_minor'] for e in events if e['match_status']=='matched')
        pending=c.execute("SELECT COUNT(*) n, COALESCE(SUM(total_minor),0) amount FROM orders WHERE business_id=? AND status='awaiting_payment'",(a['business_id'],)).fetchone()
        claims=c.execute("SELECT COUNT(*) n FROM payment_claims pc JOIN orders o ON o.id=pc.order_id WHERE o.business_id=? AND o.status='awaiting_payment'",(a['business_id'],)).fetchone()['n']
        return {'currency':'NGN','verified_matched_minor':verified_receipts,
                'unpaid_orders':pending['n'],'unpaid_order_total_minor':pending['amount'],
                'unverified_claim_count':claims,
                'exceptions':[rowdict(e) for e in events if e['match_status']!='matched'],
                'matched_payment_count':sum(e['match_status']=='matched' for e in events)}

def get_inventory_alerts(session_token):
    with tx() as c:
        a=actor_from_token(c,session_token,'desk')
        rows=c.execute('SELECT * FROM products WHERE business_id=? AND active=1',(a['business_id'],)).fetchall()
        return {'alerts':[{'product_id':p['id'],'name':p['name'],'available_qty':p['stock_on_hand']-p['stock_reserved'],
                    'threshold':p['low_stock_threshold'],'type': 'out_of_stock' if p['stock_on_hand']==p['stock_reserved'] else 'low_stock'}
                    for p in rows if p['stock_on_hand']-p['stock_reserved']<=p['low_stock_threshold']]}

def record_stock_adjustment(session_token,product_id,new_stock_on_hand,reason):
    require(isinstance(new_stock_on_hand,int) and new_stock_on_hand>=0,'INVALID_INPUT','Valid nonnegative quantity required')
    require(isinstance(reason,str) and len(reason.strip())>=4,'INVALID_INPUT','Provide a meaningful adjustment reason')
    with tx() as c:
        a=actor_from_token(c,session_token,'desk');require_role(a,'admin')
        p=c.execute('SELECT * FROM products WHERE id=? AND business_id=?',(product_id,a['business_id'])).fetchone()
        require(p is not None,'NOT_FOUND','Product not found')
        require(new_stock_on_hand>=p['stock_reserved'],'STOCK_RESERVED','Physical stock cannot be below current reservations')
        c.execute('UPDATE products SET stock_on_hand=?,updated_at=? WHERE id=?',(new_stock_on_hand,now(),product_id))
        rid=new_id('adj')
        c.execute('INSERT INTO inventory_adjustments VALUES(?,?,?,?,?,?,?,?)',
                  (rid,a['business_id'],product_id,p['stock_on_hand'],new_stock_on_hand,reason.strip(),a['id'],now()))
        audit(c,a,'stock.adjusted',product_id,{'from':p['stock_on_hand'],'to':new_stock_on_hand,'reason':reason.strip()})
        return {'adjustment_id':rid,'product_id':product_id,'previous_qty':p['stock_on_hand'],'new_qty':new_stock_on_hand}

def create_support_case(session_token,category,message,order_id=None):
    require(category in ('complaint','inquiry'),'INVALID_INPUT','Category must be complaint or inquiry')
    require(isinstance(message,str) and len(message.strip())>=5,'INVALID_INPUT','Please describe the issue')
    with tx() as c:
        a=actor_from_token(c,session_token,'shop')
        if order_id:
            o=c.execute('SELECT id FROM orders WHERE id=? AND customer_id=? AND business_id=?',(order_id,a['id'],a['business_id'])).fetchone()
            require(o is not None,'NOT_FOUND','Order not found for this customer')
        case=new_id('case')
        c.execute('INSERT INTO support_cases VALUES(?,?,?,?,?,?,?,?,?)',
                  (case,a['business_id'],a['id'],order_id,category,'open',now(),now(),None))
        c.execute('INSERT INTO support_messages VALUES(?,?,?,?,?,?)',
                  (new_id('msg'),case,a['id'],'customer',message.strip(),now()))
        audit(c,a,'support.opened',case,{'category':category})
        return {'case_id':case,'status':'open','message':'Your message has been passed to the team'}

def get_my_support_case(session_token,case_id):
    with tx() as c:
        a=actor_from_token(c,session_token,'shop')
        case=c.execute('SELECT * FROM support_cases WHERE id=? AND business_id=? AND customer_id=?',(case_id,a['business_id'],a['id'])).fetchone()
        require(case is not None,'NOT_FOUND','Support case not found for this customer')
        msgs=c.execute('SELECT sender_kind,body,created_at FROM support_messages WHERE case_id=? ORDER BY created_at',(case_id,)).fetchall()
        return {'case_id':case_id,'status':case['status'],'messages':[rowdict(m) for m in msgs]}

def list_support_cases(session_token):
    with tx() as c:
        a=actor_from_token(c,session_token,'desk')
        rows=c.execute('SELECT id,customer_id,order_id,category,status,opened_at FROM support_cases WHERE business_id=? ORDER BY updated_at DESC',(a['business_id'],)).fetchall()
        return {'cases':[rowdict(r) for r in rows]}

def reply_support_case(session_token,case_id,message):
    require(isinstance(message,str) and len(message.strip())>=3,'INVALID_INPUT','Provide a reply')
    with tx() as c:
        a=actor_from_token(c,session_token,'desk')
        case=c.execute('SELECT * FROM support_cases WHERE id=? AND business_id=?',(case_id,a['business_id'])).fetchone()
        require(case is not None,'NOT_FOUND','Support case not found')
        require(case['status']!='closed','INVALID_STATE','Case is closed')
        c.execute('INSERT INTO support_messages VALUES(?,?,?,?,?,?)',(new_id('msg'),case_id,a['id'],'staff',message.strip(),now()))
        c.execute('UPDATE support_cases SET status=?,updated_at=?,last_staff_response_at=? WHERE id=?',('answered',now(),now(),case_id))
        audit(c,a,'support.replied',case_id)
        return {'case_id':case_id,'status':'answered','recorded':True,'customer_delivery':'not_yet_verified'}

def get_merchant_catchup(session_token,since=None):
    """Structured merchant catch-up. Defaults to the most recent 24 hours."""
    if since:
        try:
            parsed=datetime.fromisoformat(since.replace('Z','+00:00'))
            require(parsed.tzinfo is not None,'INVALID_INPUT','since needs a timezone offset')
            since=parsed.astimezone(timezone.utc).isoformat(timespec='seconds')
        except (TypeError,ValueError) as ex:
            raise ToolFailure('INVALID_INPUT','since must be ISO-8601 with timezone') from ex
    else:
        since=(datetime.now(timezone.utc)-timedelta(hours=24)).isoformat(timespec='seconds')
    with tx() as c:
        a=actor_from_token(c,session_token,'desk')
        order_rows=c.execute('SELECT status,COUNT(*) n, COALESCE(SUM(total_minor),0) total FROM orders WHERE business_id=? AND created_at>=? GROUP BY status',(a['business_id'],since)).fetchall()
        payments=c.execute('SELECT match_status,COUNT(*) n, COALESCE(SUM(amount_minor),0) total FROM payment_events WHERE business_id=? AND created_at>=? GROUP BY match_status',(a['business_id'],since)).fetchall()
        open_cases=c.execute("SELECT id,customer_id,category,opened_at FROM support_cases WHERE business_id=? AND status='open' ORDER BY opened_at ASC",(a['business_id'],)).fetchall()
        changes=c.execute('SELECT action,target_id,created_at FROM audit WHERE business_id=? AND created_at>=? ORDER BY created_at DESC LIMIT 20',(a['business_id'],since)).fetchall()
        adjustments=c.execute('SELECT product_id,before_qty,after_qty,reason,created_at FROM inventory_adjustments WHERE business_id=? AND created_at>=? ORDER BY created_at DESC LIMIT 15',(a['business_id'],since)).fetchall()
        overdue=[]
        for case in open_cases:
            opened=datetime.fromisoformat(case['opened_at'])
            if (datetime.now(timezone.utc)-opened).total_seconds()>600:overdue.append(case['id'])
    return {'since':since,'orders_by_status':[rowdict(x) for x in order_rows],
            'verified_payment_events_by_status':[rowdict(x) for x in payments],
            'open_support_count':len(open_cases),'support_cases_waiting_over_10_minutes':overdue,
            'recent_inventory_adjustments':[rowdict(x) for x in adjustments],
            'recent_activity':[rowdict(x) for x in changes],
            'reconciliation':get_reconciliation_report(session_token),
            'inventory':get_inventory_alerts(session_token)}

TOOLS={
 'shop':{
  'link_identity':link_identity,'get_catalog':get_catalog,'create_order':create_order,
  'get_my_order':get_my_order,'record_payment_claim':record_payment_claim,
  'create_support_case':create_support_case,'get_my_support_case':get_my_support_case
 },
 'desk':{
  'link_identity':link_identity,'get_catalog':get_catalog,'upsert_product':upsert_product,
  'get_order_queue':get_order_queue,'update_order_status':update_order_status,
  'get_reconciliation_report':get_reconciliation_report,'get_merchant_catchup':get_merchant_catchup,
  'get_inventory_alerts':get_inventory_alerts,'record_stock_adjustment':record_stock_adjustment,
  'list_support_cases':list_support_cases,'reply_support_case':reply_support_case
 }
}

def invoke(channel,name,args):
    require(name in TOOLS[channel],'FORBIDDEN','Tool not enabled for this channel')
    params=dict(args or {})
    if name=='link_identity':params['channel']=channel
    if name=='get_catalog':params['channel']=channel
    try:
        return TOOLS[channel][name](**params)
    except TypeError as ex:
        raise ToolFailure('INVALID_INPUT',f'Tool arguments invalid: {str(ex)[:160]}') from ex
