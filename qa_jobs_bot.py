import os
import requests
import json
from datetime import datetime
from typing import List, Dict, Set
import time
import hashlib
import xml.etree.ElementTree as ET
import logging

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

# Job sources configuration
ENABLED_SOURCES = [
    'programathor',
    'gupy',
    'remoteok',
    'greenhouse',
    'github',
    'remotive',
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

def search_programathor() -> List[Dict]:
    """Search Programathor jobs API - Vagas brasileiras"""
    jobs = []
    try:
        url = "https://api.programathor.com.br/jobs/search"
        params = {'query': 'QA', 'page': 1, 'per_page': 15}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)', 'Accept': 'application/json'}
        response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
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
        response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
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
        else:
            logger.warning(f"Gupy returned status: {response.status_code}")
    except Exception as e:
        logger.error(f"Error searching Gupy: {e}")
    return jobs

def search_remote_ok() -> List[Dict]:
    """Search Remote OK for remote jobs that accept LATAM"""
    jobs = []
    try:
        url = "https://remoteok.com/api"
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            for job in data[1:]:  # First item is metadata
                if isinstance(job, dict):
                    title = job.get('position', '').lower()
                    tags = [tag.lower() for tag in job.get('tags', [])] if job.get('tags') else []
                    qa_keywords = ['qa', 'quality', 'test', 'tester', 'testing', 'assurance']
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
                        if len(jobs) >= 5:
                            break
        else:
            logger.warning(f"RemoteOK returned status: {response.status_code}")
    except Exception as e:
        logger.error(f"Error searching RemoteOK: {e}")
    return jobs

def search_greenhouse_jobs() -> List[Dict]:
    """Search Greenhouse job boards - Many companies use Greenhouse"""
    jobs = []
    greenhouse_companies = ['nubank', 'stone', 'vtex', 'mercadolivre', 'creditas', 'bemobi', 'iqoption', 'quintoandar']
    try:
        for company in greenhouse_companies[:3]:  # Limit to 3 companies per run
            url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                jobs_list = data.get('jobs', [])
                
                for job in jobs_list:
                    title = job.get('title', '').lower()
                    if any(keyword in title for keyword in ['qa', 'quality', 'test', 'tester']):
                        job_id = generate_job_id(job.get('title', ''), company)
                        jobs.append({
                            'title': job.get('title', 'N/A'),
                            'company': company.capitalize(),
                            'location': job.get('location', {}).get('name', 'Remoto') if isinstance(job.get('location'), dict) else 'Remoto',
                            'url': job.get('absolute_url', '#'),
                            'id': f"greenhouse_{job_id}",
                            'source': 'Greenhouse',
                            'country': '🇧🇷 Brasil'
                        })
                        if len(jobs) >= 3:
                            break
            time.sleep(0.5)  # Be nice to API
            if len(jobs) >= 3:
                break
    except Exception as e:
        logger.error(f"Error searching Greenhouse: {e}")
    return jobs

def search_github_jobs_rss() -> List[Dict]:
    """Search GitHub Jobs via search API"""
    jobs = []
    try:
        url = "https://api.github.com/search/issues"
        params = {
            'q': 'qa OR "quality assurance" OR tester in:title label:job,hiring repo:org/repo',
            'sort': 'created',
            'order': 'desc',
            'per_page': 10
        }
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)', 'Accept': 'application/vnd.github+json'}
        response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            for item in data.get('items', [])[:5]:
                title = item.get('title', 'N/A')
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
    except Exception as e:
        logger.error(f"Error searching GitHub Jobs: {e}")
    return jobs

def search_remotive_rss() -> List[Dict]:
    """Search Remotive.io API"""
    jobs = []
    try:
        url = "https://remotive.com/api/remote-jobs?category=qa"
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; QAJobBot/1.0)'}
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            for job in data.get('jobs', [])[:5]:
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
    embed_color = 0x00FFFF if is_br else 0xFF10F0  # Cyan for BR, Neon Pink for International
    
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
        "color": embed_color,
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
                {"name": "⏰ Próxima Busca", "value": "Em ~15 minutos", "inline": True}
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
                time.sleep(1)  # Rate limiting
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
    all_jobs = []
    
    sources = [
        ('Programathor (BR)', search_programathor),
        ('Gupy (BR)', search_gupy_jobs),
        ('RemoteOK (International)', search_remote_ok),
        ('Greenhouse (BR)', search_greenhouse_jobs),
        ('GitHub Jobs', search_github_jobs_rss),
        ('Remotive.io', search_remotive_rss),
    ]
    
    for source_name, search_func in sources:
        logger.info(f"Searching {source_name}...")
        try:
            found = search_func()
            logger.info(f"Found {len(found)} jobs from {source_name}")
            all_jobs.extend(found)
        except Exception as e:
            logger.error(f"Error in {source_name}: {e}")
    
    logger.info(f"📊 Found {len(all_jobs)} total jobs")
    
    # Filter for QA-related keywords
    qa_keywords = ['qa', 'quality', 'qualidade', 'tester', 'teste', 'test', 'testing', 'assurance']
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