import socket
import unittest
from unittest.mock import patch
from reader import parse_feed, parse_headlines, timestamp, ArticleText

FEED={'id':'test','name':'Test News','url':'https://example.org/rss'}
_REAL_RESOLVE = None

def fake_resolve(host, port):
    name = host.lower().rstrip('.')
    if name in ('example.org', 'example.com', 'cdn.example.org'):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]
    return _REAL_RESOLVE(host, port)

class ReaderTests(unittest.TestCase):
    def setUp(self):
        global _REAL_RESOLVE
        from reader import _resolve_host
        _REAL_RESOLVE = _resolve_host
        self.dns = patch('reader._resolve_host', side_effect=fake_resolve)
        self.dns.start()

    def tearDown(self):
        self.dns.stop()

    def test_rss_content_is_plain_text_and_unsafe_links_are_skipped(self):
        data=b'''<rss><channel><item><title>A &amp; B</title><link>https://example.org/story</link><description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;&lt;script&gt;bad()&lt;/script&gt;</description><pubDate>Sun, 11 Oct 2026 12:00:00 GMT</pubDate></item><item><title>Unsafe</title><link>javascript:alert(1)</link></item></channel></rss>'''
        stories=parse_feed(data,FEED)
        self.assertEqual(len(stories),1)
        self.assertEqual(stories[0]['body'],'Hello world')
        self.assertEqual(stories[0]['title'],'A & B')
        self.assertGreater(stories[0]['published'],0)
    def test_atom_namespaces_and_relative_links(self):
        data=b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Example</title><link href="/story"/><updated>2026-10-11T12:00:00Z</updated><summary>Excerpt</summary></entry></feed>'''
        self.assertEqual(parse_feed(data,FEED)[0]['url'],'https://example.org/story')
    def test_entity_declarations_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_feed(b'<!DOCTYPE rss [<!ENTITY e "unsafe">]><rss/>',FEED)
    def test_utf16_entity_declarations_are_rejected(self):
        data='<!DOCTYPE rss [<!ENTITY e "unsafe">]><rss/>'.encode('utf-16')
        self.assertNotIn(b'<!DOCTYPE', data.upper())
        with self.assertRaises(ValueError):
            parse_feed(data,FEED)
    def test_doctype_without_entities_is_readable(self):
        data=b'<!DOCTYPE rss><rss><channel><item><title>Ok</title><link>https://example.org/story</link></item></channel></rss>'
        self.assertEqual(parse_feed(data,FEED)[0]['title'],'Ok')
        utf16='<rss><channel><item><title>Ok</title><link>https://example.org/story</link></item></channel></rss>'.encode('utf-16')
        self.assertEqual(parse_feed(utf16,FEED)[0]['title'],'Ok')
    def test_private_image_urls_are_not_kept(self):
        for image in ('http://127.0.0.1/photo.jpg','http://169.254.169.254/latest/','http://[::1]/photo.jpg','http://10.1.2.3/a.jpg','http://2130706433/a.jpg','http://localhost/a.jpg','ftp://example.org/a.jpg'):
            xml=('<rss><channel><item><title>Story</title><link>https://example.org/story</link><enclosure type="image/jpeg" url="%s"/></item></channel></rss>'%image).encode()
            with self.subTest(image=image):
                self.assertEqual(parse_feed(xml,FEED)[0]['image'],'')
    def test_private_and_ftp_urls_are_not_contacted(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading
        from reader import ensure_public_http_url, open_public_url, PublicRedirectHandler
        hits=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200); self.end_headers()
            def log_message(self, format, *args):
                pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            for url in ('http://127.0.0.1/rss','http://169.254.169.254/','http://[::1]/','http://10.1.2.3/','ftp://example.org/rss','http://user:pass@example.org/rss',f'http://127.0.0.1:{server.server_address[1]}/rss'):
                with self.subTest(url=url):
                    with self.assertRaises(ValueError):
                        ensure_public_http_url(url)
            with self.assertRaises(ValueError):
                open_public_url(f'http://127.0.0.1:{server.server_address[1]}/rss')
            self.assertEqual(hits,[])
            handler=PublicRedirectHandler()
            request=__import__('urllib.request',fromlist=['Request']).Request('https://example.org/rss')
            from urllib.error import HTTPError
            for target in ('http://127.0.0.1/secret','ftp://example.org/file'):
                with self.subTest(target=target):
                    with self.assertRaises(HTTPError) as caught:
                        handler.redirect_request(request,None,302,'Found',{},target)
                    caught.exception.close()
            redirected=handler.redirect_request(request,None,302,'Found',{},'https://example.com/next')
            self.assertEqual(redirected.full_url,'https://example.com/next')
        finally:
            server.shutdown(); server.server_close()
    def test_cached_private_image_literals_are_hidden(self):
        from reader import image_host_is_blocked_offline
        self.assertTrue(image_host_is_blocked_offline('http://192.168.1.1/a.jpg'))
        self.assertTrue(image_host_is_blocked_offline('http://localhost/a.jpg'))
        self.assertFalse(image_host_is_blocked_offline('https://example.org/a.jpg'))
    def test_media_caption_does_not_replace_article_excerpt(self):
        data=b'''<rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>Story</title><link>https://example.org/story</link><description>Article excerpt</description><media:content url="image.jpg"><media:description>Photo caption</media:description></media:content></item></channel></rss>'''
        self.assertEqual(parse_feed(data,FEED)[0]['body'],'Article excerpt')
    def test_feed_photo_sources_and_unsafe_images(self):
        for image, expected in [
            ('<media:thumbnail url="/photo.jpg"/>', 'https://example.org/photo.jpg'),
            ('<enclosure type="image/jpeg" url="https://cdn.example.org/photo.jpg"/>', 'https://cdn.example.org/photo.jpg'),
            ('<description>&lt;img src="/inline.jpg"&gt;Excerpt</description>', 'https://example.org/inline.jpg'),
            ('<media:thumbnail url="javascript:alert(1)"/>', ''),
            ('<media:content medium="video" url="https://example.org/video.mp4"/>', ''),
        ]:
            with self.subTest(image=image):
                xml = ('<rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>Story</title><link>https://example.org/story</link>' + image + '</item></channel></rss>').encode()
                self.assertEqual(parse_feed(xml, FEED)[0]['image'], expected)

    def test_reader_extracts_prose_without_navigation_or_scripts(self):
        parser=ArticleText()
        prose='Readable publisher paragraph with useful details. '*12
        parser.feed('<nav><p>Navigation</p></nav><article><h2>Section</h2><p>'+prose+'<script>unsafe()</script></p><aside><p>Advertisement</p></aside><p>Last paragraph.</p></article>')
        text=parser.text()
        self.assertIn(prose.strip(),text)
        self.assertIn('Last paragraph.',text)
        for unwanted in ('Navigation','unsafe()','Advertisement'):
            self.assertNotIn(unwanted,text)

    def test_reader_supports_structured_articles_and_rejects_empty_pages(self):
        import json
        parser=ArticleText()
        body='Structured article text. '*30
        parser.feed('<script type="application/ld+json">'+json.dumps({'@graph':[{'articleBody':body}]})+'</script>')
        self.assertEqual(parser.text(),body.strip())
        with self.assertRaises(ValueError):ArticleText().text()

    def test_full_feed_content_is_preferred_and_keeps_paragraphs(self):
        xml=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Story</title><link href="/story"/><summary>Short summary</summary><content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml"><p>First paragraph.</p><p>Second paragraph.</p></div></content></entry></feed>'
        self.assertEqual(parse_feed(xml,FEED)[0]['body'],'First paragraph.\n\nSecond paragraph.')

    def test_tracking_pixels_are_not_story_photos(self):
        for markup in ('<img src="https://feedpress.me/link/20202/123.gif">', '<img width="1" height="1" src="https://example.org/pixel">'):
            import html
            xml=('<rss><channel><item><title>Story</title><link>https://example.org/story</link><description>'+html.escape(markup+'<img src="https://example.org/photo.jpg">')+'</description></item></channel></rss>').encode()
            self.assertEqual(parse_feed(xml,FEED)[0]['image'],'https://example.org/photo.jpg')

    def test_drudge_fallback_preserves_source_identity(self):
        from unittest.mock import patch
        from reader import fetch_feed, DRUDGE_RSS, SOURCE
        feed={**FEED,'id':'drudge','url':DRUDGE_RSS,'fallback_url':SOURCE}
        with patch('reader.fetch_feed_once',side_effect=[OSError('Feed unavailable'),[{'id':'fallback'}]]) as fetch:
            self.assertEqual(fetch_feed(feed),[{'id':'fallback'}])
            self.assertEqual(fetch.call_args.args[0]['kind'],'drudge')
            self.assertEqual(fetch.call_args.args[0]['id'],'drudge')
        with patch('reader.fetch_feed_once',side_effect=OSError('Unavailable')):
            with self.assertRaises(OSError):fetch_feed(FEED)

    def test_drudge_filters_directories_and_promotes_lead(self):
        html='<div id="DR-HU-MAIN"><a href="https://example.org/lead">LEAD</a></div>'
        html+=''.join(f'<a href="https://example.org/story/{i}">A headline with enough words {i}</a>' for i in range(5))
        html+='<a href="https://example.org/">PUBLICATION</a>'
        stories=parse_headlines(html)
        self.assertEqual(len(stories),6)
        self.assertTrue(stories[0]['lead'])

