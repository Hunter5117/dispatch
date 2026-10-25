#!/usr/bin/env python3
"""A local Omarchy-themed RSS, Atom, and Drudge news reader."""
import hashlib
import http.client
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import threading
import time
import tomllib
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPSHandler, HTTPHandler, HTTPRedirectHandler, Request, build_opener
import xml.parsers.expat as expat

SOURCE = 'https://www.drudgereport.com/'
DRUDGE_RSS = 'https://feedpress.me/drudgereportfeed'
ROOT = Path(__file__).resolve().parent
DATA = Path.home() / '.local/share/omarchy-news'
CACHE = Path.home() / '.cache/omarchy-news'

class Headlines(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.divs, self.items, self.seen = [], [], set()
        self.link = None
        self.ignore = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'):
            self.ignore += 1
        if tag == 'div':
            self.divs.append(attrs.get('id', ''))
        if tag == 'a' and not self.ignore:
            self.link = {'url': urljoin(SOURCE, attrs.get('href', '')), 'parts': [],
                         'lead': 'DR-HU-MAIN' in self.divs}
        if tag == 'br' and self.link:
            self.link['parts'].append(' ')

    def handle_data(self, data):
        if self.link and not self.ignore:
            self.link['parts'].append(data)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.ignore = max(0, self.ignore - 1)
        if tag == 'div' and self.divs:
            self.divs.pop()
        if tag != 'a' or not self.link:
            return
        link, self.link = self.link, None
        text = re.sub(r'\s+', ' ', ''.join(link['parts'])).strip()
        url = link['url']
        parsed = urlparse(url)
        host = parsed.hostname or ''
        if parsed.scheme not in ('http', 'https') or not host or 'drudgereport' in host:
            return
        if not text or url in self.seen:
            return
        # The source also contains large publication directories and utility links.
        if not link['lead'] and (len(text.split()) < 4 or len(parsed.path.strip('/')) < 3):
            return
        if re.match(r'^(PRIVACY|RECENT HEADLINES|IPHONE|ANDROID|WORLD NEWSPAPERS|FRONT PAGES)', text):
            return
        self.seen.add(url)
        self.items.append({'id': hashlib.sha256(url.encode()).hexdigest()[:20], 'title': text,
                           'url': url, 'source': host.removeprefix('www.').removeprefix('www1.'),
                           'lead': link['lead']})

def parse_headlines(html):
    parser = Headlines()
    parser.feed(html)
    if len(parser.items) < 5:
        raise ValueError('The source layout changed or returned too few headlines')
    return sorted(parser.items, key=lambda story: not story['lead'])

def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False))
    temp.replace(path)

def theme_colors():
    colors = {'background':'#1a1b26', 'lighter_background':'#24283b', 'foreground':'#a9b1d6',
              'bright_foreground':'#c0caf5', 'accent':'#7aa2f7', 'muted':'#414868', 'green':'#9ece6a'}
    path = Path.home() / '.local/state/omarchy/current/theme/colors.toml'
    try:
        colors.update(tomllib.loads(path.read_text()))
    except (OSError, ValueError):
        pass
    return colors

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

DEFAULT_FEEDS = [
    {'id':'drudge','name':'Drudge Report','url':DRUDGE_RSS,'kind':'rss','fallback_url':SOURCE},
    {'id':'bbc','name':'BBC World','url':'https://feeds.bbci.co.uk/news/world/rss.xml','kind':'rss'},
    {'id':'guardian','name':'The Guardian','url':'https://www.theguardian.com/world/rss','kind':'rss'},
    {'id':'npr','name':'NPR News','url':'https://feeds.npr.org/1001/rss.xml','kind':'rss'},
    {'id':'ars','name':'Ars Technica','url':'https://feeds.arstechnica.com/arstechnica/index','kind':'rss'},
]
MAX_FOLDER_DEPTH = 6

def clean_name(value):
    name = ' '.join(str(value or '').split())
    if not name:
        raise ValueError('Enter a name.')
    return name[:70]

