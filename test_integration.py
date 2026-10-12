import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import integration


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.desktop, self.icon = root / 'apps/dispatch.desktop', root / 'icons/dispatch.svg'
        self.patches = [patch.object(integration, 'DESKTOP', self.desktop),
                        patch.object(integration, 'ICON', self.icon),
                        patch.object(integration.subprocess, 'run')]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def test_install_and_remove_only_owned_launcher(self):
        integration.manage('install')
        self.assertIn(integration.MARKER, self.desktop.read_text())
        self.assertTrue(self.icon.exists())
        integration.manage('remove')
        self.assertFalse(self.desktop.exists())
        self.assertFalse(self.icon.exists())

    def test_user_entry_is_preserved(self):
        self.desktop.parent.mkdir()
        self.desktop.write_text('User launcher')
        integration.manage('install')
        integration.manage('remove')
        self.assertEqual(self.desktop.read_text(), 'User launcher')

    def test_symlink_is_never_followed(self):
        target = Path(self.tmp.name) / 'precious'
        target.write_text('Keep me')
        self.desktop.parent.mkdir()
        self.desktop.symlink_to(target)
        integration.manage('install')
        integration.manage('remove')
        self.assertEqual(target.read_text(), 'Keep me')
        self.assertTrue(self.desktop.is_symlink())
