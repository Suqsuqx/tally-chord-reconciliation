"""Business tools: all private operations require validated sandbox session tokens."""
import hashlib
import os
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from .db import tx, rowdict

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

def issue_link_code(actor_id, ttl_minutes=10):
    require(os.getenv('TALLY_ENV','sandbox')=='sandbox','SANDBOX_ONLY','Demo codes are disabled outside sandbox')
    with tx() as c:
        a=c.execute('SELECT * FROM actors WHERE id=? AND active=1',(actor_id,)).fetchone()
        require(a is not None, 'NOT_FOUND', 'Unknown active actor')
        code=secrets.token_urlsafe(24)
        exp=(datetime.now(timezone.utc)+timedelta(minutes=ttl_minutes)).isoformat()
        c.execute('INSERT INTO access_codes VALUES(?,?,?,NULL)',(digest(code),actor_id,exp))
        return code

def _slug(value):
    value=re.sub(r'[^a-z0-9]+','-',str(value or '').strip().lower()).strip('-')
    require(2<=len(value)<=60,'INVALID_INPUT','Provide a valid business shop name or slug')
    return value

def _shop_access(shop_slug,onboarding_status):
    result={'status':onboarding_status,'shop_slug':shop_slug}
    if onboarding_status=='active':
        base=os.getenv('TALLY_PUBLIC_BASE_URL','').strip().rstrip('/')
        bound=os.getenv('TALLY_SHOP_BOUND_SLUG','').strip()
        target=os.getenv('TALLY_SHOP_AGENT_URL','').strip()
        if base and bound and _slug(bound)==shop_slug and target.startswith('https://'):
            result['entry_url']=f'{base}/shop/{shop_slug}'
    return result

def _sender_hash(sender_identity):
    require(isinstance(sender_identity,str) and 3<=len(sender_identity.strip())<=200,
            'INVALID_INPUT','A simulator sender identity is required')
    normalized=' '.join(sender_identity.strip().lower().split())
    return digest('tally|sandbox-sender|'+normalized)

def _customer_email(value):
    require(isinstance(value,str),'INVALID_INPUT','Provide a valid customer email address')
    email=value.strip().lower()
    require(len(email)<=254 and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) is not None,
            'INVALID_INPUT','Provide a valid customer email address')
    return email

def _customer_name(value):
    require(isinstance(value,str),'INVALID_INPUT','Provide a valid customer name')
    name=' '.join(value.strip().split())
    require(1<=len(name)<=160,'INVALID_INPUT','Provide a valid customer name')
    return name

def _integration_status(c,business_id):
    connections={row['provider']:row for row in c.execute(
        """SELECT provider,status,environment FROM provider_connections
           WHERE business_id=? AND status='active'""",(business_id,)).fetchall()}
    workspace=c.execute("SELECT parent_page_id FROM notion_workspaces WHERE business_id=?",
                        (business_id,)).fetchone()
    notion_connected='notion' in connections
    paystack_connected='paystack' in connections
    notion={'connection_status':'connected' if notion_connected else 'not_connected',
            'workspace_status':'active' if workspace else ('pending' if notion_connected else 'not_configured')}
    if workspace:
        notion['workspace_url']='https://www.notion.so/'+workspace['parent_page_id'].replace('-','')
        notion['managed_sections']=5
    return {'notion':notion,
            'paystack':{'connection_status':'connected' if paystack_connected else 'not_connected'}}

def _issue_session(c,actor,registration_status='resumed'):
    session=secrets.token_urlsafe(32)
    expires=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
    c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(digest(session),actor['id'],expires,now()))
    business=c.execute('SELECT name FROM businesses WHERE id=?',(actor['business_id'],)).fetchone()
    settings=c.execute('SELECT shop_slug,onboarding_status,payment_method FROM business_settings WHERE business_id=?',
                       (actor['business_id'],)).fetchone()
    product_count=c.execute('SELECT COUNT(*) n FROM products WHERE business_id=? AND active=1',
                            (actor['business_id'],)).fetchone()['n']
    result={'session_token':session,'role':actor['role'],'business_id':actor['business_id'],
            'business_name':business['name'],'shop_slug':settings['shop_slug'] if settings else None,
            'shop_status':settings['onboarding_status'] if settings else 'onboarding',
            'shop_access':_shop_access(settings['shop_slug'],settings['onboarding_status']) if settings else None,
            'registration_status':registration_status,
            'catalogue':{'product_count':product_count},
            'expires_at':expires,
            'identity_assurance':'unverified_simulator' if actor['id'].startswith(('own-','cus-')) else 'sandbox_code',
            'note':'Sandbox routing only. The live product must derive identity from the authenticated WhatsApp sender.'}
    if actor['kind']=='staff':
        result['integrations']=_integration_status(c,actor['business_id'])
    if actor['kind']=='customer':
        saved_name=actor['display_name'] if actor['display_name']!='Customer' else None
        result['customer_profile']={
            'display_name':saved_name,
            'name_on_file':bool(saved_name),
            'payment_email_on_file':bool(actor['email']),
        }
        result['checkout']={'method':settings['payment_method'] if settings else None}
        pending=c.execute('''SELECT kind,order_id,message FROM customer_notifications
                             WHERE customer_id=? AND business_id=? AND status='pending'
                             ORDER BY created_at''',(actor['id'],actor['business_id'])).fetchall()
        result['pending_actions']=[rowdict(item) for item in pending]
    return result