def new_folder_id():
    return 'fld_' + secrets.token_hex(6)

def _parent(item):
    parent = item.get('parent') if isinstance(item, dict) else ''
    return parent if isinstance(parent, str) else ''

def folder_depth(folders, folder_id):
    if not folder_id:
        return 0
    by_id = {folder['id']: folder for folder in folders}
    if folder_id not in by_id:
        raise ValueError('That folder is no longer there.')
    seen, current, depth = set(), folder_id, 0
    while current:
        if current in seen:
            raise ValueError('That folder contains itself.')
        seen.add(current)
        depth += 1
        if depth > MAX_FOLDER_DEPTH:
            raise ValueError('That folder is nested too deeply.')
        current = _parent(by_id.get(current) or {})
    return depth

def descendant_folders(folders, folder_id):
    found, stack = set(), [folder_id]
    while stack:
        current = stack.pop()
        for folder in folders:
            if _parent(folder) == current and folder['id'] not in found:
                found.add(folder['id'])
                stack.append(folder['id'])
    return found

def subtree_depth(folders, folder_id):
    children = [folder['id'] for folder in folders if _parent(folder) == folder_id]
    if not children:
        return 0
    return 1 + max(subtree_depth(folders, child) for child in children)

def assert_new_parent(folders, parent):
    if parent and not any(folder['id'] == parent for folder in folders):
        raise ValueError('That folder is no longer there.')
    if folder_depth(folders, parent) + 1 > MAX_FOLDER_DEPTH:
        raise ValueError('That folder is nested too deeply.')

def assert_move_folder(folders, folder_id, parent):
    if parent == folder_id or parent in descendant_folders(folders, folder_id):
        raise ValueError('A folder cannot sit inside itself.')
    assert_new_parent(folders, parent)
    if folder_depth(folders, parent) + 1 + subtree_depth(folders, folder_id) > MAX_FOLDER_DEPTH:
        raise ValueError('That folder is nested too deeply.')

def normalize_feed(feed):
    if not isinstance(feed, dict) or not isinstance(feed.get('url'), str) or not feed.get('url'):
        return None
    item = {
        'id': str(feed.get('id') or hashlib.sha256(feed['url'].encode()).hexdigest()[:12]),
        'name': str(feed.get('name') or '')[:70],
        'url': feed['url'],
        'kind': str(feed.get('kind') or 'rss'),
        'parent': _parent(feed),
    }
    if isinstance(feed.get('fallback_url'), str) and feed.get('fallback_url'):
        item['fallback_url'] = feed['fallback_url']
    return item

def normalize_folder(folder):
    if not isinstance(folder, dict) or not isinstance(folder.get('id'), str) or not folder.get('id'):
        return None
    return {'id': folder['id'][:24], 'name': str(folder.get('name') or 'Folder')[:70] or 'Folder', 'parent': _parent(folder)}

def repair_library(folders, feeds):
    kept, seen = [], set()
    for folder in folders:
        if folder['id'] in seen:
            continue
        seen.add(folder['id'])
        kept.append(folder)
    folders = kept
    ids = {folder['id'] for folder in folders}
    for folder in folders:
        if folder['parent'] not in ids:
            folder['parent'] = ''
    for folder in folders:
        try:
            folder_depth(folders, folder['id'])
        except ValueError:
            folder['parent'] = ''
    seen_feeds = set()
    clean_feeds = []
    for feed in feeds:
        if feed['id'] in seen_feeds:
            continue
        seen_feeds.add(feed['id'])
        if feed['parent'] not in ids:
            feed['parent'] = ''
        clean_feeds.append(feed)
    return folders, clean_feeds

def load_library(data):
    """Accept the older flat feed list and the version-2 folder library."""
    if isinstance(data, list):
        feeds = [item for item in (normalize_feed(feed) for feed in data) if item]
        return repair_library([], feeds)
    if isinstance(data, dict) and isinstance(data.get('feeds'), list):
        folders = [item for item in (normalize_folder(folder) for folder in data.get('folders') or []) if item]
        feeds = [item for item in (normalize_feed(feed) for feed in data['feeds']) if item]
        return repair_library(folders, feeds)
    raise ValueError('Feed library could not be read.')

