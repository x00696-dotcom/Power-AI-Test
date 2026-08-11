import io
import os
import re
import time
import html as htmlmod
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_file
from pypdf import PdfReader

BASE = Path(__file__).resolve().parent
APP_HTML = BASE / "app.html"

app = Flask(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/142 Safari/537.36 PowerAI-Cloud/1.0"
)

OFFICIAL_DOMAINS = {
    "Texas Instruments": ["ti.com", "www.ti.com"],
    "Silergy": ["silergy.com", "us1.silergy.com", "www.silergy.com"],
    "Monolithic Power Systems": ["monolithicpower.com", "www.monolithicpower.com"],
    "Richtek": ["richtek.com", "www.richtek.com"],
    "Renesas": ["renesas.com", "www.renesas.com"],
    "onsemi": ["onsemi.com", "www.onsemi.com"],
    "Onsemi": ["onsemi.com", "www.onsemi.com"],
    "Analog Devices": ["analog.com", "www.analog.com"],
    "Infineon": ["infineon.com", "www.infineon.com"],
}
ALL_DOMAINS = sorted({d for v in OFFICIAL_DOMAINS.values() for d in v})
CACHE = {}
CACHE_SECONDS = 60 * 60 * 12
MAX_HTML_BYTES = 4_000_000
MAX_PDF_BYTES = 20_000_000


def allowed_host(url: str, domains):
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)


def fetch(url: str, timeout=15, max_bytes=MAX_HTML_BYTES):
    r = requests.get(
        url,
        timeout=timeout,
        allow_redirects=True,
        headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"},
        stream=True,
    )
    r.raise_for_status()
    data = bytearray()
    for chunk in r.iter_content(65536):
        if not chunk:
            continue
        data.extend(chunk)
        if len(data) > max_bytes:
            raise ValueError("Remote file is larger than the safety limit.")
    return bytes(data), r.headers.get("content-type", ""), r.url


def normalize_part(part: str):
    p = re.sub(r"\s+", "", (part or "").upper())
    # Known TI orderable suffixes: keep the base family PN for the product page.
    m = re.match(r"^(BQ\d{5})", p)
    if m:
        return m.group(1)
    return p


def mfr_domains(mfr: str):
    ml = (mfr or "").lower()
    for k, domains in OFFICIAL_DOMAINS.items():
        if k.lower() in ml or (ml and ml in k.lower()):
            return domains
    return ALL_DOMAINS


def direct_urls(part: str, mfr: str):
    p = normalize_part(part)
    ml = (mfr or "").lower()
    urls = []
    if "texas" in ml or p.startswith(("BQ", "TPS", "LM", "UCC")):
        urls.append(f"https://www.ti.com/product/{p}")
    if "silergy" in ml or p.startswith("SY"):
        urls.append(f"https://us1.silergy.com/productsview/{p}")
    return urls


