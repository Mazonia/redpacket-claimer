# Security Policy

## 🔒 Security Overview

Security and privacy are top priorities for **Binance Auto-Claimer**. Because this tool interacts with your Telegram account and Binance session locally, protecting your sensitive data is critical.

---

## 🛡️ Critical Security Practices

### 1. Credentials & Session Protection
- **Never commit `.env` or `*.session` files**: These files contain your private Telegram API credentials, phone number, and MTProto session key.
- **Browser Context Cookies (`./user_data/`)**: Contains your active Binance session cookies. Ensure this folder remains private and excluded from version control (`.gitignore` protects this by default).

### 2. Local Execution
- All code runs locally on your own machine.
- No credentials, tokens, or network requests are sent to third-party tracking services or external analytics servers.

---

## ⚠️ Reporting a Vulnerability

If you discover a security vulnerability within this project, please **do not** open a public issue.

Instead, please report it privately:
1. Contact the maintainers directly or send an email/message to the repository administrator.
2. Provide a detailed description of the vulnerability, including steps to reproduce or proof-of-concept code.
3. Allow reasonable time for the maintainers to address and patch the issue before public disclosure.

We appreciate your assistance in responsibly disclosing security issues to help keep the project and its users safe.
