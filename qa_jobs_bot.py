#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIGURAÇÃO
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("qa_job_bot")

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
POSTED_JOBS_FILE = os.getenv("POSTED_JOBS_FILE", "posted_jobs.json")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))
MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "20"))
DISCORD_POST_DELAY = float(os.getenv("DISCORD_POST_DELAY", "1.0"))
KEEP_HISTORY_DAYS = int(os.getenv("KEEP_HISTORY_DAYS", "60"))

# Empresas Greenhouse/Lever podem ser sobrescritas via env var, separadas por vírgula.
# Ex.: GREENHOUSE_COMPANIES="nubank,vtex,stripe,notion"
DEFAULT_GREENHOUSE_COMPANIES = [
    # Verificadas como usuárias reais do board público do Greenhouse.
    "nubank", "vtex", "stripe", "notion", "figma", "airtable", "webflow",
    "cloudflare", "gitlab", "mongodb", "twilio", "coinbase", "asana",
    "affirm", "robinhood", "grammarly", "instacart", "doordash", "reddit",
    "zapier", "linear", "vercel", "supabase", "planetscale", "railway",
    "mercadolibre", "globant", "thoughtworks", "globalsign",
]
DEFAULT_LEVER_COMPANIES = [
    "netflix", "shopify", "spotify", "canva", "brex", "ramp", "loom",
    "rippling", "attentive", "eightsleep", "plaid", "airbnb", "uber",
    "lyft", "doordash", "instacart", "coinbase", "stripe",
]

GREENHOUSE_COMPANIES = [
    c.strip() for c in os.getenv("GREENHOUSE_COMPANIES", "").split(",") if c.strip()
] or DEFAULT_GREENHOUSE_COMPANIES

LEVER_COMPANIES = [
    c.strip() for c in os.getenv("LEVER_COMPANIES", "").split(",") if c.strip()
] or DEFAULT_LEVER_COMPANIES

QA_KEYWORDS = [
    r"\bqa\b",
    r"quality assurance",
    r"qualidade",
    r"tester",
    r"testador",
    r"testadora",
    r"\bteste\b",
    r"\btests?\b",
    r"\btesting\b",
    r"\bsdet\b",
    r"playwright",
    r"cypress",
    r"selenium",
    r"appium",
    r"postman",
    r"cucumber",
    r"robot framework",
    r"test engineer",
    r"engenheiro de testes",
    r"engenheira de testes",
    r"quality engineer",
    r"qa engineer",
    r"automation",
    r"automação",
    r"jest",
    r"pytest",
    r"junit",
    r"testng",
    r"k6",
    r"jmeter",
]
# Regex único com \b para evitar falsos positivos tipo "contest", "latest".
QA_PATTERN = re.compile(
    "|".join(QA_KEYWORDS), flags=re.IGNORECASE
)

# Palavras que NÃO são QA (para filtrar falsos positivos)
NON_QA_EXCLUDE = [
    r"\barchitect\b",
    r"\bdrafter\b",
    r"\bdesigner\b",
    r"\bdeveloper\b",
    r"\bdevops\b",
    r"\bbackend\b",
    r"\bfrontend\b",
    r"\bfullstack\b",
    r"\bdata scientist\b",
    r"\bdata engineer\b",
    r"\bml engineer\b",
    r"\bmachine learning\b",
    r"\bproduct manager\b",
    r"\bproject manager\b",
    r"\bscrum master\b",
    r"\btech lead\b",
    r"\bengineering manager\b",
    r"\bsupport\b",
    r"\bcustomer\b",
    r"\bsales\b",
    r"\bmarketing\b",
    r"\bhr\b",
    r"\brecruiter\b",
    r"\bui/ux\b",
    r"\bux\b",
    r"\bui\b",
    r"\bassurance\b",
    r"\bmechatronic\b",
    r"\btechnician\b",
    r"\boperator\b",
    r"\bclerk\b",
    r"\bdriver\b",
    r"\bdiver\b",
    r"\bnavigator\b",
    r"\bhealth\b",
    r"\brestaurant\b",
    r"\bdrafter\b",
    r"\bcoordinator\b",
    r"\badministrative\b",
    r"\binstructor\b",
    r"\bspecialist\b",
    r"\bmanager\b",
    r"\bdirector\b",
    r"\bvp\b",
    r"\bvice president\b",
]

NON_QA_PATTERN = re.compile(
    "|".join(NON_QA_EXCLUDE), flags=re.IGNORECASE
)

SENIORITY_PATTERNS = {
    "🌱 Júnior": re.compile(r"\b(jr|junior|júnior|trainee|estagio|estágio|intern)\b", re.I),
    "🚀 Pleno": re.compile(r"\b(pleno|mid|middle|ii)\b", re.I),
    "⭐ Sênior": re.compile(r"\b(senior|sênior|sr|lead|principal|staff|iii)\b", re.I),
}

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; QAJobBot/2.0; +https://github.com/)",
    "Accept": "application/json, application/rss+xml, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
}


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str
    country: str
    id: str = field(default="")
    salary: Optional[str] = None
    posted_at: Optional[str] = None

    def __post_init__(self):
        if not self.id:
            self.id = generate_job_id(self.title, self.company, self.source)


# ============================================================
# HELPERS
# ============================================================

