"""
Script to analyze GitHub PR comments within a specified date range.
Usage:
    python pr_comment_stats.py --repo https://github.com/owner/repo --token YOUR_GITHUB_PAT --start-date 2024-01-01 --end-date 2024-01-31
"""
import argparse
import json
import re
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
        comments = response.json()
        return {
            'pr_number': pr_number,
            'comment_count': len(comments),
            'comments': [comment.get('body', '') for comment in comments]
        }
    except requests.exceptions.HTTPError as http_err:
        print(f'HTTP error occurred while fetching comments for PR #{pr_number}: {http_err}')
    except requests.exceptions.RequestException as req_err:
        print(f'Network error occurred while fetching comments for PR #{pr_number}: {req_err}')
    return 0


def analyze_comments_with_gemini(comments_batch, gemini_api_key):
    """Analyze comments using Gemini API to classify issue types."""
    if not comments_batch or not gemini_api_key:
        return {'style': 0, 'design': 0, 'performance': 0, 'security': 0, 'logic': 0, 'other': 0}
    
    combined_comments = "\n---\n".join(comments_batch)
    
    prompt = f"""
    Analyze these GitHub PR review comments and classify them into categories. 
    Return ONLY a JSON object with percentages that sum to 100:

    Comments to analyze:
    {combined_comments}

    Classify each comment into one of these categories:
    - style: Code formatting, naming conventions, syntax style
    - design: Architecture, design patterns, code structure
    - performance: Performance improvements, optimization suggestions
    - security: Security vulnerabilities, best practices
    - logic: Business logic, algorithm correctness, functionality
    - other: Documentation, tests, or anything else

    Return format (percentages must sum to 100):
    {{"style": 30, "design": 25, "performance": 15, "security": 10, "logic": 15, "other": 5}}
    """
    
    headers = {
        'Content-Type': 'application/json',
    }
    
    payload = {
        'contents': [{
            'parts': [{'text': prompt}]
        }],
        'generationConfig': {
            'temperature': 0.1,
            'topK': 1,
            'topP': 1,
            'maxOutputTokens': 200,
        }
    }
    
    try:
        url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={gemini_api_key}'
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        result = response.json()
        
        if 'candidates' in result and result['candidates']:
            candidate = result['candidates'][0]
            if 'content' in candidate and 'parts' in candidate['content']:
                text = candidate['content']['parts'][0]['text']
                
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    categories = json.loads(json_match.group())
                    
                    total = sum(categories.values())
                    if total > 0:
                        categories = {k: round((v/total) * 100) for k, v in categories.items()}
                    
                    return categories
                
    except Exception as e:
        print(f'Error analyzing comments with Gemini: {e}')
    
    return {'style': 20, 'design': 20, 'performance': 15, 'security': 15, 'logic': 20, 'other': 10}


def generate_observations_with_gemini(pr_data_summary, gemini_api_key):
    """Generate observability insights using Gemini API."""
    if not gemini_api_key:
        return "AI analysis not available (no Gemini API key provided)"
    
    prompt = f"""
    Based on this GitHub PR analysis data, provide 2-3 key observations about patterns and insights:

    {pr_data_summary}

    Focus on:
    - Review time patterns (fast/slow reviews)
    - Comment distribution patterns
    - Day-of-week trends
    - Any notable patterns in PR activity

    Keep observations concise and actionable. Format as bullet points.
    """
    
    headers = {'Content-Type': 'application/json'}
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.3,
            'maxOutputTokens': 300,
        }
    }
    
    try:
        url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={gemini_api_key}'
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        result = response.json()
        if 'candidates' in result and result['candidates']:
            candidate = result['candidates'][0]
            if 'content' in candidate and 'parts' in candidate['content']:
                return candidate['content']['parts'][0]['text'].strip()
            
    except Exception as e:
        print(f'Error generating observations with Gemini: {e}')
    
    return "Unable to generate AI-powered observations"


