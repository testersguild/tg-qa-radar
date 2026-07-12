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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional

import requests

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
MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "25"))
DISCORD_POST_DELAY = float(os.getenv("DISCORD_POST_DELAY", "1.0"))
KEEP_HISTORY_DAYS = int(os.getenv("KEEP_HISTORY_DAYS", "60"))

# Quantas páginas buscar em fontes paginadas (The Muse).
THEMUSE_PAGES = int(os.getenv("THEMUSE_PAGES", "3"))

# Empresas Greenhouse/Lever podem ser sobrescritas via env var, separadas por vírgula.
# Ex.: GREENHOUSE_COMPANIES="nubank,vtex,stripe,notion"
# Lista verificada (boards públicos ativos em boards-api.greenhouse.io).
DEFAULT_GREENHOUSE_COMPANIES = [
    "nubank", "vtex", "stripe", "figma", "airtable", "webflow", "cloudflare",
    "gitlab", "mongodb", "twilio", "coinbase", "asana", "affirm", "robinhood",
    "instacart", "reddit", "vercel", "planetscale", "thoughtworks", "databricks",
    "datadog", "dropbox", "elastic", "gusto", "brex", "chime", "sofi", "monzo",
    "faire", "discord", "samsara", "scaleai", "anthropic", "lattice", "fivetran",
    "postman", "circleci", "launchdarkly", "algolia", "contentful", "amplitude",
    "mixpanel", "pendo", "calendly", "huntress", "tailscale", "remotecom",
    "gympass", "quintoandar", "ebanx",
]
# Lista verificada (postings públicos ativos em api.lever.co).
DEFAULT_LEVER_COMPANIES = [
    "spotify", "palantir", "matchgroup", "tala", "gopuff", "houzz", "kavak",
]

GREENHOUSE_COMPANIES = [
    c.strip() for c in os.getenv("GREENHOUSE_COMPANIES", "").split(",") if c.strip()
] or DEFAULT_GREENHOUSE_COMPANIES

LEVER_COMPANIES = [
    c.strip() for c in os.getenv("LEVER_COMPANIES", "").split(",") if c.strip()
] or DEFAULT_LEVER_COMPANIES

# ------------------------------------------------------------
# FILTRO QA — duas camadas para maximizar recall SEM perder precisão.
#
#   * STRONG: sinais inequívocos de QA. Se casar, é vaga QA — mesmo que o
#     título também contenha "manager", "specialist", "lead" etc.
#     (ex.: "QA Manager", "Test Automation Specialist", "SDET Lead").
#   * WEAK: sinais ambíguos (uma ferramenta, "automation", "test" solto).
#     Só contam como QA se o título NÃO casar com um papel claramente não-QA.
# ------------------------------------------------------------
STRONG_QA_KEYWORDS = [
    r"\bqa\b",
    r"\bqe\b",
    r"quality assurance",
    r"quality engineer",
    r"qualidade de software",
    r"garantia da qualidade",
    r"controle de qualidade",
    r"analista de qualidade",
    r"\bsdet\b",
    r"software development engineer in test",
    r"\btesters?\b",
    r"\btestador(?:a|es|as)?\b",
    r"test engineer",
    r"test automation",
    r"automation tester",
    r"automa[çc][ãa]o de testes",
    r"engenheir[oa] de (?:teste|qa|qualidade)",
    r"analista de test",
    r"quality analyst",
    r"test analyst",
    r"\bqa analyst\b",
    r"qa engineer",
    r"qa automation",
    r"qa lead",
    r"test lead",
]
WEAK_QA_KEYWORDS = [
    r"\btests?\b",
    r"\btesting\b",
    r"\bteste\b",
    r"\btestes\b",
    r"playwright",
    r"cypress",
    r"selenium",
    r"appium",
    r"cucumber",
    r"robot framework",
    r"\bjest\b",
    r"pytest",
    r"junit",
    r"testng",
    r"\bk6\b",
    r"jmeter",
]