def generate_job_id(title: str, company: str, source: str = "") -> str:
    unique_string = f"{title.lower().strip()}_{company.lower().strip()}_{source.lower().strip()}"
    return hashlib.md5(unique_string.encode("utf-8")).hexdigest()[:16]


def is_qa_job(title: str) -> bool:
    if not title:
        return False
    # Must match QA keywords
    if not QA_PATTERN.search(title):
        return False
    # Must NOT match excluded terms
    if NON_QA_PATTERN.search(title):
        return False
    return True


def detect_seniority(title: str) -> str:
    for label, pattern in SENIORITY_PATTERNS.items():
        if pattern.search(title or ""):
            return label
    return ""


def make_request(
    url: str,
    params: dict = None,
    headers: dict = None,
    max_retries: int = 3,
) -> Optional[requests.Response]:
    """GET com retry/backoff exponencial e tratamento de rate limit."""
    req_headers = {**DEFAULT_HEADERS, **(headers if headers else {})}
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=req_headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                wait = min(2 ** attempt * 2, 30)
                logger.warning(f"429 rate limited em {url}, aguardando {wait}s...")
                time.sleep(wait)
                continue
            return resp
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout ({attempt + 1}/{max_retries}) em {url}")
            time.sleep(2 ** attempt)
        except requests.exceptions.RequestException as e:
            logger.warning(f"Erro de request ({attempt + 1}/{max_retries}) em {url}: {e}")
            time.sleep(2 ** attempt)
    return None


# ============================================================
# ESTADO PERSISTENTE (dedup)
# ============================================================

def load_posted_jobs() -> Dict[str, str]:
    """Retorna {job_id: iso_timestamp}. Compatível com formato antigo (lista simples)."""
    if not os.path.exists(POSTED_JOBS_FILE):
        return {}
    try:
        with open(POSTED_JOBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            # formato antigo: lista de ids sem timestamp
            now = datetime.now(timezone.utc).isoformat()
            return {job_id: now for job_id in data}
        if isinstance(data, dict):
            return data
    except Exception as e:
        logger.warning(f"Erro lendo {POSTED_JOBS_FILE}: {e}")
    return {}


def save_posted_jobs(posted: Dict[str, str]):
    """Escrita atômica: grava em arquivo temporário e faz rename."""
    try:
        dir_name = os.path.dirname(os.path.abspath(POSTED_JOBS_FILE)) or "."
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_name, delete=False, suffix=".tmp", encoding="utf-8"
        ) as tmp:
            json.dump(posted, tmp, ensure_ascii=False, indent=0)
            tmp_path = tmp.name
        os.replace(tmp_path, POSTED_JOBS_FILE)
    except Exception as e:
        logger.error(f"Erro salvando {POSTED_JOBS_FILE}: {e}")


def prune_old_entries(posted: Dict[str, str]) -> Dict[str, str]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_HISTORY_DAYS)
    pruned = {}
    for job_id, ts in posted.items():
        try:
            when = datetime.fromisoformat(ts)
        except Exception:
            pruned[job_id] = ts  # mantém se não conseguir parsear
            continue
        if when >= cutoff:
            pruned[job_id] = ts
    return pruned


# ============================================================
# FONTES REAIS (todas verificadas)
# ============================================================

def search_remoteok() -> List[Job]:
    jobs = []
    resp = make_request("https://remoteok.com/api")
    if not (resp and resp.status_code == 200):
        return jobs
    try:
        data = resp.json()
    except ValueError:
        return jobs
    for item in data:
        if not isinstance(item, dict) or "position" not in item:
            continue  # primeiro item é metadata da API, sem "position"
        title = item.get("position", "")
        tags = " ".join(item.get("tags", []) or [])
        if not is_qa_job(title) and not is_qa_job(tags):
            continue
        jobs.append(Job(
            title=title,
            company=item.get("company", "N/A"),
            location=item.get("location") or "Remote",
            url=item.get("url") or f"https://remoteok.com/remote-jobs/{item.get('id')}",
            source="RemoteOK",
            country="🌎 Internacional (Remote)",
            salary=_remoteok_salary(item),
        ))
    return jobs


def _remoteok_salary(item: dict) -> Optional[str]:
    lo, hi = item.get("salary_min"), item.get("salary_max")
    if lo and hi:
        return f"${lo:,} - ${hi:,}"
    return None


def search_remotive() -> List[Job]:
    jobs = []
    resp = make_request("https://remotive.com/api/remote-jobs", params={"category": "qa-testing"})
    if not (resp and resp.status_code == 200):
        return jobs
    try:
        data = resp.json()
    except ValueError:
        return jobs
    for item in data.get("jobs", []):
        title = item.get("title", "N/A")
        if not is_qa_job(title):
            continue
        jobs.append(Job(
            title=title,
            company=item.get("company_name", "N/A"),
            location=item.get("candidate_required_location") or "Remote",
            url=item.get("url", "#"),
            source="Remotive",
            country="🌎 Internacional (Remote)",
            salary=item.get("salary") or None,
        ))
    return jobs


def search_arbeitnow() -> List[Job]:
    jobs = []
    resp = make_request("https://www.arbeitnow.com/api/job-board-api")
    if not (resp and resp.status_code == 200):
        return jobs
    try:
        data = resp.json()
    except ValueError:
        return jobs
    for item in data.get("data", []):
        title = item.get("title", "N/A")
        tags = " ".join(item.get("tags", []) or [])
        if not is_qa_job(title) and not is_qa_job(tags):
            continue
        jobs.append(Job(
            title=title,
            company=item.get("company_name", "N/A"),
            location=item.get("location") or ("Remote" if item.get("remote") else "N/A"),
            url=item.get("url", "#"),
            source="Arbeitnow",
            country="🌍 Europa/Remote",
        ))
    return jobs


