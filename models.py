import time

from dataclasses import dataclass, asdict
from enum import Enum

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

@dataclass
class JobPosting:
    title: str = None
    link: str = None
    id: str = None

@dataclass
class Company:
    name: str
    active: bool = True
    careers_landing_page: str = None
    jobs_page: str = None
    jobs_page_class: any = None
    load_sleep: int = 1
    scroll_sleep: int = 1
    diff_page: bool = False
    location: str = None
    no_jobs_phrase: str = None
    notes: str = None
    relevant_search_terms: list[str] = None
    tags: list[str] = None
    what: str = None
    referral: str = None
    application_history: str = None

class JobsPageStatus(Enum):
    SPECIFIC_NO_JOBS_PHRASE_FOUND = 1
    GENERIC_NO_JOBS_PHRASE_FOUND = 2
    NO_JOBS_PHRASE_NOT_FOUND_BUT_NO_JOBS = 3
    SOME_JOB_FOUND = 4


