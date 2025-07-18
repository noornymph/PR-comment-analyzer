"""
Script to analyze GitHub PR comments within a specified date range.
Usage:
    python pr_comment_stats.py --repo https://github.com/owner/repo --token YOUR_GITHUB_PAT --start-date 2024-01-01 --end-date 2024-01-31
"""
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests


def calculate_business_hours(start_time, end_time):
    """Calculate hours between two datetime objects excluding weekends."""

    if start_time >= end_time:
        return 0
    total_hours = 0
    current = start_time
    
    while current.date() < end_time.date():

        if current.weekday() < 5:
            end_of_day = current.replace(hour=23, minute=59, second=59, microsecond=999999)
            hours_in_day = (end_of_day - current).total_seconds() / 3600
            total_hours += hours_in_day
        current = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    if current.date() == end_time.date() and current.weekday() < 5:
        hours_final_day = (end_time - current).total_seconds() / 3600
        total_hours += hours_final_day
    return total_hours


def extract_repo_info(repo_url):
    """Extract owner and repo name from GitHub URL."""

    if not isinstance(repo_url, str):
        print('Repository URL must be a string.')
        sys.exit(1)
    parts = urlparse(repo_url).path.strip('/').split('/')

    if len(parts) < 2:
        print('Invalid GitHub repository URL. Expected format: https://github.com/owner/repo')
        sys.exit(1)
    return parts[0], parts[1]


def parse_date(date_string):
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_string, '%Y-%m-%d')
    except ValueError:
        print(f'Invalid date format: {date_string}. Expected format: YYYY-MM-DD')
        sys.exit(1)


def fetch_pull_requests_in_range(owner, repo, token, start_date, end_date):
    """Get PRs created within the specified date range with creation dates."""
    print(f'\nFetching PRs for `{owner}/{repo}` created between {start_date.date()} and {end_date.date()}...')
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': f'Bearer {token}',
    }
    pull_requests = []
    page = 1
    has_next = True
    date_range = f'{start_date.date()}..{end_date.date()}'
    query = f'repo:{owner}/{repo}+type:pr+created:{date_range}'

    while has_next:
        url = f'https://api.github.com/search/issues?q={query}&per_page=100&page={page}'

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
        except requests.exceptions.HTTPError as http_err:
            print(f'HTTP error while fetching pull requests: {http_err}')
            sys.exit(1)
        except requests.RequestException as req_err:
            print(f'Error occurred while fetching pull requests: {req_err}')
            sys.exit(1)
        data = response.json()
        items = data.get('items', [])

        if not items:
            break

        for item in items:
            pull_requests.append({
                'number': item['number'],
                'created_at': datetime.strptime(item['created_at'], '%Y-%m-%dT%H:%M:%SZ')
            })
        has_next = 'next' in response.links
        page += 1
    return pull_requests


def get_first_review_time(owner, repo, pr_number, pr_created_at, token):
    """Get the time from PR creation to first review comment."""
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json',
    }
    comments_url = f'https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments'
    reviews_url = f'https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews'
    earliest_review_time = None
    
    try:
        response = requests.get(comments_url, headers=headers)
        response.raise_for_status()
        comments = response.json()
        
        if comments:
            first_comment_time = datetime.strptime(comments[0]['created_at'], '%Y-%m-%dT%H:%M:%SZ')
            earliest_review_time = first_comment_time
        response = requests.get(reviews_url, headers=headers)
        response.raise_for_status()
        reviews = response.json()
        
        if reviews:
            first_review_time = datetime.strptime(reviews[0]['submitted_at'], '%Y-%m-%dT%H:%M:%SZ')

            if earliest_review_time is None or first_review_time < earliest_review_time:
                earliest_review_time = first_review_time
        
        if earliest_review_time:
            business_hours = calculate_business_hours(pr_created_at, earliest_review_time)
            return business_hours 
    except requests.exceptions.HTTPError as http_err:
        print(f'HTTP error while fetching review time for PR #{pr_number}: {http_err}')
    except requests.exceptions.RequestException as req_err:
        print(f'Network error while fetching review time for PR #{pr_number}: {req_err}')
    except Exception as e:
        print(f'Unexpected error for PR #{pr_number}: {e}')
    return None