def _validate_profile(profile):
    if profile is None:return None
    profile=_decode_structured_argument(profile,dict,'Business profile must be a JSON object')
    require(isinstance(profile,dict) and len(profile)<=30,'INVALID_INPUT','Business profile must be an object')
    clean={}
    for key,value in profile.items():
        require(isinstance(key,str) and 1<=len(key)<=80 and isinstance(value,(str,int,float,bool)),
                'INVALID_INPUT','Business profile contains an unsupported value')
        clean[key.strip()]=str(value)[:1000] if not isinstance(value,bool) else value
    return clean

def _validate_policies(policies):
    if policies is None:return None
    policies=_decode_structured_argument(policies,list,'Policies must be a JSON list')
    require(isinstance(policies,list) and len(policies)<=50,'INVALID_INPUT','Policies must be a list')
    clean=[]
    for item in policies:
        require(isinstance(item,dict) and isinstance(item.get('question'),str) and
                isinstance(item.get('answer'),str),'INVALID_INPUT','Each policy needs question and answer')
        clean.append({'question':item['question'].strip()[:300],'answer':item['answer'].strip()[:2000]})
    return clean

def _decode_structured_argument(value,expected_type,message):
    """Accept JSON containers serialized by chat tool transports, without accepting prose."""
    if isinstance(value,str):
        try:
            value=json.loads(value)
        except (TypeError,ValueError):
            raise ToolFailure('INVALID_INPUT',message)
    require(isinstance(value,expected_type),'INVALID_INPUT',message)
    return value

def _configure_business(c,actor,profile=None,policies=None,manual_bank=None,activate_shop=False):
    require(actor['role']=='admin','FORBIDDEN','Only an admin may change onboarding settings')
    settings=c.execute('SELECT * FROM business_settings WHERE business_id=?',(actor['business_id'],)).fetchone()
    require(settings is not None,'INVALID_STATE','Business onboarding settings are unavailable')
    profile_value=_validate_profile(profile)
    policies_value=_validate_policies(policies)
    if profile_value is not None:
        c.execute('UPDATE business_settings SET profile_json=?,updated_at=? WHERE business_id=?',
                  (json.dumps(profile_value),now(),actor['business_id']))
    if policies_value is not None:
        c.execute('UPDATE business_settings SET policies_json=?,updated_at=? WHERE business_id=?',
                  (json.dumps(policies_value),now(),actor['business_id']))
    if manual_bank is not None:
        manual_bank=_decode_structured_argument(
            manual_bank,dict,'Manual bank setup must be a JSON object')
        require(isinstance(manual_bank,dict),'INVALID_INPUT','Manual bank setup must be an object')
        bank_name=str(manual_bank.get('bank_name','')).strip()
        account_name=str(manual_bank.get('account_name','')).strip()
        account_number=str(manual_bank.get('account_number','')).replace(' ','')
        require(bank_name and account_name and re.fullmatch(r'[0-9]{10,20}',account_number),
                'INVALID_INPUT','Provide valid manual bank details')
        bank={'bank_name':bank_name[:100],'account_name':account_name[:160],
              'account_number':account_number}
        c.execute('''UPDATE business_settings SET payment_method='manual_bank',bank_details_json=?,updated_at=?
                     WHERE business_id=?''',(json.dumps(bank),now(),actor['business_id']))
    if activate_shop:
        products=c.execute('SELECT COUNT(*) n FROM products WHERE business_id=? AND active=1',
                           (actor['business_id'],)).fetchone()['n']
        current=c.execute('SELECT payment_method,bank_details_json FROM business_settings WHERE business_id=?',
                          (actor['business_id'],)).fetchone()
        provider=c.execute("""SELECT 1 FROM provider_connections WHERE business_id=? AND provider='paystack'
                              AND environment='test' AND status='active'""",(actor['business_id'],)).fetchone()
        payment_ready=(current['payment_method']=='manual_bank' and current['bank_details_json']) or provider is not None
        require(products>0,'ONBOARDING_INCOMPLETE','Add at least one approved product before activation')
        require(bool(payment_ready),'ONBOARDING_INCOMPLETE','Connect Paystack or add manual bank details before activation')
        bound_slug=os.getenv('TALLY_SHOP_BOUND_SLUG','').strip()
        agent_url=os.getenv('TALLY_SHOP_AGENT_URL','').strip()
        require(bound_slug and _slug(bound_slug)==settings['shop_slug'] and
                agent_url.startswith('https://'),'SHOP_CHANNEL_UNAVAILABLE',
                'Provision this business-specific Tally Shop channel before activation')
        method='paystack' if provider is not None else 'manual_bank'
        c.execute('''UPDATE business_settings SET onboarding_status='active',payment_method=?,updated_at=?
                     WHERE business_id=?''',(method,now(),actor['business_id']))
    if any(value is not None for value in (profile_value,policies_value,manual_bank)) or activate_shop:
        audit(c,actor,'business.onboarding_updated',actor['business_id'],{'activated':bool(activate_shop)})

