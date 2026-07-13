"""Canonical occupation taxonomy for NexusReach.

The taxonomy is the single source of truth for:
- the occupation chips shown to users in the frontend
- default search queries fed to JSearch/Adzuna during job discovery
- the `occupation:<key>` tag stamped on jobs during ingestion
- peer/manager title seeds used by people discovery
- the department bucket fed to TheOrg traversal and ranking
- whether GitHub-org enrichment should run for a given job context

Add new entries here only — do not duplicate this list elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OCCUPATION_TAG_PREFIX = "occupation:"


@dataclass(frozen=True)
class Occupation:
    key: str
    label: str
    aliases: tuple[str, ...]
    default_search_queries: tuple[str, ...]
    peer_title_seeds: tuple[str, ...]
    manager_title_seeds: tuple[str, ...]
    department_bucket: str
    engineering_flavored: bool = False
    startup_friendly: bool = False
    newgrad_jobs_path: str | None = None
    # Short prompt fragment injected into outreach drafting so the model frames
    # the message in the recipient's professional vocabulary. Keep these to
    # 1–3 sentences; the rest of the system prompt handles tone & structure.
    outreach_playbook: str | None = None


# v1: mirror the 23 categories surfaced on newgrad-jobs.com.
OCCUPATIONS: tuple[Occupation, ...] = (
    Occupation(
        key="software_engineering",
        label="Software Engineering",
        aliases=(
            "software engineer",
            "software developer",
            "swe",
            "backend engineer",
            "backend developer",
            "frontend engineer",
            "frontend developer",
            "full stack",
            "fullstack",
            "full-stack",
            "mobile engineer",
            "ios engineer",
            "android engineer",
            "platform engineer",
            "infrastructure engineer",
            "site reliability",
            "sre",
            "devops engineer",
            "founding engineer",
            "staff engineer",
            "principal engineer",
            "qa engineer",
            "quality assurance",
            "sdet",
        ),
        default_search_queries=(
            "Software Engineer",
            "Backend Developer",
            "Frontend Developer",
            "Full Stack Developer",
            "New Grad Software",
        ),
        peer_title_seeds=(
            "Software Engineer",
            "Software Developer",
            "Backend Engineer",
            "Frontend Engineer",
            "Full Stack Engineer",
            "Site Reliability Engineer",
        ),
        manager_title_seeds=(
            "Engineering Manager",
            "Software Engineering Manager",
            "Software Development Manager",
            "Team Lead",
            "Tech Lead",
            "Technical Lead",
            "Software Engineering Lead",
            "Senior Engineering Manager",
            "Group Engineering Manager",
            "Director of Engineering",
            "Head of Engineering",
            "VP of Engineering",
        ),
        department_bucket="engineering",
        engineering_flavored=True,
        startup_friendly=True,
        newgrad_jobs_path="software-engineer-jobs",
        outreach_playbook=(
            "Lead with a concrete technical detail (project, repo, stack, or "
            "architecture choice) that connects your work to the team's. Ask "
            "specific, engineer-to-engineer questions about codebase, on-call, "
            "or the team's roadmap."
        ),
    ),
    Occupation(
        key="data_analyst",
        label="Data Analyst",
        aliases=(
            "data analyst",
            "business intelligence analyst",
            "bi analyst",
            "analytics analyst",
            "analytics manager",
            "bi developer",
            "business intelligence",
            "data visualization",
            "reporting analyst",
            "operations analyst",
        ),
        default_search_queries=(
            "Data Analyst",
            "Business Intelligence Analyst",
            "Analytics Analyst",
        ),
        peer_title_seeds=(
            "Data Analyst",
            "Business Intelligence Analyst",
            "Analytics Analyst",
            "Reporting Analyst",
        ),
        manager_title_seeds=(
            "Analytics Manager",
            "Manager of Data Analytics",
            "Head of Analytics",
            "Director of Analytics",
        ),
        department_bucket="data",
        startup_friendly=True,
        newgrad_jobs_path="data-analyst",
        outreach_playbook=(
            "Reference a specific analysis or dashboard you've shipped and the "
            "decision it informed. Use measurement vocabulary (cohorts, lift, "
            "funnel, attribution) and ask how the team currently sources and "
            "models its core metrics."
        ),
    ),
    Occupation(
        key="marketing",
        label="Marketing",
        aliases=(
            # The bare word "marketing" already matches any "... Marketing ..."
            # title (Digital/Product/Field Marketing, Marketing Analyst, etc.);
            # the rest cover common marketing roles that DON'T contain the word.
            "marketing",
            "growth marketing",
            "performance marketing",
            "brand marketing",
            "content marketing",
            "lifecycle marketing",
            "demand generation",
            "demand gen",
            "seo specialist",
            "seo",
            "marketing coordinator",
            "marketing manager",
            "brand manager",
            "social media",
            "content strategist",
            "communications manager",
            "communications specialist",
            "public relations",
            "media buyer",
            "paid media",
            "campaign manager",
        ),
        default_search_queries=(
            "Marketing Manager",
            "Growth Marketing",
            "Content Marketing",
            "Brand Marketing",
        ),
        peer_title_seeds=(
            "Marketing Manager",
            "Growth Marketer",
            "Content Marketer",
            "Brand Marketing Manager",
            "Marketing Coordinator",
        ),
        manager_title_seeds=(
            "Marketing Director",
            "Head of Marketing",
            "VP of Marketing",
            "Chief Marketing Officer",
        ),
        department_bucket="marketing",
        startup_friendly=True,
        outreach_playbook=(
            "Open with a real campaign, content piece, or growth experiment "
            "you ran and the outcome (CAC, conversion, retention, brand lift). "
            "Speak in marketer vocabulary: channel mix, audience, creative, "
            "funnel stage."
        ),
    ),
    Occupation(
        key="machine_learning_ai",
        label="Machine Learning and AI",
        aliases=(
            "machine learning",
            "ml engineer",
            "machine learning engineer",
            "ai engineer",
            "applied scientist",
            "research scientist",
            "deep learning",
            "nlp engineer",
            "computer vision",
            "mlops",
            "data scientist",
            "ai researcher",
            "ai scientist",
            "llm",
            "generative ai",
        ),
        default_search_queries=(
            "Machine Learning Engineer",
            "AI Engineer",
            "Applied Scientist",
            "Research Scientist",
        ),
        peer_title_seeds=(
            "Machine Learning Engineer",
            "AI Engineer",
            "Applied Scientist",
            "Research Engineer",
            "MLOps Engineer",
        ),
        manager_title_seeds=(
            "Machine Learning Manager",
            "Director of Machine Learning",
            "Head of AI",
            "VP of Machine Learning",
        ),
        department_bucket="ml_ai",
        engineering_flavored=True,
        startup_friendly=True,
        outreach_playbook=(
            "Cite a paper, model, or applied ML project that's relevant to the "
            "team's work. Be precise about modeling choices (architecture, "
            "training data, eval metric) rather than vague references to AI."
        ),
    ),
    Occupation(
        key="data_engineer",
        label="Data Engineer",
        aliases=(
            "data engineer",
            "analytics engineer",
            "data platform engineer",
            "etl engineer",
            "data infrastructure",
            "data pipeline engineer",
            "etl",
            "data warehouse",
        ),
        default_search_queries=(
            "Data Engineer",
            "Analytics Engineer",
            "Data Platform Engineer",
        ),
        peer_title_seeds=(
            "Data Engineer",
            "Analytics Engineer",
            "Data Platform Engineer",
            "ETL Developer",
        ),
        manager_title_seeds=(
            "Data Engineering Manager",
            "Director of Data Engineering",
            "Head of Data Engineering",
        ),
        department_bucket="data",
        engineering_flavored=True,
        startup_friendly=True,
        outreach_playbook=(
            "Mention the warehouse, orchestration, and modeling tools you've "
            "shipped with. Ask concrete questions about pipeline reliability, "
            "schema evolution, or data contracts."
        ),
    ),
    Occupation(
        key="business_analyst",
        label="Business Analyst",
        aliases=(
            "business analyst",
            "business systems analyst",
            "process analyst",
            "operations analyst",
            "strategy analyst",
            "process improvement",
        ),
        default_search_queries=(
            "Business Analyst",
            "Business Systems Analyst",
            "Strategy Analyst",
        ),
        peer_title_seeds=(
            "Business Analyst",
            "Business Systems Analyst",
            "Strategy Analyst",
            "Operations Analyst",
        ),
        manager_title_seeds=(
            "Business Analysis Manager",
            "Director of Business Analysis",
            "Head of Business Operations",
        ),
        department_bucket="business",
        outreach_playbook=(
            "Frame your impact in terms of operational improvement (cycle time, "
            "cost reduction, process change). Reference a specific stakeholder "
            "you partnered with and the recommendation that shipped."
        ),
    ),
    Occupation(
        key="product_management",
        label="Product Management",
        aliases=(
            "product manager",
            "associate product manager",
            "apm",
            "senior product manager",
            "group product manager",
            "principal product manager",
            "head of product",
            "director of product",
            "product owner",
            "product lead",
            "chief product officer",
            "cpo",
        ),
        default_search_queries=(
            "Product Manager",
            "Associate Product Manager",
            "Senior Product Manager",
        ),
        peer_title_seeds=(
            "Product Manager",
            "Associate Product Manager",
            "Senior Product Manager",
            "Group Product Manager",
        ),
        manager_title_seeds=(
            "Director of Product",
            "Head of Product",
            "VP of Product",
            "Chief Product Officer",
        ),
        department_bucket="product",
        startup_friendly=True,
        outreach_playbook=(
            "Show product judgment: name a recent product decision you'd ask "
            "about (deprecation, pricing, positioning) and tie it to a problem "
            "you've shipped through. Avoid generic 'I love your product' framing."
        ),
    ),
    Occupation(
        key="creatives_design",
        label="Creatives and Design",
        aliases=(
            "designer",
            "ux designer",
            "ui designer",
            "product designer",
            "graphic designer",
            "visual designer",
            "art director",
            "creative director",
            "industrial designer",
            "motion designer",
            "creative",
            "illustrator",
            "copywriter",
        ),
        default_search_queries=(
            "Product Designer",
            "UX Designer",
            "UI Designer",
            "Graphic Designer",
        ),
        peer_title_seeds=(
            "Product Designer",
            "UX Designer",
            "UI Designer",
            "Visual Designer",
            "Graphic Designer",
        ),
        manager_title_seeds=(
            "Design Manager",
            "Head of Design",
            "Director of Design",
            "VP of Design",
            "Creative Director",
        ),
        department_bucket="design",
        startup_friendly=True,
        newgrad_jobs_path="ux-designer",
        outreach_playbook=(
            "Reference a specific flow, surface, or visual decision in the "
            "team's product. Offer a portfolio link if your bio doesn't already "
            "and ask about the design team's research and critique rhythm."
        ),
    ),
    Occupation(
        key="accounting_finance",
        label="Accounting and Finance",
        aliases=(
            "accountant",
            # Bare function nouns, matching the marketing/sales alias style:
            # "accounting" itself ("Accounting Manager" / "Technical Accounting"
            # never contain the token "accountant" — word-boundary matching can't
            # stem) and "finance" ("VP Finance" / "Strategic Finance" /
            # "Quantitative Finance Analyst" carry no other finance alias).
            "accounting",
            "finance",
            "accounts payable",
            "accounts receivable",
            "financial analyst",
            "finance manager",
            "controller",
            "auditor",
            # bare "audit"/"tax" would collide (e.g. "Tax Attorney" is legal);
            # multi-word forms keep the boundary-matched aliases precise.
            "internal audit",
            "tax analyst",
            "tax accountant",
            "tax manager",
            "fp&a analyst",
            "treasury analyst",
            "treasurer",
            "bookkeeper",
            "cfo",
        ),
        default_search_queries=(
            "Financial Analyst",
            "Accountant",
            "Finance Manager",
            "FP&A Analyst",
        ),
        peer_title_seeds=(
            "Financial Analyst",
            "Accountant",
            "FP&A Analyst",
            "Tax Analyst",
            "Treasury Analyst",
        ),
        manager_title_seeds=(
            "Finance Manager",
            "Controller",
            "Director of Finance",
            "VP of Finance",
            "Chief Financial Officer",
        ),
        department_bucket="finance",
        outreach_playbook=(
            "Be precise and credentialed. Reference relevant certifications "
            "(CPA, CFA, ACCA) if applicable, the financial systems you've used, "
            "and a close or audit cycle you owned."
        ),
    ),
    Occupation(
        key="consulting",
        label="Consulting",
        aliases=(
            # No bare "consultant": it's the classic generic-collision alias —
            # "Solutions Consultant" / "Sales Consultant" / "Leasing Consultant"
            # are pre-sales, sales-floor, and property roles, and they were the
            # majority of this tag (measured 2026-07-05). Bare "consulting" is
            # safe: sales roles say "Sales Consultant", never "Sales Consulting",
            # while firm-side titles do ("Consulting Analyst", "Technology
            # Consulting Manager").
            "consulting",
            "management consultant",
            "strategy consultant",
            "senior consultant",
            "associate consultant",
            "business analyst consultant",
            "engagement manager",
            "principal consultant",
            "advisory",
        ),
        default_search_queries=(
            "Consultant",
            "Management Consultant",
            "Strategy Consultant",
            "Associate Consultant",
        ),
        peer_title_seeds=(
            "Consultant",
            "Associate Consultant",
            "Senior Consultant",
            "Engagement Manager",
        ),
        manager_title_seeds=(
            "Principal Consultant",
            "Director of Consulting",
            "Partner",
            "Managing Director",
        ),
        department_bucket="consulting",
        outreach_playbook=(
            "Open with a hypothesis or framing about the recipient's practice "
            "area, not just enthusiasm for the firm. Mention a case team or "
            "engagement type (turnaround, due diligence, growth strategy) you "
            "want to learn about."
        ),
    ),
    Occupation(
        key="engineering_development",
        label="Engineering and Development",
        aliases=(
            "mechanical engineer",
            "electrical engineer",
            "civil engineer",
            "industrial engineer",
            "chemical engineer",
            "aerospace engineer",
            "manufacturing engineer",
            "structural engineer",
            "robotics engineer",
            "embedded engineer",
            "process engineer",
            "quality engineer",
            "hardware engineer",
        ),
        default_search_queries=(
            "Mechanical Engineer",
            "Electrical Engineer",
            "Manufacturing Engineer",
            "Aerospace Engineer",
        ),
        peer_title_seeds=(
            "Mechanical Engineer",
            "Electrical Engineer",
            "Manufacturing Engineer",
            "Industrial Engineer",
        ),
        manager_title_seeds=(
            "Mechanical Engineering Manager",
            "Electrical Engineering Manager",
            "Manufacturing Engineering Manager",
            "Engineering Manager",
            "Director of Engineering",
            "Head of Engineering",
        ),
        department_bucket="hardware_engineering",
        outreach_playbook=(
            "Speak the language of physical systems (CAD tool, materials, "
            "tolerances, manufacturing methods). Reference a specific build or "
            "test you ran and what the failure mode taught you."
        ),
    ),
    Occupation(
        key="human_resources",
        label="Human Resources",
        aliases=(
            "human resources",
            # Bare "hr" (word-boundary): "HR Coordinator" / "HR Specialist" /
            # "HR Director" / "HR Analyst" carried no matching alias — the
            # generalist/business-partner/manager phrases missed every other
            # HR-prefixed title.
            "hr",
            "hr generalist",
            "hr business partner",
            "people partner",
            "people operations",
            "people analytics",
            "head of people",
            "chief people officer",
            "talent acquisition",
            "hr manager",
            "chro",
            "learning and development",
            "recruiter",
            "recruiting",
            "recruitment",
            "sourcer",
            "payroll",
            "employee relations",
            "benefits administrator",
            "total rewards",
            "hris",
            # Multi-word compensation forms only: bare "compensation" would
            # mis-tag insurance "Workers' Compensation" claims roles.
            "compensation analyst",
            "compensation manager",
            "compensation and benefits",
        ),
        default_search_queries=(
            "Human Resources",
            "People Operations",
            "HR Business Partner",
            "Talent Acquisition",
        ),
        peer_title_seeds=(
            "HR Generalist",
            "HR Business Partner",
            "People Operations",
            "People Partner",
        ),
        manager_title_seeds=(
            "HR Manager",
            "People Operations Manager",
            "Director of People",
            "VP of People",
            "Chief People Officer",
        ),
        department_bucket="people",
        outreach_playbook=(
            "Lead with a people problem you've owned (onboarding, calibration, "
            "comp, performance). Reference the recipient's program work and ask "
            "about how the team partners with business leaders."
        ),
    ),
    Occupation(
        key="arts_entertainment",
        label="Arts and Entertainment",
        aliases=(
            # Bare "director"/"producer"/"editor"/"writer" matched *every*
            # "Marketing Director", "Sales Producer", "Engineering ... Editor"
            # title, cross-tagging unrelated roles as arts. Use specific forms.
            "artist",
            "musician",
            "actor",
            "film producer",
            "music producer",
            "executive producer",
            "art director",
            "creative director",
            "film director",
            "screenwriter",
            "video editor",
            "photo editor",
            "film editor",
            "videographer",
            "animator",
            "audio engineer",
            "photographer",
            "journalist",
            "copywriter",
            "content creator",
            "sound engineer",
            "camera operator",
            "casting director",
            "casting associate",
            "talent agent",
            "curator",
            "broadcast",
        ),
        default_search_queries=(
            "Producer",
            "Editor",
            "Animator",
            "Videographer",
        ),
        peer_title_seeds=(
            "Producer",
            "Editor",
            "Videographer",
            "Animator",
            "Writer",
        ),
        manager_title_seeds=(
            "Executive Producer",
            "Creative Director",
            "Head of Production",
        ),
        department_bucket="arts",
        outreach_playbook=(
            "Lead with a piece of work you made — credit, release, exhibition, "
            "or production — and what you learned from it. Speak craft, not "
            "just enthusiasm."
        ),
    ),
    Occupation(
        key="management_executive",
        label="Management and Executive",
        aliases=(
            "chief executive",
            "ceo",
            "coo",
            "cto",
            "cfo",
            "cmo",
            "general manager",
            "managing director",
            "executive director",
            "vice president",
            "chief of staff",
            "chief operating officer",
        ),
        default_search_queries=(
            "General Manager",
            "Managing Director",
            "Vice President",
        ),
        peer_title_seeds=(
            "General Manager",
            "Managing Director",
            "Vice President",
            "Executive Director",
        ),
        manager_title_seeds=(
            "Chief Executive Officer",
            "Chief Operating Officer",
            "Chief Financial Officer",
            "President",
        ),
        department_bucket="executive",
        outreach_playbook=(
            "Be respectful of time. One sentence on what you've built or run, "
            "one specific question about the company's direction, and a clear "
            "low-friction ask. No filler."
        ),
    ),
    Occupation(
        key="customer_service_support",
        label="Customer Service and Support",
        aliases=(
            "customer support",
            "customer service",
            "customer success",
            "client success",
            "customer care",
            "customer advocate",
            "support engineer",
            "technical support",
            "client services",
            "account manager",
            "customer experience",
            # High-volume service-desk families the bank/retail vertical call
            # centers post; no bare "support" — it collides with everything
            # from "Sales Support" to "Child Support Officer".
            "help desk",
            "service desk",
            "call center",
            "contact center",
            "desktop support",
            "support specialist",
            "support representative",
            "support agent",
            "support technician",
            "guest services",
        ),
        default_search_queries=(
            "Customer Success Manager",
            "Customer Support",
            "Technical Support",
            "Customer Experience",
        ),
        peer_title_seeds=(
            "Customer Success Manager",
            "Customer Support Specialist",
            "Technical Support Engineer",
            "Account Manager",
        ),
        manager_title_seeds=(
            "Customer Success Manager",
            "Director of Customer Success",
            "Head of Support",
            "VP of Customer Experience",
        ),
        department_bucket="customer_success",
        startup_friendly=True,
        outreach_playbook=(
            "Lead with empathy and account-health vocabulary (NPS, churn, "
            "expansion, escalation). Reference a difficult customer situation "
            "you turned around and ask how the team measures success."
        ),
    ),
    Occupation(
        key="legal_compliance",
        label="Legal and Compliance",
        aliases=(
            "lawyer",
            "attorney",
            "counsel",
            "general counsel",
            "paralegal",
            # Bare function nouns, matching the marketing/sales/finance alias
            # style: "Legal Operations" / "Head of Legal" / "Compliance
            # Manager" / "Compliance Specialist" carried no matching alias
            # ("compliance officer" was the only compliance form) and fell
            # through untagged. Word-boundary matching keeps "paralegal" and
            # "legally" from matching bare "legal".
            "legal",
            "compliance",
            "litigation",
            "compliance officer",
            "legal analyst",
            "regulatory affairs",
        ),
        default_search_queries=(
            "Attorney",
            "Counsel",
            "Compliance Officer",
            "Paralegal",
        ),
        peer_title_seeds=(
            "Attorney",
            "Associate Counsel",
            "Compliance Analyst",
            "Paralegal",
        ),
        manager_title_seeds=(
            "General Counsel",
            "Director of Legal",
            "Head of Compliance",
            "Chief Legal Officer",
        ),
        department_bucket="legal",
        outreach_playbook=(
            "Use a formal register. Reference your bar admission or jurisdiction "
            "if relevant, the practice area you're focused on, and a specific "
            "matter type you've worked on. Avoid hyperbolic claims."
        ),
    ),
    Occupation(
        key="sales",
        label="Sales",
        aliases=(
            "sales",
            "account executive",
            "ae",
            "sdr",
            "sales development representative",
            "bdr",
            "business development",
            "inside sales",
            "field sales",
            "enterprise sales",
            "sales engineer",
            # Pre-sales titles that used to mis-tag as consulting via the old
            # bare-"consultant" alias: a Solutions Consultant demos and closes,
            # they don't bill engagements.
            "solutions consultant",
            "sales consultant",
            "solutions engineer",
            "presales",
            "pre-sales",
            # Sales families whose titles don't carry the word "sales"
            # (measured 2026-07-06: all fell through untagged).
            "territory manager",
            "account director",
            "partnerships",
            "channel partner",
            "alliances",
            # "revops" only — the spelled-out "revenue operations" phrase would
            # push the "operations" token's doc-frequency over the Muse gate's
            # distinctiveness ceiling and silently break the business_analyst
            # gate (its archetypal titles depend on "operations" being
            # distinctive). RevOps long-form titles keep their analyst tags.
            "revops",
        ),
        default_search_queries=(
            "Account Executive",
            "Sales Development Representative",
            "Business Development",
            "Sales Engineer",
        ),
        peer_title_seeds=(
            "Account Executive",
            "Sales Development Representative",
            "Business Development Representative",
            "Sales Engineer",
        ),
        manager_title_seeds=(
            "Sales Manager",
            "Director of Sales",
            "VP of Sales",
            "Chief Revenue Officer",
        ),
        department_bucket="sales",
        startup_friendly=True,
        outreach_playbook=(
            "Lead with quota attainment, segment, and deal size. Be specific "
            "about ICP, sales motion (inbound/outbound, PLG, enterprise), and "
            "a deal you closed or lost and learned from."
        ),
    ),
    Occupation(
        key="public_sector_government",
        label="Public Sector and Government",
        aliases=(
            "policy analyst",
            "government affairs",
            "public affairs",
            "legislative aide",
            "diplomat",
            "foreign service",
            "civil servant",
            "public administrator",
            "program officer",
            "city planner",
            "urban planner",
        ),
        default_search_queries=(
            "Policy Analyst",
            "Government Affairs",
            "Public Affairs",
            "Legislative Aide",
        ),
        peer_title_seeds=(
            "Policy Analyst",
            "Government Affairs Specialist",
            "Public Affairs Officer",
            "Legislative Aide",
        ),
        manager_title_seeds=(
            "Director of Policy",
            "Head of Government Affairs",
            "Director of Public Affairs",
        ),
        department_bucket="public_policy",
        outreach_playbook=(
            "Reference a specific policy area, bill, or regulatory development "
            "you've followed. Speak in policy vocabulary (stakeholders, "
            "rulemaking, constituency) and keep the tone professionally neutral."
        ),
    ),
    Occupation(
        key="education_training",
        label="Education and Training",
        aliases=(
            "teacher",
            "professor",
            "instructor",
            "trainer",
            "curriculum designer",
            "instructional designer",
            "learning designer",
            "educator",
            "academic advisor",
            "lecturer",
            "tutor",
            "faculty",
            "teaching assistant",
            "school counselor",
            "registrar",
            "curriculum",
            "admissions",
            "dean",
        ),
        default_search_queries=(
            "Teacher",
            "Instructor",
            "Instructional Designer",
            "Curriculum Designer",
        ),
        peer_title_seeds=(
            "Teacher",
            "Instructor",
            "Trainer",
            "Instructional Designer",
        ),
        manager_title_seeds=(
            "Principal",
            "Director of Education",
            "Head of Learning",
            "Dean",
        ),
        department_bucket="education",
        outreach_playbook=(
            "Speak in terms of learner outcomes, curriculum design, and "
            "assessment. Reference a course or program you've built and the "
            "evidence it worked."
        ),
    ),
    Occupation(
        key="cybersecurity",
        label="Cybersecurity",
        aliases=(
            "security engineer",
            "cybersecurity analyst",
            "infosec",
            "information security",
            "penetration tester",
            "security analyst",
            "security architect",
            "soc analyst",
            "ciso",
            "appsec",
        ),
        default_search_queries=(
            "Security Engineer",
            "Cybersecurity Analyst",
            "Information Security Analyst",
            "Penetration Tester",
        ),
        peer_title_seeds=(
            "Security Engineer",
            "Cybersecurity Analyst",
            "Security Analyst",
            "Penetration Tester",
        ),
        manager_title_seeds=(
            "Security Manager",
            "Director of Security",
            "Head of Information Security",
            "Chief Information Security Officer",
        ),
        department_bucket="security",
        engineering_flavored=True,
        startup_friendly=True,
        newgrad_jobs_path="cyber-security",
        outreach_playbook=(
            "Reference specific threat models, frameworks (NIST, MITRE ATT&CK, "
            "ISO 27001), or controls you've implemented. Mention certifications "
            "(OSCP, CISSP, CEH) if relevant and ask about the team's detection "
            "or response posture."
        ),
    ),
    Occupation(
        key="project_management",
        label="Project Management",
        aliases=(
            "project manager",
            "program manager",
            "technical program manager",
            "tpm",
            "scrum master",
            "agile coach",
            "delivery manager",
            "project coordinator",
            "pmo",
            "project management",
        ),
        default_search_queries=(
            "Project Manager",
            "Program Manager",
            "Technical Program Manager",
            "Scrum Master",
        ),
        peer_title_seeds=(
            "Project Manager",
            "Program Manager",
            "Technical Program Manager",
            "Scrum Master",
        ),
        manager_title_seeds=(
            "Director of Project Management",
            "Director of Program Management",
            "Head of Project Management",
            "VP of Program Management",
        ),
        department_bucket="program_management",
        outreach_playbook=(
            "Frame outcomes around schedule, scope, and risk. Reference a "
            "specific cross-functional program you ran end-to-end and how you "
            "handled an unblocking decision."
        ),
    ),
    Occupation(
        key="healthcare",
        label="Healthcare",
        aliases=(
            "nurse",
            "registered nurse",
            "rn",
            "lpn",
            "cna",
            "physician",
            "surgeon",
            "doctor",
            # Bare clinical function nouns (word-boundary): the health-system
            # verticals post whole title families these cover — "Clinical
            # Resource Manager", "Medical Receptionist", "Patient Service
            # Representative", "Pharmacy Technician", "Surgical Services".
            # Measured 2026-07-05: these families were the bulk of the
            # untagged pool from the ten health-system employers.
            "clinical",
            "clinic",
            "medical",
            "medicine",
            "patient",
            "pharmacy",
            "surgical",
            "surgery",
            "dental",
            "hygienist",
            "therapist",
            "radiology",
            "technologist",
            "hospital",
            "home health",
            "behavioral health",
            "mental health",
            "caregiver",
            "dietitian",
            "nutritionist",
            "phlebotomist",
            "sonographer",
            "dosimetrist",
            "paramedic",
            "emt",
            "midwife",
            # Specialist physicians: titles carry the specialty noun and no
            # generic keyword ("Gastroenterologist - Marlborough, MA").
            "cardiologist",
            "gastroenterologist",
            "dermatologist",
            "oncologist",
            "neurologist",
            "radiologist",
            "pathologist",
            "anesthesiologist",
            "psychiatrist",
            "psychologist",
            "pulmonologist",
            "urologist",
            "nephrologist",
            "ophthalmologist",
            "endocrinologist",
            "hematologist",
            "rheumatologist",
            "hospitalist",
            "pediatrician",
            "obstetrician",
            "gynecologist",
            "medical assistant",
            "clinical research",
            "pharmacist",
            "physical therapist",
            "occupational therapist",
            "healthcare administrator",
        ),
        default_search_queries=(
            "Registered Nurse",
            "Medical Assistant",
            "Clinical Research Associate",
            "Healthcare Administrator",
        ),
        peer_title_seeds=(
            "Registered Nurse",
            "Medical Assistant",
            "Clinical Research Associate",
            "Pharmacist",
        ),
        manager_title_seeds=(
            "Nurse Manager",
            "Director of Nursing",
            "Healthcare Administrator",
            "Chief Medical Officer",
        ),
        department_bucket="healthcare",
        outreach_playbook=(
            "Lead with credentials and patient-care setting. Use clinical "
            "vocabulary appropriate to the role and avoid embellishing scope of "
            "practice. Respect the formality of the field."
        ),
    ),
    Occupation(
        key="supply_chain",
        label="Supply Chain",
        aliases=(
            "supply chain",
            "logistics",
            "procurement",
            "operations manager",
            "warehouse manager",
            "inventory analyst",
            "supply chain analyst",
            "buyer",
            "demand planner",
            # Specific warehouse forms only — bare "warehouse" would claim
            # "Data Warehouse Engineer" (a data-engineering title).
            "warehouse associate",
            "warehouse supervisor",
            "warehouse operations",
            "inventory",
            "fulfillment",
            "strategic sourcing",
            "sourcing manager",
        ),
        default_search_queries=(
            "Supply Chain Analyst",
            "Logistics Coordinator",
            "Procurement Specialist",
            "Demand Planner",
        ),
        peer_title_seeds=(
            "Supply Chain Analyst",
            "Logistics Coordinator",
            "Procurement Specialist",
            "Demand Planner",
            "Inventory Analyst",
        ),
        manager_title_seeds=(
            "Supply Chain Manager",
            "Director of Logistics",
            "Head of Supply Chain",
            "VP of Operations",
        ),
        department_bucket="supply_chain",
        outreach_playbook=(
            "Reference SKU count, lead time, or supplier network specifics. "
            "Lead with a procurement, demand planning, or logistics decision "
            "you owned and what it changed about throughput or cost."
        ),
    ),
)

_BY_KEY: dict[str, Occupation] = {occ.key: occ for occ in OCCUPATIONS}
_BY_DEPARTMENT: dict[str, list[Occupation]] = {}
for _occ in OCCUPATIONS:
    _BY_DEPARTMENT.setdefault(_occ.department_bucket, []).append(_occ)


def all_occupations() -> tuple[Occupation, ...]:
    """Return every occupation in stable display order."""
    return OCCUPATIONS


def occupation_by_key(key: str) -> Occupation | None:
    return _BY_KEY.get((key or "").strip().lower())


def occupation_keys() -> list[str]:
    return [occ.key for occ in OCCUPATIONS]


def occupations_for_keys(keys: list[str] | None) -> list[Occupation]:
    """Look up occupations by key, silently dropping unknown values."""
    if not keys:
        return []
    seen: set[str] = set()
    result: list[Occupation] = []
    for key in keys:
        occ = occupation_by_key(key)
        if occ and occ.key not in seen:
            seen.add(occ.key)
            result.append(occ)
    return result


def occupation_tag(key: str) -> str:
    """Build the canonical job tag for an occupation key."""
    return f"{OCCUPATION_TAG_PREFIX}{key}"


def is_occupation_tag(tag: str | None) -> bool:
    return bool(tag) and tag.startswith(OCCUPATION_TAG_PREFIX)


def occupation_keys_from_tags(tags: list[str] | None) -> list[str]:
    """Extract `occupation:<key>` slugs from a job's tags array."""
    if not tags:
        return []
    keys: list[str] = []
    for tag in tags:
        if not is_occupation_tag(tag):
            continue
        key = tag[len(OCCUPATION_TAG_PREFIX):]
        if key and key not in keys:
            keys.append(key)
    return keys


