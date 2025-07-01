# PR Comment Analysis
This directory contains a script and GitHub Action workflow to analyze PR comments from the previous month.
## Files
- `scripts/pr_comment_analyzer.py` - The main analysis script
- `README.md` - This documentation file

**Note:** The script only requires the `requests` library, which is installed directly in the GitHub Action.
## GitHub Action Workflow
The workflow is located at `.github/workflows/pr-comment-analysis.yml` and:
- **Runs automatically** every month on the 1st at 2 AM UTC
- **Can be triggered manually** via the GitHub Actions tab
- **Saves results** as artifacts with 365-day retention
- **Uses the built-in `GITHUB_TOKEN`** for authentication
- **Requires read permissions** for repository contents and pull requests
## Manual Usage
To run the script manually:
```bash
# Install dependencies
pip install requests
# Run the analysis
python scripts/pr_comment_analyzer.py \
  --repo https://github.com/owner/repo \
  --token YOUR_GITHUB_PAT
```
## Output
The script outputs:
- Mean number of comments per PR
- Minimum number of comments
- Maximum number of comments
## GitHub Action Results
When the GitHub Action runs:
1. Results are saved as a markdown file with timestamp
2. The file is uploaded as an artifact named `pr-comment-analysis-{run_number}`
3. A summary is created in the GitHub Actions run summary
4. Artifacts are retained for 365 days
## Permissions
The workflow uses the built-in `GITHUB_TOKEN` with explicit read permissions for repository contents and pull requests. No additional setup is required for basic usage.
## Customization
To modify the schedule, edit the `cron` expression in `.github/workflows/pr-comment-analysis.yml`:
```yaml
schedule:
  - cron: '0 2 1 * *'  # Monthly on the 1st at 2 AM UTC
```
Common cron patterns:
- `'0 2 * * *'` - Daily at 2 AM
- `'0 2 * * 1'` - Weekly on Mondays at 2 AM
- `'0 2 1 * *'` - Monthly on the 1st at 2 AM