def link_identity(code=None, channel='shop', sender_identity=None, display_name=None, customer_email=None, business_name=None,
                  business_slug=None, profile=None, policies=None, manual_bank=None, activate_shop=False):
    """Legacy code linking plus sandbox sender-routed onboarding.

    sender_identity is deliberately accepted only in this sandbox. A live adapter must
    inject the authenticated WhatsApp sender and never accept a typed phone number.
    """
    require(os.getenv('TALLY_ENV','sandbox')=='sandbox','SANDBOX_ONLY','Demo linking is disabled outside sandbox')
    if code:
        return _link_identity_code(code,channel)
    identity_hash=_sender_hash(sender_identity)
    requested_slug=_slug(business_slug or business_name) if (business_slug or business_name) else None
    with tx() as c:
        if channel=='desk':
            membership=c.execute('''SELECT a.* FROM channel_identities i JOIN actors a ON a.id=i.actor_id
                                    JOIN business_settings s ON s.business_id=a.business_id
                                    WHERE i.channel='desk' AND i.identity_hash=? AND a.active=1
                                    AND (? IS NULL OR s.shop_slug=?)''',
                                 (identity_hash,requested_slug,requested_slug)).fetchone()
            created=False
            if membership is None:
                require(isinstance(business_name,str) and business_name.strip(),
                        'NOT_REGISTERED','Tell Tally the business name to start onboarding')
                slug=requested_slug
                conflict=c.execute('SELECT business_id FROM business_settings WHERE shop_slug=?',(slug,)).fetchone()
                require(conflict is None,'BUSINESS_EXISTS','That shop identifier is already registered')
                business_id=new_id('biz')
                c.execute('INSERT INTO businesses VALUES(?,?,?)',(business_id,business_name.strip()[:160],'NGN'))
                c.execute('''INSERT INTO business_settings VALUES(?,?,?,'{}','[]',NULL,NULL,?,?)''',
                          (business_id,slug,'onboarding',now(),now()))
                created=True
                actor_id=new_id('own')
                c.execute('''INSERT INTO actors (id,business_id,kind,role,display_name) VALUES(?,?,?,?,?)''',
                          (actor_id,business_id,'staff','admin',(display_name or 'Business owner')[:160]))
                c.execute('INSERT INTO channel_identities VALUES(?,?,?,?,?)',
                          ('desk',identity_hash,business_id,actor_id,now()))
                membership=c.execute('SELECT * FROM actors WHERE id=?',(actor_id,)).fetchone()
                audit(c,membership,'business.registered',business_id,{'shop_slug':slug})
            _configure_business(c,membership,profile,policies,manual_bank,activate_shop)
            return _issue_session(c,membership,'created' if created else 'resumed')
        require(channel=='shop','INVALID_INPUT','Unknown channel')
        require(requested_slug is not None,'INVALID_INPUT','A shop identifier is required')
        clean_name=_customer_name(display_name) if display_name is not None else None
        clean_email=_customer_email(customer_email) if customer_email is not None else None
        settings=c.execute('SELECT * FROM business_settings WHERE shop_slug=?',(requested_slug,)).fetchone()
        require(settings is not None and settings['onboarding_status']=='active','SHOP_UNAVAILABLE','This shop is not active')
        membership=c.execute('''SELECT a.* FROM channel_identities i JOIN actors a ON a.id=i.actor_id
                                WHERE i.channel='shop' AND i.identity_hash=? AND i.business_id=? AND a.active=1''',
                             (identity_hash,settings['business_id'])).fetchone()
        if membership is None:
            actor_id=new_id('cus')
            c.execute('''INSERT INTO actors (id,business_id,kind,role,display_name,email) VALUES(?,?,?,?,?,?)''',
                      (actor_id,settings['business_id'],'customer','customer',clean_name or 'Customer',clean_email))
            c.execute('INSERT INTO channel_identities VALUES(?,?,?,?,?)',
                      ('shop',identity_hash,settings['business_id'],actor_id,now()))
            membership=c.execute('SELECT * FROM actors WHERE id=?',(actor_id,)).fetchone()
        elif clean_name is not None or clean_email is not None:
            c.execute('''UPDATE actors SET display_name=COALESCE(?,display_name),email=COALESCE(?,email)
                         WHERE id=?''',(clean_name,clean_email,membership['id']))
            membership=c.execute('SELECT * FROM actors WHERE id=?',(membership['id'],)).fetchone()
            audit(c,membership,'customer.profile_updated',membership['id'],{
                'name_updated':clean_name is not None,'email_updated':clean_email is not None})
        return _issue_session(c,membership)

