#! /usr/bin/env python3
# Need selenium because postings might take js to load

import argparse
import datetime
import json
import os
import time
from collections import defaultdict
from tempfile import mkdtemp

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from models import *

def get_new_relevant_jobs(driver, existing_relevant_jobs: dict[str, list[str]], limit_company = None, additional_search_term = None):

    existing_relevant_jobs = defaultdict(set, {key: set(value) for key, value in existing_relevant_jobs.items()})

    relevant_jobs, skipped_companies, verify_no_jobs, errors = get_relevant_jobs(driver, limit_company, additional_search_term)
    new_relevant_jobs = {}

    # Group jobs by company, and update existing
    for company, job in relevant_jobs:
        if job.id not in existing_relevant_jobs[company.name]:
            if company.name in new_relevant_jobs:
                new_relevant_jobs[company.name]["jobs"].append(job)
            else:
                new_relevant_jobs[company.name] = {
                    "company": company,
                    "jobs": [job]
                }

            existing_relevant_jobs[company.name].add(job.id)

    existing_relevant_jobs = {key: sorted(list(value)) for key, value in existing_relevant_jobs.items()}

    return new_relevant_jobs, existing_relevant_jobs, verify_no_jobs, errors

def get_relevant_jobs(driver, limit_company, additional_search_term):
    relevant_jobs: list[tuple[Company, list[JobPosting]]] = []
    skipped_companies = []
    verify_no_jobs = []
    errors: list[tuple[str, Exception]] = []

    # Dynamic import so that we can e.g. dynamically pull this file from s3, and change the config without repackaging the docker image
    import config
    companies = [Company(**company) for company in config.companies]

    search_terms = config.search_terms
    if additional_search_term:
        search_terms.append(additional_search_term)

    for company in companies:
        if limit_company and limit_company.lower() not in company.name.lower():
            continue
        
        if company.active:
            assert company.jobs_page
            print("Checking", company.name)
            try:
                company_relevant_jobs, jobs_page_status = get_company_relevant_jobs(driver, company, search_terms)
                if len(company_relevant_jobs) > 0:
                    for job in company_relevant_jobs:
                        relevant_jobs.append((company, job))
                elif jobs_page_status in {JobsPageStatus.GENERIC_NO_JOBS_PHRASE_FOUND, JobsPageStatus.NO_JOBS_PHRASE_NOT_FOUND_BUT_NO_JOBS}:
                    verify_no_jobs.append(company)
            except Exception as e:
                errors.append((company.name, e))
        
        else:
            skipped_companies.append(company.name)
    
    driver.close()  # Close the original browser window
    return relevant_jobs, skipped_companies, verify_no_jobs, errors

def get_company_relevant_jobs(driver, company, search_terms) -> (list[JobPosting], JobsPageStatus):
    driver.get(company.jobs_page)
    time.sleep(company.load_sleep)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);") # Scroll to bottom to lazy load everything
    time.sleep(company.scroll_sleep)

    company_has_jobs, jobs_page_status = has_jobs(driver, company)
    if company_has_jobs:
        if company.jobs_page_class:
            jobs = company.jobs_page_class.get_jobs(driver)
            if len(jobs) > 0:
                jobs_page_status = JobsPageStatus.SOME_JOB_FOUND
            relevant_jobs = [job for job in jobs if title_is_relevant(company, job.title, search_terms)]
        else:
            raise Exception("Scrape not implemented")
    else:
        return [], jobs_page_status

    return relevant_jobs, jobs_page_status

def has_jobs(driver, company) -> (bool, JobsPageStatus):
    all_text_lower = driver.find_element(By.TAG_NAME, 'body').text.lower()
    if all_text_lower is None or all_text_lower == "":
        raise Exception(company.name + ": Error retrieving text")
    if company.no_jobs_phrase:
        if company.no_jobs_phrase.lower() in all_text_lower:
            return False, JobsPageStatus.SPECIFIC_NO_JOBS_PHRASE_FOUND
        return True, JobsPageStatus.NO_JOBS_PHRASE_NOT_FOUND_BUT_NO_JOBS
    else:
        generic_no_jobs_phrases = ['No available positions', "No positions", "Sorry", "No job", "No current", "No open", 'None available', 'Don\'t have', 'don\'t currently', 'No openings']
        has_jobs = all(phrase.lower() not in all_text_lower for phrase in generic_no_jobs_phrases)
        return has_jobs, JobsPageStatus.NO_JOBS_PHRASE_NOT_FOUND_BUT_NO_JOBS if has_jobs else JobsPageStatus.GENERIC_NO_JOBS_PHRASE_FOUND

def title_is_relevant(company, title, search_terms) -> bool:
    if company.relevant_search_terms:
        return any(search_term.lower() in title.lower() for search_term in company.relevant_search_terms)

    return any(search_term.lower() in title.lower() for search_term in search_terms)

def format_new_jobs_message(new_jobs: dict[str, dict[str, any]]) -> str:
    message = ""
    for company_name, info in new_jobs.items():
        message += f"\n{company_name} ({info["company"].jobs_page}):\n"
        for job in info["jobs"]:
                message += f"\t {job.title.replace("\n", " ")} {job.link if job.link else ""}\n"
    return message

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Scrape new jobs.')
    parser.add_argument('existing_jobs_json', type=str, help='path to file with existing jobs')
    parser.add_argument('--additional_search_term', type=str, default=None, help='Search term to add in considering a job relevant')
    parser.add_argument('--limit_company', type=str, default=None, help='Search only companies that contain this string in their name')
    parser.add_argument('--dont_replace_existing', action='store_true', help="Don't replace the existing jobs file")
    parser.add_argument('--dont_write_existing', action='store_true', help="Don't write the existing jobs file")
    parser.add_argument('--headless', action='store_true', help="Run headless")
    args = parser.parse_args()

    existing_relevant_jobs = {}
    with open(args.existing_jobs_json) as f:
        existing_relevant_jobs = json.load(f)

    options = webdriver.ChromeOptions()
    if args.headless:
        options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)

    new_relevant_jobs, existing_relevant_jobs, verify_no_jobs, errors = get_new_relevant_jobs(
        driver, 
        existing_relevant_jobs,
        args.limit_company,
        args.additional_search_term
    )

    if len(verify_no_jobs) > 0:
        print(bcolors.OKBLUE + "No jobs at all, but no specific no jobs phrase:\n" + "\n".join([company.name for company in verify_no_jobs]) + bcolors.ENDC)
    if len(new_relevant_jobs) > 0:
        print(bcolors.OKGREEN + format_new_jobs_message(new_relevant_jobs) + bcolors.ENDC)
    if len(errors) > 0:
        print(bcolors.FAIL + "Errors:\n" + "\n".join([f"{company_name}: {error}" for company_name, error in errors]) + bcolors.ENDC)
    if len(new_relevant_jobs) == 0:
        print("No new jobs")

    if len(new_relevant_jobs) > 0 and not args.dont_write_existing: # disconnected logic not tied with a hard constraint
        filename = args.existing_jobs_json
        if args.dont_replace_existing:
            path, extension = os.path.splitext(filename)
            filename = f"{path}_{str(datetime.datetime.now()).replace(" ", "_")}{extension}"
        with open(filename, 'w') as f:
            json.dump(existing_relevant_jobs, f, indent=4)
        print(f"Wrote new existing jobs to {filename}")