class LibraryTests(unittest.TestCase):
    def test_flat_list_loads_at_the_top_level(self):
        from reader import DEFAULT_FEEDS, load_library
        folders, feeds = load_library(DEFAULT_FEEDS)
        self.assertEqual(folders, [])
        self.assertEqual([feed['id'] for feed in feeds], ['drudge', 'bbc', 'guardian', 'npr', 'ars'])
        self.assertTrue(all(feed['parent'] == '' for feed in feeds))
        self.assertEqual(feeds[0]['fallback_url'], 'https://www.drudgereport.com/')

    def test_folder_depth_move_and_delete(self):
        from reader import MAX_FOLDER_DEPTH, assert_move_folder, assert_new_parent, load_library, remove_folder
        folders = []
        parent = ''
        for index in range(MAX_FOLDER_DEPTH):
            assert_new_parent(folders, parent)
            folder = {'id': f'fld_{index}', 'name': str(index), 'parent': parent}
            folders.append(folder)
            parent = folder['id']
        with self.assertRaises(ValueError):
            assert_new_parent(folders, parent)
        with self.assertRaises(ValueError):
            assert_move_folder(folders, 'fld_0', 'fld_5')
        feeds = [{'id': 'bbc', 'name': 'BBC', 'url': 'https://example.org/rss', 'kind': 'rss', 'parent': 'fld_0'}]
        child = {'id': 'fld_child', 'name': 'Inside', 'parent': 'fld_0'}
        folders.append(child)
        remove_folder(folders, feeds, 'fld_0')
        self.assertEqual(feeds[0]['parent'], '')
        self.assertEqual(child['parent'], '')
        self.assertFalse(any(folder['id'] == 'fld_0' for folder in folders))
        repaired, repaired_feeds = load_library({'version': 2, 'folders': [
            {'id': 'fld_a', 'name': 'A', 'parent': 'fld_b'},
            {'id': 'fld_b', 'name': 'B', 'parent': 'fld_a'},
        ], 'feeds': [{'id': 'gone', 'name': 'Gone', 'url': 'https://example.org/rss', 'parent': 'missing'}]})
        self.assertEqual(repaired[0]['parent'], '')
        self.assertEqual(repaired[1]['parent'], 'fld_a')
        self.assertEqual(repaired_feeds[0]['parent'], '')

if __name__=='__main__':unittest.main()