def discover_queries_for_occupations(keys: list[str] | None) -> list[dict]:
    """Build job-discover query dicts (query/location/remote_only) from occupation keys.

    Returns the SWE-flavored default set only when no keys were supplied,
    preserving the default feed for new users. A non-empty all-invalid list
    returns no queries so stale taxonomy values cannot launch software search.
    """
    occupations = occupations_for_keys(keys)
    if not occupations and not keys:
        occupations = [occupation_by_key("software_engineering")]  # type: ignore[list-item]
        occupations = [occ for occ in occupations if occ is not None]
    queries: list[dict] = []
    seen: set[str] = set()
    for occ in occupations:
        for raw in occ.default_search_queries:
            normalized = raw.strip()
            key = normalized.casefold()
            if not normalized or key in seen:
                continue
            seen.add(key)
            queries.append(
                {
                    "query": normalized,
                    "location": None,
                    "remote_only": False,
                    "occupation": occ.key,
                }
            )
    return queries


def startup_query_strings_for_occupations(keys: list[str] | None) -> list[str]:
    """Flatten startup-friendly occupations into raw query strings."""
    occupations = occupations_for_keys(keys)
    if not occupations:
        occupations = [occ for occ in OCCUPATIONS if occ.startup_friendly]
    queries: list[str] = []
    seen: set[str] = set()
    for occ in occupations:
        if not occ.startup_friendly and keys:
            # User explicitly asked for this occupation — honor it even if not
            # nominally startup-friendly. But when we're filling in defaults
            # (no keys), we already filter on startup_friendly above.
            pass
        for raw in occ.default_search_queries:
            normalized = raw.strip()
            key = normalized.casefold()
            if not normalized or key in seen:
                continue
            seen.add(key)
            queries.append(normalized)
    return queries


