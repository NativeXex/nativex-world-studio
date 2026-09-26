import unittest
from unittest.mock import patch

from studio.skate3.world_probe_xbox import activate, require_aurora, REMOTE, LIVE


class FakeConsole:
    def __init__(self, files, title='Aurora.xex', fail_install=False):
        self.files = {REMOTE+'\\'+k: v for k,v in files.items()}
        self.files[LIVE] = files['xbox-original.big']
        self.title = title
        self.fail_install = fail_install
        self.moves = []

    def command(self, text):
        return '202- response\nname="\\Device\\Harddisk0\\Partition1\\'+self.title+'"'

    def read(self, path):
        return self.files[path]

    def exists(self, path):
        return path in self.files

    def rename(self, source, destination):
        if self.fail_install and source.endswith('unchanged.big'):
            raise RuntimeError('simulated staging rename failure')
        if destination in self.files:
            raise RuntimeError('destination exists')
        self.moves.append((source,destination))
        self.files[destination] = self.files.pop(source)

    def upload_new(self, path, data):
        if path in self.files and self.files[path] != data:
            raise RuntimeError('different existing file')
        self.files[path] = data


def local_files():
    # Original synthetic bytes; never load or distribute retail fixtures.
    return {'xbox-original.big': b'original synthetic archive',
            'unchanged.big': b'original synthetic archive',
            'magenta-floor.big': b'edited synthetic archive'}

class WorldProbeXboxTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        original=hashlib.sha256(local_files()['xbox-original.big']).hexdigest()
        patcher=patch('studio.skate3.world_probe_xbox.SOURCE_SHA256',original)
        patcher.start();self.addCleanup(patcher.stop)

    def test_aurora_guard_rejects_game_and_unknown_title(self):
        for reply in ['202- reply\nname="Hdd:\\skate 3\\default.xex"','200- okay','202- reply\nname="Hdd:\\notAurora.xex"']:
            with self.assertRaises(RuntimeError):
                require_aurora(reply)
        require_aurora('202- reply\nname="Usb0:\\Aurora\\Aurora.xex"')

    @patch('studio.skate3.world_probe_xbox.journal')
    def test_running_game_prevents_all_file_mutations(self, log):
        files=local_files(); console=FakeConsole(files,title='default.xex')
        with self.assertRaises(RuntimeError):
            activate(console,files,'unchanged')
        self.assertEqual(console.moves,[])

    @patch('studio.skate3.world_probe_xbox.journal')
    def test_unknown_live_bytes_prevent_replacement(self, log):
        files=local_files();console=FakeConsole(files);console.files[LIVE]=b'unknown'
        with self.assertRaises(RuntimeError):
            activate(console,files,'magenta')
        self.assertEqual(console.moves,[])

    @patch('studio.skate3.world_probe_xbox.journal')
    def test_failed_install_restores_previous_archive(self, log):
        files=local_files();console=FakeConsole(files,fail_install=True)
        with self.assertRaises(RuntimeError):
            activate(console,files,'unchanged')
        self.assertEqual(console.files[LIVE],files['xbox-original.big'])
        self.assertEqual(len(console.moves),2)

    @patch('studio.skate3.world_probe_xbox.journal')
    def test_install_and_restore_keep_verified_original_backup(self, log):
        files=local_files();console=FakeConsole(files)
        activate(console,files,'magenta')
        self.assertEqual(console.files[LIVE],files['magenta-floor.big'])
        activate(console,files,'restore')
        self.assertEqual(console.files[LIVE],files['xbox-original.big'])
        self.assertEqual(console.files[REMOTE+'\\xbox-original.big'],files['xbox-original.big'])


if __name__ == '__main__':
    unittest.main()
