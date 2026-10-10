#!/usr/bin/python3
"""Cache a bounded set of public force-sensor documents and list manufacturer links."""

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution
OUTPUT=ROOT/"build/engineering/force_sources"
ALLOWED={"www.sparkfun.com","cdn.sparkfun.com","learn.sparkfun.com","www.nuvoton.com",
         "www.ati-ia.com","ati-ia.com","raw.githubusercontent.com","doc.i2rt.com"}


class DocumentLinks(HTMLParser):
    def __init__(self,base):
        super().__init__();self.base=base;self.links=set()
    def handle_starttag(self,tag,attributes):
        values=dict(attributes)
        if tag=="a" and "href" in values:
            url=urljoin(self.base,values["href"])
            if any(word in url.lower() for word in (".pdf",".step",".stp","github","datasheet","drawing","learn.sparkfun")):
                self.links.add(url)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls",nargs="+")
    args=parser.parse_args()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with execution(ROOT/"build/records","Read public load-cell mechanical drawings, rated-load specifications, and ADC documentation") as record:
        entries=[]
        for url in args.urls:
            parsed=urlsplit(url)
            if parsed.scheme!="https" or parsed.hostname not in ALLOWED:
                raise ValueError("Document URL is outside the named primary-source hosts")
            request=Request(url,headers={"User-Agent":"enpire-force-prototype-study"})
            with urlopen(request,timeout=30) as response:
                if urlsplit(response.url).hostname not in ALLOWED:
                    raise ValueError("Unexpected document redirect")
                data=response.read(16*1024*1024+1);content_type=response.headers.get("Content-Type","")
            if len(data)>16*1024*1024:raise ValueError("Document exceeds download bound")
            suffix=".pdf" if data.startswith(b"%PDF") else ".html"
            name=hashlib.sha256(url.encode()).hexdigest()[:12]+suffix
            (OUTPUT/name).write_bytes(data)
            entry={"url":url,"file":name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}
            if suffix==".html":
                links=DocumentLinks(url);links.feed(data.decode("utf-8",errors="replace"))
                entry["document_links"]=sorted(links.links)
            entries.append(entry)
        record["sources"]=entries
        (OUTPUT/"last_collection.json").write_text(json.dumps(entries,indent=2)+"\n")
        print(json.dumps(entries,indent=2))


if __name__=="__main__":
    main()