def _link_identity_code(code,channel):
    with tx() as c:
        rec=c.execute('SELECT * FROM access_codes WHERE code_hash=?',(digest(code),)).fetchone()
        require(rec is not None and rec['used_at'] is None and rec['expires_at']>now(),
                'INVALID_CODE', 'This access code is invalid or expired')
        a=c.execute('SELECT * FROM actors WHERE id=? AND active=1',(rec['actor_id'],)).fetchone()
        require(a is not None, 'FORBIDDEN', 'Actor inactive')
        require((channel=='shop' and a['kind']=='customer') or (channel=='desk' and a['kind']=='staff'),
                'FORBIDDEN','Access code does not belong to this channel')
        c.execute('UPDATE access_codes SET used_at=? WHERE code_hash=?',(now(),digest(code)))
        return _issue_session(c,a)

def actor_from_token(conn, token, channel):
    require(isinstance(token,str) and len(token)>20,'UNAUTHORIZED','Please link your sandbox identity first')
    a=conn.execute('''SELECT a.* FROM sessions s JOIN actors a ON a.id=s.actor_id
                      WHERE s.token_hash=? AND s.expires_at>? AND a.active=1''',(digest(token),now())).fetchone()
    require(a is not None,'UNAUTHORIZED','Session expired or invalid. Link your identity again')
    require((channel=='shop' and a['kind']=='customer') or (channel=='desk' and a['kind']=='staff'),
            'FORBIDDEN','This session cannot use these tools')
    if channel=='shop':
        active=conn.execute("""SELECT 1 FROM business_settings WHERE business_id=?
                               AND onboarding_status='active'""",(a['business_id'],)).fetchone()
        require(active is not None,'SHOP_UNAVAILABLE','This shop is not active')
    return a

def bind_shop_call(name,args,bound_shop_slug=None):
    """Apply a server-controlled single-business binding to one Shop MCP instance."""
    params=dict(args or {})
    if not bound_shop_slug:
        return params
    bound=_slug(bound_shop_slug)
    slug_field='shop_slug' if name=='get_catalog' else 'business_slug'
    supplied=params.get(slug_field)
    if supplied is not None:
        require(_slug(supplied)==bound,'SHOP_CONTEXT_MISMATCH',
                'This Tally Shop belongs to a different business')
    if name=='link_identity':
        require(not params.get('code'),'SHOP_CONTEXT_MISMATCH',
                'Legacy actor codes cannot select this bound Tally Shop')
        params['business_slug']=bound
    elif name=='get_catalog' and not params.get('session_token'):
        params['shop_slug']=bound
    token=params.get('session_token')
    if token:
        with tx() as conn:
            actor=actor_from_token(conn,token,'shop')
            settings=conn.execute('SELECT shop_slug FROM business_settings WHERE business_id=?',
                                  (actor['business_id'],)).fetchone()
            require(settings is not None and settings['shop_slug']==bound,
                    'SHOP_CONTEXT_MISMATCH','This customer session belongs to a different business')
    return params

