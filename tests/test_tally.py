import json
import os
import uuid
import hmac
import hashlib
import time
import pytest
from fastapi.testclient import TestClient
from server.app import app
from server.business import (seed,issue_link_code,link_identity,get_catalog,upsert_product,
    create_order,record_payment_claim,get_my_order,get_reconciliation_report,get_inventory_alerts,
    get_merchant_catchup,update_order_status,create_support_case,list_support_cases,
    reply_support_case,get_my_support_case,ToolFailure,record_stock_adjustment)

@pytest.fixture(autouse=True)
def setup(tmp_path,monkeypatch):
    monkeypatch.setenv('TALLY_DB_PATH',str(tmp_path/'store.db'))
    monkeypatch.setenv('TALLY_ENV','sandbox')
    monkeypatch.setenv('TALLY_SHOP_MCP_TOKEN','SHOP_SUPER_LONG_RANDOM_TEST_SECRET')
    monkeypatch.setenv('TALLY_DESK_MCP_TOKEN','DESK_OTHER_LONG_RANDOM_TEST_SECRET')
    monkeypatch.setenv('TALLY_WEBHOOK_SECRET','WEBHOOK_LONG_RANDOM_TEST_SECRET')
    seed()

def sess(actor,channel):return link_identity(issue_link_code(actor),channel)['session_token']

def pay_http(order_id, amount_minor, event_id=None, invalid=False, currency="NGN"):
    event={'event_id':event_id or uuid.uuid4().hex,'reference':order_id,'amount_minor':amount_minor,'currency':currency,'event_status':'success'}
    body=json.dumps(event,separators=(',',':')).encode()
    ts=str(int(time.time()))
    sig='sha256='+hmac.new(os.environ['TALLY_WEBHOOK_SECRET'].encode(),ts.encode()+b'.'+body,hashlib.sha256).hexdigest()
    if invalid:sig='sha256='+'0'*64
    return TestClient(app).post('/sandbox/provider-event',content=body,headers={'X-Tally-Timestamp':ts,'X-Tally-Signature':sig,'Content-Type':'application/json'})

def test_two_roles_restrict_data_and_edits():
    customer=sess('cust-ada','shop'); another=sess('cust-bola','shop');op=sess('staff-tola','desk')
    admin=sess('staff-eni','desk')
    order=create_order(customer,[{'product_id':'cup-choc','quantity':1}],'req-one')
    with pytest.raises(ToolFailure) as e:get_my_order(another,order['order_id'])
    assert e.value.code=='NOT_FOUND'
    with pytest.raises(ToolFailure) as e:upsert_product(op,'Chocolate cupcake',280000,10)
    assert e.value.code=='FORBIDDEN'
    with pytest.raises(ToolFailure) as e:get_reconciliation_report(customer)
    assert e.value.code=='FORBIDDEN'
    with pytest.raises(ToolFailure) as e:link_identity(issue_link_code('staff-eni'),'shop')
    assert e.value.code=='FORBIDDEN'
    assert get_reconciliation_report(admin)['unpaid_orders']==1

def test_catalog_stock_and_order_idempotency():
    customer=sess('cust-ada','shop')
    assert next(p for p in get_catalog()['products'] if p['id']=='cup-vanilla')['available'] is False
    with pytest.raises(ToolFailure) as e:create_order(customer,[{'product_id':'cup-vanilla','quantity':1}],'req-two')
    assert e.value.code=='OUT_OF_STOCK'
    order=create_order(customer,[{'product_id':'cup-choc','quantity':2}],'req-three')
    same=create_order(customer,[{'product_id':'cup-choc','quantity':2}],'req-three')
    assert same['duplicate'] and same['order_id']==order['order_id']
    p=next(p for p in get_catalog()['products'] if p['id']=='cup-choc')
    assert p['available_qty']==12
    assert order['total_minor']==500000

def test_claim_is_not_verified_and_payment_is_signed_idempotent():
    cust=sess('cust-ada','shop');admin=sess('staff-eni','desk')
    order=create_order(cust,[{'product_id':'cup-choc','quantity':1}],'req-four')
    record_payment_claim(cust,order['order_id'])
    assert get_my_order(cust,order['order_id'])['status']=='awaiting_payment'
    assert pay_http(order['order_id'],250000,invalid=True).status_code==401
    wrong=pay_http(order['order_id'],249999,event_id='wrong-payment')
    assert wrong.json()['match_status']=='amount_mismatch'
    assert get_my_order(cust,order['order_id'])['status']=='awaiting_payment'
    ok=pay_http(order['order_id'],250000,event_id='matching-payment')
    assert ok.status_code==200 and ok.json()['match_status']=='matched'
    again=pay_http(order['order_id'],250000,event_id='matching-payment')
    assert again.json()['duplicate'] is True
    assert get_my_order(cust,order['order_id'])['status']=='confirmed'
    report=get_reconciliation_report(admin)
    assert report['verified_matched_minor']==250000
    assert any(x['match_status']=='amount_mismatch' for x in report['exceptions'])


