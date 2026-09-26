import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from studio.server import Handler

class CleanStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def request(self,path,body=None,headers=None):
        c=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        c.request('POST' if body is not None else 'GET',path,body=body,headers=headers or {})
        r=c.getresponse();data=r.read();status=r.status;c.close();return status,data
    def test_empty_checkout_home_and_world_inventory(self):
        status,body=self.request('/');self.assertEqual(status,200)
        self.assertIn(b'gameFolderForm',body)
        status,body=self.request('/api/worlds');self.assertEqual(status,200)
        self.assertFalse(json.loads(body)['xboxConfigured'])
        status,body=self.request('/api/bootstrap');self.assertEqual(status,200)
        self.assertIsInstance(json.loads(body)['catalog']['assets'],list)
    def test_local_api_rejects_foreign_host_and_unauthorized_writes(self):
        self.assertEqual(self.request('/api/library',headers={'Host':'example.com'})[0],400)
        self.assertEqual(self.request('/api/library/configure',b'{}',{'Content-Type':'application/json'})[0],400)
        _,body=self.request('/api/bootstrap');token=json.loads(body)['token']
        headers={'Content-Type':'application/json','X-NativeX-Token':token,'Origin':'https://example.com'}
        self.assertEqual(self.request('/api/library/configure',b'{}',headers)[0],400)
    def test_path_escape_is_not_served(self):
        self.assertEqual(self.request('/../studio/server.py')[0],404)

if __name__=='__main__':unittest.main()