def resolve_shop_entry(shop_slug,bound_shop_slug=None):
    """Resolve a public entry only for an active shop served by this instance."""
    slug=_slug(shop_slug)
    if bound_shop_slug:
        require(slug==_slug(bound_shop_slug),'SHOP_UNAVAILABLE','This shop is not available here')
    with tx() as conn:
        row=conn.execute('''SELECT b.name,s.shop_slug,s.onboarding_status
                            FROM business_settings s JOIN businesses b ON b.id=s.business_id
                            WHERE s.shop_slug=?''',(slug,)).fetchone()
        require(row is not None and row['onboarding_status']=='active',
                'SHOP_UNAVAILABLE','This shop is not active')
    target=os.getenv('TALLY_SHOP_AGENT_URL','').strip()
    require(target.startswith('https://'),'SHOP_CHANNEL_UNAVAILABLE',
            'This shop does not have a customer channel configured')
    return {'business':row['name'],'shop_slug':row['shop_slug'],'agent_url':target}

def require_role(actor,role):
    require(actor['role']==role,'FORBIDDEN',f'Only a {role} may perform this action')

def get_catalog(channel='shop',session_token=None,shop_slug=None,notion_resource_id=None):
    with tx() as c:
        if channel=='desk':
            actor=actor_from_token(c,session_token,channel);business_id=actor['business_id']
        elif session_token:
            actor=actor_from_token(c,session_token,'shop');business_id=actor['business_id']
        elif shop_slug:
            settings=c.execute("""SELECT * FROM business_settings WHERE shop_slug=?
                                  AND onboarding_status='active'""",(_slug(shop_slug),)).fetchone()
            require(settings is not None,'SHOP_UNAVAILABLE','This shop is not active')
            business_id=settings['business_id']
        else:
            raise ToolFailure(
                'SHOP_CONTEXT_REQUIRED',
                'Select an active merchant shop before requesting its catalogue')
        business=c.execute('SELECT * FROM businesses WHERE id=?',(business_id,)).fetchone()
        require(business is not None,'NOT_FOUND','Business not found')
        settings=c.execute('SELECT * FROM business_settings WHERE business_id=?',(business_id,)).fetchone()
        products=c.execute('SELECT * FROM products WHERE business_id=? AND active=1 ORDER BY name',(business_id,)).fetchall()
        result={'business':business['name'],'business_id':business_id,'currency':business['currency'],
                'shop_slug':settings['shop_slug'] if settings else None,'products':[
            {'id':p['id'],'name':p['name'],'price_minor':p['price_minor'],
             'available_qty':max(0,p['stock_on_hand']-p['stock_reserved']),
             'available':p['stock_on_hand']-p['stock_reserved']>0} for p in products]}
        if settings:
            result['business_profile']=json.loads(settings['profile_json'] or '{}')
            result['policies']=json.loads(settings['policies_json'] or '[]')
            result['checkout']={'method':settings['payment_method']}
        if channel=='desk' and settings:
            resources=c.execute('''SELECT resource_id,resource_type,title FROM provider_resources
                                   WHERE business_id=? AND provider='notion' ORDER BY title''',(business_id,)).fetchall()
            profile=result['business_profile']
            policies=result['policies']
            result['onboarding']={'status':settings['onboarding_status'],
                                  'payment_method':settings['payment_method'],
                                  'integrations':_integration_status(c,business_id),
                                  'notion_resources':[rowdict(row) for row in resources],
                                  'sections':{
                                      'business_profile':{'status':'saved' if profile else 'not_started',
                                                          'recommended':True},
                                      'catalogue':{'status':'ready' if products else 'not_started',
                                                   'product_count':len(products),'required_for_activation':True},
                                      'policies':{'status':'saved' if policies else 'not_started',
                                                  'policy_count':len(policies),'required_for_activation':False},
                                      'payment':{'status':'ready' if settings['payment_method'] else 'not_started',
                                                 'method':settings['payment_method'],
                                                 'required_for_activation':True},
                                  },
                                  'activation_ready':bool(products and settings['payment_method'])}
    if channel=='desk' and notion_resource_id:
        from .notion_connections import preview_notion_resource_sync
        result['notion_preview']=preview_notion_resource_sync(session_token,notion_resource_id)
    return result

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

