#!/usr/bin/env python3
"""A local Omarchy-themed RSS, Atom, and Drudge news reader."""
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import tomllib
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

SOURCE = 'https://www.drudgereport.com/'
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
    {'id':'drudge','name':'Drudge Report','url':SOURCE,'kind':'drudge'},
    {'id':'bbc','name':'BBC World','url':'https://feeds.bbci.co.uk/news/world/rss.xml','kind':'rss'},
    {'id':'guardian','name':'The Guardian','url':'https://www.theguardian.com/world/rss','kind':'rss'},
    {'id':'npr','name':'NPR News','url':'https://feeds.npr.org/1001/rss.xml','kind':'rss'},
    {'id':'ars','name':'Ars Technica','url':'https://feeds.arstechnica.com/arstechnica/index','kind':'rss'},
]

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
    p.feed(value or '')
    return '\n\n'.join(re.sub(r'\s+',' ',line).strip() for line in ''.join(p.parts).splitlines() if line.strip())[:20000]

def timestamp(value):
    try: return parsedate_to_datetime(value).timestamp()
    except (ValueError, TypeError, OverflowError):
        try: return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
        except (ValueError, TypeError, AttributeError): return 0

def parse_feed(data, feed):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('Unsupported XML entity declarations')
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
            value = ''.join(child.itertext()).strip()
            values[tag] = value
            if tag == 'link':
                if child.get('rel','alternate') == 'alternate':
                    links.append(child.get('href') or value)
        url = next((urljoin(feed['url'],link) for link in links if link), '')
        if not url or urlparse(url).scheme not in ('http','https') or url in seen: continue
        title = plain(values.get('title','')).replace('\n',' ')
        if not title: continue
        seen.add(url)
        body = plain(values.get('encoded') or values.get('content') or values.get('description') or values.get('summary',''))
        stories.append({'id':hashlib.sha256(url.encode()).hexdigest()[:20], 'title':title,'url':url,
                        'source':feed['name'], 'feed_id':feed['id'], 'body':body,
                        'published':timestamp(values.get('pubDate') or values.get('published') or values.get('updated')),
                        'lead':False})
    if not stories: raise ValueError('No RSS or Atom stories found at this URL')
    return stories[:150]

def fetch_feed(feed):
    request = Request(feed['url'],headers={'User-Agent':'Mozilla/5.0 OmarchyNews/1.0'})
    with urlopen(request,timeout=20) as response:
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
        self.feeds=read_json(DATA/'feeds.json',DEFAULT_FEEDS)
        self.cache=read_json(CACHE/'feeds.json',{})
        self.state=read_json(DATA/'state.json',{'read':[],'saved':{},'compact':False})
        self.errors={}
        self.notice=None

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
        return sorted(result,key=lambda s:s.get('published',0),reverse=True)

    def emit(self):
        if self.ready:
            self.evaluate('window.receive('+json.dumps({'stories':self.stories(),'feeds':self.feeds,
                'state':self.state,'colors':theme_colors(),'loading':self.fetching,'errors':self.errors,
                'updated':max((v.get('updated',0) for k,v in self.cache.items() if k in {f['id'] for f in self.feeds}),default=0),
                'notice':self.notice})+')')

    def message(self,manager,result):
        try:
            m=json.loads(result.get_js_value().to_string());action=m.get('action')
            self.notice=None
            if action=='ready': self.ready=True
            elif action=='refresh': self.refresh();return
            elif action=='add': self.add_feed(m);return
            elif action=='remove':
                self.feeds=[f for f in self.feeds if f['id']!=m.get('id')]
                write_json(DATA/'feeds.json',self.feeds)
            elif action=='compact':
                self.state['compact']=not self.state.get('compact',False)
            elif action=='mark_all':
                ids=m.get('ids',[])
                valid={s['id'] for s in self.stories()}
                self.state['read']=list(set(self.state['read'])|{i for i in ids if i in valid})[-5000:]
            elif action in ('open','save','read'):
                story=next((s for s in self.stories()+list(self.state['saved'].values()) if s['id']==m.get('id')),None)
                if not story:return
                sid=story['id']
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

    def add_feed(self,m):
        url=m.get('url','').strip()
        if urlparse(url).scheme not in ('http','https') or not urlparse(url).hostname:
            self.notice='Enter an http or https RSS/Atom feed URL.';self.emit();return
        if any(f['url']==url for f in self.feeds):
            self.notice='That source is already in your reader.';self.emit();return
        feed={'id':hashlib.sha256(url.encode()).hexdigest()[:12],
              'name':m.get('name','').strip()[:70] or urlparse(url).hostname,'url':url,'kind':'rss'}
        def load():
            try:GLib.idle_add(self.added,feed,fetch_feed(feed),None)
            except Exception as exc:GLib.idle_add(self.added,feed,None,'Could not add feed: '+str(exc))
        self.notice='Checking feed…';self.emit()
        threading.Thread(target=load,daemon=True).start()

    def added(self,feed,stories,error):
        if error:self.notice=error
        elif not any(f['url']==feed['url'] for f in self.feeds):
            self.feeds.append(feed);write_json(DATA/'feeds.json',self.feeds)
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
