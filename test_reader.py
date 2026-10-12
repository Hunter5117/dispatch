import unittest
from reader import parse_feed, parse_headlines, timestamp

FEED={'id':'test','name':'Test News','url':'https://example.org/rss'}
class ReaderTests(unittest.TestCase):
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
    def test_media_caption_does_not_replace_article_excerpt(self):
        data=b'''<rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>Story</title><link>https://example.org/story</link><description>Article excerpt</description><media:content url="image.jpg"><media:description>Photo caption</media:description></media:content></item></channel></rss>'''
        self.assertEqual(parse_feed(data,FEED)[0]['body'],'Article excerpt')
    def test_drudge_filters_directories_and_promotes_lead(self):
        html='<div id="DR-HU-MAIN"><a href="https://example.org/lead">LEAD</a></div>'
        html+=''.join(f'<a href="https://example.org/story/{i}">A headline with enough words {i}</a>' for i in range(5))
        html+='<a href="https://example.org/">PUBLICATION</a>'
        stories=parse_headlines(html)
        self.assertEqual(len(stories),6)
        self.assertTrue(stories[0]['lead'])

if __name__=='__main__':unittest.main()