def remove_folder(folders, feeds, folder_id):
    folder = next((item for item in folders if item['id'] == folder_id), None)
    if folder is None:
        raise ValueError('That folder is no longer there.')
    parent = _parent(folder)
    for item in folders + feeds:
        if _parent(item) == folder_id:
            item['parent'] = parent
    folders.remove(folder)

class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style'): self.hidden += 1
        if tag in ('p','br','div','li'): self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script','style'): self.hidden = max(0,self.hidden-1)
        if tag in ('p','div','li'): self.parts.append('\n')
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)

def plain(value):
    p = PlainText()
    p.feed(re.sub(r'(<\/?)[\w]+:',r'\1',value or ''))
    return '\n\n'.join(re.sub(r'\s+',' ',line).strip() for line in ''.join(p.parts).splitlines() if line.strip())[:200000]

class ArticleText(HTMLParser):
    """Collect prose from article/main containers, never render publisher HTML."""
    VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    SKIP = {'script','style','nav','header','footer','aside','form','button','noscript','svg'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.candidates = []
        self.paragraph = None
        self.jsonld = None
        self.structured = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        hidden = (self.stack[-1][1] if self.stack else False) or tag in self.SKIP
        if tag == 'script' and attrs.get('type','').lower() == 'application/ld+json':
            self.jsonld = []
        if tag in self.VOID:
            if tag == 'br' and self.paragraph is not None: self.paragraph.append(' ')
            return
        hint = attrs.get('class','') + ' ' + attrs.get('id','') + ' ' + attrs.get('itemprop','')
        candidate = None
        if not hidden and (tag in ('article','main') or re.search(r'article[-_ ]?(body|content)|story[-_ ]?(body|content)|entry-content|articleBody',hint,re.I)):
            candidate = []
            self.candidates.append((3 if tag == 'article' or 'articleBody' in hint else 2, candidate))
        self.stack.append((tag,hidden,candidate))
        if not hidden and tag in ('p','h2','h3','blockquote','li'):
            self.finish_paragraph()
            self.paragraph = []

    def handle_data(self, value):
        if self.jsonld is not None: self.jsonld.append(value)
        if self.paragraph is not None and self.stack and not self.stack[-1][1]:
            self.paragraph.append(value)

    def finish_paragraph(self):
        if self.paragraph is None: return
        text = re.sub(r'\s+',' ',''.join(self.paragraph)).strip()
        if text:
            for _, hidden, candidate in self.stack:
                if candidate is not None and not hidden: candidate.append(text)
        self.paragraph = None

    def handle_endtag(self, tag):
        if tag == 'script' and self.jsonld is not None:
            try: self.structured.append(json.loads(''.join(self.jsonld)))
            except ValueError: pass
            self.jsonld = None
        if tag in ('p','h2','h3','blockquote','li','article','main','div'): self.finish_paragraph()
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def text(self):
        self.finish_paragraph()
        def bodies(value):
            if isinstance(value,dict):
                if isinstance(value.get('articleBody'),str): yield plain(value['articleBody'])
                for child in value.values(): yield from bodies(child)
            elif isinstance(value,list):
                for child in value: yield from bodies(child)
        options = [text for value in self.structured for text in bodies(value)]
        options += ['\n\n'.join(parts) for _,parts in self.candidates]
        body = max(options,key=len,default='')
        if len(body) < 300: raise ValueError('This publisher did not provide readable article text. The feed text is still available below.')
        return body[:200000]

def fetch_article(url):
    with open_public_url(url, headers={'User-Agent':'Mozilla/5.0 Dispatch/1.0', 'Accept':'text/html'}) as response:
        if response.headers.get_content_type() not in ('text/html','application/xhtml+xml'):
            raise ValueError('This link is not an HTML article.')
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000: raise ValueError('Article page is too large.')
        html = raw.decode(response.headers.get_content_charset() or 'utf-8',errors='replace')
    parser = ArticleText()
    parser.feed(html)
    return parser.text()

def timestamp(value):
    try: return parsedate_to_datetime(value).timestamp()
    except (ValueError, TypeError, OverflowError):
        try: return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
        except (ValueError, TypeError, AttributeError): return 0

def address_is_public(ip):
    mapped = getattr(ip, 'ipv4_mapped', None)
    if mapped is not None:
        ip = mapped
    # is_global is true for multicast. Those addresses are not article or feed hosts.
    return bool(ip.is_global) and not ip.is_multicast

def _resolve_host(host, port):
    result = {}
    def run():
        try:
            result['infos'] = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except BaseException as exc:
            result['error'] = exc
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(5)
    if thread.is_alive():
        raise TimeoutError('Could not resolve host')
    if 'error' in result:
        raise result['error']
    return result.get('infos') or []

def public_addresses(host, port):
    host = host.strip()
    if not host or '\x00' in host:
        raise ValueError('Unsupported URL')
    literal = host.split('%', 1)[0]
    try:
        ip = ipaddress.ip_address(literal)
    except ValueError:
        ip = None
    if ip is not None:
        if not address_is_public(ip):
            raise ValueError('URL host is not a public address')
        return [literal]
    try:
        infos = _resolve_host(host, port)
    except (socket.gaierror, TimeoutError, UnicodeError) as exc:
        raise ValueError('Could not resolve host') from exc
    found = []
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split('%', 1)[0])
        if not address_is_public(ip):
            raise ValueError('URL host is not a public address')
        found.append(str(info[4][0]).split('%', 1)[0])
    if not found:
        raise ValueError('Could not resolve host')
    return list(dict.fromkeys(found))

