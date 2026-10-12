# Marketplace submission draft

Title: **[Plugin]: Dispatch**

Review and confirm all checklist items before submitting this body through the marketplace form:
https://github.com/omacom/omarchy-plugin-marketplace/issues/new?template=submit-plugin.yml

### Repository URL

https://github.com/samcapshaw/dispatch

### Category

Productivity

### Tags

quickshell, media, launcher

### Suggest a missing tag

News

### Maintainer notes

Dispatch is a local GTK/WebKit RSS and Atom reader with an original Omarchy theme-aware interface and a Drudge headline adapter. The Quickshell service opens its desktop window on demand; an optional bar button and managed desktop launcher provide access.

Dependencies: Python 3.11+, python-gobject, GTK 3 and WebKitGTK 4.1. These are documented for explicit installation; enabling the plugin never installs packages or runs privileged commands. Network requests fetch the user's configured feed URLs and Drudge's public homepage while the reader is open. No scripts or remote images from publishers load in the reading surface. Original links open in the default browser.

Writes: subscriptions/state in ~/.local/share/omarchy-news/, cache in ~/.cache/omarchy-news/, and only its own marked launcher and matching icon under ~/.local/share/. User configuration, dock pins and other desktop launchers are not overwritten. Disabling removes the managed launcher/icon; library data is retained. MIT licensed; application code, icon and fictional preview headlines are original. Publisher content is fetched at runtime and is not bundled.

Validated with Omarchy's manifest validator and installed/tested on an Omarchy desktop. Eight automated tests cover feed parsing and managed launcher installation/removal, including preservation of existing entries and symlinks. Shell command and launcher registration were checked live.

### Submission checklist

- [ ] The repository is public and contains installation and removal instructions.
- [ ] I have documented the plugin license and any external dependencies.
- [ ] I confirm that I own or have permission to submit this plugin and its preview assets.
- [ ] The plugin does not overwrite user configuration without explicit consent.
- [ ] I understand that approval is for listing and is not a security review.
