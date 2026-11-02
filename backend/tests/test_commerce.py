import os
import re
from uuid import uuid4
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from web3 import Web3

from nexopass import schema as s
from nexopass.app import create_app
from nexopass.worker import tick
from test_accounts import api, account, engine
from test_catalog import create_concert


def verify(api):
    message = next(m for m in api.get('/api/v1/me/mailbox').json() if 'Verifica' in m['subject'])
    token = re.search(r'token=([\w-]+)', message['body']).group(1)
    assert api.post('/api/v1/auth/verify', json={'token':token}).status_code == 200


def buy(api, engine, result='approved'):
    event, zone = create_concert(api, engine)
    verify(api)
    seat = api.get(f'/api/v1/events/{event["id"]}/zones/{zone["id"]}/seats').json()[0]
    reserve = api.post('/api/v1/reservations', json={'event_id':event['id'],'zone_id':zone['id'],'unit_ids':[seat['unit_id']]})
    assert reserve.status_code == 201, reserve.text
    body = {'idempotency_key':str(uuid4()),'expected_total':reserve.json()['total'],'attendees':[{'full_name':'Persona de prueba','email':api.get('/api/v1/auth/me').json()['email'],
        'document_type':'DNI','document_number':'0801199900001'}], 'method':'card_demo','result':result,
        'card_number':'4111111111111111','card_holder':'DEMO','expiry':'12/30','cvv':'123'}
    response=api.post('/api/v1/reservations/'+reserve.json()['id']+'/checkout',json=body)
    assert response.status_code==200,response.text
    again=api.post('/api/v1/reservations/'+reserve.json()['id']+'/checkout',json=body)
    assert again.status_code==200 and again.json()['order_id']==response.json()['order_id']
    body['attendees'][0]['full_name']='Otra persona'
    assert api.post('/api/v1/reservations/'+reserve.json()['id']+'/checkout',json=body).status_code==409
    tickets=api.get('/api/v1/me/tickets').json()
    return event,zone,tickets[0],response.json()


def test_rejected_payment_releases_inventory_without_mint(api,engine):
    event,zone,ticket,order=buy(api,engine,'rejected')
    assert ticket['status']=='cancelled' and not ticket['operations']
    assert api.get('/api/v1/events/'+event['id']).json()['availability']['zones'][0]['available']==12


def test_pending_payment_can_be_resolved_without_duplicate_ticket(api,engine):
    event,zone,ticket,order=buy(api,engine,'pending')
    assert ticket['status']=='pending_mint' and not ticket['operations']
    response=api.post('/api/v1/orders/'+order['order_id']+'/resolve-demo',json={'result':'approved'})
    assert response.status_code==200,response.text
    assert len(api.get('/api/v1/me/tickets').json())==1
    assert api.post('/api/v1/orders/'+order['order_id']+'/resolve-demo',json={'result':'approved'}).status_code==409


def test_complete_blockchain_transfer_and_admission(api,engine,monkeypatch):
    assert os.environ.get('NEXOPASS_TEST_CHAIN_RPC_URL'), 'Se requiere cadena EVM aislada para esta prueba'
    web3=Web3(Web3.HTTPProvider(os.environ['NEXOPASS_TEST_CHAIN_RPC_URL']))
    snapshot=web3.provider.make_request('evm_snapshot',[])['result']
    try:
        event,zone,ticket,order=buy(api,engine)
        settings=api.app.state.settings
        tick(settings,api.app.state.database)
        ticket=api.get('/api/v1/tickets/'+ticket['id']).json()
        assert ticket['status']=='active',ticket
        assert ticket['nft'] and ticket['operations'][0]['status']=='confirmed'
        old_qr=api.post('/api/v1/tickets/'+ticket['id']+'/qr').json()['token']
        with TestClient(create_app(settings),client=('friend-'+uuid4().hex,50000)) as friend:
            email,_=account(friend);verify(friend)
            assert friend.get('/api/v1/tickets/'+ticket['id']).status_code==404
            invitation=api.post('/api/v1/tickets/'+ticket['id']+'/transfers',json={'email':email})
            assert invitation.status_code==201,invitation.text
            accepted=friend.post('/api/v1/transfers/'+invitation.json()['id']+'/accept',json={
                'full_name':'Receptora del boleto','email':email,'document_type':'DNI','document_number':'0801200000002'})
            assert accepted.status_code==200,accepted.text
            tick(settings,api.app.state.database)
            received=friend.get('/api/v1/tickets/'+ticket['id']).json()
            assert received['transfer_count']==1 and received['full_name']=='Receptora del boleto',received
            assert api.post('/api/v1/access/check',json={'token':old_qr}).status_code==400
            assert friend.post('/api/v1/tickets/'+ticket['id']+'/transfers',json={'email':'other@example.com'}).status_code==409
            qr=friend.post('/api/v1/tickets/'+ticket['id']+'/qr').json()['token']
            check=api.post('/api/v1/access/check',json={'token':qr})
            assert check.status_code==200 and check.json()['document_number']=='0801200000002'
            denied=api.post('/api/v1/access/consume',json={'token':qr,'identity_matches':False})
            assert denied.json()['status']=='denied'
            door=datetime.fromisoformat(event['doors_open_at'])
            current=web3.eth.get_block('latest')['timestamp']
            web3.provider.make_request('evm_increaseTime',[int(door.timestamp())-current+10]);web3.provider.make_request('evm_mine',[])
            monkeypatch.setattr('nexopass.access.now',lambda:datetime.fromtimestamp(door.timestamp()+10,door.tzinfo))
            admission=api.post('/api/v1/access/consume',json={'token':qr,'identity_matches':True})
            assert admission.status_code==200,admission.text
            assert admission.json()['status']=='pending'
            tick(settings,api.app.state.database)
            final=api.get('/api/v1/access/attempts/'+admission.json()['attempt_id'])
            assert final.json()['authorized'] is True,final.text
            assert friend.get('/api/v1/tickets/'+ticket['id']).json()['status']=='used'
            assert api.post('/api/v1/access/consume',json={'token':qr,'identity_matches':True}).status_code in (400,409)
    finally:
        web3.provider.make_request('evm_revert',[snapshot])