def ensure_public_http_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or not parsed.hostname:
        raise ValueError('Unsupported URL')
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError('Unsupported URL') from exc
    if port == 0:
        raise ValueError('Unsupported URL')
    public_addresses(parsed.hostname, port or (443 if parsed.scheme == 'https' else 80))
    return url

def public_http_url(url):
    try:
        ensure_public_http_url(url)
    except ValueError:
        return False
    return True

def image_host_is_blocked_offline(url):
    """Block image hosts that are unsafe without a DNS lookup. Other names are checked when fetched."""
    if not isinstance(url, str) or not url:
        return True
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme not in ('http', 'https') or not host or parsed.username or parsed.password:
        return True
    bare = host.lower().rstrip('.')
    if bare in ('localhost', 'localhost.localdomain') or bare.endswith('.localhost') or bare.endswith('.local'):
        return True
    if re.fullmatch(r'(?:\d+|0x[0-9a-f]+)', bare):
        return True
    if re.fullmatch(r'(?:\d{1,3}\.){3}\d{1,3}', bare) and any(len(part) > 1 and part.startswith('0') for part in bare.split('.')):
        return True
    try:
        ip = ipaddress.ip_address(bare.split('%', 1)[0])
    except ValueError:
        return False
    return not address_is_public(ip)

def hide_blocked_images(stories):
    for story in stories:
        if isinstance(story, dict) and story.get('image') and image_host_is_blocked_offline(story['image']):
            story['image'] = ''

def _connect_public(address, timeout, source_address):
    host, port = address
    error = None
    for ip in public_addresses(host, port):
        try:
            return socket.create_connection((ip, port), timeout, source_address)
        except OSError as exc:
            error = exc
    if error is not None:
        raise error
    raise OSError('Could not connect')

class PublicHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        # A proxy connection uses the proxy host. Direct connections pin the resolved public address.
        if not self._tunnel_host:
            self._create_connection = _connect_public
        super().connect()

class PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        if not self._tunnel_host:
            self._create_connection = _connect_public
        super().connect()