def ddg_search(part: str, domains):
    # Search is only used to LOCATE an official manufacturer page.
    # Returned URLs are still validated against the official domain allowlist.
    scope = " OR ".join("site:" + d for d in domains[:5])
    q = f'"{part}" datasheet ({scope})'
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q)
    try:
        raw, _, _ = fetch(url, timeout=12, max_bytes=2_000_000)
    except Exception:
        return []
    soup = BeautifulSoup(raw, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = htmlmod.unescape(a.get("href", ""))
        if "uddg=" in href:
            try:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                href = qs.get("uddg", [href])[0]
            except Exception:
                pass
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("http") and allowed_host(href, domains) and href not in links:
            links.append(href)
        if len(links) >= 8:
            break
    return links


def strip_html(raw: bytes):
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def title_from_html(raw: bytes):
    try:
        soup = BeautifulSoup(raw, "html.parser")
        return re.sub(r"\s+", " ", soup.title.get_text(" ", strip=True)).strip() if soup.title else ""
    except Exception:
        return ""


def find_pdf_links(raw: bytes, base_url: str, domains):
    soup = BeautifulSoup(raw, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        u = urllib.parse.urljoin(base_url, htmlmod.unescape(a["href"]))
        if not allowed_host(u, domains):
            continue
        low = u.lower()
        txt = a.get_text(" ", strip=True).lower()
        if (
            ".pdf" in low
            or "/lit/ds/" in low
            or "datasheet" in low
            or "data sheet" in txt
            or "download" in low
        ):
            if u not in links:
                links.append(u)
    return links[:15]


def extract_pdf_text(pdf_bytes: bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    # Cap extraction to prevent pathological PDFs from consuming too much time.
    for page in reader.pages[:120]:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    text = "\n".join(pages)
    return re.sub(r"[ \t]+", " ", text), len(reader.pages)


def first_match(text, patterns):
    for pat in patterns:
        m = re.search(pat, text, re.I | re.S)
        if m:
            return m.group(1)
    return None


def extract_specs(text: str):
    s = {}

    s["vin_min"] = first_match(text, [
        r"Vin\s*\(min\)\s*\(V\)\s*([0-9.]+)",
        r"Input Voltage Range\s*(?:from)?\s*([0-9.]+)\s*V\s*(?:to|-)",
        r"input voltage(?: range)?\s*(?:is|of|:)?\s*([0-9.]+)\s*V\s*(?:to|-)",
    ])
    s["vin_max"] = first_match(text, [
        r"Vin\s*\(max\)\s*\(V\)\s*([0-9.]+)",
        r"Input Voltage Range.{0,50}?[0-9.]+\s*V\s*(?:to|-)\s*([0-9.]+)\s*V",
        r"input voltage(?: range)?\s*(?:is|of|:)?\s*[0-9.]+\s*V\s*(?:to|-)\s*([0-9.]+)\s*V",
    ])
    s["abs_vin_max"] = first_match(text, [
        r"Absolute max Vin\s*\(max\)\s*\(V\)\s*([0-9.]+)",
        r"Absolute Maximum.{0,250}?V(?:IN|BUS).{0,100}?([0-9.]+)\s*V",
    ])
    s["charge_current_max"] = first_match(text, [
        r"Charge current\s*\(max\)\s*\(A\)\s*([0-9.]+)",
        r"Battery Charge Current\s*\(max\)\s*\(A\)\s*([0-9.]+)",
        r"(?:charge|charging) current.{0,80}?(?:up to|max(?:imum)?|:)\s*([0-9.]+)\s*A",
    ])
    s["charge_voltage_max"] = first_match(text, [
        r"Battery charge voltage\s*\(max\)\s*\(V\)\s*([0-9.]+)",
        r"Battery Charge Voltage\s*\(max\)\s*\(V\)\s*([0-9.]+)",
    ])

    m = re.search(r"([1-6])\s*(?:-|to)\s*([1-6])\s*[- ]?cell", text, re.I)
    if m:
        s["cells"] = f"{m.group(1)}–{m.group(2)}"
    else:
        m = re.search(r"([1-6])\s*(?:-|to)\s*([1-6])\s*S\b", text, re.I)
        if m:
            s["cells"] = f"{m.group(1)}–{m.group(2)}"

    if re.search(r"buck[- ]?boost|buck boost", text, re.I):
        s["topology"] = "Buck-Boost"
    elif re.search(r"\bbuck\b", text, re.I):
        s["topology"] = "Buck"
    elif re.search(r"\bboost\b", text, re.I):
        s["topology"] = "Boost"

    if re.search(r"\bSMBus\b", text, re.I):
        s["interface"] = "SMBus"
    elif re.search(r"\bI2C\b|\bI²C\b", text, re.I):
        s["interface"] = "I²C"

    package_patterns = [
        r"(W?QFN\s*4\s*[x×]\s*4\s*[- ]?32)",
        r"(TQFN\s*4\s*[x×]\s*5\s*[- ]?30)",
        r"(WLCSP[\w .×x-]{0,50})",
        r"(QFN[- ]?\d{2,3})",
    ]
    s["package"] = first_match(text, package_patterns)

    m = re.search(
        r"(?:Operating|Ambient|Junction).{0,40}?temperature.{0,100}?(-\d+)\s*°?\s*C.{0,60}?([+]?\d+)\s*°?\s*C",
        text,
        re.I | re.S,
    )
    if m:
        s["operating_temp"] = f"{m.group(1)} to {m.group(2)} °C"

    # Prefer explicitly labelled switching-frequency values.
    sf = first_match(text, [
        r"(?:Switching|Switch) Frequency.{0,80}?([0-9.]+\s*(?:kHz|MHz))",
        r"fSW.{0,80}?([0-9.]+\s*(?:kHz|MHz))",
    ])
    if sf:
        s["switching_frequency"] = re.sub(r"\s+", "", sf)

    return {k: v for k, v in s.items() if v not in (None, "")}


def merge_specs(primary, secondary):
    out = dict(secondary or {})
    out.update(primary or {})
    return out


def lookup_official(part: str, mfr: str):
    key = (part.upper(), (mfr or "").lower())
    cached = CACHE.get(key)
    if cached and time.time() - cached["time"] < CACHE_SECONDS:
        return cached["data"]

    domains = mfr_domains(mfr)
    urls = []
    for u in direct_urls(part, mfr) + ddg_search(part, domains):
        if u not in urls:
            urls.append(u)

    best = None
    best_score = -1

    for url in urls[:10]:
        if not allowed_host(url, domains):
            continue
        try:
            raw, _, final = fetch(url)
        except Exception:
            continue
        if not allowed_host(final, domains):
            continue

        page_text = strip_html(raw)
        page_specs = extract_specs(page_text)
        pdfs = find_pdf_links(raw, final, domains)

        # Stable TI PDF pattern for base product pages.
        p = normalize_part(part)
        if "ti.com" in (urllib.parse.urlparse(final).hostname or "") and p.startswith(("BQ", "TPS", "LM", "UCC")):
            ti_pdf = f"https://www.ti.com/lit/ds/symlink/{p.lower()}.pdf"
            if ti_pdf not in pdfs:
                pdfs.insert(0, ti_pdf)

        datasheet_url = None
        pdf_specs = {}
        pdf_pages = 0
        pdf_parsed = False

        for pdf_url in pdfs[:5]:
            if not allowed_host(pdf_url, domains):
                continue
            try:
                pdf_raw, ctype, pdf_final = fetch(pdf_url, timeout=20, max_bytes=MAX_PDF_BYTES)
                looks_pdf = (
                    pdf_raw[:5] == b"%PDF-"
                    or "application/pdf" in (ctype or "").lower()
                    or ".pdf" in pdf_final.lower()
                )
                if not looks_pdf:
                    continue
                pdf_text, pdf_pages = extract_pdf_text(pdf_raw)
                pdf_specs = extract_specs(pdf_text)
                datasheet_url = pdf_final
                pdf_parsed = True
                break
            except Exception:
                continue

        specs = merge_specs(pdf_specs, page_specs)
        score = len(specs) * 10 + (20 if pdf_parsed else 0) + (5 if datasheet_url else 0)

        candidate = {
            "part": part,
            "manufacturer": mfr,
            "product_url": final,
            "datasheet_url": datasheet_url,
            "title": title_from_html(raw),
            "specs": specs,
            "official": True,
            "pdf_parsed": pdf_parsed,
            "pdf_pages": pdf_pages,
        }
        if score > best_score:
            best = candidate
            best_score = score
        if pdf_parsed and len(specs) >= 6:
            break

    if best is None:
        best = {
            "part": part,
            "manufacturer": mfr,
            "product_url": None,
            "datasheet_url": None,
            "title": "",
            "specs": {},
            "official": False,
            "pdf_parsed": False,
            "pdf_pages": 0,
        }

    CACHE[key] = {"time": time.time(), "data": best}
    return best


@app.get("/")
def root():
    return send_file(APP_HTML)


@app.get("/api/official")
def official():
    part = (request.args.get("part") or "").strip()
    mfr = (request.args.get("mfr") or "").strip()
    if not part or len(part) > 80:
        return jsonify({"error": "Invalid part number"}), 400
    try:
        return jsonify(lookup_official(part, mfr))
    except Exception as e:
        return jsonify({"error": f"Official lookup failed: {e}"}), 500


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "Power AI Cloud v1.0"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