def get_command_line_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            'Analyze GitHub PR comments within a specified date range with AI-powered insights.\n\n'
            'Example usage:\n'
            '  python pr_comment_stats.py --repo https://github.com/owner/repo --token YOUR_GITHUB_PAT --start-date 2024-01-01 --end-date 2024-01-31\n'
            '  python pr_comment_stats.py --repo https://github.com/owner/repo --token YOUR_GITHUB_PAT --start-date 2024-01-01 --end-date 2024-01-31 --gemini-key YOUR_GEMINI_API_KEY\n'
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('--repo', required=True, help='GitHub repo URL (e.g. https://github.com/owner/repo)')
    parser.add_argument('--token', required=True, help='GitHub personal access token (PAT)')
    parser.add_argument('--start-date', required=True, help='Start date in YYYY-MM-DD format (e.g. 2024-01-01)')
    parser.add_argument('--end-date', required=True, help='End date in YYYY-MM-DD format (e.g. 2024-01-31)')
    parser.add_argument('--gemini-key', help='Google Gemini API key for AI analysis')
    return parser.parse_args()


def write_results_to_file(repo, start_date, end_date, comments_data):
    repo_file_name = repo.replace('/', '_')
    output_file_name = f'{repo_file_name}-{start_date.date()}_{end_date.date()}.json'
    comments_to_save = []

    for pr_data in comments_data:
        comments_to_save.append({
            'pr_number': pr_data['pr_number'],
            'comments': pr_data['comments']
        })

    with open(output_file_name, 'w', encoding='utf-8') as f:
        json.dump(comments_to_save, f, indent=2)
    print(f'\nSaved PR comments to {output_file_name}')

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
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        comment_workers = [
            executor.submit(get_review_comment_count, owner, repo, pr['number'], args.token)
            for pr in pull_requests
        ]
        review_time_workers = [
            executor.submit(get_first_review_time, owner, repo, pr['number'], pr['created_at'], args.token)
            for pr in pull_requests
        ]
        comment_results = [worker.result() for worker in comment_workers]
        review_times = [worker.result() for worker in review_time_workers]
    
    comment_counts = [result['comment_count'] for result in comment_results]
    all_comments_data = [result for result in comment_results if result['comments']]
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
    
    print(':robot: Analyzing comment patterns with AI...')
    
    all_comments = []
    for result in comment_results:
        all_comments.extend(result['comments'])
    
    issue_types = {'style': 0, 'design': 0, 'performance': 0, 'security': 0, 'logic': 0, 'other': 0}
    
    if args.gemini_key and all_comments:
        batch_size = 20
        total_weight = 0
        
        for i in range(0, len(all_comments), batch_size):
            batch = all_comments[i:i + batch_size]
            if batch:
                batch_results = analyze_comments_with_gemini(batch, args.gemini_key)
                batch_weight = len(batch)
                total_weight += batch_weight
                
                for category, percentage in batch_results.items():
                    issue_types[category] += percentage * batch_weight
        
        if total_weight > 0:
            issue_types = {k: round(v / total_weight) for k, v in issue_types.items()}
            
            total_pct = sum(issue_types.values())
            if total_pct != 100 and total_pct > 0:
                largest_cat = max(issue_types, key=issue_types.get)
                issue_types[largest_cat] += 100 - total_pct
    
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
    
    day_counts = {}
    for pr in prs_with_activity:
        day = pr['created_at'].strftime('%A')
        day_counts[day] = day_counts.get(day, 0) + 1
    
    summary_data = {
        'total_prs': len(prs_with_activity),
        'avg_review_time_hours': avg_review_time if valid_activity_review_times else 0,
        'mean_comments': avg_comments if activity_comment_counts else 0,
        'day_distribution': day_counts,
        'issue_types': issue_types
    }
    
    observations = generate_observations_with_gemini(str(summary_data), args.gemini_key)
    
    write_results_to_file(repo, start_date, end_date, all_comments_data)
    
    print('\n' + '='*60)
    print(':bar_chart: PR COMMENT ANALYSIS REPORT')
    print('='*60)
    
    print('\n:clock1: Code metrics:')
    print(f'• PRs with activity: {len(prs_with_activity)}')
    print(f'{comment_stats}')
    print(f'{review_stats}')
    
    if args.gemini_key:
        print('\n:label: Issue Types:')
        issue_type_str = ', '.join([f'{k.title()} = {v}%' for k, v in issue_types.items() if v > 0])
        print(f'• {issue_type_str}')
        
        print('\n:eyes: Observations:')
        print(f'• {observations}')
    
    print('\n' + '='*60)


if __name__ == '__main__':
    main()