def newgrad_jobs_paths(keys: list[str] | None = None) -> list[str]:
    """Return the newgrad-jobs.com category slugs for the requested occupations.

    When `keys` is None, returns the union of every occupation that has a known
    path. Falls back to legacy behavior so the scraper never returns nothing.
    """
    occupations = occupations_for_keys(keys) if keys else list(OCCUPATIONS)
    paths: list[str] = []
    for occ in occupations:
        if occ.newgrad_jobs_path and occ.newgrad_jobs_path not in paths:
            paths.append(occ.newgrad_jobs_path)
    return paths


# --- Title classification ----------------------------------------------------

_WORD_BOUNDARY_CACHE: dict[str, re.Pattern[str]] = {}

_GENERIC_TITLE_WORDS = frozenset({
    "associate", "assistant", "advisor", "consultant", "coordinator", "director",
    "intern", "lead", "manager", "officer", "representative", "specialist",
    "staff", "technician", "trainee", "analyst", "clerk", "professional",
})
_TITLE_NOISE_WORDS = frozenset({
    "senior", "sr", "junior", "jr", "entry", "level", "new", "grad",
    "i", "ii", "iii", "iv", "remote", "hybrid",
})


def _alias_pattern(alias: str) -> re.Pattern[str]:
    cached = _WORD_BOUNDARY_CACHE.get(alias)
    if cached is not None:
        return cached
    # Treat alias as case-insensitive substring with word-boundary on edges that
    # are alphanumeric. This handles "ml engineer" vs "html engineer".
    escaped = re.escape(alias)
    pattern = re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)
    _WORD_BOUNDARY_CACHE[alias] = pattern
    return pattern


