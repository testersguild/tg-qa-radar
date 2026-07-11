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
# JOB SOURCES - Add/remove sources here
# ============================================================
ENABLED_SOURCES = [
    # Brazilian sources
    'programathor',
    'gupy',
    'trampos',
    'catho',
    'vagas',
    'infojobs',
    'greenhouse',
    
    # International remote sources
    'remoteok',
    'remotive',
    'weworkremotely',
    'stackoverflow',
    'github',
    'landing_jobs',
    'wellfound',
    'ycombinator',
    'otg',
    'jobspresso',
    'remote_co',
    
    # RSS/Feed sources
    'stackoverflow_rss',
    'linkedin_rss',
    'indeed_rss',
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

# ============================================================
# BRAZILIAN SOURCES
# ============================================================

def search_programathor() -> List[Dict]:
    """Search Programathor jobs API - Vagas brasileiras"""
    jobs = []
    try:
        url = "https://api.programathor.com.br/jobs/search"
        params = {'query': 'QA', 'page': 1, 'per_page': 20}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)', 'Accept': 'application/json'}
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            jobs_list = data.get('jobs', data.get('data', []))
            
            for job in jobs_list[:12]:
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
        else:
            logger.warning(f"Programathor returned status: {response.status_code}")
    except Exception as e:
        logger.error(f"Error searching Programathor: {e}")
    return jobs

def search_gupy_jobs() -> List[Dict]:
    """Search jobs from Gupy platform - Vagas brasileiras"""
    jobs = []
    try:
        url = "https://api.gupy.io/api/v1/jobs"
        params = {'q': 'QA', 'limit': 20, 'offset': 0}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)', 'Accept': 'application/json'}
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            jobs_list = data.get('data', data.get('jobs', []))
            
            for job in jobs_list[:10]:
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
        else:
            logger.warning(f"Gupy returned status: {response.status_code}")
    except Exception as e:
        logger.error(f"Error searching Gupy: {e}")
    return jobs

def search_trampos() -> List[Dict]:
    """Search Trampos.co - Vagas brasileiras tech"""
    jobs = []
    try:
        # Trampos API search endpoint
        url = "https://api.trampos.co/v1/oportunidades"
        params = {'q': 'QA', 'page': 1, 'per_page': 15}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)', 'Accept': 'application/json'}
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            # Handle different response formats
            if isinstance(data, dict):
                jobs_list = data.get('oportunidades', data.get('data', []))
            elif isinstance(data, list):
                jobs_list = data
            else:
                jobs_list = []
            
            for job in jobs_list[:10]:
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
        else:
            logger.warning(f"Trampos returned status: {response.status_code}")
    except Exception as e:
        logger.error(f"Error searching Trampos: {e}")
    return jobs

def search_catho() -> List[Dict]:
    """Search Catho - Vagas brasileiras"""
    jobs = []
    try:
        # Catho has a public API
        url = "https://api.catho.com.br/v1/vagas"
        params = {'q': 'QA', 'limit': 15}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)', 'Accept': 'application/json'}
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
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
        else:
            logger.warning(f"Catho returned status: {response.status_code}")
    except Exception as e:
        logger.error(f"Error searching Catho: {e}")
    return jobs

def search_vagas() -> List[Dict]:
    """Search Vagas.com.br"""
    jobs = []
    try:
        url = "https://api.vagas.com.br/v1/vagas"
        params = {'q': 'QA', 'limit': 15}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)', 'Accept': 'application/json'}
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
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
        else:
            logger.warning(f"Vagas returned status: {response.status_code}")
    except Exception as e:
        logger.error(f"Error searching Vagas: {e}")
    return jobs

def search_infojobs() -> List[Dict]:
    """Search InfoJobs"""
    jobs = []
    try:
        url = "https://api.infojobs.com.br/api/2/vagas"
        params = {'q': 'QA', 'limit': 15}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)', 'Accept': 'application/json'}
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
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
        else:
            logger.warning(f"InfoJobs returned status: {response.status_code}")
    except Exception as e:
        logger.error(f"Error searching InfoJobs: {e}")
    return jobs

# ============================================================
# GREENHOUSE & GLOBAL SOURCES
# ============================================================

def search_greenhouse_jobs() -> List[Dict]:
    """Search Greenhouse job boards"""
    jobs = []
    greenhouse_companies = [
        'nubank', 'stone', 'vtex', 'mercadolivre', 'creditas', 
        'bemobi', 'iqoption', 'quintoandar', 'ebank', 'c6bank',
        'stripe', 'notion', 'linear', 'vercel', 'railway', 
        'planetscale', 'supabase', 'prisma', 'temporal', 'turso',
        'netlify', 'cloudflare', 'datadog', 'hashicorp', 'mongodb'
    ]
    
    try:
        for company in greenhouse_companies[:5]:  # Limit to 5 companies per run
            url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
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
                            'id': f"greenhouse_{job_id}",
                            'source': 'Greenhouse',
                            'country': '🇧🇷 Brasil' if company in ['nubank', 'stone', 'vtex', 'mercadolivre', 'creditas', 'bemobi', 'iqoption', 'quintoandar', 'ebank', 'c6bank'] else '🌎 Internacional'
                        })
                        if len(jobs) >= 5:
                            break
            time.sleep(0.3)
            if len(jobs) >= 5:
                break
    except Exception as e:
        logger.error(f"Error searching Greenhouse: {e}")
    return jobs