def test_order_status_and_inventory_warnings():
    customer=sess('cust-ada','shop');op=sess('staff-tola','desk');admin=sess('staff-eni','desk')
    order=create_order(customer,[{'product_id':'brownie','quantity':3}],'req-five')
    assert any(x['product_id']=='brownie' for x in get_inventory_alerts(op)['alerts'])
    with pytest.raises(ToolFailure) as e:update_order_status(op,order['order_id'],'dispatched')
    assert e.value.code=='INVALID_TRANSITION'
    assert pay_http(order['order_id'],1950000).json()['match_status']=='matched'
    for state in ['preparing','dispatched','fulfilled']:
        assert update_order_status(op,order['order_id'],state)['status']==state
    assert get_my_order(customer,order['order_id'])['status']=='fulfilled'
    with pytest.raises(ToolFailure) as e:record_stock_adjustment(op,'brownie',2,'Physical recount')
    assert e.value.code=='FORBIDDEN'
    assert record_stock_adjustment(admin,'brownie',1,'Physical recount')['new_qty']==1


def test_case_privacy_staff_replies_and_catchup():
    cust=sess('cust-ada','shop');other=sess('cust-bola','shop');staff=sess('staff-femi','desk')
    case=create_support_case(cust,'complaint','Where is my delivery?')['case_id']
    assert len(list_support_cases(staff)['cases'])==1
    with pytest.raises(ToolFailure) as e:get_my_support_case(other,case)
    assert e.value.code=='NOT_FOUND'
    result=reply_support_case(staff,case,'Please allow until 5 PM for the dispatch update.')
    assert result['customer_delivery']=='not_yet_verified'
    messages=get_my_support_case(cust,case)['messages']
    assert messages[-1]['sender_kind']=='staff'
    assert 'open_support_count' in get_merchant_catchup(staff)


def test_mcp_discovery_role_isolation_and_real_tool_invocation():
    client=TestClient(app)
    assert client.post('/mcp/shop',json={'jsonrpc':'2.0','id':1,'method':'tools/list'}).status_code==401
    shop_h={'Authorization':'Bearer SHOP_SUPER_LONG_RANDOM_TEST_SECRET'}
    desk_h={'Authorization':'Bearer DESK_OTHER_LONG_RANDOM_TEST_SECRET'}
    initialized=client.post('/mcp/shop',headers=shop_h,json={'jsonrpc':'2.0','id':1,'method':'initialize'})
    assert initialized.status_code==200
    assert len(initialized.headers['mcp-session-id'])>=24
    shop=client.post('/mcp/shop',headers=shop_h,json={'jsonrpc':'2.0','id':2,'method':'tools/list'}).json()
    desk=client.post('/mcp/desk',headers=desk_h,json={'jsonrpc':'2.0','id':3,'method':'tools/list'}).json()
    s_names={x['name'] for x in shop['result']['tools']};d_names={x['name'] for x in desk['result']['tools']}
    assert 'get_reconciliation_report' not in s_names
    assert 'get_reconciliation_report' in d_names
    assert 'create_order' not in d_names
    called=client.post('/mcp/shop',headers=shop_h,json={'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'get_catalog','arguments':{}}}).json()
    result=json.loads(called['result']['content'][0]['text'])
    assert any(x['id']=='cup-choc' for x in result['products'])
    blocked=client.post('/mcp/shop',headers=shop_h,json={'jsonrpc':'2.0','id':5,'method':'tools/call','params':{'name':'get_reconciliation_report','arguments':{}}}).json()
    assert blocked['result']['isError'] is True

def test_idempotency_conflict_and_time_window():
    customer=sess('cust-ada','shop');staff=sess('staff-eni','desk')
    create_order(customer,[{'product_id':'cup-choc','quantity':1}],'stable-001')
    with pytest.raises(ToolFailure) as e:create_order(customer,[{'product_id':'brownie','quantity':1}],'stable-001')
    assert e.value.code=='IDEMPOTENCY_CONFLICT'
    assert get_merchant_catchup(staff,'2020-01-01T00:00:00+00:00')['orders_by_status']
    with pytest.raises(ToolFailure) as e:get_merchant_catchup(staff,'yesterday')
    assert e.value.code=='INVALID_INPUT'


def test_unknown_reference_and_currency_mismatch_are_visible_exceptions():
    cust=sess('cust-ada','shop');admin=sess('staff-eni','desk')
    order=create_order(cust,[{'product_id':'cup-choc','quantity':1}],'new-123')
    assert pay_http('TLY-nonexistent',100000,event_id='unmatched-ref').json()['match_status']=='unmatched_reference'
    assert pay_http(order['order_id'],250000,event_id='wrong-currency',currency='USD').json()['match_status']=='currency_mismatch'
    assert get_my_order(cust,order['order_id'])['status']=='awaiting_payment'
    kinds={x['match_status'] for x in get_reconciliation_report(admin)['exceptions']}
    assert 'unmatched_reference' in kinds and 'currency_mismatch' in kinds

def test_reused_provider_event_id_with_changed_details_is_rejected():
    cust=sess('cust-ada','shop')
    order=create_order(cust,[{'product_id':'cup-choc','quantity':1}],'new-456')
    assert pay_http(order['order_id'],250000,event_id='unique-x').json()['match_status']=='matched'
    conflict=pay_http(order['order_id'],500000,event_id='unique-x')
    assert conflict.status_code==400 and conflict.json()['error']=='EVENT_ID_CONFLICT'
