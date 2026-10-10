#!/usr/bin/python3
"""Cache explicitly named B1 manufacturer/tool references; never execute downloaded content."""

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin,urlsplit
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution

ALLOWED={"www.melexis.com","media.melexis.com","www.kicad.org","downloads.kicad.org","www.supermagnete.com",
         "www.supermagnete.de","www.adafruit.com","learn.adafruit.com","cdn-learn.adafruit.com",
         "raw.githubusercontent.com","api.github.com"}
OUTPUT=ROOT/"build/engineering/b1/sources"


class Links(HTMLParser):
    def __init__(self,base):
        super().__init__();self.base=base;self.urls=[]
    def handle_starttag(self,tag,attrs):
        fields=dict(attrs)
        if tag=="a" and fields.get("href"):
            self.urls.append(urljoin(self.base,fields["href"]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls",nargs="+")
    args=parser.parse_args()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with execution(ROOT/"build/records","Read bounded public B1 sensor, magnet and CAD-tool references") as record:
        index_path=OUTPUT/"collection.json"
        previous=json.loads(index_path.read_text()) if index_path.exists() else []
        results=[]
        for url in args.urls:
            if urlsplit(url).scheme!="https" or urlsplit(url).hostname not in ALLOWED:
                raise ValueError("URL outside the named reference hosts")
            request=Request(url,headers={"User-Agent":"enpire-b1-design-study"})
            try:
                with urlopen(request,timeout=30) as response:
                    final=response.url
                    if urlsplit(final).hostname not in ALLOWED:raise ValueError("Unlisted redirect host")
                    data=response.read(16*1024*1024+1)
            except Exception as error:
                results.append({"url":url,"error":f"{type(error).__name__}: {error}"})
                continue
            if len(data)>16*1024*1024:raise ValueError("Reference exceeds the download bound")
            suffix=".pdf" if data.startswith(b"%PDF") else ".json" if urlsplit(url).hostname=="api.github.com" else ".txt"
            name=hashlib.sha256(url.encode()).hexdigest()[:12]+suffix
            (OUTPUT/name).write_bytes(data)
            item={"url":url,"final_url":final,"file":name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}
            if suffix==".txt":
                text=data.decode("utf-8",errors="replace");links=Links(final);links.feed(text)
                discovered=links.urls+re.findall(r'https://[^"\'<>\s]+',text)
                item["relevant_links"]=sorted({html.unescape(link) for link in discovered
                    if any(term in link.lower() for term in (".pdf","appimage","sha256","github","datasheet"))})
            results.append(item)
        record["references"]=results
        combined={item["url"]:item for item in previous}
        combined.update({item["url"]:item for item in results})
        index_path.write_text(json.dumps(list(combined.values()),indent=2)+"\n")
        displayed=[]
        for result in results:
            shown={key:value for key,value in result.items() if key!="relevant_links"}
            if "relevant_links" in result:
                shown["relevant_link_count"]=len(result["relevant_links"])
                shown["first_relevant_links"]=result["relevant_links"][:8]
            displayed.append(shown)
        print(json.dumps(displayed,indent=2))


if __name__=="__main__":
    main()
