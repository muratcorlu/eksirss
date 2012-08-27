#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import os
import webapp2
import urllib
import urllib2
from xml.dom.minidom import parse, parseString, Document
import os.path, time
from google.appengine.api import memcache
import hashlib
import datetime

class MainHandler(webapp2.RequestHandler):
    def _addLinks(self, a):
        link = a.getAttribute('href')
        if link.startswith("http://") or link.startswith('https://'):
            return a

        a.setAttribute('href', 'http://www.eksisozluk.com/%s' % link)
        return a

    def get(self):
        word = self.request.get('t')

        if word:
            # show rss feed
            #self.response.headers['Content-Type'] = 'application/rss+xml'

            key = hashlib.md5(word).hexdigest()

            # if cache exists send response from cache
            data = memcache.get(key)
            #if data is not None:
            #    self.response.out.write(data)
            #    return

            # else get updated feed
            urlparams = {'t':word,'i':900090020}
            params = urllib.urlencode( urlparams )

            response = urllib2.urlopen('http://www.eksisozluk.com/show.asp?%s' % params)
            html = response.read()

            try:
                start = html.index('<ol')
                end = html.index('</ol>') + 5
            except e:
                return

            listhtml = html[start:end]
            dom = parseString(listhtml)

            # rss document
            doc = Document()
            rss = doc.createElement('rss')
            rss.setAttribute('version','2.0')
            doc.appendChild(rss)

            channel = doc.createElement('channel')
            rss.appendChild(channel)

            title = doc.createElement('title')
            ttext = doc.createTextNode("%s - Eksisozluk" % word)
            title.appendChild(ttext)
            channel.appendChild(title)

            link = doc.createElement('link')
            ltext = doc.createTextNode("http://www.eksisozluk.com/show.asp?%s" % params)
            link.appendChild(ltext)
            channel.appendChild(link)

            language = doc.createElement('language')
            llanguage = doc.createTextNode('tr')
            language.appendChild(llanguage)
            channel.appendChild(language)

            lbd = doc.createElement('lastBuildDate')
            llbd = doc.createTextNode( datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S %z") )
            lbd.appendChild(llbd)
            channel.appendChild(lbd)

            # fix relative urls
            for anchor in dom.getElementsByTagName('a'):
                self._addLinks(anchor)

            for node in reversed(dom.getElementsByTagName('li')):
                id = node.getAttribute('id').replace('d','')

                infodiv = node.getElementsByTagName('div')[0]
                infodiv.removeChild( infodiv.getElementsByTagName('div')[0] )

                node.removeChild( node.getElementsByTagName('div')[0] )

                author = infodiv.getElementsByTagName('a')[0]

                date = " ".join(t.nodeValue for t in infodiv.childNodes if t.nodeType == t.TEXT_NODE)
                date = date.replace(' , ', '')

                title_text = '%s %s' % (author.firstChild.nodeValue, date)

                item = doc.createElement('item')

                item_title = doc.createElement('title')
                item_title_text = doc.createTextNode( title_text )
                item_title.appendChild(item_title_text)
                item.appendChild(item_title)

                item_desc = doc.createElement('description')
                item_desc_text = doc.createTextNode( " ".join(i.toxml() for i in node.childNodes) )
                item_desc.appendChild(item_desc_text)
                item.appendChild(item_desc)

                item_link = doc.createElement('link')
                item_link_text = doc.createTextNode('http://www.eksisozluk.com/show.asp?id=%s' % id)
                item_link.appendChild(item_link_text)
                item.appendChild(item_link)

                channel.appendChild(item)

            text = doc.toxml()

            memcache.add(key, text, 60 * 60 * 3)

            self.response.out.write(text)
        else:
            # show main page

            # read main page html
            f = open('main.html', "r")
            html = f.read()
            f.close()

            self.response.out.write(html)

app = webapp2.WSGIApplication([('/', MainHandler)],
                              debug=True)