def get_review_comment_count(owner, repo, pr_number, token):
    """Fetch number of review comments on a PR."""
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json',
    }
    url = f'https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments'

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return len(response.json())
    except requests.exceptions.HTTPError as http_err:
        print(f'HTTP error occurred while fetching comments for PR #{pr_number}: {http_err}')
    except requests.exceptions.RequestException as req_err:
        print(f'Network error occurred while fetching comments for PR #{pr_number}: {req_err}')
    return 0


def get_command_line_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            'Analyze GitHub PR comments within a specified date range.\n\n'
            'Example usage:\n'
            '  python pr_comment_stats.py --repo https://github.com/owner/repo --token YOUR_GITHUB_PAT --start-date 2024-01-01 --end-date 2024-01-31\n'
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('--repo', required=True, help='GitHub repo URL (e.g. https://github.com/owner/repo)')
    parser.add_argument('--token', required=True, help='GitHub personal access token (PAT)')
    parser.add_argument('--start-date', required=True, help='Start date in YYYY-MM-DD format (e.g. 2024-01-01)')
    parser.add_argument('--end-date', required=True, help='End date in YYYY-MM-DD format (e.g. 2024-01-31)')
    return parser.parse_args()


def main():
    args = get_command_line_args()
    owner, repo = extract_repo_info(args.repo)

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)

    if start_date > end_date:
        print('Error: Start date must be before or equal to end date.')
        sys.exit(1)
    pull_requests = fetch_pull_requests_in_range(owner, repo, args.token, start_date, end_date)

    if not pull_requests:
        print(f'No PRs found between {start_date.date()} and {end_date.date()}.')
        return
    comment_counts = []
    review_times = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        comment_workers = [
            executor.submit(get_review_comment_count, owner, repo, pr['number'], args.token)
            for pr in pull_requests
        ]
        review_time_workers = [
            executor.submit(get_first_review_time, owner, repo, pr['number'], pr['created_at'], args.token)
            for pr in pull_requests
        ]
        comment_counts.extend([worker.result() for worker in comment_workers])
        review_times.extend([worker.result() for worker in review_time_workers])

    prs_with_activity = []
    activity_comment_counts = []
    activity_review_times = []

    for i, pr in enumerate(pull_requests):
        has_comments = comment_counts[i] > 0
        has_reviews = review_times[i] is not None
        
        if has_comments or has_reviews:
            prs_with_activity.append(pr)
            activity_comment_counts.append(comment_counts[i])
            activity_review_times.append(review_times[i])
    comment_stats = ""
    review_stats = ""

    if activity_comment_counts:
        avg_comments = sum(activity_comment_counts) / len(activity_comment_counts)
        comment_stats = (
            f'• Mean comments: {avg_comments:.1f}\n'
            f'• Max comments: {max(activity_comment_counts)}\n'
            f'• Min comments: {min(activity_comment_counts)}'
        )
    else:
        comment_stats = '• No comments found on PRs'
    valid_activity_review_times = [rt for rt in activity_review_times if rt is not None]

    if valid_activity_review_times:
        avg_review_time = sum(valid_activity_review_times) / len(valid_activity_review_times)
        review_stats = f'• Avg review time: {avg_review_time:.1f} business hours (excluding weekends)'
    else:
        review_stats = '• Avg review time: No reviews found on any PRs'
    
    print(
        f'PR Comment Stats for {start_date.date()} to {end_date.date()}:\n'
        f'• PRs with activity: {len(prs_with_activity)}\n'
        f'{comment_stats}\n'
        f'{review_stats}'
    )


if __name__ == '__main__':
    main()
