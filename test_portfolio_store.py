"""Durable snapshots, conflicts, invalid input, and failure-safe local storage."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from portfolio_store import PortfolioStore, SavePortfolio, StoreError, WorkspaceState
import terminal_api


class PortfolioStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'data'/'portfolios.sqlite3'
        self.store=PortfolioStore(self.path)
        self.client=TestClient(terminal_api.app)
        self.patcher=patch('terminal_api.portfolio_store',self.store)
        self.patcher.start();self.addCleanup(self.patcher.stop)

    def payload(self,**overrides):
        state=WorkspaceState().model_dump()
        state.update(holdings=[{'ticker':'AAPL','name':'Apple','exchange':'Nasdaq','currency':'USD','qty':'','avg_cost':'180.125','percent':'35','dollars':'4000','purchase_price':'190.50'}],
                     research=[{'ticker':'SPY','name':'SPDR','exchange':'NYSE','currency':'USD'}],cash='1234.56',budget='12000.00',unit='dollars',source='allocation',
                     csv={'name':'positions.csv','positions':[{'ticker':'MSFT','qty':1.125,'avg_cost':400.,'currency':'USD'}]})
        state['settings'].update(benchmark='QQQ',period='5y',interval='1wk',window='52',return_basis='total',risk_free_percent='4.25')
        return {'id':str(uuid4()),'name':'Long-term portfolio','revision':0,'state':state,**overrides}

    def test_full_workspace_round_trip_after_reopening_database(self):
        body=self.payload()
        response=self.client.post('/api/portfolios/save',json=body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['revision'],1)
        reopened=PortfolioStore(self.path).get(body['id'])
        self.assertEqual(reopened['state'],body['state'])
        self.assertEqual(reopened['state']['holdings'][0]['qty'],'')
        listed=self.client.get('/api/portfolios').json()['portfolios']
        self.assertEqual(len(listed),1);self.assertNotIn('state',listed[0])
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)

    def test_save_updates_only_target_and_names_are_case_insensitively_unique(self):
        one=self.payload();two=self.payload(name='Income')
        self.client.post('/api/portfolios/save',json=one)
        self.client.post('/api/portfolios/save',json=two)
        one['revision']=1;one['name']='Growth';one['state']['cash']='99'
        self.assertEqual(self.client.post('/api/portfolios/save',json=one).json()['revision'],2)
        self.assertEqual(self.store.get(two['id'])['name'],'Income')
        duplicate=self.client.post('/api/portfolios/save',json=self.payload(name=' growth '))
        self.assertEqual(duplicate.status_code,409)
        self.assertEqual(len(self.store.list()),2)

    def test_stale_updates_do_not_overwrite_and_uncertain_save_retry_is_idempotent(self):
        original=self.payload()
        self.client.post('/api/portfolios/save',json=original)
        self.assertEqual(self.client.post('/api/portfolios/save',json=original).json()['revision'],1)
        changed=self.payload(id=original['id'],revision=1)
        changed['state']['cash']='200'
        self.client.post('/api/portfolios/save',json=changed)
        changed['state']['cash']='300'
        response=self.client.post('/api/portfolios/save',json=changed)
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.store.get(original['id'])['state']['cash'],'200')

    def test_simultaneous_saves_preserve_one_complete_version(self):
        body=self.payload();self.store.save(SavePortfolio.model_validate(body))
        def update(cash):
            req=self.payload(id=body['id'],revision=1);req['state']['cash']=cash
            try:return self.store.save(SavePortfolio.model_validate(req))['revision']
            except StoreError as exc:return exc.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(update,['100','200']))
        self.assertCountEqual(outcomes,[2,409])
        self.assertIn(self.store.get(body['id'])['state']['cash'],['100','200'])

    def test_validation_rejects_unsupported_state_without_writing(self):
        for changes in [{'name':'   '},{'name':'bad\nname'},{'id':'../../elsewhere'}]:
            self.assertEqual(self.client.post('/api/portfolios/save',json=self.payload(**changes)).status_code,422)
        bad=self.payload();bad['state']['schema_version']=2
        self.assertEqual(self.client.post('/api/portfolios/save',json=bad).status_code,422)
        bad=self.payload();bad['state']['cash']={'bad':'type'}
        self.assertEqual(self.client.post('/api/portfolios/save',json=bad).status_code,422)
        self.assertEqual(self.store.list(),[])

    def test_storage_failure_and_corruption_do_not_replace_saved_data(self):
        body=self.payload();self.store.save(SavePortfolio.model_validate(body))
        before=self.path.read_bytes()
        with patch.object(self.store,'connect',side_effect=sqlite3.OperationalError('disk unavailable')):
            self.assertEqual(self.client.post('/api/portfolios/save',json=body).status_code,503)
        self.assertEqual(self.path.read_bytes(),before)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE portfolios SET state_json = ? WHERE id = ?',('{bad json',body['id']))
        response=self.client.get('/api/portfolios/'+body['id'])
        self.assertEqual(response.status_code,500);self.assertIn('kept',response.json()['error'])

    def test_unknown_id_and_foreign_origin(self):
        self.assertEqual(self.client.get('/api/portfolios/'+str(uuid4())).status_code,404)
        self.assertEqual(self.client.post('/api/portfolios/save',json=self.payload(),headers={'origin':'https://other.example'}).status_code,403)


if __name__=='__main__':unittest.main()
