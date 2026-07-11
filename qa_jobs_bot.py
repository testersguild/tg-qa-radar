import os
import requests
import json
from datetime import datetime
from typing import List, Dict, Set
import time
import hashlib
import xml.etree.ElementTree as ET
import logging
import re
from urllib.parse import urljoin, quote
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Discord Webhook URL from environment variable
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

# File to track posted jobs (prevents duplicates)
POSTED_JOBS_FILE = 'posted_jobs.json'

# Request timeout
REQUEST_TIMEOUT = 15

# ============================================================
# JOB SOURCES - Expanded list
# ============================================================
ENABLED_SOURCES = [
    # Brazilian sources
    'programathor',
    'gupy',
    'trampos',
    'catho',
    'vagas',
    'infojobs',
    'linkedin_br',
    'greenhouse_br',
    'trabalha_br',
    'keppler',
    'revelo',
    'geekhunter',
    
    # International remote sources (API-based)
    'remoteok',
    'remotive',
    'weworkremotely',
    'landing_jobs',
    'wellfound',
    'ycombinator',
    'otg',
    'jobspresso',
    'remote_co',
    'builtin',
    'dice',
    ' Otta',
    'arc_dev',
    'himalayas',
    'remote_rocketship',
    
    # Greenhouse companies
    'greenhouse_global',
    
    # GitHub/Stack Overflow
    'github_jobs',
    'stackoverflow_rss',
    
    # RSS/Feed sources
    'indeed_rss',
    'linkedin_rss',
    'glassdoor_rss',
]

