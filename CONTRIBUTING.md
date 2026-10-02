# Contributing to Binance Auto-Claimer

Thank you for your interest in contributing to **Binance Auto-Claimer**! We welcome contributions from the community to help improve code quality, fix bugs, add new features, and enhance documentation.

---

## 🛠️ How to Get Started

### 1. Fork & Clone the Repository
Fork the repository on GitHub, then clone your fork locally:
```bash
git clone https://github.com/your-username/redpacket-claimer.git
cd redpacket-claimer
```

### 2. Set Up Your Environment
Create and activate a virtual environment, then install dependencies:
```bash
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium
```

### 3. Environment Configuration
Copy `.env.example` to `.env` and fill in your test credentials if needed:
```bash
cp .env.example .env
```

---

## 💡 Guidelines for Contributions

### Reporting Bugs
Before opening a new issue, please check existing issues to avoid duplicates. When filing a bug report, include:
- Operating System and Python version.
- Detailed steps to reproduce the issue.
- Expected behavior vs. actual behavior.
- Relevant error logs (ensure credentials and tokens are redacted!).

### Submitting Pull Requests (PRs)
1. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Write clean, readable code following PEP 8 guidelines.
3. Keep pull requests focused on a single topic/feature.
4. Run syntax checks and tests before submitting:
   ```bash
   python -m py_compile main.py redemption.py parser.py
   python scratch/test_lockout.py
   python scratch/test_backoff.py
   ```
5. Commit your changes with descriptive commit messages:
   ```bash
   git commit -m "feat: add support for new red packet format"
   ```
6. Push to your branch and open a Pull Request against `main`.

---

## 🔒 Security Best Practices

- **Never commit `.env` or session files (`*.session`)**: Check `git status` carefully before committing.
- Do not log sensitive credentials (e.g. API keys, phone numbers, auth cookies).

---

## 📜 Code of Conduct

Please note that this project operates under a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to abide by its terms.