# ============================================================
# INTERNATIONAL REMOTE SOURCES
# ============================================================

def search_remoteok() -> List[Dict]:
    """Search Remote OK for remote jobs"""
    jobs = []
    try:
        url = "https://remoteok.com/api"
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
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
                        if len(jobs) >= 8:
                            break
        else:
            logger.warning(f"RemoteOK returned status: {response.status_code}")
    except Exception as e:
        logger.error(f"Error searching RemoteOK: {e}")
    return jobs

def search_remotive() -> List[Dict]:
    """Search Remotive.io API"""
    jobs = []
    try:
        url = "https://remotive.com/api/remote-jobs?category=qa"
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            for job in data.get('jobs', [])[:10]:
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
        url = "https://weworkremotely.com/categories/remote-qa-jobs.rss"
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            for item in root.findall('.//item')[:10]:
                title = item.find('title').text if item.find('title') is not None else 'N/A'
                link = item.find('link').text if item.find('link') is not None else '#'
                description = item.find('description').text if item.find('description') is not None else ''
                
                if any(keyword in title.lower() for keyword in ['qa', 'quality', 'test', 'tester']):
                    # Extract company from title or description
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

def search_stackoverflow_rss() -> List[Dict]:
    """Search Stack Overflow Jobs RSS"""
    jobs = []
    try:
        url = "https://stackoverflow.com/jobs/feed?q=qa+quality+assurance+tester+automation+sdet"
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
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
                        'id': f"stackoverflow_{job_id}",
                        'source': 'Stack Overflow',
                        'country': '🌎 Internacional'
                    })
    except Exception as e:
        logger.error(f"Error searching Stack Overflow RSS: {e}")
    return jobs

def search_github_jobs_rss() -> List[Dict]:
    """Search GitHub Jobs via search API"""
    jobs = []
    try:
        # Search GitHub for QA job postings in repos
        url = "https://api.github.com/search/issues"
        params = {
            'q': '(qa OR "quality assurance" OR tester OR sdet) in:title label:job,hiring',
            'sort': 'created',
            'order': 'desc',
            'per_page': 10
        }
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)', 'Accept': 'application/vnd.github+json'}
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
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
                        'id': f"github_{generate_job_id(title, 'GitHub')}",
                        'source': 'GitHub Jobs',
                        'country': '🌎 Internacional'
                    })
    except Exception as e:
        logger.error(f"Error searching GitHub Jobs: {e}")
    return jobs

def search_landing_jobs() -> List[Dict]:
    """Search Landing.jobs - European/Remote jobs"""
    jobs = []
    try:
        url = "https://landing.jobs/api/v1/jobs"
        params = {'q': 'qa quality tester sdet automation', 'remote': 'true', 'limit': 15}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
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
    except Exception as e:
        logger.error(f"Error searching Landing.jobs: {e}")
    return jobs

def search_wellfound() -> List[Dict]:
    """Search Wellfound (AngelList) - startup jobs"""
    jobs = []
    try:
        url = "https://wellfound.com/api/v1/jobs"
        params = {'query': 'qa quality tester', 'remote': 'true', 'limit': 10}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            jobs_list = data.get('jobs', data.get('data', []))
            
            for job in jobs_list[:8]:
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
    except Exception as e:
        logger.error(f"Error searching Wellfound: {e}")
    return jobs

def search_ycombinator() -> List[Dict]:
    """Search Y Combinator jobs"""
    jobs = []
    try:
        url = "https://www.ycombinator.com/jobs/search"
        params = {'q': 'qa quality assurance tester automation', 'remote': 'true'}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
            # YC uses HTML, would need parsing
            # For now, use their API if available
            pass
    except Exception as e:
        logger.error(f"Error searching YCombinator: {e}")
    return jobs

def search_otg() -> List[Dict]:
    """Search OTG (On The Go) - remote jobs"""
    jobs = []
    try:
        url = "https://onthegohq.com/api/v1/jobs"
        params = {'category': 'qa', 'remote': 'true'}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
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
                    'id': f"otg_{generate_job_id(title, company)}",
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
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
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
                    'id': f"jobspresso_{generate_job_id(title, company)}",
                    'source': 'Jobspresso',
                    'country': '🌎 Internacional'
                })
    except Exception as e:
        logger.error(f"Error searching Jobspresso: {e}")
    return jobs

def search_remote_co() -> List[Dict]:
    """Search Remote.co - curated remote jobs"""
    jobs = []
    try:
        url = "https://remote.co/remote-jobs/search"
        params = {'search': 'qa'}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
            # Would need HTML parsing
            pass
    except Exception as e:
        logger.error(f"Error searching Remote.co: {e}")
    return jobs

