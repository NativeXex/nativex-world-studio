import json, tempfile, unittest, struct
from pathlib import Path
from unittest.mock import patch
from studio.worlds import inventory
from studio.skate3 import world_job

class WorldBrowserTests(unittest.TestCase):
    def test_inventory_distinguishes_collection_import_and_offline_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sources=root/'data/world-source';sources.mkdir(parents=True)
            (sources/'worldDIST_University.big.part').write_bytes(b'incoming')
            (sources/'worldDIST_MegaPark.big').write_bytes(b'overlay')
            result={w['id']:w for w in inventory(root)['worlds']}
            self.assertEqual(result['university']['status'],'collecting')
            self.assertFalse(result['university']['canOpen'])
            self.assertEqual(result['mega-park']['kind'],'overlay')
            self.assertFalse(result['mega-park']['canOpen'])
            self.assertEqual(result['downtown']['status'],'not-collected')
            bundle=root/'web/worlds/blackbox';bundle.mkdir(parents=True)
            m=dict(id='blackbox',name='Test',sourceArchive='worldDIST_BlackBoxPark.big',sourceSha256='abc',importStatus='ready-preview',
                   sections=[dict(id='one',models=[dict(url='/worlds/blackbox/model.nxdata')])],summary={},textures={},unsupported=[])
            (bundle/'manifest.json').write_text(json.dumps(m))
            result={w['id']:w for w in inventory(root)['worlds']}
            self.assertEqual(result['blackbox']['status'],'invalid')
            self.assertFalse(result['blackbox']['canOpen'])
            (bundle/'model.nxdata').write_text('{}')
            result={w['id']:w for w in inventory(root)['worlds']}
            self.assertTrue(result['blackbox']['canOpen'])
            self.assertFalse(result['blackbox']['collected'])
            self.assertEqual(result['blackbox']['status'],'ready')

    def test_manifest_does_not_make_incomplete_world_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle=root/'web/worlds/university';bundle.mkdir(parents=True)
            m=dict(sourceSha256='abc',importStatus='unsupported-or-partial',sections=[],summary={'missingDiffuseTextures':['unresolved']},unsupported=[])
            (bundle/'manifest.json').write_text(json.dumps(m))
            item=next(w for w in inventory(root)['worlds'] if w['id']=='university')
            self.assertEqual(item['status'],'partial');self.assertFalse(item['canOpen'])

    def test_collection_only_reads_known_archive_and_promotes_a_complete_copy(self):
        payload=b'original archive bytes';commands=[]
        class Socket:
            def settimeout(self,n):pass
            def sendall(self,data):commands.append(data)
        class Connection:
            def __init__(self,host):self.sock=Socket();self.data=bytearray(struct.pack('<I',len(payload))+payload)
            def line(self):return b'203- binary response follows'
            def exact(self,n):value=bytes(self.data[:n]);del self.data[:n];return value
            def close(self):pass
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data/world-source').mkdir(parents=True)
            with patch.object(world_job,'ROOT',root),patch.object(world_job,'XBDM',Connection),patch.object(world_job,'progress'):
                target=world_job.collect('university','127.0.0.1')
                self.assertEqual(target.read_bytes(),payload)
                self.assertFalse(target.with_suffix('.big.part').exists())
                self.assertEqual(len(commands),1)
                self.assertTrue(commands[0].startswith(b'getfile name="Hdd:'))
                self.assertIsNotNone(world_job.collect('university','127.0.0.1'))
                self.assertEqual(len(commands),1,'A cached archive must not contact Xbox again')

if __name__=='__main__':unittest.main()