def search_jobicy() -> List[Job]:
    jobs = []
    resp = make_request(
        "https://jobicy.com/api/v2/remote-jobs",
        params={"count": 50, "tag": "qa"},
    )
    if not (resp and resp.status_code == 200):
        return jobs
    try:
        data = resp.json()
    except ValueError:
        return jobs
    for item in data.get("jobs", []):
        title = item.get("jobTitle", "N/A")
        if not is_qa_job(title):
            continue
        salary = None
        if item.get("annualSalaryMin") and item.get("annualSalaryMax"):
            salary = f"{item['annualSalaryMin']} - {item['annualSalaryMax']} {item.get('salaryCurrency', '')}".strip()
        jobs.append(Job(
            title=title,
            company=item.get("companyName", "N/A"),
            location=item.get("jobGeo") or "Remote",
            url=item.get("url", "#"),
            source="Jobicy",
            country="🌎 Internacional (Remote)",
            salary=salary,
            posted_at=item.get("pubDate"),
        ))
    return jobs


def search_weworkremotely() -> List[Job]:
    jobs = []
    feeds = [
        "https://weworkremotely.com/categories/remote-qa-jobs.rss",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    ]
    for url in feeds:
        resp = make_request(url, headers={"Accept": "application/rss+xml"})
        if not (resp and resp.status_code == 200):
            continue
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            continue
        for item in root.findall(".//item"):
            title_el = item.find("title")
            link_el = item.find("link")
            title = title_el.text.strip() if title_el is not None else "N/A"
            link = link_el.text if link_el is not None else "#"
            if not is_qa_job(title):
                continue
            company = "Various"
            if title and ":" in title:  # formato comum: "Company: Job Title"
                company, _, rest = title.partition(":")
                title = rest.strip() or title
            jobs.append(Job(
                title=title,
                company=company.strip(),
                location="Remote",
                url=link,
                source="We Work Remotely",
                country="🌎 Internacional (Remote)",
            ))
    return jobs


def search_greenhouse_company(company: str) -> List[Job]:
    jobs = []
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
    resp = make_request(url, params={"content": "true"})
    if not (resp and resp.status_code == 200):
        return jobs
    try:
        data = resp.json()
    except ValueError:
        return jobs
    for item in data.get("jobs", []):
        title = item.get("title", "N/A")
        if not is_qa_job(title):
            continue
        location = item.get("location", {})
        loc_name = location.get("name") if isinstance(location, dict) else "N/A"
        jobs.append(Job(
            title=title,
            company=company.capitalize(),
            location=loc_name or "N/A",
            url=item.get("absolute_url", "#"),
            source="Greenhouse",
            country="🌎 Internacional",
        ))
    return jobs


def search_greenhouse_all() -> List[Job]:
    jobs = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(search_greenhouse_company, c): c for c in GREENHOUSE_COMPANIES}
        for fut in as_completed(futures):
            try:
                jobs.extend(fut.result())
            except Exception as e:
                logger.error(f"Erro Greenhouse/{futures[fut]}: {e}")
    return jobs


def search_lever_company(company: str) -> List[Job]:
    jobs = []
    url = f"https://api.lever.co/v0/postings/{company}"
    resp = make_request(url, params={"mode": "json"})
    if not (resp and resp.status_code == 200):
        return jobs
    try:
        data = resp.json()
    except ValueError:
        return jobs
    if not isinstance(data, list):
        return jobs
    for item in data:
        title = item.get("text", "N/A")
        if not is_qa_job(title):
            continue
        categories = item.get("categories", {}) or {}
        jobs.append(Job(
            title=title,
            company=company.capitalize(),
            location=categories.get("location") or "N/A",
            url=item.get("hostedUrl", "#"),
            source="Lever",
            country="🌎 Internacional",
        ))
    return jobs


def search_lever_all() -> List[Job]:
    jobs = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(search_lever_company, c): c for c in LEVER_COMPANIES}
        for fut in as_completed(futures):
            try:
                jobs.extend(fut.result())
            except Exception as e:
                logger.error(f"Erro Lever/{futures[fut]}: {e}")
    return jobs


# ============================================================
# NOVAS FONTES BRASILEIRAS E INTERNACIONAIS
# ============================================================

def search_programathor() -> List[Job]:
    """Programathor - Principal site de vagas tech no Brasil"""
    jobs = []
    url = "https://programathor.com.br/jobs"
    resp = make_request(url)
    if not (resp and resp.status_code == 200):
        return jobs
    
    soup = BeautifulSoup(resp.content, 'html.parser')
    # Programathor usa cards de vaga
    for card in soup.find_all('div', class_=re.compile(r'job-card|vaga-card|job-item')):
        title_el = card.find('h3') or card.find('h2') or card.find('a', class_=re.compile(r'title'))
        company_el = card.find('span', class_=re.compile(r'company|empresa'))
        location_el = card.find('span', class_=re.compile(r'location|local'))
        link_el = card.find('a', href=True)
        
        if not title_el:
            continue
            
        title = title_el.get_text(strip=True)
        if not is_qa_job(title):
            continue
            
        company = company_el.get_text(strip=True) if company_el else "N/A"
        location = location_el.get_text(strip=True) if location_el else "Brasil"
        url_val = link_el['href'] if link_el else url
        
        if url_val.startswith('/'):
            url_val = f"https://programathor.com.br{url_val}"
            
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=url_val,
            source="Programathor",
            country="🇧🇷 Brasil",
        ))
    return jobs