def _order_payment_instructions(business_id,order_id,total_minor,payment_email=None):
    with tx() as c:
        settings=c.execute('SELECT payment_method,bank_details_json FROM business_settings WHERE business_id=?',
                           (business_id,)).fetchone()
    if not settings or not settings['payment_method']:
        return {'method':'sandbox','status':'awaiting_external_payment','verified':False}
    if settings['payment_method']=='manual_bank':
        bank=json.loads(settings['bank_details_json'] or '{}')
        return {'method':'manual_bank','status':'awaiting_manual_confirmation','bank':bank,
                'amount_minor':total_minor,'reference':order_id,
                'notice':'A payment claim remains unverified until an Admin confirms receipt.'}
    if settings['payment_method']=='paystack':
        if not payment_email:
            return {'method':'paystack','status':'customer_email_required',
                    'notice':'Provide an email address to create the hosted Paystack TEST checkout.'}
        try:
            from .paystack_connections import initialize_test_transaction
            return initialize_test_transaction(business_id,order_id,total_minor,payment_email)
        except (ToolFailure,ValueError):
            return {'method':'paystack','status':'temporarily_unavailable',
                    'notice':'The order is saved, but checkout could not be initialized. Retry with the same request_id.'}
    return {'method':'unconfigured','status':'unavailable'}

def create_order(session_token,items,request_id,payment_email=None):
    require(isinstance(request_id,str) and len(request_id)>=4,'INVALID_INPUT','Stable request_id required for safe retries')
    require(isinstance(items,list) and len(items)>0 and len(items)<=20,'INVALID_INPUT','At least one item required')
    supplied_email=_customer_email(payment_email) if payment_email is not None else None
    with tx() as c:
        a=actor_from_token(c,session_token,'shop')
        checkout_email=supplied_email or a['email']
        if supplied_email and supplied_email!=a['email']:
            c.execute('UPDATE actors SET email=? WHERE id=?',(supplied_email,a['id']))
            audit(c,a,'customer.payment_email_updated',a['id'])
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
            result={'order_id':prior['id'],'total_minor':prior['total_minor'],'currency':prior['currency'],
                    'status':prior['status'],'duplicate':True,'business_id':a['business_id']}
            business_id=a['business_id'];order_id=prior['id'];order_total=prior['total_minor']
        else:
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
            result={'order_id':oid,'total_minor':total,'currency':'NGN','status':'awaiting_payment',
                    'duplicate':False,'business_id':a['business_id']}
            business_id=a['business_id'];order_id=oid;order_total=total
    # Finish provider checkout after the order transaction commits. Retrying with
    # the same request_id is safe and can recover an interrupted network call.
    result['payment']=_order_payment_instructions(business_id,order_id,order_total,checkout_email)
    return result

FULFILMENT_STAGES=('confirmed','preparing','dispatched','delivery_reported','fulfilled')

def _record_forward_order_status(c,actor,order,new_status,source,note=None):
    require(order['status'] in FULFILMENT_STAGES,'INVALID_TRANSITION',
            'Payment must be confirmed before fulfilment can be recorded')
    current_index=FULFILMENT_STAGES.index(order['status'])
    target_index=FULFILMENT_STAGES.index(new_status)
    require(target_index>current_index,'INVALID_TRANSITION',
            f'Cannot move {order["status"]} to {new_status}')
    skipped=list(FULFILMENT_STAGES[current_index+1:target_index])
    c.execute('UPDATE orders SET status=?,updated_at=? WHERE id=?',(new_status,now(),order['id']))
    if new_status=='delivery_reported':
        c.execute('''INSERT OR IGNORE INTO customer_notifications
                     (id,business_id,customer_id,order_id,kind,message,status,created_at,resolved_at)
                     VALUES(?,?,?,?,?,?,'pending',?,NULL)''',
                  (new_id('notice'),order['business_id'],order['customer_id'],order['id'],
                   'confirm_delivery',
                   'The merchant reported this order delivered. Please confirm whether you received it.',now()))
    if new_status=='fulfilled':
        for item in c.execute('SELECT * FROM order_items WHERE order_id=?',(order['id'],)).fetchall():
            c.execute('''UPDATE products
                         SET stock_on_hand=stock_on_hand-?,stock_reserved=stock_reserved-?,updated_at=?
                         WHERE id=?''',(item['qty'],item['qty'],now(),item['product_id']))
        c.execute('''UPDATE customer_notifications SET status='confirmed',resolved_at=?
                     WHERE order_id=? AND customer_id=? AND kind='confirm_delivery' AND status='pending' ''',
                  (now(),order['id'],order['customer_id']))
    audit(c,actor,'order.status_changed',order['id'],{
        'from':order['status'],'to':new_status,'source':source,
        'skipped_statuses':skipped,'note':str(note or '')[:500]})
    return {'order_id':order['id'],'previous_status':order['status'],'status':new_status,
            'skipped_statuses':skipped,'recorded_from':source}

