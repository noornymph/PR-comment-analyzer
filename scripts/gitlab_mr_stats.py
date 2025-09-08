"""
Script to analyze GitLab MR (Merge Request) comments within a specified date range.
Usage:
    python gitlab_mr_stats.py --url https://gitlab.com/group/project --token YOUR_GITLAB_PAT --start-date 2024-01-01 --end-date 2024-01-31
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import quote, urlparse

import requests


def parse_gitlab_datetime(datetime_str):
    """Parse GitLab datetime string handling various formats."""
    clean_datetime = re.split(r'[+\-]\d{2}:\d{2}|Z', datetime_str)[0]

    try:
        return datetime.strptime(clean_datetime, '%Y-%m-%dT%H:%M:%S.%f')
    except ValueError:
        try:
            return datetime.strptime(clean_datetime, '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            return datetime.strptime(clean_datetime, '%Y-%m-%dT%H:%M')


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


def extract_project_info(gitlab_url):
    """Extract GitLab project path from URL."""
    if not isinstance(gitlab_url, str):
        print('GitLab URL must be a string.')
        sys.exit(1)

    parsed = urlparse(gitlab_url)
    if not parsed.netloc:
        print('Invalid GitLab URL. Expected format: https://gitlab.com/group/project')
        sys.exit(1)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    project_path = parsed.path.strip('/')

    if not project_path:
        print('Invalid GitLab project URL. Expected format: https://gitlab.com/group/project')
        sys.exit(1)
    
    return base_url, project_path


def parse_date(date_string):
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_string, '%Y-%m-%d')
    except ValueError:
        print(f'Invalid date format: {date_string}. Expected format: YYYY-MM-DD')
        sys.exit(1)


def fetch_merge_requests_in_range(base_url, project_path, token, start_date, end_date):
    """Get MRs created within the specified date range."""
    print(f'\nFetching MRs for project `{project_path}` created between {start_date.date()} and {end_date.date()}...')
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    merge_requests = []
    page = 1
    per_page = 100
    encoded_project_path = quote(project_path, safe='')
    
    while True:
        url = f'{base_url}/api/v4/projects/{encoded_project_path}/merge_requests'
        params = {
            'created_after': start_date.isoformat(),
            'created_before': end_date.isoformat(),
            'state': 'all',
            'per_page': per_page,
            'page': page
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
        except requests.exceptions.HTTPError as http_err:
            print(f'HTTP error while fetching merge requests: {http_err}')
            print(f'Response: {response.text}')
            sys.exit(1)
        except requests.RequestException as req_err:
            print(f'Error occurred while fetching merge requests: {req_err}')
            sys.exit(1)
        data = response.json()

        if not data:
            break

        for mr in data:
            merge_requests.append({
                'iid': mr['iid'],
                'created_at': parse_gitlab_datetime(mr['created_at'])
            })

        if len(data) < per_page:
            break
        page += 1
    return merge_requests


def get_first_review_time(base_url, project_path, mr_iid, mr_created_at, token):
    """Get the time from MR creation to first review activity (comments, approvals, etc.)."""
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    encoded_project_path = quote(project_path, safe='')
    notes_url = f'{base_url}/api/v4/projects/{encoded_project_path}/merge_requests/{mr_iid}/notes'
    mr_url = f'{base_url}/api/v4/projects/{encoded_project_path}/merge_requests/{mr_iid}'
    earliest_review_time = None
    review_activities = []
    
    try:
        response = requests.get(notes_url, headers=headers)
        response.raise_for_status()
        notes = response.json()
        
        for note in notes:
            note_time = parse_gitlab_datetime(note['created_at'])
            note_body = note.get('body', '').lower()
            is_system = note.get('system', False)

            is_review_activity = (
                not is_system or
                'approved this merge request' in note_body or
                'unapproved this merge request' in note_body or
                'requested changes' in note_body or
                'rejected' in note_body or
                'merged' in note_body or
                'closed' in note_body
            )
            is_review_request = 'requested review' in note_body or 'removed review request' in note_body
            
            if is_review_activity and not is_review_request:
                review_activities.append({
                    'type': 'system_note' if is_system else 'comment',
                    'time': note_time,
                    'body': note_body[:50] + '...' if len(note_body) > 50 else note_body
                })

        response = requests.get(mr_url, headers=headers)
        response.raise_for_status()
        mr_data = response.json()

        if mr_data.get('merge_status') == 'can_be_merged' or mr_data.get('detailed_merge_status') == 'mergeable':

            try:
                approvals_url = f'{base_url}/api/v4/projects/{encoded_project_path}/merge_requests/{mr_iid}/approvals'
                response = requests.get(approvals_url, headers=headers)
                if response.status_code == 200:
                    approvals_data = response.json()
                    approved_by = approvals_data.get('approved_by', [])
                    
                    for approval in approved_by:
                        if approval.get('created_at'):
                            approval_time = parse_gitlab_datetime(approval['created_at'])
                            review_activities.append({
                                'type': 'approval',
                                'time': approval_time,
                                'body': f"approved by {approval.get('user', {}).get('name', 'unknown')}"
                            })
            except:
                pass  # Approvals API might not be available

        if review_activities:
            review_activities.sort(key=lambda x: x['time'])
            earliest_review_time = review_activities[0]['time']
            
        if earliest_review_time:
            business_hours = calculate_business_hours(mr_created_at, earliest_review_time)
            return business_hours
            
    except requests.exceptions.HTTPError as http_err:
        print(f'HTTP error while fetching review time for MR !{mr_iid}: {http_err}')
    except requests.exceptions.RequestException as req_err:
        print(f'Network error while fetching review time for MR !{mr_iid}: {req_err}')
    except Exception as e:
        print(f'Unexpected error for MR !{mr_iid}: {e}')
    return None


def get_review_comment_count(base_url, project_path, mr_iid, token):
    """Fetch number of review comments on an MR."""
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    encoded_project_path = quote(project_path, safe='')
    notes_url = f'{base_url}/api/v4/projects/{encoded_project_path}/merge_requests/{mr_iid}/notes'
    
    try:
        response = requests.get(notes_url, headers=headers)
        response.raise_for_status()
        notes = response.json()
        user_notes = [note for note in notes if not note.get('system', False)]
        comment_count = len(user_notes)
        comment_texts = [note.get('body', '') for note in user_notes if note.get('body', '').strip()]
        return {
            'mr_iid': mr_iid,
            'comment_count': comment_count,
            'comments': comment_texts
        }
    except requests.exceptions.HTTPError as http_err:
        print(f'HTTP error occurred while fetching comments for MR !{mr_iid}: {http_err}')
    except requests.exceptions.RequestException as req_err:
        print(f'Network error occurred while fetching comments for MR !{mr_iid}: {req_err}')
    return {'mr_iid': mr_iid, 'comment_count': 0, 'comments': []}


def analyze_comments_with_gemini(comments_batch, gemini_api_key):
    """Analyze comments using Gemini API to classify issue types."""
    if not comments_batch or not gemini_api_key:
        return {'style': 0, 'design': 0, 'performance': 0, 'security': 0, 'logic': 0, 'other': 0}
    
    combined_comments = "\n---\n".join(comments_batch)
    
    prompt = f"""
    Analyze these GitLab MR review comments and classify them into categories. 
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


