"""Local CLI (server-only): issue sandbox role-linked codes; generate signed payment payloads."""
import argparse
import hmac
import hashlib
import json
import os
import time
from server.business import seed,issue_link_code

if __name__=='__main__':
 p=argparse.ArgumentParser()
 sub=p.add_subparsers(dest='command',required=True)
 c=sub.add_parser('issue-code');c.add_argument('actor_id',choices=['cust-ada','cust-bola','staff-eni','staff-tola','staff-femi'])
 e=sub.add_parser('sign-event');e.add_argument('order_id');e.add_argument('amount_minor',type=int);e.add_argument('--event-id')
 args=p.parse_args()
 if args.command=='issue-code':
  seed();print(issue_link_code(args.actor_id))
 elif args.command=='sign-event':
  from uuid import uuid4
  data={'event_id':args.event_id or str(uuid4()),'reference':args.order_id,'amount_minor':args.amount_minor,'currency':'NGN','event_status':'success'}
  body=json.dumps(data,separators=(',',':')).encode()
  ts=str(int(time.time()))
  sig='sha256='+hmac.new(os.environ['TALLY_WEBHOOK_SECRET'].encode(),ts.encode()+b'.'+body,hashlib.sha256).hexdigest()
  print('TIMESTAMP='+ts);print('SIGNATURE='+sig);print('BODY='+body.decode())
