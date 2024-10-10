import os
import sys
import json
import datetime
import boto3
import argparse
from selenium import webdriver
from tempfile import mkdtemp

def lambda_handler(event, context, local=False):
    limit_company = event["limit_company"] if "limit_company" in event else None
    temp_term = event["temp_term"] if "temp_term" in event else None
    dont_replace_existing = event["dont_replace_existing"] if "dont_replace_existing" in event else False
    dont_write_existing = event["dont_write_existing"] if "dont_write_existing" in event else False

    options = webdriver.ChromeOptions()

    if not local:
        service = webdriver.ChromeService("/opt/chromedriver")
        options.binary_location = '/opt/chrome/chrome'

    options.add_argument("--headless=new")
    options.add_argument('--no-sandbox')
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280x1696")
    options.add_argument("--single-process")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-dev-tools")
    options.add_argument("--no-zygote")
    options.add_argument(f"--user-data-dir={mkdtemp()}")
    options.add_argument(f"--data-path={mkdtemp()}")
    options.add_argument(f"--disk-cache-dir={mkdtemp()}")
    options.add_argument("--remote-debugging-port=9222")

    if local:
        driver = webdriver.Chrome(options=options)
    else:
        driver = webdriver.Chrome(options=options, service=service)
    
    # So that we can update the config without repackaging and deploying the image
    os.makedirs("/tmp/job_scrape", exist_ok=True)
    s3 = boto3.resource('s3')
    bucket = s3.Bucket(event["aws_config"]["bucket_name"])
    bucket.download_file(event["aws_config"]["config_file"], '/tmp/job_scrape/config.py')
    bucket.download_file(event["aws_config"]["scrapers_file"], '/tmp/job_scrape/scrapers.py')

    sys.path.append(os.path.abspath("/tmp/job_scrape"))

    existing_jobs_object = s3.Object(event["aws_config"]["bucket_name"], event["aws_config"]["existing_jobs_json"])
    file_content = existing_jobs_object.get()['Body'].read().decode('utf-8')
    existing_relevant_jobs = json.loads(file_content)

    # dynamic import so we can dynamically pull config file
    from jobscrape import get_new_relevant_jobs, format_new_jobs_message

    new_relevant_jobs, existing_relevant_jobs, verify_no_jobs, errors = get_new_relevant_jobs(
        driver,
        existing_relevant_jobs,
        limit_company,
        temp_term
    )
    return_message = {}
    

    sns = boto3.client('sns')
    if len(new_relevant_jobs) > 0:
        new_jobs_message = format_new_jobs_message(new_relevant_jobs)

        if dont_replace_existing:
            path, extension = os.path.splitext(event["aws_config"]["existing_jobs_json"])
            existing_jobs_object = s3.Object(event["aws_config"]["bucket_name"], f"{path}_{str(datetime.datetime.now()).replace(" ", "_")}{extension}")
        if not dont_write_existing:
            existing_jobs_object.put(Body=json.dumps(existing_relevant_jobs, indent=4))

        response = sns.publish(
            TopicArn=event["aws_config"]["sns_topic_arn"],
            Message=new_jobs_message,
            Subject='New jobs',
        )
        print("New jobs:")
        print(new_jobs_message)
        return_message["new_jobs"] = new_jobs_message

    errors_object = s3.Object(event["aws_config"]["bucket_name"], event["aws_config"]["errors_json"])
    file_content = errors_object.get()['Body'].read().decode('utf-8')
    existing_errors = json.loads(file_content)
    existing_errors_company_names = {error["company_name"] for error in existing_errors}
    
    if len(errors) > 0:
        has_new_errors = False

        new_existing_errors = []
        for company_name, error in errors:
            new_existing_errors.append({
                "company_name": company_name,
                "message": str(error),
            })
            foo = company_name not in existing_errors_company_names
            print("company_name not in existing_errors_company_names", foo)
            if company_name not in existing_errors_company_names:
                has_new_errors = True

        errors_message = f"All errors:\n{"\n".join([f"{company_name}: {error}" for company_name, error in errors])}"

        if has_new_errors:
            response = sns.publish(
                TopicArn=event["aws_config"]["sns_topic_arn"],
                Message=errors_message,
                Subject='New scrape errors',
            )

        errors_object.put(Body=json.dumps(new_existing_errors, indent=4))
        print(errors_message)
        return_message["errors"] = errors_message

    elif len(existing_errors_company_names) > 0:
        errors_object.put(Body=json.dumps([], indent=4))


    return {
        'statusCode': 200,
        'body': return_message
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Run with aws resources to scrape new jobs and notify.')
    parser.add_argument('event_json', type=str, help="""Path to lambda event json. Expected structure:
{
    "aws_config": {
        "bucket_name": "",
        "config_file": "",
        "scrapers_file": "",
        "existing_jobs_json": "",
        "errors_json": "",
        "sns_topic_arn": "",
    }
    "limit_company": "",
    "dont_replace_existing": true/false,
    "dont_write_existing": true/false,
}
        """)

    args = parser.parse_args()

    with open(args.event_json) as f:
        lambda_event = json.load(f)
        lambda_handler(
            lambda_event,
            context=None,
            local=True
        )