def load_posted_jobs() -> Set[str]:
    """Load previously posted job IDs to avoid duplicates"""
    try:
        if os.path.exists(POSTED_JOBS_FILE):
            with open(POSTED_JOBS_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
    except Exception as e:
        logger.warning(f"Error loading posted jobs: {e}")
    return set()

def save_posted_jobs(job_ids: Set[str]):
    """Save posted job IDs"""
    try:
        with open(POSTED_JOBS_FILE, 'w') as f:
            json.dump(list(job_ids), f)
    except Exception as e:
        logger.error(f"Error saving posted jobs: {e}")

def generate_job_id(title: str, company: str) -> str:
    """Generate unique ID for a job based on title and company"""
    unique_string = f"{title.lower().strip()}_{company.lower().strip()}"
    return hashlib.md5(unique_string.encode()).hexdigest()[:16]

def make_request(url: str, params: dict = None, headers: dict = None, method: str = 'GET', data: dict = None) -> requests.Response:
    """Make HTTP request with retries and rate limiting"""
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/html, */*',
        'Accept-Language': 'en-US,en;q=0.9,pt-BR;q=0.8',
    }
    if headers:
        default_headers.update(headers)
    
    for attempt in range(3):
        try:
            if method == 'GET':
                response = requests.get(url, params=params, headers=default_headers, timeout=REQUEST_TIMEOUT)
            else:
                response = requests.post(url, json=data, headers=default_headers, timeout=REQUEST_TIMEOUT)
            
            if response.status_code == 429:  # Rate limited
                wait_time = 2 ** attempt + 1
                logger.warning(f"Rate limited, waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            
            return response
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout on attempt {attempt + 1}/3 for {url}")
            time.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"Request error for {url}: {e}")
            time.sleep(2 ** attempt)
    
    return None

# ============================================================
# BRAZILIAN SOURCES - Enhanced
# ============================================================

def search_programathor() -> List[Dict]:
    """Search Programathor jobs API - Vagas brasileiras"""
    jobs = []
    try:
        # Try multiple search queries for better coverage
        queries = ['QA', 'Quality Assurance', 'Testes', 'Automação', 'SDET']
        for query in queries:
            url = "https://api.programathor.com.br/jobs/search"
            params = {'query': query, 'page': 1, 'per_page': 20}
            headers = {'Accept': 'application/json'}
            response = make_request(url, params=params, headers=headers)
            
            if response and response.status_code == 200:
                data = response.json()
                jobs_list = data.get('jobs', data.get('data', []))
                
                for job in jobs_list[:8]:
                    job_id = job.get('id', job.get('slug', 'unknown'))
                    jobs.append({
                        'title': job.get('title', job.get('name', 'N/A')),
                        'company': job.get('company_name', job.get('company', {}).get('name', 'N/A')),
                        'location': job.get('location', job.get('city', 'Remoto')),
                        'url': f"https://programathor.com.br/jobs/{job_id}",
                        'id': f"programathor_{job_id}",
                        'source': 'Programathor',
                        'country': '🇧🇷 Brasil'
                    })
            time.sleep(0.5)
            if len(jobs) >= 15:
                break
    except Exception as e:
        logger.error(f"Error searching Programathor: {e}")
    return jobs

def search_gupy_jobs() -> List[Dict]:
    """Search jobs from Gupy platform - Vagas brasileiras"""
    jobs = []
    try:
        queries = ['QA', 'Quality Assurance', 'Testes', 'Automação', 'SDET']
        for query in queries:
            url = "https://api.gupy.io/api/v1/jobs"
            params = {'q': query, 'limit': 20, 'offset': 0}
            headers = {'Accept': 'application/json'}
            response = make_request(url, params=params, headers=headers)
            
            if response and response.status_code == 200:
                data = response.json()
                jobs_list = data.get('data', data.get('jobs', []))
                
                for job in jobs_list[:8]:
                    job_id = job.get('id', 'unknown')
                    company_info = job.get('company', {}) if isinstance(job.get('company'), dict) else {}
                    jobs.append({
                        'title': job.get('name', job.get('title', 'N/A')),
                        'company': company_info.get('name', job.get('companyName', 'N/A')),
                        'location': job.get('city', job.get('location', 'Remoto')),
                        'url': job.get('jobUrl', job.get('url', f"https://portal.gupy.io/job/{job_id}")),
                        'id': f"gupy_{job_id}",
                        'source': 'Gupy',
                        'country': '🇧🇷 Brasil'
                    })
            time.sleep(0.5)
            if len(jobs) >= 15:
                break
    except Exception as e:
        logger.error(f"Error searching Gupy: {e}")
    return jobs

def search_trampos() -> List[Dict]:
    """Search Trampos.co - Vagas brasileiras tech"""
    jobs = []
    try:
        queries = ['QA', 'Quality Assurance', 'Testes', 'Automação']
        for query in queries:
            url = "https://api.trampos.co/v1/oportunidades"
            params = {'q': query, 'page': 1, 'per_page': 15}
            headers = {'Accept': 'application/json'}
            response = make_request(url, params=params, headers=headers)
            
            if response and response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    jobs_list = data.get('oportunidades', data.get('data', []))
                elif isinstance(data, list):
                    jobs_list = data
                else:
                    jobs_list = []
                
                for job in jobs_list[:8]:
                    job_id = job.get('id', job.get('slug', 'unknown'))
                    jobs.append({
                        'title': job.get('titulo', job.get('title', 'N/A')),
                        'company': job.get('empresa', job.get('company', {}).get('nome', 'N/A')),
                        'location': job.get('localidade', job.get('city', 'Remoto')),
                        'url': f"https://trampos.co/oportunidade/{job_id}",
                        'id': f"trampos_{job_id}",
                        'source': 'Trampos.co',
                        'country': '🇧🇷 Brasil'
                    })
            time.sleep(0.5)
            if len(jobs) >= 15:
                break
    except Exception as e:
        logger.error(f"Error searching Trampos: {e}")
    return jobs

def search_catho() -> List[Dict]:
    """Search Catho - Vagas brasileiras"""
    jobs = []
    try:
        queries = ['QA', 'Quality Assurance', 'Tester', 'Automação de Testes']
        for query in queries:
            url = "https://api.catho.com.br/v1/vagas"
            params = {'q': query, 'limit': 15}
            headers = {'Accept': 'application/json'}
            response = make_request(url, params=params, headers=headers)
            
            if response and response.status_code == 200:
                data = response.json()
                jobs_list = data.get('vagas', data.get('data', []))
                
                for job in jobs_list[:8]:
                    job_id = job.get('id', job.get('codigo', 'unknown'))
                    jobs.append({
                        'title': job.get('titulo', job.get('title', 'N/A')),
                        'company': job.get('empresa', job.get('company', {}).get('nome', 'N/A')),
                        'location': job.get('cidade', job.get('location', 'Remoto')),
                        'url': f"https://www.catho.com.br/vagas/{job_id}",
                        'id': f"catho_{job_id}",
                        'source': 'Catho',
                        'country': '🇧🇷 Brasil'
                    })
            time.sleep(0.5)
            if len(jobs) >= 15:
                break
    except Exception as e:
        logger.error(f"Error searching Catho: {e}")
    return jobs

def search_vagas() -> List[Dict]:
    """Search Vagas.com.br"""
    jobs = []
    try:
        queries = ['QA', 'Quality Assurance', 'Testes', 'Automação']
        for query in queries:
            url = "https://api.vagas.com.br/v1/vagas"
            params = {'q': query, 'limit': 15}
            headers = {'Accept': 'application/json'}
            response = make_request(url, params=params, headers=headers)
            
            if response and response.status_code == 200:
                data = response.json()
                jobs_list = data.get('vagas', data.get('data', []))
                
                for job in jobs_list[:8]:
                    job_id = job.get('id', job.get('codigo', 'unknown'))
                    jobs.append({
                        'title': job.get('titulo', job.get('title', 'N/A')),
                        'company': job.get('empresa', job.get('company', {}).get('nome', 'N/A')),
                        'location': job.get('cidade', job.get('location', 'Remoto')),
                        'url': f"https://www.vagas.com.br/vagas/{job_id}",
                        'id': f"vagas_{job_id}",
                        'source': 'Vagas.com.br',
                        'country': '🇧🇷 Brasil'
                    })
            time.sleep(0.5)
            if len(jobs) >= 15:
                break
    except Exception as e:
        logger.error(f"Error searching Vagas: {e}")
    return jobs

def search_infojobs() -> List[Dict]:
    """Search InfoJobs"""
    jobs = []
    try:
        queries = ['QA', 'Quality Assurance', 'Tester', 'Automação']
        for query in queries:
            url = "https://api.infojobs.com.br/api/2/vagas"
            params = {'q': query, 'limit': 15}
            headers = {'Accept': 'application/json'}
            response = make_request(url, params=params, headers=headers)
            
            if response and response.status_code == 200:
                data = response.json()
                jobs_list = data.get('vagas', data.get('data', []))
                
                for job in jobs_list[:8]:
                    job_id = job.get('id', job.get('codigo', 'unknown'))
                    jobs.append({
                        'title': job.get('titulo', job.get('title', 'N/A')),
                        'company': job.get('empresa', job.get('company', {}).get('nome', 'N/A')),
                        'location': job.get('cidade', job.get('location', 'Remoto')),
                        'url': f"https://www.infojobs.com.br/vaga/{job_id}",
                        'id': f"infojobs_{job_id}",
                        'source': 'InfoJobs',
                        'country': '🇧🇷 Brasil'
                    })
            time.sleep(0.5)
            if len(jobs) >= 15:
                break
    except Exception as e:
        logger.error(f"Error searching InfoJobs: {e}")
    return jobs

def search_linkedin_br() -> List[Dict]:
    """Search LinkedIn Brazil via RSS/Feed"""
    jobs = []
    try:
        # LinkedIn has public RSS feeds for job searches
        url = "https://www.linkedin.com/jobs/search/?keywords=qa&location=Brasil&f_TPR=r604800&f_WT=2"
        # Use RSS feed if available
        rss_url = "https://www.linkedin.com/jobs/search/?keywords=qa%20quality%20assurance&location=Brasil&f_WT=2&f_TPR=r604800&format=rss"
        
        headers = {'Accept': 'application/rss+xml, application/xml, text/xml'}
        response = make_request(rss_url, headers=headers)
        
        if response and response.status_code == 200:
            root = ET.fromstring(response.content)
            for item in root.findall('.//item')[:10]:
                title = item.find('title').text if item.find('title') is not None else 'N/A'
                link = item.find('link').text if item.find('link') is not None else '#'
                description = item.find('description').text if item.find('description') is not None else ''
                
                if any(keyword in title.lower() for keyword in ['qa', 'quality', 'test', 'tester', 'automation', 'sdet']):
                    company = 'Various'
                    if ' at ' in title:
                        company = title.split(' at ')[-1]
                    
                    job_id = generate_job_id(title, company)
                    jobs.append({
                        'title': title,
                        'company': company,
                        'location': 'Brasil',
                        'url': link,
                        'id': f"linkedin_br_{job_id}",
                        'source': 'LinkedIn Brasil',
                        'country': '🇧🇷 Brasil'
                    })
    except Exception as e:
        logger.error(f"Error searching LinkedIn Brasil: {e}")
    return jobs

def search_revelo() -> List[Dict]:
    """Search Revelo - Brazilian tech jobs platform"""
    jobs = []
    try:
        queries = ['qa', 'quality-assurance', 'testes', 'automacao']
        for query in queries:
            url = f"https://api.revelo.com.br/v1/jobs"
            params = {'search': query, 'limit': 15}
            headers = {'Accept': 'application/json'}
            response = make_request(url, params=params, headers=headers)
            
            if response and response.status_code == 200:
                data = response.json()
                jobs_list = data.get('jobs', data.get('data', []))
                
                for job in jobs_list[:8]:
                    job_id = job.get('id', 'unknown')
                    jobs.append({
                        'title': job.get('title', job.get('name', 'N/A')),
                        'company': job.get('company', {}).get('name', 'N/A') if isinstance(job.get('company'), dict) else job.get('company_name', 'N/A'),
                        'location': job.get('location', 'Remoto'),
                        'url': f"https://www.revelo.com.br/vaga/{job_id}",
                        'id': f"revelo_{job_id}",
                        'source': 'Revelo',
                        'country': '🇧🇷 Brasil'
                    })
            time.sleep(0.5)
            if len(jobs) >= 15:
                break
    except Exception as e:
        logger.error(f"Error searching Revelo: {e}")
    return jobs

def search_geekhunter() -> List[Dict]:
    """Search GeekHunter - Brazilian dev jobs"""
    jobs = []
    try:
        url = "https://api.geekhunter.com.br/v1/jobs"
        params = {'q': 'QA', 'limit': 15}
        headers = {'Accept': 'application/json'}
        response = make_request(url, params=params, headers=headers)
        
        if response and response.status_code == 200:
            data = response.json()
            jobs_list = data.get('jobs', data.get('data', []))
            
            for job in jobs_list[:10]:
                job_id = job.get('id', 'unknown')
                jobs.append({
                    'title': job.get('title', job.get('name', 'N/A')),
                    'company': job.get('company', {}).get('name', 'N/A') if isinstance(job.get('company'), dict) else job.get('company_name', 'N/A'),
                    'location': job.get('city', job.get('location', 'Remoto')),
                    'url': f"https://geekhunter.com.br/vaga/{job_id}",
                    'id': f"geekhunter_{job_id}",
                    'source': 'GeekHunter',
                    'country': '🇧🇷 Brasil'
                })
    except Exception as e:
        logger.error(f"Error searching GeekHunter: {e}")
    return jobs

def search_trabalha_br() -> List[Dict]:
    """Search Trabalha Brasil"""
    jobs = []
    try:
        url = "https://www.trabalhabrasil.com.br/api/v1/vagas"
        params = {'q': 'QA', 'limit': 15}
        headers = {'Accept': 'application/json'}
        response = make_request(url, params=params, headers=headers)
        
        if response and response.status_code == 200:
            data = response.json()
            jobs_list = data.get('vagas', data.get('data', []))
            
            for job in jobs_list[:10]:
                job_id = job.get('id', 'unknown')
                jobs.append({
                    'title': job.get('titulo', job.get('title', 'N/A')),
                    'company': job.get('empresa', job.get('company', {}).get('nome', 'N/A')),
                    'location': job.get('cidade', job.get('location', 'Remoto')),
                    'url': f"https://www.trabalhabrasil.com.br/vaga/{job_id}",
                    'id': f"trabalha_br_{job_id}",
                    'source': 'Trabalha Brasil',
                    'country': '🇧🇷 Brasil'
                })
    except Exception as e:
        logger.error(f"Error searching Trabalha Brasil: {e}")
    return jobs

def search_keppler() -> List[Dict]:
    """Search Keppler"""
    jobs = []
    try:
        url = "https://api.keppler.com.br/v1/vagas"
        params = {'q': 'QA', 'limit': 15}
        headers = {'Accept': 'application/json'}
        response = make_request(url, params=params, headers=headers)
        
        if response and response.status_code == 200:
            data = response.json()
            jobs_list = data.get('vagas', data.get('data', []))
            
            for job in jobs_list[:10]:
                job_id = job.get('id', 'unknown')
                jobs.append({
                    'title': job.get('titulo', job.get('title', 'N/A')),
                    'company': job.get('empresa', job.get('company', {}).get('nome', 'N/A')),
                    'location': job.get('cidade', job.get('location', 'Remoto')),
                    'url': f"https://www.keppler.com.br/vaga/{job_id}",
                    'id': f"keppler_{job_id}",
                    'source': 'Keppler',
                    'country': '🇧🇷 Brasil'
                })
    except Exception as e:
        logger.error(f"Error searching Keppler: {e}")
    return jobs

# ============================================================
# GREENHOUSE - Brazilian & Global Companies
# ============================================================

def search_greenhouse_br() -> List[Dict]:
    """Search Greenhouse for Brazilian companies"""
    jobs = []
    greenhouse_companies_br = [
        'nubank', 'stone', 'vtex', 'mercadolivre', 'creditas', 
        'bemobi', 'iqoption', 'quintoandar', 'ebank', 'c6bank',
        'btg', 'inter', 'xinvest', 'modalmais', 'warren',
        'ifood', 'loggi', '99', 'getninjas', 'doghero',
        'eby', 'contabilizei', 'makes', 'rockcontent', 'resultadosdigitais',
        'pipefy', 'RD', 'samba', 'take', 'vindi',
        'ebanz', 'neon', 'will', 'cora', 'inter',
    ]
    
    try:
        for company in greenhouse_companies_br[:8]:
            url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
            headers = {'Accept': 'application/json'}
            response = make_request(url, headers=headers)
            
            if response and response.status_code == 200:
                data = response.json()
                jobs_list = data.get('jobs', [])
                
                for job in jobs_list:
                    title = job.get('title', '').lower()
                    if any(keyword in title for keyword in ['qa', 'quality', 'test', 'tester', 'automation', 'sdet']):
                        job_id = generate_job_id(job.get('title', ''), company)
                        jobs.append({
                            'title': job.get('title', 'N/A'),
                            'company': company.capitalize(),
                            'location': job.get('location', {}).get('name', 'Remoto') if isinstance(job.get('location'), dict) else 'Remoto',
                            'url': job.get('absolute_url', '#'),
                            'id': f"greenhouse_br_{job_id}",
                            'source': 'Greenhouse (BR)',
                            'country': '🇧🇷 Brasil'
                        })
                        if len(jobs) >= 8:
                            break
            time.sleep(0.3)
            if len(jobs) >= 8:
                break
    except Exception as e:
        logger.error(f"Error searching Greenhouse BR: {e}")
    return jobs

def search_greenhouse_global() -> List[Dict]:
    """Search Greenhouse for global companies"""
    jobs = []
    greenhouse_companies_global = [
        'stripe', 'notion', 'linear', 'vercel', 'railway', 
        'planetscale', 'supabase', 'prisma', 'temporal', 'turso',
        'netlify', 'cloudflare', 'datadog', 'hashicorp', 'mongodb',
        'figma', 'miro', 'airtable', 'webflow', 'zapier',
        'github', 'gitlab', 'atlassian', 'shopify', 'twilio',
        'coinbase', 'robinhood', 'plaid', 'stripe', 'square',
        'openai', 'anthropic', 'cohere', 'huggingface', 'langchain',
    ]
    
    try:
        for company in greenhouse_companies_global[:6]:
            url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
            headers = {'Accept': 'application/json'}
            response = make_request(url, headers=headers)
            
            if response and response.status_code == 200:
                data = response.json()
                jobs_list = data.get('jobs', [])
                
                for job in jobs_list:
                    title = job.get('title', '').lower()
                    if any(keyword in title for keyword in ['qa', 'quality', 'test', 'tester', 'automation', 'sdet']):
                        job_id = generate_job_id(job.get('title', ''), company)
                        jobs.append({
                            'title': job.get('title', 'N/A'),
                            'company': company.capitalize(),
                            'location': job.get('location', {}).get('name', 'Remote') if isinstance(job.get('location'), dict) else 'Remote',
                            'url': job.get('absolute_url', '#'),
                            'id': f"greenhouse_int_{job_id}",
                            'source': 'Greenhouse (Global)',
                            'country': '🌎 Internacional'
                        })
                        if len(jobs) >= 6:
                            break
            time.sleep(0.3)
            if len(jobs) >= 6:
                break
    except Exception as e:
        logger.error(f"Error searching Greenhouse Global: {e}")
    return jobs

# ============================================================
# INTERNATIONAL REMOTE SOURCES - Enhanced
# ============================================================

def search_remoteok() -> List[Dict]:
    """Search Remote OK for remote jobs"""
    jobs = []
    try:
        url = "https://remoteok.com/api"
        headers = {'Accept': 'application/json'}
        response = make_request(url, headers=headers)
        if response and response.status_code == 200:
            data = response.json()
            for job in data[1:]:  # First item is metadata
                if isinstance(job, dict):
                    title = job.get('position', '').lower()
                    tags = [tag.lower() for tag in job.get('tags', [])] if job.get('tags') else []
                    qa_keywords = ['qa', 'quality', 'test', 'tester', 'testing', 'assurance', 'sdet', 'automation']
                    if any(keyword in title for keyword in qa_keywords) or any(keyword in tags for keyword in qa_keywords):
                        jobs.append({
                            'title': job.get('position', 'N/A'),
                            'company': job.get('company', 'N/A'),
                            'location': job.get('location', 'Remote'),
                            'url': f"https://remoteok.com/remote-jobs/{job.get('id')}",
                            'id': f"remoteok_{job.get('id')}",
                            'source': 'RemoteOK',
                            'country': '🌎 Internacional (Remote)'
                        })
                        if len(jobs) >= 10:
                            break
    except Exception as e:
        logger.error(f"Error searching RemoteOK: {e}")
    return jobs

def search_remotive() -> List[Dict]:
    """Search Remotive.io API"""
    jobs = []
    try:
        url = "https://remotive.com/api/remote-jobs?category=qa"
        headers = {'Accept': 'application/json'}
        response = make_request(url, headers=headers)
        
        if response and response.status_code == 200:
            data = response.json()
            for job in data.get('jobs', [])[:12]:
                title = job.get('title', 'N/A')
                company = job.get('company_name', 'N/A')
                job_id = generate_job_id(title, company)
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': job.get('candidate_required_location', 'Remote'),
                    'url': job.get('url', '#'),
                    'id': f"remotive_{job_id}",
                    'source': 'Remotive',
                    'country': '🌎 Internacional (Remote)'
                })
    except Exception as e:
        logger.error(f"Error searching Remotive: {e}")
    return jobs

def search_weworkremotely() -> List[Dict]:
    """Search We Work Remotely via RSS feed"""
    jobs = []
    try:
        urls = [
            "https://weworkremotely.com/categories/remote-qa-jobs.rss",
            "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
            "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        ]
        for url in urls:
            headers = {'Accept': 'application/rss+xml'}
            response = make_request(url, headers=headers)
            
            if response and response.status_code == 200:
                root = ET.fromstring(response.content)
                for item in root.findall('.//item')[:8]:
                    title = item.find('title').text if item.find('title') is not None else 'N/A'
                    link = item.find('link').text if item.find('link') is not None else '#'
                    description = item.find('description').text if item.find('description') is not None else ''
                    
                    if any(keyword in title.lower() for keyword in ['qa', 'quality', 'test', 'tester', 'automation', 'sdet', 'playwright', 'cypress', 'selenium']):
                        company = 'Various'
                        if ' at ' in title:
                            company = title.split(' at ')[-1]
                        
                        job_id = generate_job_id(title, company)
                        jobs.append({
                            'title': title,
                            'company': company,
                            'location': 'Remote',
                            'url': link,
                            'id': f"weworkremotely_{job_id}",
                            'source': 'WeWorkRemotely',
                            'country': '🌎 Internacional (Remote)'
                        })
    except Exception as e:
        logger.error(f"Error searching WeWorkRemotely: {e}")
    return jobs

def search_landing_jobs() -> List[Dict]:
    """Search Landing.jobs - European/Remote jobs"""
    jobs = []
    try:
        queries = ['qa', 'quality assurance', 'tester', 'sdet', 'test automation']
        for query in queries:
            url = "https://landing.jobs/api/v1/jobs"
            params = {'q': query, 'remote': 'true', 'limit': 15}
            headers = {'Accept': 'application/json'}
            response = make_request(url, params=params, headers=headers)
            
            if response and response.status_code == 200:
                data = response.json()
                jobs_list = data.get('jobs', data.get('data', []))
                
                for job in jobs_list[:8]:
                    if not isinstance(job, dict):
                        continue
                    
                    title = job.get('title', job.get('name', 'N/A'))
                    company_data = job.get('company', {})
                    company = company_data.get('name', 'N/A') if isinstance(company_data, dict) else job.get('company_name', 'N/A')
                    job_id = generate_job_id(title, str(company))
                    
                    jobs.append({
                        'title': title,
                        'company': company,
                        'location': job.get('remote', 'Remote'),
                        'url': job.get('url', job.get('link', '#')),
                        'id': f"landingjobs_{job_id}",
                        'source': 'Landing.jobs',
                        'country': '🌎 Internacional'
                    })
            time.sleep(0.5)
            if len(jobs) >= 15:
                break
    except Exception as e:
        logger.error(f"Error searching Landing.jobs: {e}")
    return jobs

def search_wellfound() -> List[Dict]:
    """Search Wellfound (AngelList) - startup jobs"""
    jobs = []
    try:
        queries = ['qa', 'quality assurance', 'test engineer', 'sdet', 'test automation']
        for query in queries:
            url = "https://wellfound.com/api/v1/jobs"
            params = {'query': query, 'remote': 'true', 'limit': 10}
            headers = {'Accept': 'application/json'}
            response = make_request(url, params=params, headers=headers)
            
            if response and response.status_code == 200:
                data = response.json()
                jobs_list = data.get('jobs', data.get('data', []))
                
                for job in jobs_list[:6]:
                    title = job.get('title', 'N/A')
                    company = job.get('startup', {}).get('name', 'N/A')
                    job_id = generate_job_id(title, company)
                    jobs.append({
                        'title': title,
                        'company': company,
                        'location': job.get('location', 'Remote'),
                        'url': f"https://wellfound.com/jobs/{job.get('id')}",
                        'id': f"wellfound_{job_id}",
                        'source': 'Wellfound',
                        'country': '🌎 Internacional'
                    })
            time.sleep(0.5)
            if len(jobs) >= 10:
                break
    except Exception as e:
        logger.error(f"Error searching Wellfound: {e}")
    return jobs

def search_ycombinator() -> List[Dict]:
    """Search Y Combinator jobs via HTML parsing"""
    jobs = []
    try:
        url = "https://www.ycombinator.com/jobs/search"
        params = {'q': 'qa quality assurance tester automation', 'remote': 'true'}
        headers = {'Accept': 'text/html'}
        response = make_request(url, params=params, headers=headers)
        
        if response and response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            job_cards = soup.find_all('div', class_='job-card')
            
            for card in job_cards[:8]:
                title_elem = card.find('h3') or card.find('h4')
                company_elem = card.find('span', class_='company')
                link_elem = card.find('a', href=True)
                
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    if any(kw in title.lower() for kw in ['qa', 'quality', 'test', 'tester', 'sdet', 'automation']):
                        company = company_elem.get_text(strip=True) if company_elem else 'YC Startup'
                        link = link_elem['href'] if link_elem else '#'
                        if link.startswith('/'):
                            link = 'https://www.ycombinator.com' + link
                        
                        job_id = generate_job_id(title, company)
                        jobs.append({
                            'title': title,
                            'company': company,
                            'location': 'Remote',
                            'url': link,
                            'id': f"ycombinator_{job_id}",
                            'source': 'Y Combinator',
                            'country': '🌎 Internacional'
                        })
    except Exception as e:
        logger.error(f"Error searching YCombinator: {e}")
    return jobs

def search_otg() -> List[Dict]:
    """Search OTG (On The Go) - remote jobs"""
    jobs = []
    try:
        url = "https://onthegohq.com/api/v1/jobs"
        params = {'category': 'qa', 'remote': 'true'}
        headers = {'Accept': 'application/json'}
        response = make_request(url, params=params, headers=headers)
        
        if response and response.status_code == 200:
            data = response.json()
            for job in data.get('jobs', [])[:8]:
                title = job.get('title', 'N/A')
                company = job.get('company', 'N/A')
                job_id = generate_job_id(title, company)
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': job.get('location', 'Remote'),
                    'url': job.get('url', '#'),
                    'id': f"otg_{job_id}",
                    'source': 'OTG',
                    'country': '🌎 Internacional'
                })
    except Exception as e:
        logger.error(f"Error searching OTG: {e}")
    return jobs

def search_jobspresso() -> List[Dict]:
    """Search Jobspresso - curated remote jobs"""
    jobs = []
    try:
        url = "https://jobspresso.co/api/jobs"
        params = {'category': 'qa-testing', 'remote': 'true'}
        headers = {'Accept': 'application/json'}
        response = make_request(url, params=params, headers=headers)
        
        if response and response.status_code == 200:
            data = response.json()
            for job in data.get('jobs', [])[:8]:
                title = job.get('title', 'N/A')
                company = job.get('company', 'N/A')
                job_id = generate_job_id(title, company)
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': job.get('location', 'Remote'),
                    'url': job.get('url', '#'),
                    'id': f"jobspresso_{job_id}",
                    'source': 'Jobspresso',
                    'country': '🌎 Internacional'
                })
    except Exception as e:
        logger.error(f"Error searching Jobspresso: {e}")
    return jobs

def search_remote_co() -> List[Dict]:
    """Search Remote.co - curated remote jobs via HTML"""
    jobs = []
    try:
        url = "https://remote.co/remote-jobs/search"
        params = {'search': 'qa'}
        headers = {'Accept': 'text/html'}
        response = make_request(url, params=params, headers=headers)
        
        if response and response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            job_listings = soup.find_all('div', class_='job_listing')
            
            for listing in job_listings[:8]:
                title_elem = listing.find('h3') or listing.find('h2')
                company_elem = listing.find('span', class_='company')
                link_elem = listing.find('a', href=True)
                
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    if any(kw in title.lower() for kw in ['qa', 'quality', 'test', 'tester', 'sdet', 'automation']):
                        company = company_elem.get_text(strip=True) if company_elem else 'Remote Company'
                        link = link_elem['href'] if link_elem else '#'
                        if link.startswith('/'):
                            link = 'https://remote.co' + link
                        
                        job_id = generate_job_id(title, company)
                        jobs.append({
                            'title': title,
                            'company': company,
                            'location': 'Remote',
                            'url': link,
                            'id': f"remote_co_{job_id}",
                            'source': 'Remote.co',
                            'country': '🌎 Internacional (Remote)'
                        })
    except Exception as e:
        logger.error(f"Error searching Remote.co: {e}")
    return jobs

def search_builtin() -> List[Dict]:
    """Search BuiltIn - tech jobs"""
    jobs = []
    try:
        url = "https://api.builtin.com/v1/jobs"
        params = {'search': 'qa', 'remote': 'true', 'limit': 15}
        headers = {'Accept': 'application/json'}
        response = make_request(url, params=params, headers=headers)
        
        if response and response.status_code == 200:
            data = response.json()
            for job in data.get('jobs', data.get('data', []))[:10]:
                title = job.get('title', 'N/A')
                company = job.get('company', {}).get('name', 'N/A') if isinstance(job.get('company'), dict) else job.get('company_name', 'N/A')
                job_id = generate_job_id(title, company)
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': job.get('location', 'Remote'),
                    'url': job.get('url', f"https://builtin.com/jobs/{job_id}"),
                    'id': f"builtin_{job_id}",
                    'source': 'BuiltIn',
                    'country': '🌎 Internacional (Remote)'
                })
    except Exception as e:
        logger.error(f"Error searching BuiltIn: {e}")
    return jobs

def search_dice() -> List[Dict]:
    """Search Dice - tech jobs"""
    jobs = []
    try:
        url = "https://api.dice.com/v1/jobs"
        params = {'text': 'qa automation', 'remote': 'true', 'page': 1, 'size': 15}
        headers = {'Accept': 'application/json'}
        response = make_request(url, params=params, headers=headers)
        
        if response and response.status_code == 200:
            data = response.json()
            for job in data.get('data', [])[:10]:
                title = job.get('title', 'N/A')
                company = job.get('company', {}).get('name', 'N/A') if isinstance(job.get('company'), dict) else job.get('companyName', 'N/A')
                job_id = generate_job_id(title, company)
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': job.get('location', 'Remote'),
                    'url': job.get('detailsUrl', f"https://www.dice.com/jobs/detail/{job_id}"),
                    'id': f"dice_{job_id}",
                    'source': 'Dice',
                    'country': '🌎 Internacional'
                })
    except Exception as e:
        logger.error(f"Error searching Dice: {e}")
    return jobs

def search_otta() -> List[Dict]:
    """Search Otta - modern job board"""
    jobs = []
    try:
        url = "https://api.otta.com/v1/jobs"
        params = {'query': 'qa', 'remote': 'true', 'limit': 15}
        headers = {'Accept': 'application/json'}
        response = make_request(url, params=params, headers=headers)
        
        if response and response.status_code == 200:
            data = response.json()
            for job in data.get('jobs', data.get('data', []))[:10]:
                title = job.get('title', 'N/A')
                company = job.get('company', {}).get('name', 'N/A') if isinstance(job.get('company'), dict) else job.get('companyName', 'N/A')
                job_id = generate_job_id(title, company)
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': job.get('location', 'Remote'),
                    'url': f"https://otta.com/jobs/{job_id}",
                    'id': f"otta_{job_id}",
                    'source': 'Otta',
                    'country': '🌎 Internacional (Remote)'
                })
    except Exception as e:
        logger.error(f"Error searching Otta: {e}")
    return jobs

def search_arc_dev() -> List[Dict]:
    """Search Arc.dev - remote developer jobs"""
    jobs = []
    try:
        url = "https://arc.dev/api/v1/jobs"
        params = {'role': 'qa', 'remote': 'true', 'limit': 10}
        headers = {'Accept': 'application/json'}
        response = make_request(url, params=params, headers=headers)
        
        if response and response.status_code == 200:
            data = response.json()
            for job in data.get('jobs', [])[:8]:
                title = job.get('title', 'N/A')
                company = job.get('company', {}).get('name', 'N/A')
                job_id = generate_job_id(title, company)
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': job.get('location', 'Remote'),
                    'url': f"https://arc.dev/jobs/{job_id}",
                    'id': f"arc_dev_{job_id}",
                    'source': 'Arc.dev',
                    'country': '🌎 Internacional (Remote)'
                })
    except Exception as e:
        logger.error(f"Error searching Arc.dev: {e}")
    return jobs

def search_himalayas() -> List[Dict]:
    """Search Himalayas - remote jobs"""
    jobs = []
    try:
        url = "https://himalayas.app/api/v1/jobs"
        params = {'search': 'qa', 'remote': 'true', 'limit': 15}
        headers = {'Accept': 'application/json'}
        response = make_request(url, params=params, headers=headers)
        
        if response and response.status_code == 200:
            data = response.json()
            for job in data.get('jobs', [])[:10]:
                title = job.get('title', 'N/A')
                company = job.get('company', {}).get('name', 'N/A')
                job_id = generate_job_id(title, company)
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': job.get('location', 'Remote'),
                    'url': f"https://himalayas.app/jobs/{job_id}",
                    'id': f"himalayas_{job_id}",
                    'source': 'Himalayas',
                    'country': '🌎 Internacional (Remote)'
                })
    except Exception as e:
        logger.error(f"Error searching Himalayas: {e}")
    return jobs

def search_remote_rocketship() -> List[Dict]:
    """Search Remote Rocketship"""
    jobs = []
    try:
        url = "https://api.remoterocketship.com/v1/jobs"
        params = {'search': 'qa', 'limit': 15}
        headers = {'Accept': 'application/json'}
        response = make_request(url, params=params, headers=headers)
        
        if response and response.status_code == 200:
            data = response.json()
            for job in data.get('jobs', [])[:10]:
                title = job.get('title', 'N/A')
                company = job.get('company', 'N/A')
                job_id = generate_job_id(title, company)
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': job.get('location', 'Remote'),
                    'url': job.get('url', f"https://remoterocketship.com/jobs/{job_id}"),
                    'id': f"remote_rocketship_{job_id}",
                    'source': 'Remote Rocketship',
                    'country': '🌎 Internacional (Remote)'
                })
    except Exception as e:
        logger.error(f"Error searching Remote Rocketship: {e}")
    return jobs

def search_github_jobs() -> List[Dict]:
    """Search GitHub Jobs via search API"""
    jobs = []
    try:
        queries = [
            '(qa OR "quality assurance" OR tester OR sdet) in:title label:job,hiring',
            '(automation OR "test engineer") in:title label:job,hiring',
        ]
        
        for query in queries:
            url = "https://api.github.com/search/issues"
            params = {
                'q': query,
                'sort': 'created',
                'order': 'desc',
                'per_page': 15
            }
            headers = {'Accept': 'application/vnd.github+json'}
            response = make_request(url, params=params, headers=headers)
            
            if response and response.status_code == 200:
                data = response.json()
                for item in data.get('items', [])[:8]:
                    title = item.get('title', 'N/A')
                    if any(kw in title.lower() for kw in ['qa', 'quality', 'test', 'tester', 'sdet', 'automation']):
                        job_id = generate_job_id(title, 'GitHub')
                        jobs.append({
                            'title': title,
                            'company': item.get('user', {}).get('login', 'GitHub Community'),
                            'location': 'Remote',
                            'url': item.get('html_url', '#'),
                            'id': f"github_{job_id}",
                            'source': 'GitHub Jobs',
                            'country': '🌎 Internacional'
                        })
            time.sleep(1)  # GitHub API rate limit
    except Exception as e:
        logger.error(f"Error searching GitHub Jobs: {e}")
    return jobs

# ============================================================
# RSS/FEED SOURCES - Enhanced
# ============================================================

def search_stackoverflow_rss() -> List[Dict]:
    """Search Stack Overflow Jobs RSS"""
    jobs = []
    try:
        queries = [
            'qa+quality+assurance+tester+automation+sdet',
            'playwright+cypress+selenium',
            'test+automation+engineer',
        ]
        
        for query in queries:
            url = f"https://stackoverflow.com/jobs/feed?q={query}"
            headers = {'Accept': 'application/rss+xml'}
            response = make_request(url, headers=headers)
            
            if response and response.status_code == 200:
                root = ET.fromstring(response.content)
                for item in root.findall('.//item')[:8]:
                    title = item.find('title').text if item.find('title') is not None else 'N/A'
                    link = item.find('link').text if item.find('link') is not None else '#'
                    
                    if any(keyword in title.lower() for keyword in ['qa', 'quality', 'test', 'tester', 'automation', 'sdet', 'playwright', 'cypress', 'selenium']):
                        company = 'Various'
                        if ' at ' in title:
                            company = title.split(' at ')[-1]
                        
                        job_id = generate_job_id(title, company)
                        jobs.append({
                            'title': title,
                            'company': company,
                            'location': 'Remote',
                            'url': link,
                            'id': f"stackoverflow_{job_id}",
                            'source': 'Stack Overflow',
                            'country': '🌎 Internacional'
                        })
    except Exception as e:
        logger.error(f"Error searching Stack Overflow RSS: {e}")
    return jobs

def search_linkedin_rss() -> List[Dict]:
    """Search LinkedIn Jobs via RSS (public feeds)"""
    jobs = []
    try:
        # LinkedIn has public RSS for some searches
        url = "https://www.linkedin.com/jobs/search/?keywords=qa&location=Remote&f_TPR=r604800&f_WT=2&format=rss"
        headers = {'Accept': 'application/rss+xml'}
        response = make_request(url, headers=headers)
        
        if response and response.status_code == 200:
            root = ET.fromstring(response.content)
            for item in root.findall('.//item')[:10]:
                title = item.find('title').text if item.find('title') is not None else 'N/A'
                link = item.find('link').text if item.find('link') is not None else '#'
                
                if any(keyword in title.lower() for keyword in ['qa', 'quality', 'test', 'tester', 'automation', 'sdet']):
                    company = 'Various'
                    if ' at ' in title:
                        company = title.split(' at ')[-1]
                    
                    job_id = generate_job_id(title, company)
                    jobs.append({
                        'title': title,
                        'company': company,
                        'location': 'Remote',
                        'url': link,
                        'id': f"linkedin_{job_id}",
                        'source': 'LinkedIn',
                        'country': '🌎 Internacional'
                    })
    except Exception as e:
        logger.error(f"Error searching LinkedIn RSS: {e}")
    return jobs

def search_indeed_rss() -> List[Dict]:
    """Search Indeed RSS"""
    jobs = []
    try:
        queries = ['qa+quality+tester', 'test+automation+engineer', 'sdet']
        
        for query in queries:
            url = f"https://rss.indeed.com/rss?q={query}&l=Remote"
            headers = {'Accept': 'application/rss+xml'}
            response = make_request(url, headers=headers)
            
            if response and response.status_code == 200:
                root = ET.fromstring(response.content)
                for item in root.findall('.//item')[:8]:
                    title = item.find('title').text if item.find('title') is not None else 'N/A'
                    link = item.find('link').text if item.find('link') is not None else '#'
                    
                    if any(keyword in title.lower() for keyword in ['qa', 'quality', 'test', 'tester', 'automation', 'sdet']):
                        company = 'Various'
                        if ' at ' in title:
                            company = title.split(' at ')[-1]
                        
                        job_id = generate_job_id(title, company)
                        jobs.append({
                            'title': title,
                            'company': company,
                            'location': 'Remote',
                            'url': link,
                            'id': f"indeed_{job_id}",
                            'source': 'Indeed',
                            'country': '🌎 Internacional'
                        })
    except Exception as e:
        logger.error(f"Error searching Indeed RSS: {e}")
    return jobs

def search_glassdoor_rss() -> List[Dict]:
    """Search Glassdoor RSS"""
    jobs = []
    try:
        url = "https://www.glassdoor.com/Job/rss.htm?keyword=qa&locationType=R&location=Remote"
        headers = {'Accept': 'application/rss+xml'}
        response = make_request(url, headers=headers)
        
        if response and response.status_code == 200:
            root = ET.fromstring(response.content)
            for item in root.findall('.//item')[:8]:
                title = item.find('title').text if item.find('title') is not None else 'N/A'
                link = item.find('link').text if item.find('link') is not None else '#'
                
                if any(keyword in title.lower() for keyword in ['qa', 'quality', 'test', 'tester', 'automation', 'sdet']):
                    company = 'Various'
                    if ' at ' in title:
                        company = title.split(' at ')[-1]
                    
                    job_id = generate_job_id(title, company)
                    jobs.append({
                        'title': title,
                        'company': company,
                        'location': 'Remote',
                        'url': link,
                        'id': f"glassdoor_{job_id}",
                        'source': 'Glassdoor',
                        'country': '🌎 Internacional'
                    })
    except Exception as e:
        logger.error(f"Error searching Glassdoor RSS: {e}")
    return jobs

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def load_posted_jobs() -> Set[str]:
    """Load previously posted job IDs to avoid duplicates"""
    try:
        if os.path.exists(POSTED_JOBS_FILE):
            with open(POSTED_JOBS_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
    except Exception as e:
        logger.warning(f"Error loading posted jobs: {e}")
    return set()

def save_posted_jobs(job_ids: Set[str]):
    """Save posted job IDs"""
    try:
        with open(POSTED_JOBS_FILE, 'w') as f:
            json.dump(list(job_ids), f)
    except Exception as e:
        logger.error(f"Error saving posted jobs: {e}")

def generate_job_id(title: str, company: str) -> str:
    """Generate unique ID for a job based on title and company"""
    unique_string = f"{title.lower().strip()}_{company.lower().strip()}"
    return hashlib.md5(unique_string.encode()).hexdigest()[:16]

# ============================================================
# MAIN SEARCH ORCHESTRATOR
# ============================================================

def search_all_sources() -> List[Dict]:
    """Search all enabled sources and return combined results"""
    all_jobs = []
    
    # Define all sources with their search functions
    sources = [
        # Brazilian Sources (prioritized)
        ('Programathor (BR)', search_programathor),
        ('Gupy (BR)', search_gupy_jobs),
        ('Trampos (BR)', search_trampos),
        ('Catho (BR)', search_catho),
        ('Vagas.com.br (BR)', search_vagas),
        ('InfoJobs (BR)', search_infojobs),
        ('LinkedIn Brasil (BR)', search_linkedin_br),
        ('Revelo (BR)', search_revelo),
        ('GeekHunter (BR)', search_geekhunter),
        ('Trabalha Brasil (BR)', search_trabalha_br),
        ('Keppler (BR)', search_keppler),
        ('Greenhouse Brasil (BR)', search_greenhouse_br),
        
        # International Remote Sources
        ('RemoteOK (INT)', search_remoteok),
        ('Remotive (INT)', search_remotive),
        ('WeWorkRemotely (INT)', search_weworkremotely),
        ('Landing.jobs (INT)', search_landing_jobs),
        ('Wellfound (INT)', search_wellfound),
        ('Y Combinator (INT)', search_ycombinator),
        ('OTG (INT)', search_otg),
        ('Jobspresso (INT)', search_jobspresso),
        ('Remote.co (INT)', search_remote_co),
        ('BuiltIn (INT)', search_builtin),
        ('Dice (INT)', search_dice),
        ('Otta (INT)', search_otta),
        ('Arc.dev (INT)', search_arc_dev),
        ('Himalayas (INT)', search_himalayas),
        ('Remote Rocketship (INT)', search_remote_rocketship),
        ('Greenhouse Global (INT)', search_greenhouse_global),
        
        # GitHub/Stack Overflow
        ('GitHub Jobs (INT)', search_github_jobs),
        ('Stack Overflow RSS (INT)', search_stackoverflow_rss),
        
        # RSS Feeds
        ('Stack Overflow RSS (INT)', search_stackoverflow_rss),
        ('Indeed RSS (INT)', search_indeed_rss),
        ('LinkedIn RSS (INT)', search_linkedin_rss),
        ('Glassdoor RSS (INT)', search_glassdoor_rss),
    ]
    
    for source_name, search_func in sources:
        logger.info(f"Searching {source_name}...")
        try:
            found = search_func()
            logger.info(f"Found {len(found)} jobs from {source_name}")
            all_jobs.extend(found)
        except Exception as e:
            logger.error(f"Error in {source_name}: {e}")
    
    return all_jobs

# ============================================================
# DISCORD INTEGRATION
# ============================================================

def create_discord_embed(job: Dict) -> Dict:
    """Create a rich embed for Discord message"""
    title_lower = job['title'].lower()
    seniority_emoji = ""
    if any(word in title_lower for word in ['jr', 'junior', 'júnior', 'trainee', 'estagio', 'estágio']):
        seniority_emoji = "🌱 "
    elif any(word in title_lower for word in ['pleno', 'mid', 'middle']):
        seniority_emoji = "🚀 "
    elif any(word in title_lower for word in ['senior', 'sênior', 'sr', 'lead', 'principal', 'staff']):
        seniority_emoji = "⭐ "
    
    work_type_emoji = ""
    location_lower = job['location'].lower()
    if any(word in location_lower for word in ['remoto', 'remote', 'anywhere']):
        work_type_emoji = "🏠"
    elif any(word in location_lower for word in ['híbrido', 'hybrid']):
        work_type_emoji = "🔄"
    else:
        work_type_emoji = "🏢"
    
    is_br = '🇧🇷' in job.get('country', '')
    embed_color = 0x00FFFF if is_br else 0xFF10F0
    
    description_lines = [
        f"### 🏢 {job['company']}",
        "",
        f"{work_type_emoji} **Local:** {job['location']}",
    ]
    
    if job.get('salary'):
        description_lines.append(f"💰 **Salário:** {job['salary']}")
    
    description = "\n".join(description_lines)
    
    embed = {
        "title": f"{seniority_emoji}{job.get('country', '🌍')} {job['title']}",
        "description": description,
        "url": job['url'],
        "color": 0x00FFFF if is_br else 0xFF10F0,
        "footer": {
            "text": f"📡 {job['source']} • Postado às {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        },
        "fields": [{
            "name": "🎯 Como Candidatar",
            "value": f"**[👉 Clique aqui para ver a vaga completa]({job['url']})**",
            "inline": False
        }]
    }
    return embed

def send_summary_to_discord(new_count: int, total_found: int):
    """Send execution summary to Discord"""
    if not DISCORD_WEBHOOK_URL or new_count == 0:
        return
    
    try:
        if new_count >= 10:
            emoji = "🎉"
            message = "Muitas oportunidades hoje!"
        elif new_count >= 5:
            emoji = "✨"
            message = "Várias vagas encontradas!"
        elif new_count >= 1:
            emoji = "👍"
            message = "Novas oportunidades disponíveis!"
        else:
            return
        
        embed = {
            "title": f"{emoji} Resumo da Busca",
            "description": message,
            "color": 0x36393F,
            "fields": [
                {"name": "📊 Vagas Encontradas", "value": f"`{total_found}` vagas totais", "inline": True},
                {"name": "🆕 Novas Vagas", "value": f"`{new_count}` postadas agora", "inline": True},
                {"name": "⏰ Próxima Busca", "value": "Em ~30 minutos", "inline": True}
            ],
            "footer": {"text": "🤖 Bot automático rodando via GitHub Actions"},
            "timestamp": datetime.utcnow().isoformat()
        }
        requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=10)
    except Exception as e:
        logger.error(f"Error sending summary: {e}")

def send_to_discord(jobs: List[Dict], posted_jobs: Set[str]) -> int:
    """Send new jobs to Discord webhook"""
    if not DISCORD_WEBHOOK_URL:
        logger.error("Error: DISCORD_WEBHOOK_URL not set")
        return 0
    
    new_jobs_count = 0
    
    for job in jobs:
        job_id = job['id']
        
        # Skip if already posted
        if job_id in posted_jobs:
            continue
        
        embed = create_discord_embed(job)
        payload = {"embeds": [embed]}
        
        try:
            response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            if response.status_code == 204:
                logger.info(f"✓ Posted: {job['title']}")
                posted_jobs.add(job_id)
                new_jobs_count += 1
                time.sleep(0.8)  # Rate limiting
            else:
                logger.error(f"✗ Failed to post {job['title']}: {response.status_code}")
        except Exception as e:
            logger.error(f"Error sending to Discord: {e}")
    
    return new_jobs_count

def main():
    """Main function to search and post jobs"""
    logger.info(f"🔍 Starting QA job search at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Load previously posted jobs
    posted_jobs = load_posted_jobs()
    logger.info(f"📝 Tracking {len(posted_jobs)} previously posted jobs")
    
    # Collect jobs from all sources
    all_jobs = search_all_sources()
    
    logger.info(f"📊 Found {len(all_jobs)} total jobs from all sources")
    
    # Filter for QA-related keywords
    qa_keywords = [
        'qa', 'quality', 'qualidade', 'tester', 'teste', 'test', 
        'testing', 'assurance', 'sdet', 'automation', 'automação',
        'playwright', 'cypress', 'selenium', 'appium', 'jest',
        'pytest', 'robot framework', 'cucumber', 'postman'
    ]
    filtered_jobs = [
        job for job in all_jobs 
        if any(keyword in job['title'].lower() for keyword in qa_keywords)
    ]
    
    logger.info(f"🎯 Filtered to {len(filtered_jobs)} QA-related jobs")
    
    # Remove duplicates based on ID
    unique_jobs = {}
    for job in filtered_jobs:
        if job['id'] not in unique_jobs:
            unique_jobs[job['id']] = job
    
    filtered_jobs = list(unique_jobs.values())
    logger.info(f"🔄 After deduplication: {len(filtered_jobs)} unique jobs")
    
    # Send to Discord
    new_count = send_to_discord(filtered_jobs, posted_jobs)
    
    # Send summary
    send_summary_to_discord(new_count, len(filtered_jobs))
    
    # Save updated posted jobs
    save_posted_jobs(posted_jobs)
    
    logger.info(f"✅ Posted {new_count} new jobs")
    logger.info(f"📝 Total tracked jobs: {len(posted_jobs)}")
    
    # Clean up old jobs (keep only last 1000)
    if len(posted_jobs) > 1000:
        posted_jobs_list = list(posted_jobs)
        posted_jobs = set(posted_jobs_list[-1000:])
        save_posted_jobs(posted_jobs)
        logger.info(f"🧹 Cleaned up old jobs, now tracking {len(posted_jobs)}")

if __name__ == "__main__":
    main()