def search_gupy() -> List[Job]:
    """Gupy - ATS muito usado no Brasil, tem API pública"""
    jobs = []
    # Gupy tem API GraphQL, vamos usar busca simples
    url = "https://api.gupy.io/api/v1/jobs"
    # Parâmetros de busca para QA
    params = {
        "search": "qa OR quality OR tester OR testador OR sdet OR automação OR playwright OR cypress OR selenium",
        "limit": 50,
        "offset": 0,
    }
    resp = make_request(url, params=params)
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        data = resp.json()
    except ValueError:
        return jobs
        
    for item in data.get("data", []):
        title = item.get("name", "N/A")
        if not is_qa_job(title):
            continue
        company = item.get("company", {}).get("name", "N/A")
        location = item.get("workplace", {}).get("city", "") + " - " + item.get("workplace", {}).get("state", "")
        url_val = item.get("careerPageUrl", "#")
        if url_val is None:
            url_val = "#"
            
        jobs.append(Job(
            title=title,
            company=company,
            location=location or "Brasil",
            url=url_val,
            source="Gupy",
            country="🇧🇷 Brasil",
        ))
    return jobs


def search_trampos() -> List[Job]:
    """Trampos.co - Vagas tech Brasil"""
    jobs = []
    url = "https://trampos.co/api/opportunities"
    params = {
        "q": "qa OR quality OR tester OR testador OR sdet OR automação OR playwright OR cypress OR selenium",
        "page": 1,
        "per_page": 50,
    }
    resp = make_request(url, params=params)
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        data = resp.json()
    except ValueError:
        return jobs
        
    for item in data.get("opportunities", []):
        title = item.get("title", "N/A")
        if not is_qa_job(title):
            continue
        company = item.get("company", {}).get("name", "N/A")
        location = item.get("city", "") + " - " + item.get("state", "")
        url_val = item.get("url", "#")
        if url_val is None:
            url_val = "#"
            
        jobs.append(Job(
            title=title,
            company=company,
            location=location or "Brasil",
            url=url_val,
            source="Trampos.co",
            country="🇧🇷 Brasil",
        ))
    return jobs


def search_catho() -> List[Job]:
    """Catho - Um dos maiores sites de emprego do Brasil"""
    jobs = []
    # Catho não tem API pública fácil, usar RSS ou scraping
    # Usar busca RSS se disponível
    url = "https://www.catho.com.br/vagas/rss/qa-teste/"
    resp = make_request(url, headers={"Accept": "application/rss+xml"})
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return jobs
        
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        
        title = title_el.text.strip() if title_el is not None and title_el.text else "N/A"
        link = link_el.text if link_el is not None else "#"
        
        if not is_qa_job(title):
            continue
            
        jobs.append(Job(
            title=title,
            company="Catho",
            location="Brasil",
            url=link,
            source="Catho",
            country="🇧🇷 Brasil",
        ))
    return jobs


def search_vagas_br() -> List[Job]:
    """Vagas.com.br - Site de empregos Brasil"""
    jobs = []
    url = "https://www.vagas.com.br/vagas-de-qa"
    resp = make_request(url)
    if not (resp and resp.status_code == 200):
        return jobs
    
    soup = BeautifulSoup(resp.content, 'html.parser')
    # Vagas.com.br usa estrutura específica
    for card in soup.find_all('div', class_=re.compile(r'vaga|job-item')):
        title_el = card.find('h2') or card.find('a', class_=re.compile(r'title|link'))
        company_el = card.find('span', class_=re.compile(r'empresa|company'))
        location_el = card.find('span', class_=re.compile(r'local|location'))
        link_el = card.find('a', href=True)
        
        if not title_el:
            continue
            
        title = title_el.get_text(strip=True)
        if not is_qa_job(title):
            continue
            
        company = company_el.get_text(strip=True) if company_el else "N/A"
        location = location_el.get_text(strip=True) if location_el else "Brasil"
        url_val = link_el['href'] if link_el else "#"
        
        if url_val.startswith('/'):
            url_val = f"https://www.vagas.com.br{url_val}"
            
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=url_val,
            source="Vagas.com.br",
            country="🇧🇷 Brasil",
        ))
    return jobs


def search_infojobs() -> List[Job]:
    """InfoJobs Brasil"""
    jobs = []
    url = "https://www.infojobs.com.br/vagas-emprego/qa.aspx"
    resp = make_request(url)
    if not (resp and resp.status_code == 200):
        return jobs
    
    soup = BeautifulSoup(resp.content, 'html.parser')
    for card in soup.find_all('div', class_=re.compile(r'job-card|vaga-item')):
        title_el = card.find('h2') or card.find('a', class_=re.compile(r'title'))
        company_el = card.find('span', class_=re.compile(r'company|empresa'))
        location_el = card.find('span', class_=re.compile(r'location|local'))
        link_el = card.find('a', href=True)
        
        if not title_el:
            continue
            
        title = title_el.get_text(strip=True)
        if not is_qa_job(title):
            continue
            
        company = company_el.get_text(strip=True) if company_el else "N/A"
        location = location_el.get_text(strip=True) if location_el else "Brasil"
        url_val = link_el['href'] if link_el else "#"
        
        if url_val.startswith('/'):
            url_val = f"https://www.infojobs.com.br{url_val}"
            
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=url_val,
            source="InfoJobs",
            country="🇧🇷 Brasil",
        ))
    return jobs


