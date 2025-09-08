============================================================
:bar_chart: PR COM

# Enhanced PR Comment Analysis

This directory contains an advanced script and GitHub Action workflow to analyze PR comments from the previous month with AI-powered insights.

## 🚀 Features

### **Enhanced Code Metrics**
- **Average Review Time**: Time from PR creation to first review comment
- **Comments per PR**: Mean, Min, Max statistics
- **Day-of-week Analysis**: PR creation patterns

### **AI-Powered Analysis** (with Gemini API)
- **Issue Type Classification**: Automatically categorizes comments into:
  - Style (code formatting, naming conventions)
  - Design (architecture, design patterns)
  - Performance (optimization suggestions)
  - Security (vulnerabilities, best practices)
  - Logic (business logic, algorithm correctness)
  - Other (documentation, tests)
- **Observability Insights**: AI-generated patterns and recommendations

### **Data Export**
- **Comments Export**: Save all comments to JSON file with metadata
- **Structured Data**: Complete comment details including author, timestamps, file paths

## 📁 Files
- `scripts/pr_comment_analyzer.py` - The enhanced analysis script
- `README.md` - This documentation file

**Dependencies:** The script requires the `requests` library, which is installed automatically in the GitHub Action.

## 🔗 GitHub Action Workflow
The workflow is located at `.github/workflows/pr-comment-analysis.yml` and:
- **Runs automatically** every month on the 1st at 2 AM UTC
- **Can be triggered manually** via the GitHub Actions tab
- **Saves results** as artifacts with 365-day retention
- **Uses the built-in `GITHUB_TOKEN`** for authentication
- **Supports Gemini API** for AI analysis (optional)
- **Requires read permissions** for repository contents and pull requests

## 💻 Manual Usage

### **Basic Analysis (without AI)**
```bash
# Install dependencies
pip install requests

# Run basic analysis
python scripts/pr_comment_analyzer.py \
  --repo https://github.com/owner/repo \
  --token YOUR_GITHUB_PAT
```

### **Enhanced Analysis (with AI)**
```bash
# Run with AI-powered insights
python scripts/pr_comment_analyzer.py \
  --repo https://github.com/owner/repo \
  --token YOUR_GITHUB_PAT \
  --gemini-key YOUR_GEMINI_API_KEY
```

### **Export Comments**
```bash
# Save all comments to JSON file
python scripts/pr_comment_analyzer.py \
  --repo https://github.com/owner/repo \
  --token YOUR_GITHUB_PAT \
  --gemini-key YOUR_GEMINI_API_KEY \
  --save-comments
```

## 📊 Output Format

### **Console Output**
