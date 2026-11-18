#!/usr/bin/env python3
"""
Henter Liveforbundets kommende koncerter fra kuto.dk og skriver en .ics-fil,
som Google Kalender kan importere eller abonnere på.

Brug:  pip install requests beautifulsoup4
       python liveforbundet_ics.py            -> skriver liveforbundet.ics
       python liveforbundet_ics.py -o sti.ics
"""
import argparse
import re
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

LIST_URL = "https://kuto.dk/liveforbundet/"
TZ = ZoneInfo("Europe/Copenhagen")
UA = {"User-Agent": "liveforbundet-ics/1.0 (personal calendar feed)"}

MONTHS = {"januar": 1, "februar": 2, "marts": 3, "april": 4, "maj": 5, "juni": 6,
          "juli": 7, "august": 8, "september": 9, "oktober": 10,
          "november": 11, "december": 12}

ADDRESSES = {
    "toldkammer": "Havnepladsen 1, 3000 Helsingør",
    "kulturværftet": "Allegade 2, 3000 Helsingør",
}

LABELS = ["Dato:", "Tid:", "Døre:", "Varighed:", "Pris:", "Sted:", "Placering:"]


def get(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def event_links():
    soup = get(LIST_URL)
    links = []
    for a in soup.select('a[href*="/arrangementer/"]'):
        href = a["href"].split("#")[0].split("?")[0]
        if re.search(r"/arrangementer/[^/]+/?$", href) and href not in links:
            links.append(href)
    return links


def fields(soup):
    lines = [l.strip() for l in soup.get_text("\n").splitlines() if l.strip()]
    out = {}
    for i, line in enumerate(lines):
        for lab in LABELS:
            if line.startswith(lab) and lab not in out:
                val = line[len(lab):].strip()
                j = i + 1
                while (not val or val.lower() in ("kl.", "kl")) and j < len(lines):
                    nxt = lines[j]
                    if any(nxt.startswith(l) for l in LABELS):
                        break
                    val = nxt if not val or val.lower().startswith("kl") else val
                    j += 1
                out[lab] = re.sub(r"^kl\.?\s*", "", val, flags=re.I).strip()
    return out


def parse_date(s):
    m = re.search(r"(\d{1,2})\.\s*([a-zæøå]+)\s+(\d{4})", s.lower())
    if not m or m.group(2) not in MONTHS:
        return None
    return int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))


def parse_time(s):
    m = re.search(r"(\d{1,2})[.:](\d{2})", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_duration(s):
    s = (s or "").lower()
    h = re.search(r"(\d+(?:[.,]\d+)?)\s*time", s)
    m = re.search(r"(\d+)\s*min", s)
    mins = (float(h.group(1).replace(",", ".")) * 60 if h else 0) + (int(m.group(1)) if m else 0)
    return timedelta(minutes=mins or 120)


def scrape(url):
    soup = get(url)
    title = soup.find("h1").get_text(strip=True) if soup.find("h1") else url
    f = fields(soup)
    d = parse_date(f.get("Dato:", ""))
    if not d:
        return None
    t = parse_time(f.get("Tid:")) or (19, 30)
    start = datetime(*d, *t, tzinfo=TZ)
    sted = f.get("Sted:", "Helsingør").replace("– Find vej", "").strip()
    addr = next((v for k, v in ADDRESSES.items() if k in sted.lower()), "Helsingør")
    desc = [f"Døre: {f['Døre:']}" if f.get("Døre:") else "",
            f"Pris: {f['Pris:']}" if f.get("Pris:") else "",
            f"Placering: {f['Placering:']}" if f.get("Placering:") else "",
            "Billet via Liveforbundet: https://app.liveforbundet.dk", url]
    return {"title": title, "start": start, "end": start + parse_duration(f.get("Varighed:")),
            "location": f"{sted}, {addr}" if addr not in sted else sted,
            "desc": "\n".join(x for x in desc if x), "url": url,
            "uid": re.sub(r"\W+", "-", url.rstrip("/").split("/")[-1]) + "@liveforbundet.kuto.dk"}


def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        c = ch.encode("utf-8")
        if len(cur) + len(c) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8")); cur = b""
        cur += c
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def to_ics(events):
    fmt = "%Y%m%dT%H%M%S"
    now = datetime.utcnow().strftime(fmt) + "Z"
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//liveforbundet-ics//DA",
         "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Liveforbundet",
         "X-WR-TIMEZONE:Europe/Copenhagen", "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
         "BEGIN:VTIMEZONE", "TZID:Europe/Copenhagen",
         "BEGIN:DAYLIGHT", "TZOFFSETFROM:+0100", "TZOFFSETTO:+0200", "TZNAME:CEST",
         "DTSTART:19700329T020000", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU", "END:DAYLIGHT",
         "BEGIN:STANDARD", "TZOFFSETFROM:+0200", "TZOFFSETTO:+0100", "TZNAME:CET",
         "DTSTART:19701025T030000", "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU", "END:STANDARD",
         "END:VTIMEZONE"]
    for e in events:
        L += ["BEGIN:VEVENT", f"UID:{e['uid']}", f"DTSTAMP:{now}",
              f"DTSTART;TZID=Europe/Copenhagen:{e['start'].strftime(fmt)}",
              f"DTEND;TZID=Europe/Copenhagen:{e['end'].strftime(fmt)}",
              f"SUMMARY:{esc('Liveforbundet: ' + e['title'])}",
              f"LOCATION:{esc(e['location'])}", f"DESCRIPTION:{esc(e['desc'])}",
              f"URL:{e['url']}", "END:VEVENT"]
    L.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in L) + "\r\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="liveforbundet.ics")
    args = ap.parse_args()
    now = datetime.now(TZ)
    events = []
    for url in event_links():
        try:
            e = scrape(url)
        except Exception as ex:
            print(f"! {url}: {ex}", file=sys.stderr); continue
        if e and e["end"] > now:
            events.append(e)
            print(f"{e['start']:%d-%m-%Y %H:%M}  {e['title']}  ({e['location']})")
        time.sleep(0.5)  # vær flink ved serveren
    events.sort(key=lambda e: e["start"])
    with open(args.output, "w", encoding="utf-8", newline="") as fh:
        fh.write(to_ics(events))
    print(f"\n{len(events)} koncerter skrevet til {args.output}")


if __name__ == "__main__":
    main()