QA_STRONG_PATTERN = re.compile("|".join(STRONG_QA_KEYWORDS), flags=re.IGNORECASE)
QA_WEAK_PATTERN = re.compile("|".join(WEAK_QA_KEYWORDS), flags=re.IGNORECASE)

# Papéis claramente NÃO-QA (usados só para desambiguar sinais fracos).
# Não incluímos "manager/specialist/lead/coordinator" aqui de propósito:
# eles são comuns em títulos legítimos de QA (ex.: "QA Manager").
NON_QA_EXCLUDE = [
    r"\barchitect\b",
    r"\bdesigner\b",
    r"\bdeveloper\b",
    r"\bdevelopment\b",
    r"\bdevops\b",
    r"\bback[\s-]?end\b",
    r"\bfront[\s-]?end\b",
    r"\bfull[\s-]?stack\b",
    r"\bdata scientist\b",
    r"\bdata engineer\b",
    r"\bdata analyst\b",
    r"\bml engineer\b",
    r"\bmachine learning\b",
    r"\bproduct manager\b",
    r"\bproject manager\b",
    r"\bprogram manager\b",
    r"\bscrum master\b",
    r"\bsales\b",
    r"\bmarketing\b",
    r"\brecruiter\b",
    r"\bsecurity engineer\b",
    r"\bsite reliability\b",
    r"\bmechatronic\b",
    r"\btechnician\b",
    r"\boperator\b",
    r"\bdriver\b",
    r"\bnurse\b",
    r"\bhealthcare\b",
    r"\brestaurant\b",
    r"\bwarehouse\b",
    r"\baccountant\b",
    r"\bcopywriter\b",
    r"\bretail\b",
    r"\bkey holder\b",
    r"\bsales associate\b",
    r"\bdetection engineering\b",
    r"\bcontrols testing\b",
    r"\btesting manager\b",
    r"\bsupplier\b",
]
NON_QA_PATTERN = re.compile("|".join(NON_QA_EXCLUDE), flags=re.IGNORECASE)

# Exclusões "duras": descartam a vaga mesmo com sinal forte de QA
# (ex.: "Penetration Tester" casa com "tester" mas é segurança, não QA).
HARD_EXCLUDE = [
    r"\bpenetration\b",
    r"\bpentest",
    r"\bwelding\b",
]
HARD_EXCLUDE_PATTERN = re.compile("|".join(HARD_EXCLUDE), flags=re.IGNORECASE)

# Postagens de teste / spam (ex.: RemoteOK "Test", "Test 1 posting").
JUNK_TITLES = {"test", "testing", "test posting", "test 1 posting", "test job", "example"}

SENIORITY_PATTERNS = {
    "🌱 Júnior": re.compile(r"\b(jr|junior|júnior|trainee|estagi|intern)\b", re.I),
    "🚀 Pleno": re.compile(r"\b(pleno|mid|middle|\bii\b)\b", re.I),
    "⭐ Sênior": re.compile(r"\b(senior|sênior|\bsr\b|lead|principal|staff|\biii\b)\b", re.I),
}

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; QAJobBot/3.0; +https://github.com/testersguild/tg-qa-radar)",
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
        self.title = (self.title or "").strip()
        self.company = (self.company or "N/A").strip() or "N/A"
        if not self.id:
            self.id = generate_job_id(self.title, self.company)


# ============================================================
# HELPERS
# ============================================================

def _normalize(text: str) -> str:
    """Normaliza para dedup: minúsculas, sem acentos/pontuação, espaços únicos."""
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9à-ÿ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def generate_job_id(title: str, company: str) -> str:
    """ID estável baseado em título+empresa (ignora a fonte -> dedup cross-source)."""
    unique = f"{_normalize(title)}|{_normalize(company)}"
    return hashlib.md5(unique.encode("utf-8")).hexdigest()[:16]