def search_revelo() -> List[Job]:
    """Revelo - Tech recruiting platform Brasil"""
    jobs = []
    url = "https://api.revelo.com.br/api/v1/opportunities"
    params = {
        "search": "qa quality tester testador sdet automação playwright cypress selenium",
        "page": 1,
        "per_page": 50,
    }
    resp = make_request(url, params=params)
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        data = resp.json()
    except ValueError:
        return jobs
        
    for item in data.get("data", []):
        title = item.get("title", "N/A")
        if not is_qa_job(title):
            continue
        company = item.get("company", {}).get("name", "N/A")
        location = item.get("city", "") + " - " + item.get("state", "")
        url_val = item.get("url", "#")
        if url_val is None:
            url_val = "#"
            
        jobs.append(Job(
            title=title,
            company=company,
            location=location or "Brasil",
            url=url_val,
            source="Revelo",
            country="🇧🇷 Brasil",
        ))
    return jobs


def search_geekhunter() -> List[Job]:
    """GeekHunter - Tech jobs Brasil"""
    jobs = []
    url = "https://geekhunter.com.br/api/jobs"
    params = {
        "search": "qa quality tester testador sdet automação playwright cypress selenium",
        "page": 1,
        "per_page": 50,
    }
    resp = make_request(url, params=params)
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        data = resp.json()
    except ValueError:
        return jobs
        
    for item in data.get("jobs", []):
        title = item.get("title", "N/A")
        if not is_qa_job(title):
            continue
        company = item.get("company", {}).get("name", "N/A")
        location = item.get("city", "") + " - " + item.get("state", "")
        url_val = item.get("url", "#")
        if url_val is None:
            url_val = "#"
            
        jobs.append(Job(
            title=title,
            company=company,
            location=location or "Brasil",
            url=url_val,
            source="GeekHunter",
            country="🇧🇷 Brasil",
        ))
    return jobs


# ============================================================
# FONTES INTERNACIONAIS ADICIONAIS
# ============================================================

def search_stackoverflow() -> List[Job]:
    """Stack Overflow Jobs (via RSS)"""
    jobs = []
    url = "https://stackoverflow.com/jobs/feed"
    resp = make_request(url, headers={"Accept": "application/rss+xml"})
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return jobs
        
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        
        title = title_el.text.strip() if title_el is not None and title_el.text else "N/A"
        link = link_el.text if link_el is not None else "#"
        
        if not is_qa_job(title):
            continue
            
        jobs.append(Job(
            title=title,
            company="Stack Overflow",
            location="Remote/Global",
            url=link,
            source="Stack Overflow",
            country="🌎 Internacional",
        ))
    return jobs


def search_wellfound() -> List[Job]:
    """Wellfound (ex AngelList) - Startups"""
    jobs = []
    # Wellfound não tem API pública simples, usar RSS se disponível
    # Placeholder - seria necessário autenticação
    return jobs


def search_yc_jobs() -> List[Job]:
    """Y Combinator Jobs"""
    jobs = []
    url = "https://www.workatastartup.com/jobs"
    resp = make_request(url)
    if not (resp and resp.status_code == 200):
        return jobs
    
    soup = BeautifulSoup(resp.content, 'html.parser')
    # YC jobs têm estrutura específica
    for card in soup.find_all('div', class_=re.compile(r'job|posting')):
        title_el = card.find('h3') or card.find('h2')
        company_el = card.find('span', class_=re.compile(r'company'))
        link_el = card.find('a', href=True)
        
        if not title_el:
            continue
            
        title = title_el.get_text(strip=True)
        if not is_qa_job(title):
            continue
            
        company = company_el.get_text(strip=True) if company_el else "YC Startup"
        url_val = link_el['href'] if link_el else "#"
        
        if url_val.startswith('/'):
            url_val = f"https://www.workatastartup.com{url_val}"
            
        jobs.append(Job(
            title=title,
            company=company,
            location="Remote/Global",
            url=url_val,
            source="Y Combinator",
            country="🌎 Internacional",
        ))
    return jobs


def search_otg() -> List[Job]:
    """OTG (On The Go) - Remote jobs aggregator"""
    jobs = []
    url = "https://onthego.io/api/jobs"
    params = {"q": "qa quality tester sdet automation"}
    resp = make_request(url, params=params)
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        data = resp.json()
    except ValueError:
        return jobs
        
    for item in data.get("jobs", []):
        title = item.get("title", "N/A")
        if not is_qa_job(title):
            continue
        company = item.get("company", "N/A")
        location = item.get("location", "Remote")
        url_val = item.get("url", "#")
        if url_val is None:
            url_val = "#"
            
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=url_val,
            source="On The Go",
            country="🌎 Internacional (Remote)",
        ))
    return jobs


