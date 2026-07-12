"""Testes do filtro de vagas QA (is_qa_job) e do dedup."""

from qa_jobs_bot import Job, dedupe_jobs, generate_job_id, is_qa_job

SHOULD_MATCH = [
    "QA Engineer",
    "Senior QA Engineer - Europe",
    "QA Manager - Editing and Productivity Groups",
    "Quality Assurance Analyst, Global Operations",
    "QA Specialist (Philippines)",
    "Software Development Engineer in Test II (SDET)",
    "Staff SDET",
    "Test Automation Engineer",
    "Test Engineer",
    "Analista de Qualidade de Software",
    "Engenheiro de Testes Pleno",
    "Testador de Software",
    "QA Lead",
]

SHOULD_NOT_MATCH = [
    "Welding Automation Engineer, Chamber and Nozzle",
    "Senior Penetration Tester",
    "Intern-Web Application Penetration Tester",
    "Retail Key Holder, Cypress, #453",
    "Head of Finance Systems & Automation",
    "CX AI & Automation Lead",
    "Backend Developer",
    "Product Manager",
    "Data Scientist",
    "Test",
    "Test 1 posting",
    "Marketing Manager, Brand & Advocacy",
]


def test_positive_titles():
    for t in SHOULD_MATCH:
        assert is_qa_job(t), f"esperava QA: {t!r}"


def test_negative_titles():
    for t in SHOULD_NOT_MATCH:
        assert not is_qa_job(t), f"não deveria ser QA: {t!r}"


def test_strong_signal_in_tags():
    # título genérico, mas tag forte de QA -> aceita
    assert is_qa_job("Software Engineer", extra="qa automation")
    # título genérico, tag forte, mas título é claramente outro papel -> rejeita
    assert not is_qa_job("Backend Developer", extra="qa")


def test_dedup_cross_source_by_title_company():
    a = Job("QA Engineer", "Acme", "Remote", "http://a", "RemoteOK", "x")
    b = Job("qa  engineer", "ACME", "Remote", "http://b", "Remotive", "x")
    assert a.id == b.id == generate_job_id("QA Engineer", "Acme")
    assert len(dedupe_jobs([a, b])) == 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK  {name}")
    print("todos os testes passaram")