def classify_title(title: str | None, description: str | None = None) -> list[str]:
    """Return occupation keys whose aliases match the job title (or description).

    Multiple matches are allowed (e.g., "ML Software Engineer" → both
    `software_engineering` and `machine_learning_ai`). Order follows the
    canonical OCCUPATIONS tuple so output is stable.
    """
    haystack_title = (title or "").strip()
    haystack_desc = (description or "").strip()
    if not haystack_title and not haystack_desc:
        return []

    matched: list[str] = []
    for occ in OCCUPATIONS:
        for alias in occ.aliases:
            pattern = _alias_pattern(alias)
            if haystack_title and pattern.search(haystack_title):
                matched.append(occ.key)
                break
    if matched:
        return matched

    # A non-empty but generic title ("Associate II", "Coordinator", "Manager")
    # is not useful evidence. Use the responsibility text only in that case;
    # specific unmatched titles remain unclassified rather than inheriting a
    # category from company boilerplate.
    title_words = [
        token for token in re.findall(r"[a-z]+", haystack_title.lower())
        if token not in _TITLE_NOISE_WORDS
    ]
    generic_title = (
        not haystack_title
        or (bool(title_words) and len(title_words) <= 2 and all(
            token in _GENERIC_TITLE_WORDS for token in title_words
        ))
    )
    if generic_title and haystack_desc:
        # Lead responsibilities carry more role signal than footer/benefits
        # boilerplate and keep the classifier bounded on long scraped pages.
        description_lead = haystack_desc[:2400]
        for occ in OCCUPATIONS:
            if any(_alias_pattern(alias).search(description_lead) for alias in occ.aliases):
                matched.append(occ.key)
    return matched


