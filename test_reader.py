import unittest
from reader import parse_feed, parse_headlines, timestamp, ArticleText

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

if __name__=='__main__':unittest.main()