def search_jobspresso() -> List[Job]:
    """Jobspresso - Remote jobs"""
    jobs = []
    url = "https://jobspresso.co/api/jobs"
    params = {"search": "qa quality tester sdet"}
    resp = make_request(url, params=params)
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        data = resp.json()
    except ValueError:
        return jobs
        
    for item in data.get("jobs", []):
        title = item.get("title", "N/A")
        if not is_qa_job(title):
            continue
        company = item.get("company", "N/A")
        location = item.get("location", "Remote")
        url_val = item.get("url", "#")
        if url_val is None:
            url_val = "#"
            
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=url_val,
            source="Jobspresso",
            country="🌎 Internacional (Remote)",
        ))
    return jobs


def search_catho() -> List[Job]:
    """Catho - Um dos maiores sites de emprego no Brasil"""
    jobs = []
    url = "https://www.catho.com.br/vagas/qa/"
    resp = make_request(url)
    if not (resp and resp.status_code == 200):
        return jobs
    
    soup = BeautifulSoup(resp.content, 'html.parser')
    for card in soup.find_all('div', class_=re.compile(r'vaga-card|job-card|vaga-item')):
        title_el = card.find('h2') or card.find('h3') or card.find('a', class_=re.compile(r'title'))
        company_el = card.find('span', class_=re.compile(r'empresa|company'))
        location_el = card.find('span', class_=re.compile(r'local|cidade|city'))
        link_el = card.find('a', href=True)
        
        if not title_el:
            continue
            
        title = title_el.get_text(strip=True)
        if not is_qa_job(title):
            continue
            
        company = company_el.get_text(strip=True) if company_el else "N/A"
        location = location_el.get_text(strip=True) if location_el else "Brasil"
        url = link_el['href'] if link_el else "#"
        
        if url.startswith('/'):
            url = f"https://www.catho.com.br{url}"
            
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=url,
            source="Catho",
            country="🇧🇷 Brasil",
        ))
    return jobs


def search_vagas_com() -> List[Job]:
    """Vagas.com.br - Site tradicional de empregos"""
    jobs = []
    url = "https://www.vagas.com.br/vagas-de-qa"
    resp = make_request(url)
    if not (resp and resp.status_code == 200):
        return jobs
    
    soup = BeautifulSoup(resp.content, 'html.parser')
    for card in soup.find_all('div', class_=re.compile(r'vaga|job')):
        title_el = card.find('h2') or card.find('a', class_=re.compile(r'titulo|title'))
        company_el = card.find('span', class_=re.compile(r'empresa|company'))
        location_el = card.find('span', class_=re.compile(r'local|cidade|city'))
        link_el = card.find('a', href=True)
        
        if not title_el:
            continue
            
        title = title_el.get_text(strip=True)
        if not is_qa_job(title):
            continue
            
        company = company_el.get_text(strip=True) if company_el else "N/A"
        location = location_el.get_text(strip=True) if location_el else "Brasil"
        url = link_el['href'] if link_el else "#"
        
        if url.startswith('/'):
            url = f"https://www.vagas.com.br{url}"
            
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=url,
            source="Vagas.com.br",
            country="🇧🇷 Brasil",
        ))
    return jobs


def search_infojobs() -> List[Job]:
    """InfoJobs - Site de empregos Brasil"""
    jobs = []
    url = "https://www.infojobs.com.br/vagas-de-emprego-qa.aspx"
    resp = make_request(url)
    if not (resp and resp.status_code == 200):
        return jobs
    
    soup = BeautifulSoup(resp.content, 'html.parser')
    for card in soup.find_all('div', class_=re.compile(r'vaga|job-item')):
        title_el = card.find('h2') or card.find('a', class_=re.compile(r'titulo|title'))
        company_el = card.find('span', class_=re.compile(r'empresa|company'))
        location_el = card.find('span', class_=re.compile(r'local|cidade|city'))
        link_el = card.find('a', href=True)
        
        if not title_el:
            continue
            
        title = title_el.get_text(strip=True)
        if not is_qa_job(title):
            continue
            
        company = company_el.get_text(strip=True) if company_el else "N/A"
        location = location_el.get_text(strip=True) if location_el else "Brasil"
        url = link_el['href'] if link_el else "#"
        
        if url.startswith('/'):
            url = f"https://www.infojobs.com.br{url}"
            
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=url,
            source="InfoJobs",
            country="🇧🇷 Brasil",
        ))
    return jobs


def search_stackoverflow() -> List[Job]:
    """Stack Overflow Jobs (agora Talent) - RSS feed"""
    jobs = []
    url = "https://stackoverflow.com/jobs/feed?q=qa+quality+tester+test+automation+playwright+cypress+selenium"
    resp = make_request(url, headers={"Accept": "application/rss+xml"})
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return jobs
    
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        title = title_el.text.strip() if title_el is not None else "N/A"
        link = link_el.text if link_el is not None else "#"
        
        if not is_qa_job(title):
            continue
            
        # Stack Overflow feed geralmente tem formato "Company - Title"
        company = "Various"
        if " - " in title:
            company, _, title = title.partition(" - ")
            
        jobs.append(Job(
            title=title.strip(),
            company=company.strip(),
            location="Remote",
            url=link,
            source="Stack Overflow",
            country="🌎 Internacional",
        ))
    return jobs


def search_github() -> List[Job]:
    """GitHub Jobs via search (GitHub não tem mais API oficial de jobs, usar busca web)"""
    jobs = []
    # GitHub tem uma seção de jobs em github.com/jobs mas não há API pública
    # Vamos usar uma abordagem diferente - buscar empresas que postam no GitHub
    return jobs  # Placeholder