def occupation_tags_for_job(
    *,
    title: str | None,
    description: str | None = None,
    explicit_keys: list[str] | None = None,
    fallback_keys: list[str] | None = None,
) -> list[str]:
    """Build occupation tag values for a job during ingestion.

    - `explicit_keys`: hints from the source itself (e.g., the newgrad-jobs path
      that yielded the job). These always win.
    - Falls back to title/description classification when no explicit hint.
    - `fallback_keys`: weakest signal (e.g., the occupation whose discover query
      surfaced the job). Used only when both stronger signals produced nothing,
      so query noise can never override a confident title classification.
    """
    keys: list[str] = []
    seen: set[str] = set()
    for key in (explicit_keys or []):
        occ = occupation_by_key(key)
        if occ and occ.key not in seen:
            seen.add(occ.key)
            keys.append(occ.key)
    if not keys:
        for key in classify_title(title, description):
            if key not in seen:
                seen.add(key)
                keys.append(key)
    if not keys:
        for key in (fallback_keys or []):
            occ = occupation_by_key(key)
            if occ and occ.key not in seen:
                seen.add(occ.key)
                keys.append(occ.key)
    return [occupation_tag(key) for key in keys]


# --- People discovery helpers ------------------------------------------------


def occupations_for_department(department: str | None) -> list[Occupation]:
    if not department:
        return []
    return list(_BY_DEPARTMENT.get(department, []))


