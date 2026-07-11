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
]
DEFAULT_LEVER_COMPANIES = [
    "netflix", "shopify", "spotify", "canva", "brex", "ramp", "loom",
    "rippling", "attentive", "eightsleep",
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
# ORQUESTRADOR
# ============================================================

SOURCES = [
    ("RemoteOK", search_remoteok),
    ("Remotive", search_remotive),
    ("Arbeitnow", search_arbeitnow),
    ("Jobicy", search_jobicy),
    ("We Work Remotely", search_weworkremotely),
    ("Greenhouse (empresas)", search_greenhouse_all),
    ("Lever (empresas)", search_lever_all),
]


def search_all_sources() -> List[Job]:
    all_jobs: List[Job] = []
    stats: Dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=len(SOURCES)) as ex:
        futures = {ex.submit(fn): name for name, fn in SOURCES}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                found = fut.result()
                stats[name] = len(found)
                all_jobs.extend(found)
                logger.info(f"✓ {name}: {len(found)} vaga(s) de QA encontradas")
            except Exception as e:
                stats[name] = 0
                logger.error(f"✗ {name}: erro - {e}")

    logger.info(f"📊 Resumo por fonte: {stats}")
    return all_jobs


def deduplicate(jobs: List[Job]) -> List[Job]:
    seen: Set[str] = set()
    unique = []
    for job in jobs:
        if job.id in seen:
            continue
        seen.add(job.id)
        unique.append(job)
    return unique


# ============================================================
# DISCORD
# ============================================================

def create_discord_embed(job: Job) -> dict:
    seniority = detect_seniority(job.title)
    location_lower = (job.location or "").lower()
    if any(w in location_lower for w in ["remoto", "remote", "anywhere"]):
        work_emoji = "🏠"
    elif any(w in location_lower for w in ["híbrido", "hybrid"]):
        work_emoji = "🔄"
    else:
        work_emoji = "🏢"

    is_br = "🇧🇷" in job.country
    color = 0x00FFFF if is_br else 0xFF10F0

    lines = [f"### 🏢 {job.company}", "", f"{work_emoji} **Local:** {job.location}"]
    if job.salary:
        lines.append(f"💰 **Salário:** {job.salary}")
    if seniority:
        lines.append(f"📈 **Nível:** {seniority}")

    return {
        "title": f"{job.country} {job.title}"[:256],
        "description": "\n".join(lines),
        "url": job.url,
        "color": color,
        "footer": {"text": f"📡 {job.source} • {datetime.now().strftime('%d/%m/%Y %H:%M')}"},
        "fields": [{
            "name": "🎯 Como Candidatar",
            "value": f"**[👉 Ver vaga completa]({job.url})**",
            "inline": False,
        }],
    }


def send_to_discord(jobs: List[Job], posted: Dict[str, str]) -> int:
    if not DISCORD_WEBHOOK_URL:
        logger.error("DISCORD_WEBHOOK_URL não configurado - abortando envio.")
        return 0

    new_jobs = [j for j in jobs if j.id not in posted]
    to_post = new_jobs[:MAX_POSTS_PER_RUN]
    skipped = len(new_jobs) - len(to_post)
    if skipped > 0:
        logger.info(f"⏳ {skipped} vaga(s) além do limite de {MAX_POSTS_PER_RUN}/execução ficarão para a próxima rodada.")

    posted_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for job in to_post:
        payload = {"embeds": [create_discord_embed(job)]}
        try:
            resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            if resp.status_code == 204:
                logger.info(f"✓ Postado: {job.title} @ {job.company}")
                posted[job.id] = now_iso
                posted_count += 1
            elif resp.status_code == 429:
                retry_after = resp.json().get("retry_after", 2)
                logger.warning(f"Rate limited pelo Discord, aguardando {retry_after}s")
                time.sleep(float(retry_after) + 0.5)
            else:
                logger.error(f"✗ Falha ao postar '{job.title}': HTTP {resp.status_code} - {resp.text[:200]}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro enviando ao Discord: {e}")
        time.sleep(DISCORD_POST_DELAY)

    return posted_count


def send_summary_to_discord(new_count: int, total_found: int):
    if not DISCORD_WEBHOOK_URL or new_count == 0:
        return
    if new_count >= 10:
        emoji, message = "🎉", "Muitas oportunidades hoje!"
    elif new_count >= 5:
        emoji, message = "✨", "Várias vagas encontradas!"
    else:
        emoji, message = "👍", "Novas oportunidades disponíveis!"

    embed = {
        "title": f"{emoji} Resumo da Busca",
        "description": message,
        "color": 0x36393F,
        "fields": [
            {"name": "📊 Vagas Encontradas", "value": f"`{total_found}`", "inline": True},
            {"name": "🆕 Novas Vagas", "value": f"`{new_count}`", "inline": True},
        ],
        "footer": {"text": "🤖 QA Job Bot"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=10)
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro enviando resumo: {e}")


# ============================================================
# MAIN
# ============================================================

def main():
    start = time.time()
    logger.info(f"🔍 Iniciando busca de vagas de QA - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    posted = load_posted_jobs()
    logger.info(f"📝 {len(posted)} vaga(s) já rastreadas no histórico")

    all_jobs = search_all_sources()
    logger.info(f"📊 {len(all_jobs)} vaga(s) de QA encontradas no total (antes de dedup)")

    unique_jobs = deduplicate(all_jobs)
    logger.info(f"🔄 {len(unique_jobs)} vaga(s) únicas após deduplicação")

    new_count = send_to_discord(unique_jobs, posted)

    send_summary_to_discord(new_count, len(unique_jobs))

    posted = prune_old_entries(posted)
    save_posted_jobs(posted)

    elapsed = time.time() - start
    logger.info(f"✅ {new_count} nova(s) vaga(s) postada(s) em {elapsed:.1f}s")
    logger.info(f"📝 {len(posted)} vaga(s) no histórico após limpeza (mantém {KEEP_HISTORY_DAYS} dias)")

    if not DISCORD_WEBHOOK_URL:
        sys.exit(1)


if __name__ == "__main__":
    main()
