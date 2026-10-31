"""Test-only proof that PR #821 scroll protection and #823 one-use IDs coexist."""
import json
import unittest
from unittest.mock import patch
from plugin.relay import server as relay

ROOT = {"left":0,"top":0,"right":1080,"bottom":2340}

class FakeSession:
    token="test-scroll-snapshot-session"
    def channel_is_expired(self,_): return False

class FakeRequest:
    query={}
    def __init__(self, method, body=None):self.method,self._body=method,body or {}
    async def json(self):return self._body

class FakeBridge:
    def __init__(self, top=950,bottom=2238,scrollable=True):
        self.top,self.bottom,self.scrollable=top,bottom,scrollable
        self.calls=[]
    async def handle_command(self,**args):
        self.calls.append(args)
        if args['path']=='/screen':
            return {"status":200,"result":{"packageName":"com.example","rootBounds":ROOT,"nodes":[{"nodeId":"w1:21","text":"Results","className":"android.widget.ScrollView","bounds":{"left":0,"top":self.top,"right":1080,"bottom":self.bottom},"scrollable":self.scrollable,"enabled":True}]}}
        if args['path']=='/scroll':return {"status":200,"result":{"ok":True}}
        raise AssertionError(args['path'])

class CombinedNodeAndScrollTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        relay._BRIDGE_NODE_SNAPSHOTS.clear()
        self.server=type('Server',(),{})();self.server.bridge=FakeBridge();self.session=FakeSession()
        self.patch=patch.object(relay,'_require_bearer_session',return_value=(self.server,self.session));self.patch.start()
    def tearDown(self):
        self.patch.stop();relay._BRIDGE_NODE_SNAPSHOTS.clear()
    async def send(self,method,path,payload=None):
        response=await relay._bridge_dispatch(FakeRequest(method,payload),path)
        return response.status,json.loads(response.text)
    async def fresh(self):
        status,body=await self.send('GET','/screen')
        self.assertEqual(status,200)
        return body['nodes'][0]['nodeId']
    async def test_overlay_fallback_preserves_one_use_security(self):
        handle=await self.fresh();self.assertTrue(handle.startswith('n-'))
        status,out=await self.send('POST','/scroll',{'nodeId':handle,'direction':'down'})
        self.assertEqual(status,200);self.assertEqual(out['scroll_fallback'],'screen_center')
        self.assertTrue(out['gesture_dispatched_only']);self.assertIsNone(out['content_movement_verified'])
        action=[x for x in self.server.bridge.calls if x['path']=='/scroll']
        self.assertEqual(len(action),1);self.assertNotIn('nodeId',action[0]['body'])
        status,out=await self.send('POST','/scroll',{'nodeId':handle,'direction':'down'})
        self.assertEqual(status,409);self.assertFalse(out['action_performed'])
        self.assertEqual(len([x for x in self.server.bridge.calls if x['path']=='/scroll']),1)
    async def test_edge_only_container_refuses_without_gesture(self):
        self.server.bridge.top,self.server.bridge.bottom=1775,2300
        handle=await self.fresh();status,out=await self.send('POST','/scroll',{'nodeId':handle,'direction':'down'})
        self.assertEqual(status,409);self.assertFalse(out['action_performed'])
        self.assertEqual(len([x for x in self.server.bridge.calls if x['path']=='/scroll']),0)
    async def test_safe_node_reaches_phone_with_verified_raw_id(self):
        self.server.bridge.top,self.server.bridge.bottom=400,1750
        handle=await self.fresh();status,out=await self.send('POST','/scroll',{'nodeId':handle,'direction':'down'})
        self.assertEqual(status,200);self.assertNotIn('scroll_fallback',out)
        action=[x for x in self.server.bridge.calls if x['path']=='/scroll']
        self.assertEqual(len(action),1);self.assertEqual(action[0]['body']['nodeId'],'w1:21')
    async def test_raw_id_never_scrolls(self):
        status,out=await self.send('POST','/scroll',{'nodeId':'w1:21','direction':'down'})
        self.assertEqual(status,409);self.assertFalse(out['action_performed'])
        self.assertEqual(self.server.bridge.calls,[])

if __name__=='__main__':unittest.main()