def peer_title_seeds_for(keys: list[str] | None, department: str | None = None) -> list[str]:
    """Resolve peer title seeds from a list of occupation keys (or a department)."""
    occupations = occupations_for_keys(keys)
    if not occupations and department:
        occupations = occupations_for_department(department)
    seeds: list[str] = []
    seen: set[str] = set()
    for occ in occupations:
        for title in occ.peer_title_seeds:
            key = title.casefold()
            if key in seen:
                continue
            seen.add(key)
            seeds.append(title)
    return seeds


def outreach_playbook_for_keys(keys: list[str] | None) -> str | None:
    """Return the first non-empty outreach playbook for the given occupation keys.

    Resolution preserves caller order: the first key supplied (that resolves to
    a known occupation with a playbook) wins. For inferred-from-title keys
    coming out of ``classify_title``, that order is canonical taxonomy order;
    for user-supplied ``profile.target_occupations`` it's the user's stated
    preference order. Returns ``None`` if no key resolves or no key carries a
    playbook.
    """
    for occ in occupations_for_keys(keys):
        if occ.outreach_playbook:
            return occ.outreach_playbook
    return None


def manager_title_seeds_for(keys: list[str] | None, department: str | None = None) -> list[str]:
    occupations = occupations_for_keys(keys)
    if not occupations and department:
        occupations = occupations_for_department(department)
    seeds: list[str] = []
    seen: set[str] = set()
    for occ in occupations:
        for title in occ.manager_title_seeds:
            key = title.casefold()
            if key in seen:
                continue
            seen.add(key)
            seeds.append(title)
    return seeds