def get_my_order(session_token,order_id,confirm_received=False,confirmation_note=None):
    with tx() as c:
        a=actor_from_token(c,session_token,'shop')
        o=c.execute('SELECT * FROM orders WHERE id=? AND business_id=? AND customer_id=?',(order_id,a['business_id'],a['id'])).fetchone()
        require(o is not None,'NOT_FOUND','Order not found for this customer')
        status_result={}
        if confirm_received:
            if o['status']=='fulfilled':
                status_result={'previous_status':'fulfilled','skipped_statuses':[],
                               'recorded_from':'customer','duplicate':True}
            else:
                status_result=_record_forward_order_status(
                    c,a,o,'fulfilled','customer',confirmation_note or 'Customer confirmed receipt')
                o=c.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
        items=c.execute('SELECT name,qty,price_minor FROM order_items WHERE order_id=?',(order_id,)).fetchall()
        result={'order_id':o['id'],'total_minor':o['total_minor'],'currency':o['currency'],'status':o['status'],
                'items':[rowdict(i) for i in items]}
        result.update(status_result)
        return result

def record_payment_claim(session_token,order_id,note='Customer reports transfer'):
    with tx() as c:
        a=actor_from_token(c,session_token,'shop')
        o=c.execute('SELECT * FROM orders WHERE id=? AND business_id=? AND customer_id=?',(order_id,a['business_id'],a['id'])).fetchone()
        require(o is not None,'NOT_FOUND','Order not found for this customer')
        cid=new_id('clm')
        c.execute('INSERT INTO payment_claims VALUES(?,?,?,?,?)',(cid,order_id,a['id'],str(note)[:500],now()))
        audit(c,a,'payment.claimed',order_id)
        business_id=a['business_id']
        result={'claim_id':cid,'order_id':order_id,'status':o['status'],'verified':False,
                'verification_source':None}
    try:
        from .paystack_connections import verify_test_transaction_for_order
        verified=verify_test_transaction_for_order(business_id,order_id)
    except (ToolFailure,ValueError):
        verified={'status':'provider_unavailable'}
    if verified and verified.get('status')=='success':
        transaction_id=verified.get('transaction_id')
        if type(transaction_id) is int and type(verified.get('amount_minor')) is int:
            event=ingest_verified_payment({
                'event_id':f'paystack-test-verify:{transaction_id}',
                'reference':order_id,'amount_minor':verified['amount_minor'],
                'currency':verified.get('currency'),'event_status':'success'},business_id=business_id)
            result.update({'verified':event['match_status']=='matched','verification_source':'paystack_api',
                           'match_status':event['match_status'],
                           'status':'confirmed' if event['match_status']=='matched' else 'awaiting_payment'})
            return result
    result['provider_check_status']=verified.get('status') if verified else 'not_connected'
    return result

def ingest_verified_payment(event,business_id=None):
    require(isinstance(business_id,str) and business_id.strip(),
            'INVALID_INPUT','A business is required for payment reconciliation')
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
        orders=c.execute('''SELECT o.id,o.customer_id,c.display_name AS customer_name,
                                   o.total_minor,o.status,o.created_at
                            FROM orders o JOIN actors c ON c.id=o.customer_id
                            WHERE o.business_id=? ORDER BY o.created_at DESC LIMIT 40''',
                         (a['business_id'],)).fetchall()
        return {'orders':[rowdict(x) for x in orders]}