def generate_observations_with_gemini(mr_data_summary, gemini_api_key):
    """Generate observability insights using Gemini API."""
    if not gemini_api_key:
        return "AI analysis not available (no Gemini API key provided)"
    
    prompt = f"""
    Based on this GitLab MR analysis data, provide 2-3 key observations about patterns and insights:

    {mr_data_summary}

    Focus on:
    - Review time patterns (fast/slow reviews)
    - Comment distribution patterns
    - Day-of-week trends
    - Any notable patterns in MR activity

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
            'Analyze GitLab MR comments within a specified date range with AI-powered insights.\n\n'
            'Example usage:\n'
            '  python gitlab_mr_stats.py --url https://gitlab.com/group/project --token YOUR_GITLAB_PAT --start-date 2024-01-01 --end-date 2024-01-31\n'
            '  python gitlab_mr_stats.py --url https://gitlab.com/group/project --token YOUR_GITLAB_PAT --start-date 2024-01-01 --end-date 2024-01-31 --gemini-key YOUR_GEMINI_API_KEY\n'
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('--url', required=True, help='GitLab project URL (e.g. https://gitlab.com/group/project)')
    parser.add_argument('--token', required=True, help='GitLab personal access token (PAT)')
    parser.add_argument('--start-date', required=True, help='Start date in YYYY-MM-DD format (e.g. 2024-01-01)')
    parser.add_argument('--end-date', required=True, help='End date in YYYY-MM-DD format (e.g. 2024-01-31)')
    parser.add_argument('--gemini-key', help='Google Gemini API key for AI analysis')
    return parser.parse_args()


def main():
    args = get_command_line_args()
    base_url, project_path = extract_project_info(args.url)

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    
    if start_date > end_date:
        print('Error: Start date must be before or equal to end date.')
        sys.exit(1)
    merge_requests = fetch_merge_requests_in_range(base_url, project_path, args.token, start_date, end_date)

    if not merge_requests:
        print(f'No MRs found between {start_date.date()} and {end_date.date()}.')
        return
    comment_results = []
    review_times = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        comment_workers = [
            executor.submit(get_review_comment_count, base_url, project_path, mr['iid'], args.token)
            for mr in merge_requests
        ]
        review_time_workers = [
            executor.submit(get_first_review_time, base_url, project_path, mr['iid'], mr['created_at'], args.token)
            for mr in merge_requests
        ]
        comment_results.extend([worker.result() for worker in comment_workers])
        review_times.extend([worker.result() for worker in review_time_workers])

    comment_counts = [result['comment_count'] for result in comment_results]
    mrs_with_activity = []
    activity_comment_counts = []
    activity_review_times = []
    
    for i, mr in enumerate(merge_requests):
        has_comments = comment_counts[i] > 0
        has_reviews = review_times[i] is not None
        
        if has_comments or has_reviews:
            mrs_with_activity.append(mr)
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
        comment_stats = '• No comments found on MRs'
    valid_activity_review_times = [rt for rt in activity_review_times if rt is not None]

    if valid_activity_review_times:
        avg_review_time = sum(valid_activity_review_times) / len(valid_activity_review_times)
        review_stats = f'• Avg review time: {avg_review_time:.1f} business hours (excluding weekends)'
    else:
        review_stats = '• Avg review time: No reviews found on any MRs'
    
    day_counts = {}
    for mr in mrs_with_activity:
        day = mr['created_at'].strftime('%A')
        day_counts[day] = day_counts.get(day, 0) + 1
    
    summary_data = {
        'total_mrs': len(mrs_with_activity),
        'avg_review_time_hours': avg_review_time if valid_activity_review_times else 0,
        'mean_comments': avg_comments if activity_comment_counts else 0,
        'day_distribution': day_counts,
        'issue_types': issue_types
    }
    
    observations = generate_observations_with_gemini(str(summary_data), args.gemini_key)
    
    print('\n' + '='*60)
    print(':bar_chart: GITLAB MR COMMENT ANALYSIS REPORT')
    print('='*60)
    
    print('\n:clock1: Code metrics:')
    print(f'• MRs with activity: {len(mrs_with_activity)}')
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
