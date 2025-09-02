"""
Enhanced Script to analyze GitHub PR comments with AI-powered insights.
Usage:
    python pr_comment_analyzer.py --repo https://github.com/owner/repo --token YOUR_GITHUB_PAT --gemini-key YOUR_GEMINI_API_KEY
"""
import argparse
import json
import re
import statistics
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
        print('Invalid GitHub repository URL. Expected format: https://github.com/owner/repo')
        sys.exit(1)
    return parts[0], parts[1]


def get_previous_month_dates():
    """Calculate previous month's date range."""
    first_day_this_month = datetime.today().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    end_last_month = first_day_this_month - timedelta(microseconds=1)
    start_last_month = end_last_month.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    return start_last_month, end_last_month


def fetch_previous_month_pull_requests(owner, repo, token):
    """Get PRs created in previous month with detailed information."""
    start_date, end_date = get_previous_month_dates()
    print(f':mag: Fetching PRs for `{owner}/{repo}` created between {start_date.date()} and {end_date.date()}...')
    
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
            
        # Extract PR details including creation time
        for item in items:
            pull_requests.append({
                'number': item['number'],
                'created_at': item['created_at'],
                'title': item['title'],
                'user': item['user']['login']
            })
            
        has_next = 'next' in response.links
        page += 1
    
    return pull_requests


def get_pr_detailed_info(owner, repo, pr_number, token):
    """Fetch detailed PR information including comments and timing."""
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json',
    }
    
    # Get PR details
    pr_url = f'https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}'
    comments_url = f'https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments'
    
    try:
        # Fetch PR details and comments concurrently
        pr_response = requests.get(pr_url, headers=headers)
        comments_response = requests.get(comments_url, headers=headers)
        
        pr_response.raise_for_status()
        comments_response.raise_for_status()
        
        pr_data = pr_response.json()
        comments_data = comments_response.json()
        
        # Calculate review time (time from PR creation to first comment)
        created_at = datetime.fromisoformat(pr_data['created_at'].replace('Z', '+00:00'))
        first_comment_time = None
        review_time_hours = None
        
        if comments_data:
            first_comment = min(comments_data, key=lambda x: x['created_at'])
            first_comment_time = datetime.fromisoformat(first_comment['created_at'].replace('Z', '+00:00'))
            review_time_hours = (first_comment_time - created_at).total_seconds() / 3600
        
        # Extract comment texts for AI analysis
        comment_texts = [comment['body'] for comment in comments_data if comment['body'].strip()]
        
        return {
            'pr_number': pr_number,
            'title': pr_data['title'],
            'created_at': created_at,
            'first_comment_time': first_comment_time,
            'review_time_hours': review_time_hours,
            'comment_count': len(comments_data),
            'comment_texts': comment_texts,
            'created_day_of_week': created_at.strftime('%A'),
            'all_comments': comments_data  # Include full comment data
        }
        
    except requests.exceptions.HTTPError as http_err:
        print(f'HTTP error occurred while fetching details for PR #{pr_number}: {http_err}')
    except requests.exceptions.RequestException as req_err:
        print(f'Network error occurred while fetching details for PR #{pr_number}: {req_err}')
    except Exception as e:
        print(f'Error processing PR #{pr_number}: {e}')
    
    return None


