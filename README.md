# Dispatch

![Dispatch with fictional sample stories](preview.png)

A local news reader for Omarchy, styled with your active theme. Read RSS and Atom feeds in one calm interface, with a Drudge Report headline adapter included.

- All, unread and saved-story views; search across sources and excerpts.
- Add and remove RSS/Atom subscriptions, verified before saving.
- Article previews, compact layout and five-minute refresh.
- Cached headlines when a publisher is unavailable; saved stories remain in your library.
- Theme colors update automatically. No account, hosted service, remote images or tracking scripts.
- Omarchy shell command, launcher entry and optional bar button.

Starter sources: BBC World, The Guardian World, NPR News, Ars Technica and Drudge Report. Use **+ beside Your Sources** to add more feeds. Feed excerpts vary in length; originals open in your default browser. Dispatch does not fetch full articles or bypass subscriptions.

## Install

Requires Omarchy Quattro with its plugin-capable Quickshell, Python 3.11+, GTK 3, PyGObject and WebKitGTK 4.1. Install the Arch dependencies yourself:

```sh
omarchy pkg add python python-gobject gtk3 webkit2gtk-4.1
omarchy plugin add https://github.com/samcapshaw/dispatch.git --enable
```

The plugin opens the reader on demand. It registers a **Dispatch** desktop launcher and provides an optional news button in the bar. Open directly with:

```sh
omarchy-shell dispatch open
```

The launcher's icon and entry are installed in your user account. The plugin leaves any existing entry at its own path alone unless it carries Dispatch's managed marker. It does not change keybindings, dock pins, existing desktop entries or system configuration. Pin the launcher using your dock's normal controls if desired.

For standalone use from a checkout, run `python reader.py` with the same Python/GTK dependencies.

## Use

Click a headline for its excerpt; **Read original** opens the publisher in your browser. Use the star to save a story. `/` or Ctrl+F searches, Ctrl+R refreshes, and Escape closes a dialog. Source management is available from **+**.

## Storage and network access

Subscriptions and reading state: `~/.local/share/omarchy-news/`. Cached feeds: `~/.cache/omarchy-news/`. These locations match the original standalone Dispatch app, preserving existing libraries.

Dispatch contacts your configured feeds at launch, every five minutes while open, and when you refresh. Adding a source fetches its URL to verify RSS/Atom content. Drudge uses a headline parser against its public homepage. A source failure keeps the last cached stories. Response size is limited to 5 MB and requests time out after 20 seconds.

Source markup is converted to text. The reading surface loads local assets only; feed scripts, HTML and remote images are not rendered. Opening an original article delegates to your browser. Feed availability and publisher formats may change. This app is independent of the publications.

## Remove

```sh
omarchy plugin remove io.github.samcapshaw.dispatch
```

Disabling/removing the plugin removes only its managed launcher and matching icon. Close any running Dispatch window separately. Your subscriptions, read history, saved stories and feed cache are retained. To erase them deliberately, delete the two storage directories listed above. A separately installed standalone version is unaffected.

## Development

```sh
python -m unittest discover -v
node --check app.js
omarchy plugin validate .
```

The Python backend uses the standard library for fetching and parsing; GTK/WebKit provide the desktop window. The QML service and bar widget are thin Omarchy integrations. No package installation or network downloads happen when enabling the plugin.

MIT licensed. The application code and SVG icon are original work. Publisher names, headlines and excerpts belong to their respective owners and are fetched at runtime; none are bundled with this repository.
