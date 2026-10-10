#!/usr/bin/python3
"""Extract only assembly-related text from the previously cached public model metadata."""

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[]
    def handle_data(self,value):
        self.parts.append(value)


def main():
    data=json.loads((ROOT/"build/engineering/sources/makerworld_70d749bc.json").read_text())
    results=[]
    def walk(value,path=""):
        if isinstance(value,dict):
            for key,item in value.items():walk(item,f"{path}.{key}")
        elif isinstance(value,list):
            for index,item in enumerate(value):walk(item,f"{path}[{index}]")
        elif isinstance(value,str) and re.search(r"\bM[345]\b|screw|insert|mount|bolt",value,re.I):
            parser=TextOnly();parser.feed(value)
            text=" ".join(parser.parts)
            for match in re.finditer(r"\bM[345]\b|screw|insert|mount|bolt",text,re.I):
                results.append({"field":path,"excerpt":text[max(0,match.start()-60):match.end()+140]})
    walk(data)
    return results[:20]


if __name__=="__main__":
    with execution(ROOT/"build/records","Read assembly-related excerpts from the cached public MakerWorld metadata") as record:
        notes=main();record["excerpt_count"]=len(notes)
        print(json.dumps(notes,indent=2))