class PublicHTTPHandler(HTTPHandler):
    def http_open(self, req):
        ensure_public_http_url(req.full_url)
        connection = http.client.HTTPConnection if req.has_proxy() else PublicHTTPConnection
        return self.do_open(connection, req)

class PublicHTTPSHandler(HTTPSHandler):
    def https_open(self, req):
        ensure_public_http_url(req.full_url)
        connection = http.client.HTTPSConnection if req.has_proxy() else PublicHTTPSConnection
        return self.do_open(connection, req, context=self._context)

class PublicRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme not in ('http', 'https'):
            raise HTTPError(newurl, code, 'Redirection to this URL is not allowed', headers, fp)
        try:
            ensure_public_http_url(newurl)
        except ValueError as exc:
            raise HTTPError(newurl, code, str(exc), headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

_OPENER = build_opener(PublicHTTPHandler(), PublicHTTPSHandler(), PublicRedirectHandler())

def open_public_url(url, headers=None, timeout=20):
    ensure_public_http_url(url)
    try:
        return _OPENER.open(Request(url, headers=headers or {}), timeout=timeout)
    except HTTPError as exc:
        exc.close()
        raise

def reject_xml_entities(data):
    """Reject entity declarations after the parser decodes the document, including UTF-16."""
    parser = expat.ParserCreate()
    def forbid(*_args):
        raise ValueError('Unsupported XML entity declarations')
    parser.EntityDeclHandler = forbid
    parser.UnparsedEntityDeclHandler = forbid
    parser.ExternalEntityRefHandler = forbid
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True)
    except ValueError:
        raise
    except expat.ExpatError:
        return

class ImageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            attrs = dict(attrs)
            if any(re.fullmatch(r'[012](?:px)?', attrs.get(d, '').strip()) for d in ('width','height')):
                return
            self.urls.append(attrs.get('src', ''))

def story_image(entry, base, markup):
    candidates = []
    for child in entry.iter():
        tag = child.tag.rsplit('}', 1)[-1]
        if child.tag.startswith('{http://search.yahoo.com/mrss/}') and tag in ('thumbnail', 'content'):
            if tag == 'thumbnail' or child.get('medium') == 'image' or child.get('type', '').startswith('image/') or not child.get('type') and not child.get('medium'):
                candidates.append(child.get('url', ''))
        elif tag in ('enclosure', 'link') and child.get('type', '').startswith('image/'):
            candidates.append(child.get('url') or child.get('href', ''))
    images = ImageLinks()
    images.feed(markup)
    candidates.extend(images.urls)
    for candidate in candidates:
        if not candidate:
            continue
        url = urljoin(base, candidate)
        parsed = urlparse(url)
        if parsed.hostname == 'feedpress.me' and parsed.path.startswith('/link/') and parsed.path.endswith('.gif'):
            continue
        if public_http_url(url):
            return url
    return ''

def parse_feed(data, feed):
    reject_xml_entities(data)
    root = ET.fromstring(data)
    local = lambda tag: tag.rsplit('}',1)[-1]
    stories, seen = [], set()
    for entry in root.iter():
        if local(entry.tag) not in ('item','entry'): continue
        values, links = {}, []
        for child in entry:
            if child.tag.startswith('{http://search.yahoo.com/mrss/}'):
                continue
            tag = local(child.tag)
            value = (''.join(ET.tostring(part, encoding='unicode') for part in child) if tag in ('content','summary') and len(child) else ''.join(child.itertext())).strip()
            values[tag] = value
            if tag == 'link':
                if child.get('rel','alternate') == 'alternate':
                    links.append(child.get('href') or value)
        url = next((urljoin(feed['url'],link) for link in links if link), '')
        if not url or urlparse(url).scheme not in ('http','https') or url in seen: continue
        title = plain(values.get('title','')).replace('\n',' ')
        if not title: continue
        seen.add(url)
        markup = values.get('encoded') or values.get('content') or values.get('description') or values.get('summary','')
        body = plain(markup)
        stories.append({'id':hashlib.sha256(url.encode()).hexdigest()[:20], 'title':title,'url':url,
                        'source':feed['name'], 'feed_id':feed['id'], 'body':body, 'image':story_image(entry, url, markup),
                        'published':timestamp(values.get('pubDate') or values.get('published') or values.get('updated')),
                        'lead':False})
    if not stories: raise ValueError('No RSS or Atom stories found at this URL')
    return stories[:150]