def save_comments_to_file(pr_details, owner, repo):
    """Save all comments to a JSON file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"pr_comments_{owner}_{repo}_{timestamp}.json"
    
    # Prepare data for export
    export_data = {
        'metadata': {
            'repository': f"{owner}/{repo}",
            'analysis_date': datetime.now().isoformat(),
            'total_prs': len(pr_details),
            'total_comments': sum(pr['comment_count'] for pr in pr_details)
        },
        'pull_requests': []
    }
    
    for pr in pr_details:
        pr_data = {
            'pr_number': pr['pr_number'],
            'title': pr['title'],
            'created_at': pr['created_at'].isoformat(),
            'created_day_of_week': pr['created_day_of_week'],
            'review_time_hours': pr['review_time_hours'],
            'comment_count': pr['comment_count'],
            'comments': []
        }
        
        # Add all comments with metadata
        for comment in pr['all_comments']:
            comment_data = {
                'id': comment.get('id'),
                'body': comment.get('body'),
                'created_at': comment.get('created_at'),
                'updated_at': comment.get('updated_at'),
                'author': {
                    'login': comment.get('user', {}).get('login'),
                    'id': comment.get('user', {}).get('id')
                },
                'path': comment.get('path'),
                'position': comment.get('position'),
                'line': comment.get('line'),
                'original_line': comment.get('original_line')
            }
            pr_data['comments'].append(comment_data)
        
        export_data['pull_requests'].append(pr_data)
    
    # Write to file
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        print(f':floppy_disk: All comments saved to: {filename}')
        return filename
    except Exception as e:
        print(f'Error saving comments to file: {e}')
        return None


def analyze_comments_with_gemini(comments_batch, gemini_api_key):
    """Analyze comments using Gemini API to classify issue types."""
    if not comments_batch or not gemini_api_key:
        return {'style': 0, 'design': 0, 'performance': 0, 'security': 0, 'logic': 0, 'other': 0}
    
    # Combine all comments for analysis
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
        # Updated to use Gemini 2.0 Flash (latest available)
        url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={gemini_api_key}'
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        result = response.json()
        
        if 'candidates' in result and result['candidates']:
            candidate = result['candidates'][0]
            if 'content' in candidate and 'parts' in candidate['content']:
                text = candidate['content']['parts'][0]['text']
                
                # Extract JSON from the response
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    categories = json.loads(json_match.group())
                    
                    # Ensure percentages sum to 100
                    total = sum(categories.values())
                    if total > 0:
                        categories = {k: round((v/total) * 100) for k, v in categories.items()}
                    
                    return categories
                
    except Exception as e:
        print(f'Error analyzing comments with Gemini: {e}')
    
    # Fallback classification
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
        # Updated to use Gemini 2.0 Flash (latest available)
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
        description='Enhanced GitHub PR comment analyzer with AI insights',
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('--repo', required=True,
                        help='GitHub repo URL (e.g. https://github.com/owner/repo)')
    parser.add_argument('--token', required=True,
                        help='GitHub personal access token (PAT)')
    parser.add_argument('--gemini-key', 
                        help='Google Gemini API key for AI analysis')
    parser.add_argument('--test-date',
                        help='Test with a specific date (YYYY-MM-DD format)')
    parser.add_argument('--save-comments', action='store_true',
                        help='Save all comments to a JSON file')
    return parser.parse_args()


def main():
    args = get_command_line_args()
    owner, repo = extract_repo_info(args.repo)
    
    # Fetch PRs from previous month
    pull_requests = fetch_previous_month_pull_requests(owner, repo, args.token)
    if not pull_requests:
        print('No PRs found in the previous month.')
        return
    
    print(f':mag: Analyzing {len(pull_requests)} PRs...')
    
    # Fetch detailed information for each PR
    pr_details = []
    all_comments = []
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        workers = [
            executor.submit(get_pr_detailed_info, owner, repo, pr['number'], args.token)
            for pr in pull_requests
        ]
        
        for worker in workers:
            result = worker.result()
            if result:
                pr_details.append(result)
                all_comments.extend(result['comment_texts'])
    
    if not pr_details:
        print('No PR details could be fetched.')
        return
    
    # Save comments to file if requested
    if args.save_comments:
        save_comments_to_file(pr_details, owner, repo)
    
    # Calculate metrics
    comment_counts = [pr['comment_count'] for pr in pr_details]
    review_times = [pr['review_time_hours'] for pr in pr_details if pr['review_time_hours'] is not None]
    
    # Basic stats
    mean_comments = round(statistics.mean(comment_counts)) if comment_counts else 0
    min_comments = min(comment_counts) if comment_counts else 0
    max_comments = max(comment_counts) if comment_counts else 0
    
    # Review time stats
    avg_review_time_hours = round(statistics.mean(review_times), 1) if review_times else 0
    
    # AI Analysis
    print(':robot: Analyzing comment patterns with AI...')
    
    # Analyze comments in batches to avoid API limits
    issue_types = {'style': 0, 'design': 0, 'performance': 0, 'security': 0, 'logic': 0, 'other': 0}
    
    if args.gemini_key and all_comments:
        # Process comments in batches of 20
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
        
        # Normalize to percentages
        if total_weight > 0:
            issue_types = {k: round(v / total_weight) for k, v in issue_types.items()}
            
            # Ensure they sum to 100
            total_pct = sum(issue_types.values())
            if total_pct != 100 and total_pct > 0:
                # Adjust the largest category
                largest_cat = max(issue_types, key=issue_types.get)
                issue_types[largest_cat] += 100 - total_pct
    
    # Generate summary for observations
    day_counts = {}
    for pr in pr_details:
        day = pr['created_day_of_week']
        day_counts[day] = day_counts.get(day, 0) + 1
    
    summary_data = {
        'total_prs': len(pr_details),
        'avg_review_time_hours': avg_review_time_hours,
        'mean_comments': mean_comments,
        'day_distribution': day_counts,
        'issue_types': issue_types
    }
    
    observations = generate_observations_with_gemini(str(summary_data), args.gemini_key)
    
    # Output results
    print('\n' + '='*60)
    print(':bar_chart: PR COMMENT ANALYSIS REPORT')
    print('='*60)
    
    print(f'\n:clock1: Code metrics :')
    print(f'• Avg Review Time: {avg_review_time_hours} hours (time from PR creation to first review comment)')
    print(f'• Comments per PR: Mean = {mean_comments}, Min = {min_comments}, Max = {max_comments}')
    
    print(f'\n:label: Issue Types:')
    issue_type_str = ', '.join([f'{k.title()} = {v}%' for k, v in issue_types.items() if v > 0])
    print(f'• {issue_type_str}')
    
    print(f'\n:eyes: Observations:')
    print(f'• {observations}')
    
    print('\n' + '='*60)


if __name__ == '__main__':
    main()
