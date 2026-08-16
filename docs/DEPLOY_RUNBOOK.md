# Eklavya — Live Deployment Runbook (as-built)

> The **authoritative, as-built** record of the running private deployment: what's where, how it
> runs, and how to update / maintain / fix it. For the generic from-scratch guide see `DEPLOY.md`.
> **No secrets live in this file** — every credential is only in `/etc/eklavya.env` on the server
> (and mirrored in `~/eklavya-deploy.env` on Govind's Mac, both `chmod 600`, both git-ignored/outside git).

Deployed: 2026-08-16.

---

## 1. The facts (where everything is)

| Thing | Value |
|---|---|
| **URL** | https://eklavyatheaitutor.duckdns.org |
| **Cloud** | AWS Lightsail · Ubuntu 22.04 · 1 GB RAM / 2 vCPU / 40 GB · **ap-south-1 (Mumbai)** |
| **Public IP** | 43.205.76.228 (static, pinned in Lightsail) · DNS via DuckDNS |
| **SSH** | `ssh -i ~/.ssh/LightsailDefaultKey-ap-south-1.pem ubuntu@43.205.76.228` |
| **App code** | `/opt/eklavya/app` (git clone of `github.com/govinda610/ekalavya`, branch `main`) |
| **App data** | `/var/lib/eklavya` (`EKLAVYA_DATA_ROOT`) — per-user SQLite + artifacts, `chmod 700` |
| **Env file** | `/etc/eklavya.env` (`chmod 600`, root-owned) — all keys + config |
| **Runs as** | system user **`eklavya`** (low-privilege; home `/opt/eklavya`) |
| **App port** | `127.0.0.1:4646` (localhost only — never exposed) |
| **Service** | `systemd` unit `eklavya.service` |
| **Web/TLS** | nginx reverse proxy + certbot (Let's Encrypt); config `/etc/nginx/sites-available/eklavya` |
| **Provider** | primary **Qwen**, sticky failover → Kimi → GLM → MiniMax (all keys set) |
| **Admin** | `govindmittal610@gmail.com` (only this account sees the Admin page) |
| **Signups** | approval-gated (new users land pending; admin approves) |
| **Email** | Gmail SMTP (signup → admin, approval → user); no-ops if unset |

Co-tenant services on the same box (do **not** disturb): `nginx`, `wedding_backend.service`,
`srilanka.service`, `docker` (+ a librespeed container), the `govindkiginni.duckdns.org` site.

## 2. How it runs (request flow)

```
Browser ──DNS──▶ 43.205.76.228 ──443──▶ nginx (TLS termination, routes by domain)
                                          └─▶ proxy_pass 127.0.0.1:4646
                                                └─▶ uvicorn (systemd: eklavya.service, user=eklavya)
                                                      └─▶ FastAPI app → per-user SQLite in /var/lib/eklavya
                                                            └─▶ LLM providers (Qwen→Kimi→GLM→MiniMax)
```
- **nginx** does HTTPS + reverse-proxies only; the app is invisible to the internet (localhost bind + Lightsail firewall opens just 22/80/443).
- **systemd** keeps the app alive (`Restart=always`) and starts it on boot; it injects `/etc/eklavya.env`.
- **certbot** auto-renews the TLS cert (systemd timer).

## 3. Everyday operations (as `ubuntu`, via SSH; `sudo` is passwordless)

```bash
# status / health
sudo systemctl status eklavya
sudo journalctl -u eklavya -f            # live logs
curl -s -o /dev/null -w '%{http_code}\n' https://eklavyatheaitutor.duckdns.org/login   # expect 200

# restart / stop / start
sudo systemctl restart eklavya
sudo systemctl stop eklavya
sudo systemctl start eklavya
```

### Update to the latest code (after pushing to `main`)
```bash
sudo -u eklavya -H bash -lc 'cd /opt/eklavya/app && git pull && ~/.local/bin/uv sync --all-extras'
sudo systemctl restart eklavya
sudo journalctl -u eklavya -n 30         # confirm it came back
```
> Migrations are additive and run automatically on first use per user — no manual migrate step.

### Approve / manage users
- **Preferred:** log in as the admin (`govindmittal610@gmail.com`) → **Admin** in the nav → Approve/Reject.
- **From the shell (fallback):**
  ```bash
  # list pending
  sudo -u eklavya python3 -c "import sqlite3;print(sqlite3.connect('/var/lib/eklavya/users.db').execute(\"SELECT email,status FROM users WHERE status!='active'\").fetchall())"
  # approve
  sudo -u eklavya python3 -c "import sqlite3;c=sqlite3.connect('/var/lib/eklavya/users.db');c.execute(\"UPDATE users SET status='active' WHERE email='PERSON@example.com'\");c.commit()"
  ```
  (The Admin page also sends the approval email; the SQL path does not.)

### Change / add provider keys, SMTP, or any config
Secrets live only in `/etc/eklavya.env`. Easiest = edit `~/eklavya-deploy.env` on the Mac, then re-push it:
```bash
# on the Mac (never commit this file — it's in $HOME, outside the repo):
cat ~/eklavya-deploy.env | ssh -i ~/.ssh/LightsailDefaultKey-ap-south-1.pem ubuntu@43.205.76.228 \
  'sudo tee /etc/eklavya.env >/dev/null && sudo chmod 600 /etc/eklavya.env && sudo systemctl restart eklavya'
```
Or edit in place: `sudo nano /etc/eklavya.env` then `sudo systemctl restart eklavya`.
(Keep `EKLAVYA_SECRET_KEY` stable — changing it logs everyone out.)

### TLS
Auto-renews. Check: `sudo certbot certificates`. Force test: `sudo certbot renew --dry-run`.

## 4. Data safety & backups
- **Data** is at `/var/lib/eklavya` (owned by `eklavya`). The app also keeps per-user snapshots under
  each user's `backups/`.
- **Lightsail automatic snapshots** are ON (whole-box rollback point — the primary safety net).
- **Manual backup / download to the Mac:**
  ```bash
  ssh -i ~/.ssh/LightsailDefaultKey-ap-south-1.pem ubuntu@43.205.76.228 \
    'sudo tar -C /var/lib -czf /tmp/eklavya-data.tgz eklavya && sudo chown ubuntu /tmp/eklavya-data.tgz'
  scp -i ~/.ssh/LightsailDefaultKey-ap-south-1.pem ubuntu@43.205.76.228:/tmp/eklavya-data.tgz ~/eklavya-backups/
  ```
- **Restore:** stop the service, replace `/var/lib/eklavya` from a tarball/snapshot, `chown -R eklavya:eklavya`, restart.
- Govind's **original laptop data** (`~/.eklavya-data`) is the ultimate source of truth — the deploy is a verified copy; it was never modified.

## 5. Troubleshooting
| Symptom | Cause / fix |
|---|---|
| `502 Bad Gateway` | app is down/restarting → `sudo systemctl status eklavya` + `journalctl -u eklavya -n 50` |
| `ModuleNotFoundError: textual` | deps out of date → `uv sync --all-extras` then restart (the web path imports the TUI helper) |
| Chat errors / "provider not configured" | a provider key wrong/expired in `/etc/eklavya.env` → fix + restart; check order `EKLAVYA_PROVIDER_ORDER` |
| Emails not arriving | Gmail App Password wrong/revoked, or `SMTP_*` unset → fix in `/etc/eklavya.env`; app still works without email |
| Out-of-memory / slow | 1 GB box is tight (uses ~1.2 GB swap). If it thrashes: `sudo docker stop librespeed` frees ~100 MB (reversible: `docker start librespeed`) |
| Cert expired | `sudo certbot renew` then `sudo systemctl reload nginx` |
| Site 404/wrong content | check `sudo nginx -T | grep -A3 eklavyatheaitutor` and that `eklavya.service` is active |

## 6. Security posture
- App runs as a **low-priv user**, bound to **localhost**, behind nginx TLS; Lightsail firewall opens only 22/80/443.
- All secrets are in `/etc/eklavya.env` (600) — **never in git** (`.env` is git-ignored; verified no keys in history).
- Signups are **approval-gated**; only the admin email sees the Admin page.
- ⚠️ **Residual (task #49):** `run_bash` is *confined, not jailed*. Fine for the current **private, trusted** users (you + wife). **Before any public/untrusted signups**, do the bubblewrap/nsjail sandbox first.

## 7. Rollback
- Fastest: **restore the Lightsail snapshot** (whole box → exactly the pre-change state).
- Code only: `cd /opt/eklavya/app && git checkout <good-sha> && uv sync --all-extras && sudo systemctl restart eklavya`.
- Data: restore `/var/lib/eklavya` from a tarball/snapshot (see §4). Laptop `~/.eklavya-data` is untouched.