def fetch_feed(feed):
    try:
        return fetch_feed_once(feed)
    except Exception:
        if feed.get('url') != DRUDGE_RSS or feed.get('fallback_url') != SOURCE:
            raise
        return fetch_feed_once({**feed,'url':SOURCE,'kind':'drudge'})

def fetch_feed_once(feed):
    with open_public_url(feed['url'], headers={'User-Agent':'Mozilla/5.0 OmarchyNews/1.0'}) as response:
        data = response.read(5_000_001)
    if len(data)>5_000_000: raise ValueError('Feed is too large')
    if feed.get('kind') == 'drudge':
        stories = parse_headlines(data.decode('utf-8',errors='replace'))
        for story in stories:
            story.update(feed_id=feed['id'],body='',published=0)
    else:
        stories = parse_feed(data,feed)
    return stories

import gi
gi.require_version('Gtk','3.0')
gi.require_version('WebKit2','4.1')
from gi.repository import Gtk,Gio,GLib,WebKit2,Gdk
GLib.set_prgname('org.omarchy.NewsReader')

class Reader(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.omarchy.NewsReader',flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window=None
        self.ready=False
        self.fetching=False
        try:
            self.folders,self.feeds=load_library(read_json(DATA/'feeds.json',DEFAULT_FEEDS))
        except ValueError:
            self.folders,self.feeds=load_library(DEFAULT_FEEDS)
        library_changed=False
        for feed in self.feeds:
            if feed.get('id')=='drudge' and feed.get('url')==SOURCE and feed.get('kind')=='drudge':
                feed.update(url=DRUDGE_RSS,kind='rss',fallback_url=SOURCE)
                library_changed=True
        if library_changed:
            self.save_library()
        self.cache=read_json(CACHE/'feeds.json',{})
        self.state=read_json(DATA/'state.json',{'read':[],'saved':{},'compact':False})
        self.errors={}
        self.notice=None
        self.articles={}
        self.article_loading=set()

    def do_activate(self):
        if self.window:
            self.window.present();return
        self.window=Gtk.ApplicationWindow(application=self,title='Dispatch · News Reader')
        self.window.set_default_size(1200,820)
        self.window.set_icon_name('org.omarchy.NewsReader')
        manager=WebKit2.UserContentManager()
        manager.register_script_message_handler('reader')
        manager.connect('script-message-received::reader',self.message)
        self.web=WebKit2.WebView(user_content_manager=manager)
        color=Gdk.RGBA();color.parse(theme_colors()['background']);self.web.set_background_color(color)
        self.web.connect('decide-policy',self.navigation)
        self.window.add(self.web)
        self.web.load_uri((ROOT/'index.html').as_uri())
        self.window.show_all()
        GLib.timeout_add_seconds(300,self.auto_refresh)
        GLib.timeout_add_seconds(20,self.sync_theme)
        self.refresh()

    def navigation(self,web,decision,kind):
        if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION,WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri=decision.get_navigation_action().get_request().get_uri()
            if not uri.startswith((ROOT/'index.html').as_uri()):
                decision.ignore();return True
        return False

    def evaluate(self,script):
        self.web.evaluate_javascript(script,-1,None,None,None,None,None)

    def stories(self):
        result,seen=[],set()
        for feed in self.feeds:
            for story in self.cache.get(feed['id'],{}).get('stories',[]):
                if story['id'] not in seen:
                    seen.add(story['id']);result.append(story)
        result = sorted(result,key=lambda s:s.get('published',0),reverse=True)
        hide_blocked_images(result)
        return result

    def emit(self):
        saved = self.state.get('saved')
        if isinstance(saved, dict):
            hide_blocked_images(saved.values())
        if self.ready:
            self.evaluate('window.receive('+json.dumps({'stories':self.stories(),'feeds':self.feeds,
                'folders':self.folders,'state':self.state,'colors':theme_colors(),'loading':self.fetching,'errors':self.errors,
                'updated':max((v.get('updated',0) for k,v in self.cache.items() if k in {f['id'] for f in self.feeds}),default=0),
                'notice':self.notice})+')')

    def message(self,manager,result):
        try:
            m=json.loads(result.get_js_value().to_string());action=m.get('action')
            self.notice=None
            if action=='ready': self.ready=True
            elif action=='refresh': self.refresh();return
            elif action=='add': self.add_feed(m);return
            elif action=='add_folder': self.add_folder(m)
            elif action=='rename': self.rename_item(m)
            elif action=='move': self.move_item(m)
            elif action=='remove': self.remove_item(m.get('id'))
            elif action=='closed':
                ids=m.get('ids')
                if not isinstance(ids,list) or not all(isinstance(item,str) and len(item)<=24 for item in ids):
                    raise ValueError('Could not save which folders are open.')
                known={folder['id'] for folder in self.folders}
                self.state['closed']=[item for item in ids if item in known][:200]
            elif action=='preferences':
                if m.get('layout') in ('briefing', 'cards', 'feed', 'headlines'):
                    self.state['layout'] = m['layout']
                    self.state['compact'] = m['layout'] == 'headlines'
                if isinstance(m.get('photos'), bool):
                    self.state['photos'] = m['photos']
            elif action=='compact':
                self.state['compact']=not self.state.get('compact',False)
                self.state['layout']='headlines' if self.state['compact'] else 'briefing'
            elif action=='mark_all':
                ids=m.get('ids',[])
                valid={s['id'] for s in self.stories()}
                self.state['read']=list(set(self.state['read'])|{i for i in ids if i in valid})[-5000:]
            elif action in ('open','save','read','article'):
                story=next((s for s in self.stories()+list(self.state['saved'].values()) if s['id']==m.get('id')),None)
                if not story:return
                sid=story['id']
                if action=='article':
                    self.load_article(story);return
                if action=='save':
                    if sid in self.state['saved']:del self.state['saved'][sid]
                    else:self.state['saved'][sid]=story
                else:
                    if sid not in self.state['read']:self.state['read'].append(sid)
                    if action=='open' and urlparse(story['url']).scheme in ('http','https'):
                        subprocess.Popen(['xdg-open',story['url']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            write_json(DATA/'state.json',self.state)
            self.emit()
        except (ValueError,KeyError,TypeError,OSError) as exc:
            self.notice=str(exc);self.emit()

    def load_article(self,story):
        sid=story['id']
        if sid in self.articles:
            self.article_result(sid,self.articles[sid],None);return
        if sid in self.article_loading:return
        self.article_loading.add(sid)
        def load():
            try:GLib.idle_add(self.article_result,sid,fetch_article(story['url']),None)
            except Exception as exc:GLib.idle_add(self.article_result,sid,None,'Could not load reader view: '+str(exc))
        threading.Thread(target=load,daemon=True).start()

    def article_result(self,sid,body,error):
        self.article_loading.discard(sid)
        if body:self.articles[sid]=body
        if self.ready:
            self.evaluate('window.receiveArticle('+json.dumps({'id':sid,'body':body,'error':error})+')')
        return False

    def save_library(self):
        write_json(DATA/'feeds.json',{'version':2,'folders':self.folders,'feeds':self.feeds})

    def find_item(self,item_id):
        for folder in self.folders:
            if folder['id']==item_id:return 'folder',folder
        for feed in self.feeds:
            if feed['id']==item_id:return 'feed',feed
        return None,None

    def add_folder(self,m):
        parent=m.get('parent') or ''
        if not isinstance(parent,str):parent=''
        assert_new_parent(self.folders,parent)
        self.folders.append({'id':new_folder_id(),'name':clean_name(m.get('name')),'parent':parent})
        self.save_library()

    def rename_item(self,m):
        kind,item=self.find_item(m.get('id'))
        if item is None:raise ValueError('That item is no longer there.')
        item['name']=clean_name(m.get('name'))
        self.save_library()

    def move_item(self,m):
        parent=m.get('parent') or ''
        if not isinstance(parent,str):parent=''
        kind,item=self.find_item(m.get('id'))
        if item is None:raise ValueError('That item is no longer there.')
        if kind=='folder':assert_move_folder(self.folders,item['id'],parent)
        elif parent and not any(folder['id']==parent for folder in self.folders):
            raise ValueError('That folder is no longer there.')
        item['parent']=parent
        self.save_library()

    def remove_item(self,item_id):
        kind,item=self.find_item(item_id)
        if item is None:raise ValueError('That item is no longer there.')
        if kind=='folder':
            remove_folder(self.folders,self.feeds,item_id)
            closed=self.state.get('closed')
            if not isinstance(closed,list):closed=[]
            self.state['closed']=[folder_id for folder_id in closed if isinstance(folder_id,str) and folder_id!=item_id]
        else:
            self.feeds=[feed for feed in self.feeds if feed['id']!=item_id]
            self.errors.pop(item_id,None)
        self.save_library()

    def add_feed(self,m):
        url=m.get('url','').strip()
        if urlparse(url).scheme not in ('http','https') or not urlparse(url).hostname:
            self.notice='Enter an http or https RSS/Atom feed URL.';self.emit();return
        if any(f['url']==url for f in self.feeds):
            self.notice='That source is already in your reader.';self.emit();return
        parent=m.get('parent') or ''
        if not isinstance(parent,str):parent=''
        if parent and not any(folder['id']==parent for folder in self.folders):
            self.notice='That folder is no longer there.';self.emit();return
        feed={'id':hashlib.sha256(url.encode()).hexdigest()[:12],
              'name':m.get('name','').strip()[:70] or urlparse(url).hostname,'url':url,'kind':'rss','parent':parent}
        def load():
            try:GLib.idle_add(self.added,feed,fetch_feed(feed),None)
            except Exception as exc:GLib.idle_add(self.added,feed,None,'Could not add feed: '+str(exc))
        self.notice='Checking feed…';self.emit()
        threading.Thread(target=load,daemon=True).start()

    def added(self,feed,stories,error):
        if error:self.notice=error
        elif not any(f['url']==feed['url'] for f in self.feeds):
            self.feeds.append(feed);self.save_library()
            self.cache[feed['id']]={'stories':stories,'updated':time.time()}
            write_json(CACHE/'feeds.json',self.cache);self.notice='Source added.'
        self.emit();return False

    def refresh(self):
        if self.fetching:return
        self.fetching=True;self.emit()
        threading.Thread(target=self.fetch,daemon=True).start()

    def fetch(self):
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures={pool.submit(fetch_feed,f):f for f in list(self.feeds)}
            for future in as_completed(futures):
                f=futures[future]
                try:GLib.idle_add(self.fetched,f,future.result(),None)
                except Exception as exc:GLib.idle_add(self.fetched,f,None,str(exc))
        GLib.idle_add(self.finished)

    def fetched(self,feed,stories,error):
        if not any(f['id']==feed['id'] for f in self.feeds):return False
        if error:self.errors[feed['id']]=error
        else:
            self.errors.pop(feed['id'],None)
            self.cache[feed['id']]={'stories':stories,'updated':time.time()}
            write_json(CACHE/'feeds.json',self.cache)
        self.emit();return False

    def finished(self):
        self.fetching=False;self.emit();return False

    def auto_refresh(self):self.refresh();return True
    def sync_theme(self):
        if self.ready:self.evaluate('window.applyTheme('+json.dumps(theme_colors())+')')
        return True

if __name__=='__main__':Reader().run()