# ============================================================
# RSS/FEED SOURCES
# ============================================================

def search_stackoverflow_rss() -> List[Dict]:
    """Search Stack Overflow Jobs RSS"""
    jobs = []
    try:
        url = "https://stackoverflow.com/jobs/feed?q=qa+quality+assurance+tester+automation+sdet"
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
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
                        'id': f"stackoverflow_{job_id}",
                        'source': 'Stack Overflow',
                        'country': '🌎 Internacional'
                    })
    except Exception as e:
        logger.error(f"Error searching Stack Overflow RSS: {e}")
    return jobs

def search_linkedin_rss() -> List[Dict]:
    """Search LinkedIn Jobs RSS (if available)"""
    jobs = []
    try:
        # LinkedIn has RSS feeds for job searches
        url = "https://www.linkedin.com/jobs/search/?keywords=qa&location=Remote&f_TPR=r86400"
        # Would need proper RSS feed URL
    except Exception as e:
        logger.error(f"Error searching LinkedIn RSS: {e}")
    return jobs

def search_indeed_rss() -> List[Dict]:
    """Search Indeed RSS"""
    jobs = []
    try:
        url = "https://rss.indeed.com/rss?q=qa+quality+tester&l=Remote"
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            for item in root.findall('.//item')[:8]:
                title = item.find('title').text if item.find('title') is not None else 'N/A'
                link = item.find('link').text if item.find('link') is not None else '#'
                
                if any(keyword in title.lower() for keyword in ['qa', 'quality', 'test', 'tester']):
                    company = 'Various'
                    if ' at ' in title:
                        company = title.split(' at ')[-1]
                    
                    job_id = generate_job_id(title, company)
                    jobs.append({
                        'title': title,
                        'company': company,
                        'location': 'Remote',
                        'url': link,
                        'id': f"indeed_{generate_job_id(title, company)}",
                        'source': 'Indeed',
                        'country': '🌎 Internacional'
                    })
    except Exception as e:
        logger.error(f"Error searching Indeed RSS: {e}")
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
    
    # Brazilian sources
    sources_br = [
        ('Programathor', search_programathor),
        ('Gupy', search_gupy_jobs),
        ('Trampos', search_trampos),
        ('Catho', search_catho),
        ('Vagas.com.br', search_vagas),
        ('InfoJobs', search_infojobs),
        ('Greenhouse (BR)', search_greenhouse_jobs),
    ]
    
    # International sources
    sources_int = [
        ('RemoteOK', search_remoteok),
        ('Remotive', search_remotive),
        ('WeWorkRemotely', search_weworkremotely),
        ('Stack Overflow RSS', search_stackoverflow_rss),
        ('GitHub Jobs', search_github_jobs_rss),
        ('Landing.jobs', search_landing_jobs),
        ('Wellfound', search_wellfound),
        ('Y Combinator', search_ycombinator),
        ('OTG', search_otg),
        ('Jobspresso', search_jobspresso),
        ('Remote.co', search_remote_co),
    ]
    
    # RSS feeds
    sources_rss = [
        ('Stack Overflow RSS', search_stackoverflow_rss),
        ('Indeed RSS', search_indeed_rss),
    ]
    
    all_sources = [
        *[(f"BR: {name}", func) for name, func in sources_br],
        *[(f"INT: {name}", func) for name, func in sources_int],
        *[(f"RSS: {name}", func) for name, func in sources_rss],
    ]
    
    for source_name, search_func in all_sources:
        logger.info(f"Searching {source_name}...")
        try:
            found = search_func()
            logger.info(f"Found {len(found)} jobs from {source_name}")
            all_jobs.extend(found)
        except Exception as e:
            logger.error(f"Error in {source_name}: {e}")
    
    return all_jobs

def search_all_sources() -> List[Dict]:
    """Search all enabled sources and return combined results"""
    all_jobs = []
    
    sources = [
        ('Programathor (BR)', search_programathor),
        ('Gupy (BR)', search_gupy_jobs),
        ('Trampos (BR)', search_trampos),
        ('Catho (BR)', search_catho),
        ('Vagas.com.br (BR)', search_vagas),
        ('InfoJobs (BR)', search_infojobs),
        ('Greenhouse (BR/INT)', search_greenhouse_jobs),
        ('RemoteOK (INT)', search_remoteok),
        ('Remotive (INT)', search_remotive),
        ('WeWorkRemotely (INT)', search_weworkremotely),
        ('Stack Overflow RSS (INT)', search_stackoverflow_rss),
        ('GitHub Jobs (INT)', search_github_jobs_rss),
        ('Landing.jobs (INT)', search_landing_jobs),
        ('Wellfound (INT)', search_wellfound),
        ('Y Combinator (INT)', search_ycombinator),
        ('OTG (INT)', search_otg),
        ('Jobspresso (INT)', search_jobspresso),
        ('Stack Overflow RSS (INT)', search_stackoverflow_rss),
        ('Indeed RSS (INT)', search_indeed_rss),
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
        'testing', 'assurance', 'sdet', 'automation', 'automação'
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