def search_wellfound() -> List[Job]:
    """Wellfound (antigo AngelList) - Startups"""
    jobs = []
    # Wellfound não tem API pública simples, usar RSS se disponível
    url = "https://wellfound.com/jobs/feed?role=qa&role=tester&role=sdet"
    resp = make_request(url, headers={"Accept": "application/rss+xml"})
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return jobs
    
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        title = title_el.text.strip() if title_el is not None else "N/A"
        link = link_el.text if link_el is not None else "#"
        
        if not is_qa_job(title):
            continue
            
        # Formato: "Title at Company"
        company = "Startup"
        if " at " in title:
            title, _, company = title.partition(" at ")
            
        jobs.append(Job(
            title=title.strip(),
            company=company.strip(),
            location="Remote",
            url=link,
            source="Wellfound",
            country="🌎 Internacional (Startups)",
        ))
    return jobs


def search_ycombinator() -> List[Job]:
    """Y Combinator jobs - Startups"""
    jobs = []
    url = "https://www.ycombinator.com/jobs/feed?role=qa&role=tester&role=sdet"
    resp = make_request(url, headers={"Accept": "application/rss+xml"})
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return jobs
    
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        title = title_el.text.strip() if title_el is not None else "N/A"
        link = link_el.text if link_el is not None else "#"
        
        if not is_qa_job(title):
            continue
            
        company = "YC Startup"
        if " at " in title:
            title, _, company = title.partition(" at ")
            
        jobs.append(Job(
            title=title.strip(),
            company=company.strip(),
            location="Remote",
            url=link,
            source="Y Combinator",
            country="🌎 Internacional (YC Startups)",
        ))
    return jobs


def search_otg() -> List[Job]:
    """On The Grid - Remote jobs"""
    jobs = []
    url = "https://onthegrid.city/jobs.rss?category=qa"
    resp = make_request(url, headers={"Accept": "application/rss+xml"})
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return jobs
    
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        title = title_el.text.strip() if title_el is not None else "N/A"
        link = link_el.text if link_el is not None else "#"
        
        if not is_qa_job(title):
            continue
            
        company = "Various"
        if " at " in title:
            title, _, company = title.partition(" at ")
            
        jobs.append(Job(
            title=title.strip(),
            company=company.strip(),
            location="Remote",
            url=link,
            source="On The Grid",
            country="🌎 Internacional",
        ))
    return jobs


def search_jobspresso() -> List[Job]:
    """Jobspresso - Curated remote jobs"""
    jobs = []
    url = "https://jobspresso.co/feed/?s=qa+quality+tester"
    resp = make_request(url, headers={"Accept": "application/rss+xml"})
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return jobs
    
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        title = title_el.text.strip() if title_el is not None else "N/A"
        link = link_el.text if link_el is not None else "#"
        
        if not is_qa_job(title):
            continue
            
        company = "Various"
        if " at " in title:
            title, _, company = title.partition(" at ")
            
        jobs.append(Job(
            title=title.strip(),
            company=company.strip(),
            location="Remote",
            url=link,
            source="Jobspresso",
            country="🌎 Internacional (Curated)",
        ))
    return jobs


def search_landing_jobs() -> List[Job]:
    """Landing.jobs - Tech jobs Europe/Remote"""
    jobs = []
    url = "https://landing.jobs/jobs/feed?skills=qa%2Ctesting%2Cautomation"
    resp = make_request(url, headers={"Accept": "application/rss+xml"})
    if not (resp and resp.status_code == 200):
        return jobs
    
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return jobs
    
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        title = title_el.text.strip() if title_el is not None else "N/A"
        link = link_el.text if link_el is not None else "#"
        
        if not is_qa_job(title):
            continue
            
        company = "Various"
        if " at " in title:
            title, _, company = title.partition(" at ")
            
        jobs.append(Job(
            title=title.strip(),
            company=company.strip(),
            location="Remote/Europe",
            url=link,
            source="Landing.jobs",
            country="🌍 Europa/Remote",
        ))
    return jobs


def search_remotive_categories() -> List[Job]:
    """Remotive com múltiplas categorias"""
    jobs = []
    categories = ["qa-testing", "programming", "devops-sysadmin"]
    for cat in categories:
        resp = make_request("https://remotive.com/api/remote-jobs", params={"category": cat})
        if not (resp and resp.status_code == 200):
            continue
        try:
            data = resp.json()
        except ValueError:
            continue
        for item in data.get("jobs", []):
            title = item.get("title", "N/A")
            if not is_qa_job(title):
                continue
            jobs.append(Job(
                title=title,
                company=item.get("company_name", "N/A"),
                location=item.get("candidate_required_location") or "Remote",
                url=item.get("url", "#"),
                source="Remotive",
                country="🌎 Internacional (Remote)",
                salary=item.get("salary") or None,
            ))
    return jobs


