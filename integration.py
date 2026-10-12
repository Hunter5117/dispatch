"""Manage only Dispatch's own launcher and icon; never replace other entries."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
MARKER = 'X-Dispatch-Managed=true'
DESKTOP = HOME / '.local/share/applications/dispatch-news.desktop'
ICON = HOME / '.local/share/icons/hicolor/scalable/apps/dispatch-news.svg'


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.dispatch-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(text)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def manage(action):
    if DESKTOP.is_symlink() or ICON.is_symlink():
        return
    if DESKTOP.exists() and MARKER not in DESKTOP.read_text():
        return
    if action == 'install':
        if ICON.exists() and not DESKTOP.exists():
            return
        atomic_write(ICON, (ROOT / 'icon.svg').read_text())
        atomic_write(DESKTOP, '[Desktop Entry]\nType=Application\nName=Dispatch\n'
                     'GenericName=News Reader\nComment=RSS, Atom and Drudge headlines in your Omarchy theme\n'
                     'Exec=omarchy-shell dispatch open\nIcon=dispatch-news\nTerminal=false\n'
                     'StartupWMClass=org.omarchy.NewsReader\nCategories=Network;News;\n'
                     'Keywords=news;rss;atom;drudge;reader;feeds;\n' + MARKER + '\n')
    elif action == 'remove' and DESKTOP.exists():
        DESKTOP.unlink()
        if ICON.exists() and ICON.read_text() == (ROOT / 'icon.svg').read_text():
            ICON.unlink()
    for command in (['update-desktop-database', str(DESKTOP.parent)],
                    ['gtk-update-icon-cache', '-f', '-t', str(ICON.parents[2])]):
        try:
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('install', 'remove'):
        raise SystemExit('Usage: python integration.py install|remove')
    manage(sys.argv[1])