def is_engineering_flavored(keys: list[str] | None, department: str | None = None) -> bool:
    """True when the requested occupations include an engineering-flavored one.

    Used to gate GitHub-org enrichment and similar engineering-only enrichments.
    """
    occupations = occupations_for_keys(keys)
    if not occupations and department:
        occupations = occupations_for_department(department)
    if not occupations and department == "engineering":
        return True
    return any(occ.engineering_flavored for occ in occupations)


# --- TheOrg department keyword bridge ----------------------------------------

# Hand-curated team keywords by department bucket. Used by the TheOrg
# traversal to score teams. Falls back to engineering keywords for unknown
# departments to preserve today's behavior.
DEPARTMENT_TEAM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "engineering": ("engineering", "software", "platform", "infrastructure"),
    "ml_ai": ("machine learning", "ai", "data science", "ml platform", "research"),
    "data": ("data", "analytics", "data platform", "business intelligence"),
    "product": ("product", "strategy", "product management"),
    "design": ("design", "ux", "creative", "product design"),
    "marketing": ("marketing", "brand", "growth", "demand generation"),
    "sales": ("sales", "revenue", "go to market", "business development"),
    "customer_success": ("customer success", "customer experience", "support"),
    "people": ("people", "human resources", "talent", "hr"),
    "finance": ("finance", "accounting", "fp&a", "treasury"),
    "legal": ("legal", "compliance", "regulatory"),
    "security": ("security", "cybersecurity", "infosec", "trust and safety"),
    "consulting": ("consulting", "advisory", "professional services"),
    "business": ("business operations", "strategy", "operations"),
    "executive": ("executive", "office of the ceo", "leadership"),
    "program_management": ("program management", "tpm", "delivery"),
    "education": ("education", "learning", "curriculum"),
    "healthcare": ("clinical", "medical", "nursing", "healthcare"),
    "supply_chain": ("supply chain", "logistics", "procurement", "operations"),
    "hardware_engineering": ("mechanical", "electrical", "manufacturing", "hardware"),
    "arts": ("creative", "production", "studio"),
    "public_policy": ("policy", "public affairs", "government affairs"),
}


def team_keywords_for_department(department: str | None) -> tuple[str, ...]:
    """Resolve TheOrg team keywords with engineering as the safe default."""
    if not department:
        return DEPARTMENT_TEAM_KEYWORDS["engineering"]
    return DEPARTMENT_TEAM_KEYWORDS.get(department, DEPARTMENT_TEAM_KEYWORDS["engineering"])
