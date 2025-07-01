"""
Script to analyze GitHub PR comments from the previous month.
Usage:
    python pr_comment_stats.py --repo https://github.com/owner/repo --token YOUR_GITHUB_PAT
"""
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests


def extract_repo_info(repo_url):
    """Extract owner and repo name from GitHub URL."""
    if not isinstance(repo_url, str):
        print('Repository URL must be a string.')
        sys.exit(1)
    parts = urlparse(repo_url).path.strip('/').split('/')
    if len(parts) < 2:
        print(
            'Invalid GitHub repository URL. Expected format: https://github.com/owner/repo')
        sys.exit(1)
    return parts[0], parts[1]


def fetch_previous_month_pull_requests(owner, repo, token):
    """Get PRs created in previous month."""
    start_date, end_date = get_previous_month_dates()
    print(
        f':mag: Fetching PRs for `{owner}/{repo}` created between {start_date.date()} and {end_date.date()}...')
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
        pull_requests.extend([item['number'] for item in items])
        has_next = 'next' in response.links
        page += 1
    return pull_requests


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
        print(
            f'HTTP error occurred while fetching comments for PR #{pr_number}: {http_err}')
    except requests.exceptions.RequestException as req_err:
        print(
            f'Network error occurred while fetching comments for PR #{pr_number}: {req_err}')
    return 0


def get_previous_month_dates():
    first_day_this_month = datetime.today().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    end_last_month = first_day_this_month - timedelta(microseconds=1)
    start_last_month = end_last_month.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    return start_last_month, end_last_month


def get_command_line_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            'Analyze GitHub PR comments for the previous month.\n\n'
            'Example usage:\n'
            '  python pr_comment_stats.py --repo https://github.com/owner/repo --token YOUR_GITHUB_PAT\n'
            '  python pr_comment_stats.py --repo https://github.com/owner/repo '
            '--token YOUR_GITHUB_PAT --test-date 2024-12-01'
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('--repo', required=True,
                        help='GitHub repo URL (e.g. https://github.com/owner/repo)')
    parser.add_argument('--token', required=True,
                        help='GitHub personal access token (PAT)')
    parser.add_argument(
        '--test-date',
        help='Test with a specific date (YYYY-MM-DD format) to analyze PRs from that month'
    )
    return parser.parse_args()


def main():
    args = get_command_line_args()
    owner, repo = extract_repo_info(args.repo)
    pull_requests = fetch_previous_month_pull_requests(owner, repo, args.token)
    if not pull_requests:
        print('No PRs found in the previous month.')
        return
    comment_counts = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        workers = [
            executor.submit(get_review_comment_count, owner,
                            repo, pr_number, args.token)
            for pr_number in pull_requests
        ]
        comment_counts.extend([worker.result() for worker in workers])
    if not comment_counts:
        print('No comments found on PRs.')
        return
    avg_comments = sum(comment_counts) / len(comment_counts)
    stats_msg = (
        f':bar_chart: PR Comment Stats:\n'
        f'• Mean: {round(avg_comments)}\n'
        f'• Min: {min(comment_counts)}\n'
        f'• Max: {max(comment_counts)}'
    )
    print(stats_msg)


if __name__ == '__main__':
    main()