def update_order_status(session_token,order_id,new_status,confirmation_note=None):
    with tx() as c:
        a=actor_from_token(c,session_token,'desk')
        o=c.execute('SELECT * FROM orders WHERE id=? AND business_id=?',(order_id,a['business_id'])).fetchone()
        require(o is not None,'NOT_FOUND','Order not found')
        if o['status']=='awaiting_payment' and new_status=='confirmed':
            require_role(a,'admin')
            settings=c.execute('SELECT payment_method FROM business_settings WHERE business_id=?',
                               (a['business_id'],)).fetchone()
            require(settings is not None and settings['payment_method']=='manual_bank','INVALID_TRANSITION',
                    'Only a configured manual-bank order can be confirmed by an Admin')
            require(isinstance(confirmation_note,str) and len(confirmation_note.strip())>=4,
                    'INVALID_INPUT','Record how the Admin confirmed the bank receipt')
            event_id=new_id('manual')
            c.execute('UPDATE orders SET status=?,updated_at=? WHERE id=?',('confirmed',now(),order_id))
            c.execute('INSERT INTO payment_events VALUES(?,?,?,?,?,?,?,?,?)',
                      (event_id,a['business_id'],order_id,o['total_minor'],o['currency'],'merchant_confirmed',
                       'merchant_confirmed',order_id,now()))
            audit(c,a,'payment.manually_confirmed',order_id,{'note':confirmation_note.strip()[:500]})
            return {'order_id':order_id,'previous_status':'awaiting_payment','status':'confirmed',
                    'payment_assurance':'merchant_confirmed_manual','provider_verified':False}
        require(new_status in FULFILMENT_STAGES[1:],'INVALID_TRANSITION','Choose a valid forward fulfilment status')
        if new_status=='fulfilled':
            require(isinstance(confirmation_note,str) and len(confirmation_note.strip())>=4,
                    'CUSTOMER_CONFIRMATION_REQUIRED',
                    'Record the customer confirmation before marking this order fulfilled')
        result=_record_forward_order_status(
            c,a,o,new_status,'merchant',confirmation_note or 'Merchant recorded offline progress')
        if new_status=='delivery_reported':
            result['customer_confirmation']={
                'status':'pending',
                'outbound_delivery':'not_verified',
                'message':'Please confirm whether your order has been delivered.',
            }
        return result

def get_reconciliation_report(session_token):
    with tx() as c:
        a=actor_from_token(c,session_token,'desk')
        events=c.execute('SELECT event_id,reference,amount_minor,match_status FROM payment_events WHERE business_id=? ORDER BY created_at DESC',(a['business_id'],)).fetchall()
        verified_receipts=sum(e['amount_minor'] for e in events if e['match_status']=='matched')
        manual_receipts=sum(e['amount_minor'] for e in events if e['match_status']=='merchant_confirmed')
        pending=c.execute("SELECT COUNT(*) n, COALESCE(SUM(total_minor),0) amount FROM orders WHERE business_id=? AND status='awaiting_payment'",(a['business_id'],)).fetchone()
        claims=c.execute("SELECT COUNT(*) n FROM payment_claims pc JOIN orders o ON o.id=pc.order_id WHERE o.business_id=? AND o.status='awaiting_payment'",(a['business_id'],)).fetchone()['n']
        return {'currency':'NGN','verified_matched_minor':verified_receipts,
                'merchant_confirmed_manual_minor':manual_receipts,
                'unpaid_orders':pending['n'],'unpaid_order_total_minor':pending['amount'],
                'unverified_claim_count':claims,
                'exceptions':[rowdict(e) for e in events if e['match_status'] not in ('matched','merchant_confirmed')],
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
        delivery_dispute=False
        if order_id:
            o=c.execute('SELECT id,status FROM orders WHERE id=? AND customer_id=? AND business_id=?',(order_id,a['id'],a['business_id'])).fetchone()
            require(o is not None,'NOT_FOUND','Order not found for this customer')
            delivery_dispute=category=='complaint' and o['status']=='delivery_reported'
        case=new_id('case')
        c.execute('INSERT INTO support_cases VALUES(?,?,?,?,?,?,?,?,?)',
                  (case,a['business_id'],a['id'],order_id,category,'open',now(),now(),None))
        c.execute('INSERT INTO support_messages VALUES(?,?,?,?,?,?)',
                  (new_id('msg'),case,a['id'],'customer',message.strip(),now()))
        if delivery_dispute:
            c.execute('''UPDATE customer_notifications SET status='disputed',resolved_at=?
                         WHERE order_id=? AND customer_id=? AND kind='confirm_delivery' AND status='pending' ''',
                      (now(),order_id,a['id']))
        audit(c,a,'support.opened',case,{'category':category})
        return {'case_id':case,'status':'open','delivery_dispute':delivery_dispute,
                'message':'Your message has been passed to the team'}

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