def search_all_sources() -> List[Job]:
    """Busca em todas as fontes em paralelo"""
    all_jobs = []
    
    # Define all sources with their functions
    sources = [
        ("RemoteOK", search_remoteok),
        ("Remotive", search_remotive),
        ("Arbeitnow", search_arbeitnow),
        ("Jobicy", search_jobicy),
        ("We Work Remotely", search_weworkremotely),
        ("Greenhouse (empresas)", search_greenhouse_all),
        ("Lever (empresas)", search_lever_all),
        # Novas fontes brasileiras
        ("Programathor", search_programathor),
        ("Gupy", search_gupy),
        ("Trampos.co", search_trampos),
        ("Catho", search_catho),
        ("Vagas.com.br", search_vagas_com),
        ("InfoJobs", search_infojobs),
        # Novas fontes internacionais
        ("Stack Overflow", search_stackoverflow),
        ("Wellfound", search_wellfound),
        ("Y Combinator", search_ycombinator),
        ("On The Grid", search_otg),
        ("Jobspresso", search_jobspresso),
        ("Landing.jobs", search_landing_jobs),
        ("Remotive (multi-cat)", search_remotive_categories),
    ]
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(func): name for name, func in sources}
        for fut in as_completed(futures):
            source_name = futures[fut]
            try:
                jobs = fut.result()
                all_jobs.extend(jobs)
                logger.info(f"✅ {source_name}: {len(jobs)} vagas QA encontradas")
            except Exception as e:
                logger.error(f"❌ Erro em {source_name}: {e}")
    
    return all_jobs


# ============================================================
# DISCORD / OUTPUT
# ============================================================

def post_to_discord(jobs: List[Job], posted_jobs: Dict[str, str]) -> int:
    """Envia vagas novas para Discord webhook. Retorna quantas foram postadas."""
    if not DISCORD_WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK_URL não configurado, pulando postagem.")
        return 0
    
    new_jobs = [j for j in jobs if j.id not in posted_jobs]
    if not new_jobs:
        logger.info("Nenhuma vaga nova para postar.")
        return 0
    
    # Limitar posts por execução
    new_jobs = new_jobs[:MAX_POSTS_PER_RUN]
    
    posted_count = 0
    for job in new_jobs:
        # Formatar embed para Discord
        embed = {
            "title": job.title,
            "url": job.url,
            "color": 0x00E5FF,  # cor ciano/teal
            "fields": [
                {"name": "🏢 Empresa", "value": job.company, "inline": True},
                {"name": "📍 Localização", "value": job.location, "inline": True},
                {"name": "🌍 País/Região", "value": job.country, "inline": True},
                {"name": "🔍 Fonte", "value": job.source, "inline": True},
            ],
            "footer": {"text": f"QA Job Bot • {job.source}"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        if job.salary:
            embed["fields"].append({"name": "💰 Salário", "value": job.salary, "inline": True})
        
        seniority = detect_seniority(job.title)
        if seniority:
            embed["fields"].append({"name": "📊 Senioridade", "value": seniority, "inline": True})
        
        payload = {"embeds": [embed]}
        
        try:
            resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            if resp.status_code in (200, 204):
                posted_jobs[job.id] = datetime.now(timezone.utc).isoformat()
                posted_count += 1
                logger.info(f"📤 Postado no Discord: {job.title} @ {job.company}")
            else:
                logger.error(f"Falha ao postar no Discord: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"Erro ao postar no Discord: {e}")
        
        time.sleep(DISCORD_POST_DELAY)
    
    return posted_count


def print_summary(jobs: List[Job], posted_jobs: Dict[str, str]):
    """Imprime resumo das vagas encontradas"""
    if not jobs:
        print("⚠️  Nenhuma vaga encontrada nesta execução.")
        return
    
    # Estatísticas por fonte
    from collections import Counter
    source_counts = Counter(j.source for j in jobs)
    country_counts = Counter(j.country for j in jobs)
    
    print(f"\n{'='*60}")
    print(f"📊 RESUMO DA BUSCA - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}")
    print(f"Total de vagas QA encontradas: {len(jobs)}")
    print(f"Vagas já conhecidas (dedup): {sum(1 for j in jobs if j.id in posted_jobs)}")
    print(f"Vagas novas: {sum(1 for j in jobs if j.id not in posted_jobs)}")
    print(f"\n📈 Por fonte:")
    for source, count in source_counts.most_common():
        print(f"  {source}: {count}")
    print(f"\n🌍 Por país/região:")
    for country, count in country_counts.most_common():
        print(f"  {country}: {count}")
    print(f"{'='*60}\n")


# ============================================================
# MAIN
# ============================================================

def main():
    logger.info("🚀 Iniciando busca de vagas QA...")
    
    # Carregar estado persistente
    posted_jobs = load_posted_jobs()
    posted_jobs = prune_old_entries(posted_jobs)
    logger.info(f"📚 Histórico carregado: {len(posted_jobs)} vagas conhecidas")
    
    # Buscar em todas as fontes
    all_jobs = search_all_sources()
    
    if not all_jobs:
        logger.warning("⚠️  Nenhuma vaga encontrada em nenhuma fonte.")
        return 0
    
    # Filtrar apenas QA (dupla verificação)
    qa_jobs = [j for j in all_jobs if is_qa_job(j.title)]
    logger.info(f"🔍 Após filtro QA: {len(qa_jobs)} vagas")
    
    # Resumo
    print_summary(qa_jobs, posted_jobs)
    
    # Postar no Discord
    posted = post_to_discord(qa_jobs, posted_jobs)
    
    # Salvar estado atualizado
    if posted > 0:
        save_posted_jobs(posted_jobs)
        logger.info(f"💾 Estado salvo: {posted} novas vagas registradas")
    
    return posted


if __name__ == "__main__":
    try:
        posted = main()
        sys.exit(0 if posted >= 0 else 1)
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuário")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Erro fatal: {e}")
        sys.exit(1)