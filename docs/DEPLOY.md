# Deploying Ekalavya

Two ways to run it:

- **Local self-host (open-source, single-user)** — just you, no server. Skip to [Local self-host](#local-self-host).
- **Multi-user (private, AWS Lightsail)** — you + a couple of trusted people, behind HTTPS + login. That's the rest of this doc.

The design target is a **small, private, trusted** deployment (2–3 accounts, no public signup). Everything below reflects that scope. Before opening it to anyone untrusted or the public internet, do the **[bubblewrap sandbox jail (#49)](#before-public-exposure)** first.

---

## Multi-user deployment (AWS Lightsail)

### 0. Provision
- A Lightsail instance (Ubuntu LTS), a **static IP**, and a domain with a DNS **A record** → that IP.
- Open ports 80 + 443 in the Lightsail firewall. Do **not** expose the app port (4646).

### 1. Install
```bash
sudo adduser --system --group eklavya
sudo mkdir -p /opt/eklavya /var/lib/eklavya/data /etc/eklavya
sudo chown -R eklavya:eklavya /opt/eklavya /var/lib/eklavya

# uv (as the eklavya user or system-wide)
curl -LsSf https://astral.sh/uv/install.sh | sh   # → /usr/local/bin/uv (adjust ExecStart path if different)

# code
cd /opt/eklavya
git clone https://github.com/govinda610/ekalavya.git eklavya-ai-coding-tutor
cd eklavya-ai-coding-tutor
uv sync --extra agent --extra web
```

### 2. Secrets + env
Create `/etc/eklavya/eklavya.env` (chmod 600, owned by eklavya — **never** in git):
```ini
# fail-loud: the app refuses to start in multi-user mode without this
EKLAVYA_SECRET_KEY=<paste `python -c "import secrets;print(secrets.token_urlsafe(48))"`>
# provider keys (at least one)
EKLAVYA_GLM_API_KEY=...
EKLAVYA_MINIMAX_API_KEY=...
EKLAVYA_QWEN_API_KEY=...
EKLAVYA_KIMI_API_KEY=...
# optional: live web search for fresh interview questions
TAVILY_API_KEY=...
# SERPER_API_KEY=...   # fallback if Tavily isn't set
```
`EKLAVYA_MULTIUSER=1` and `EKLAVYA_DATA_ROOT=/var/lib/eklavya/data` are set in the systemd unit.

### 3. Create accounts (no public signup)
```bash
sudo -u eklavya EKLAVYA_DATA_ROOT=/var/lib/eklavya/data \
  uv run --project /opt/eklavya/eklavya-ai-coding-tutor eklavya adduser --email you@example.com
# repeat for each trusted user
```

### 4. Migrate your existing data (once, for your own account)
Moves this machine's `~/.eklavya` into the multi-user layout for your account. **Copy-not-move; the original is never touched (fully reversible).** Stop the app first.
```bash
# rehearse (copies, verifies parity, then removes the copy — proves it works)
EKLAVYA_DATA_ROOT=/var/lib/eklavya/data uv run eklavya migrate --email you@example.com --dry-run
# for real
EKLAVYA_DATA_ROOT=/var/lib/eklavya/data uv run eklavya migrate --email you@example.com
```
It verifies row-for-row parity across every table + byte-identical profile before keeping the copy, and aborts (leaving the original intact) on any mismatch. After first login, confirm your curriculum/ratings/chats are all there.

> Note: your real learner data lives in `~/.eklavya` on *your laptop*; you'd run this migration on the box that holds the data you want to carry over (copy `~/.eklavya` to the server first if migrating your laptop's data).

### 5. Run it (systemd, single worker)
```bash
sudo cp deploy/eklavya.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now eklavya
sudo systemctl status eklavya
```
One process = one worker on purpose (the in-memory login throttle is per-process).

### 6. HTTPS + headers (Caddy)
```bash
# install Caddy (see caddyserver.com), then:
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile   # edit the domain first
sudo systemctl reload caddy
```
Caddy auto-provisions the TLS cert and adds the security headers. The app stays bound to `127.0.0.1:4646`; only Caddy is internet-facing.

### 7. Security checklist (#52)
- [x] **Single worker** — `uvicorn.run(app)` is one process (systemd runs exactly one).
- [x] **HTTPS + security headers** — Caddy (HSTS, nosniff, DENY frame, referrer policy).
- [x] **Fail-loud secret** — app won't start multi-user without `EKLAVYA_SECRET_KEY`.
- [x] **No public signup** — accounts only via `eklavya adduser`.
- [x] **Per-user data isolation** — contextvar + per-user SQLite (F1/F4/F5/F7 fixed).
- [x] **Login throttle** — per (email, ip); behind Caddy the ip is the proxy's, so it's effectively per-email, which is fine for the 2-user scope. *(Optional hardening: read `X-Forwarded-For` in the login route to restore per-source-IP.)*
- [ ] **run_bash jail (#49)** — deferred for the private stage; **required before any public/untrusted exposure.**
- Keep `uv sync` deps patched.

### Rollback
Your original `~/.eklavya` is never modified by the migration. To roll back, stop the service and point back at single-user mode (unset `EKLAVYA_MULTIUSER`) — your laptop data is untouched.

---

## Local self-host

Open-source, single-user, no server, no auth:
```bash
uv sync --extra agent --extra tui --extra web
cp .env.example .env          # add a provider key
uv run eklavya                # onboards on first run, else practice
```
Your data stays in `~/.eklavya`. `EKLAVYA_MULTIUSER` unset = single-user; nothing here changes.

---

## Before public exposure
This deployment is scoped to **trusted** users. Before letting anyone untrusted in, do **#49 (bubblewrap jail for `run_bash`)** — until then the agent's shell is powerful and only network-gated, not OS-jailed. Also consider fronting Caddy with Cloudflare (free) for WAF/DDoS.