def is_qa_job(title: str, extra: str = "") -> bool:
    """True se for vaga de QA. `extra` = tags/categoria (campos curtos, não a descrição)."""
    if not title:
        return False
    if _normalize(title) in JUNK_TITLES:
        return False
    # 0) Exclusão dura: nunca é QA, mesmo com "tester" no título.
    if HARD_EXCLUDE_PATTERN.search(title):
        return False
    # 1) Sinal forte no título -> QA garantido.
    if QA_STRONG_PATTERN.search(title):
        return True
    # 2) Sinal forte em tags/categoria + título não é claramente outro papel.
    if extra and QA_STRONG_PATTERN.search(extra) and not NON_QA_PATTERN.search(title):
        return True
    # 3) Sinal fraco no título -> só se não for claramente outro papel.
    if QA_WEAK_PATTERN.search(title) and not NON_QA_PATTERN.search(title):
        return True
    return False


def detect_seniority(title: str) -> str:
    for label, pattern in SENIORITY_PATTERNS.items():
        if pattern.search(title or ""):
            return label
    return ""


def _abs_url(base: str, url: Optional[str]) -> str:
    if not url:
        return base
    if url.startswith("/"):
        return base.rstrip("/") + url
    return url


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


def _parse_rss_items(content: bytes):
    """Itera (title, link, description) de um feed RSS/Atom. Robusto a erros."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        title = (title_el.text or "").strip() if title_el is not None else ""
        link = (link_el.text or "").strip() if link_el is not None else "#"
        desc = (desc_el.text or "") if desc_el is not None else ""
        yield title, link, desc


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
# FONTES (todas verificadas como ativas)
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
        if not is_qa_job(title, tags):
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
    """Remotive — busca em múltiplas categorias relevantes."""
    jobs = []
    categories = ["qa", "software-dev", "devops"]
    seen = set()
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
            tags = " ".join(item.get("tags", []) or [])
            if not is_qa_job(title, tags):
                continue
            url = item.get("url", "#")
            if url in seen:
                continue
            seen.add(url)
            jobs.append(Job(
                title=title,
                company=item.get("company_name", "N/A"),
                location=item.get("candidate_required_location") or "Remote",
                url=url,
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
        if not is_qa_job(title, tags):
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
    """Jobicy — busca ampla (a API rejeita tags curtas como 'qa') e filtra localmente."""
    jobs = []
    resp = make_request("https://jobicy.com/api/v2/remote-jobs", params={"count": 100})
    if not (resp and resp.status_code == 200):
        return jobs
    try:
        data = resp.json()
    except ValueError:
        return jobs
    for item in data.get("jobs", []):
        title = item.get("jobTitle", "N/A")
        industry = " ".join(item.get("jobIndustry", []) or []) if isinstance(item.get("jobIndustry"), list) else str(item.get("jobIndustry", ""))
        if not is_qa_job(title, industry):
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
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ]
    for url in feeds:
        resp = make_request(url, headers={"Accept": "application/rss+xml"})
        if not (resp and resp.status_code == 200):
            continue
        for title, link, _desc in _parse_rss_items(resp.content):
            if not is_qa_job(title):
                continue
            company = "Various"
            if ":" in title:  # formato comum: "Company: Job Title"
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


def search_workingnomads() -> List[Job]:
    """Working Nomads — API pública de vagas remotas."""
    jobs = []
    resp = make_request("https://www.workingnomads.com/api/exposed_jobs/")
    if not (resp and resp.status_code == 200):
        return jobs
    try:
        data = resp.json()
    except ValueError:
        return jobs
    if not isinstance(data, list):
        return jobs
    for item in data:
        title = item.get("title", "N/A")
        extra = f"{item.get('category_name', '')} {item.get('tags', '')}"
        if not is_qa_job(title, extra):
            continue
        jobs.append(Job(
            title=title,
            company=item.get("company_name", "N/A"),
            location=item.get("location") or "Remote",
            url=item.get("url", "#"),
            source="Working Nomads",
            country="🌎 Internacional (Remote)",
            posted_at=item.get("pub_date"),
        ))
    return jobs


def search_fourdayweek() -> List[Job]:
    """4dayweek.io — vagas remotas. A API suporta busca textual via `q`."""
    jobs = []
    seen = set()
    for query in ("qa", "tester", "sdet", "test automation"):
        resp = make_request("https://4dayweek.io/api/jobs", params={"q": query})
        if not (resp and resp.status_code == 200):
            continue
        try:
            data = resp.json()
        except ValueError:
            continue
        for item in data.get("jobs", []):
            title = item.get("title", "N/A")
            if not is_qa_job(title, str(item.get("category", ""))):
                continue
            slug = item.get("slug")
            if slug in seen:
                continue
            seen.add(slug)
            locs = item.get("locations") or []
            loc_names = [
                (loc.get("name") if isinstance(loc, dict) else str(loc))
                for loc in locs
            ]
            loc_names = [l for l in loc_names if l]
            jobs.append(Job(
                title=title,
                company=item.get("company_name", "N/A"),
                location=", ".join(loc_names) if loc_names else "Remote",
                url=f"https://4dayweek.io/remote-job/{slug}" if slug else "https://4dayweek.io",
                source="4dayweek.io",
                country="🌎 Internacional (Remote)",
            ))
    return jobs


def search_themuse() -> List[Job]:
    """The Muse — API pública, categoria Software Engineering (QA está aqui)."""
    jobs = []
    for page in range(1, THEMUSE_PAGES + 1):
        resp = make_request(
            "https://www.themuse.com/api/public/jobs",
            params={"category": "Software Engineering", "page": page},
        )
        if not (resp and resp.status_code == 200):
            break
        try:
            data = resp.json()
        except ValueError:
            break
        results = data.get("results", [])
        if not results:
            break
        for item in results:
            title = item.get("name", "N/A")
            cats = " ".join(c.get("name", "") for c in item.get("categories", []) or [])
            if not is_qa_job(title, cats):
                continue
            company = (item.get("company") or {}).get("name", "N/A")
            locs = [loc.get("name", "") for loc in item.get("locations", []) or []]
            url = (item.get("refs") or {}).get("landing_page", "#")
            jobs.append(Job(
                title=title,
                company=company,
                location=", ".join(locs) if locs else "N/A",
                url=url,
                source="The Muse",
                country="🌎 Internacional",
                posted_at=item.get("publication_date"),
            ))
    return jobs


def search_jobspresso() -> List[Job]:
    """Jobspresso — feed RSS (WordPress) de vagas remotas."""
    jobs = []
    resp = make_request("https://jobspresso.co/feed/?s=qa+quality+tester+test", headers={"Accept": "application/rss+xml"})
    if not (resp and resp.status_code == 200):
        return jobs
    for title, link, _desc in _parse_rss_items(resp.content):
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
        depts = " ".join(d.get("name", "") for d in item.get("departments", []) or [])
        if not is_qa_job(title, depts):
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
    return _search_companies(search_greenhouse_company, GREENHOUSE_COMPANIES, "Greenhouse")


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
        categories = item.get("categories", {}) or {}
        team = f"{categories.get('team', '')} {categories.get('department', '')}"
        if not is_qa_job(title, team):
            continue
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
    return _search_companies(search_lever_company, LEVER_COMPANIES, "Lever")


def _search_companies(fn: Callable[[str], List[Job]], companies: Iterable[str], label: str) -> List[Job]:
    jobs = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fn, c): c for c in companies}
        for fut in as_completed(futures):
            try:
                jobs.extend(fut.result())
            except Exception as e:
                logger.error(f"Erro {label}/{futures[fut]}: {e}")
    return jobs


# ============================================================
# ORQUESTRAÇÃO
# ============================================================

def search_all_sources() -> List[Job]:
    """Busca em todas as fontes em paralelo."""
    all_jobs: List[Job] = []
    sources = [
        ("RemoteOK", search_remoteok),
        ("Remotive", search_remotive),
        ("Arbeitnow", search_arbeitnow),
        ("Jobicy", search_jobicy),
        ("We Work Remotely", search_weworkremotely),
        ("Working Nomads", search_workingnomads),
        ("4dayweek.io", search_fourdayweek),
        ("The Muse", search_themuse),
        ("Jobspresso", search_jobspresso),
        ("Greenhouse", search_greenhouse_all),
        ("Lever", search_lever_all),
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


def dedupe_jobs(jobs: List[Job]) -> List[Job]:
    """Remove duplicatas cross-source mantendo a primeira ocorrência."""
    seen = set()
    unique = []
    for job in jobs:
        if job.id in seen:
            continue
        seen.add(job.id)
        unique.append(job)
    return unique


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

    new_jobs = new_jobs[:MAX_POSTS_PER_RUN]

    posted_count = 0
    for job in new_jobs:
        embed = {
            "title": job.title[:250] or "Vaga QA",
            "url": job.url if job.url and job.url != "#" else None,
            "color": 0x00E5FF,
            "fields": [
                {"name": "🏢 Empresa", "value": job.company, "inline": True},
                {"name": "📍 Localização", "value": job.location or "N/A", "inline": True},
                {"name": "🌍 País/Região", "value": job.country, "inline": True},
                {"name": "🔍 Fonte", "value": job.source, "inline": True},
            ],
            "footer": {"text": f"QA Job Bot • {job.source}"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if job.salary:
            embed["fields"].append({"name": "💰 Salário", "value": str(job.salary), "inline": True})

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
            elif resp.status_code == 429:
                retry = 2.0
                try:
                    retry = float(resp.json().get("retry_after", 2.0))
                except Exception:
                    pass
                logger.warning(f"Discord rate limit, aguardando {retry}s...")
                time.sleep(retry)
            else:
                logger.error(f"Falha ao postar no Discord: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"Erro ao postar no Discord: {e}")

        time.sleep(DISCORD_POST_DELAY)

    return posted_count


def print_summary(jobs: List[Job], posted_jobs: Dict[str, str]):
    """Imprime resumo das vagas encontradas."""
    if not jobs:
        print("⚠️  Nenhuma vaga encontrada nesta execução.")
        return

    from collections import Counter
    source_counts = Counter(j.source for j in jobs)
    country_counts = Counter(j.country for j in jobs)

    print(f"\n{'='*60}")
    print(f"📊 RESUMO DA BUSCA - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}")
    print(f"Total de vagas QA (após dedup): {len(jobs)}")
    print(f"Vagas já conhecidas (histórico): {sum(1 for j in jobs if j.id in posted_jobs)}")
    print(f"Vagas novas: {sum(1 for j in jobs if j.id not in posted_jobs)}")
    print("\n📈 Por fonte:")
    for source, count in source_counts.most_common():
        print(f"  {source}: {count}")
    print("\n🌍 Por país/região:")
    for country, count in country_counts.most_common():
        print(f"  {country}: {count}")
    print(f"{'='*60}\n")


# ============================================================
# MAIN
# ============================================================

def main():
    logger.info("🚀 Iniciando busca de vagas QA...")

    posted_jobs = load_posted_jobs()
    posted_jobs = prune_old_entries(posted_jobs)
    logger.info(f"📚 Histórico carregado: {len(posted_jobs)} vagas conhecidas")

    all_jobs = search_all_sources()
    if not all_jobs:
        logger.warning("⚠️  Nenhuma vaga encontrada em nenhuma fonte.")
        return 0

    qa_jobs = dedupe_jobs(all_jobs)
    logger.info(f"🔍 {len(all_jobs)} vagas brutas -> {len(qa_jobs)} após dedup")

    print_summary(qa_jobs, posted_jobs)

    posted = post_to_discord(qa_jobs, posted_jobs)

    if posted > 0:
        save_posted_jobs(posted_jobs)
        logger.info(f"💾 Estado salvo: {posted} novas vagas registradas")

    return posted


if __name__ == "__main__":
    try:
        posted = main()
        sys.exit(0)
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuário")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Erro fatal: {e}")
        sys.exit(1)
