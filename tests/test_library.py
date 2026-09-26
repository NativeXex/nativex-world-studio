import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from studio import library, level_builds
from studio.catalog import empty_catalog
from studio.skate3.xbox import XBDM, xbox_content_path

class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'studio';self.root.mkdir()
        self.game=Path(self.temp.name)/'My SSD'/'Skate 3'/'Data'/'Content';self.game.mkdir(parents=True)
        self.archive=self.game/'worldDIST_BlackBoxPark.big';self.archive.write_bytes(b'EB synthetic archive fixture')
        for name,value in [('ROOT',self.root),('SETTINGS',self.root/'data/settings.local.json')]:
            p=patch.object(library,name,value);p.start();self.addCleanup(p.stop)
    def test_finds_only_supported_game_folders_and_names(self):
        result=library.configure(str(self.game.parents[1]))
        self.assertEqual(result['worlds'],['blackbox']);self.assertTrue(result['mounted'])
        self.assertEqual(library.content_folder(str(self.game)),self.game.resolve())
        with self.assertRaises(ValueError):library.configure(str(self.archive))
        with self.assertRaises(ValueError):library.content_folder(str(self.root))
    def test_verified_copy_keeps_source_and_reuses_identical_cache(self):
        before=self.archive.read_bytes();stamp=self.archive.stat().st_mtime_ns
        library.configure(str(self.game));target=library.stage(self.archive.name)
        self.assertEqual(target.read_bytes(),before);self.assertEqual(self.archive.read_bytes(),before)
        self.assertEqual(self.archive.stat().st_mtime_ns,stamp)
        self.assertEqual(library.stage(self.archive.name),target)
        self.assertFalse(list(target.parent.glob('*.tmp')))
    def test_different_cached_archive_is_never_overwritten(self):
        library.configure(str(self.game));target=library.stage(self.archive.name)
        self.archive.write_bytes(b'EB a different source')
        with self.assertRaisesRegex(ValueError,'different source'):library.stage(self.archive.name)
        self.assertEqual(target.read_bytes(),b'EB synthetic archive fixture')
        self.assertFalse(list(target.parent.glob('*.tmp')))
    def test_invalid_archive_and_unknown_names_do_not_promote(self):
        library.configure(str(self.game));self.archive.write_bytes(b'not an archive')
        with self.assertRaisesRegex(ValueError,'EB archive'):library.stage(self.archive.name)
        self.assertFalse((self.root/'data/world-source'/self.archive.name).exists())
        with self.assertRaises(ValueError):library.stage('../private.txt')
    def test_disconnected_drive_is_clear_and_offline(self):
        library.configure(str(self.game));self.archive.unlink();self.game.rmdir()
        self.assertFalse(library.describe()['mounted'])
        with self.assertRaisesRegex(ValueError,'Reconnect'):library.stage(self.archive.name)
    def test_no_game_files_catalog_and_no_default_console_connection(self):
        self.assertEqual(empty_catalog()['assets'],[])
        with patch('socket.create_connection') as network:
            with self.assertRaisesRegex(ValueError,'not configured'):XBDM(None)
            network.assert_not_called()
    def test_xbox_path_rejects_command_injection(self):
        with patch.dict('os.environ',{'NATIVEX_XBOX_CONTENT':'Usb0:\\Games\\Skate 3\\data\\content'}):
            self.assertTrue(xbox_content_path().startswith('Usb0:'))
        for invalid in ['Hdd:\\bad"', 'Hdd:\\bad\r\nreboot', '/tmp/content']:
            with patch.dict('os.environ',{'NATIVEX_XBOX_CONTENT':invalid}):
                with self.assertRaises(ValueError):xbox_content_path()
    def test_known_duplicate_collision_failure_cannot_reach_console(self):
        result={'report':{'plan':{'instances':[{'origin':'copy'}]}}}
        with patch.object(level_builds,'read',return_value=result),patch.object(level_builds,'Console') as console:
            with self.assertRaisesRegex(ValueError,'duplication collision'):level_builds.install('build',{},None)
            console.assert_not_called()

if __name__=='__main__':unittest.main()
