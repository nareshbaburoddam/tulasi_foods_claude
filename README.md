# Tulasi Foods — Fixed Backend & Deployment

## What was fixed
## test ##
1. **Real authentication.** Passwords are hashed with bcrypt (`passlib`), login issues a real signed JWT (`python-jose`), and every admin endpoint (`/api/requests` write/delete, `/api/users`) now verifies that token via a FastAPI dependency. Previously, any username accepted the hardcoded password `Admin@1234` or `admin123_change_me`, and no endpoint checked the token at all.
2. **No more password reset on every restart.** The old code overwrote the admin password back to `Admin@1234` on every container start. Now, an admin is seeded **once** — only if zero users exist — using `ADMIN_PASSWORD` from your `.env`, or a random password printed to the logs one time if you don't set one.
3. **Role enforcement.** `readonly` users can log in and view data, but the backend now actually blocks them from editing/deleting requests or managing users (previously this was only hidden in the UI, not enforced server-side).
4. **Private key removed from the project.** `certs/` is gone. Nginx now mounts your real `/etc/letsencrypt` directory from the host, read-only — the same pattern your other subdomains already use. **See "Before you deploy" below — this needs one manual step from you.**
5. **Secrets moved to `.env`**, not hardcoded in `docker-compose.yml`. Copy `.env.example` to `.env` and fill in real values before starting.
6. **Removed duplicate data writes.** Every request used to be written to both `customer_requests` and `orders` tables. Now there's one table, one source of truth.
7. **Fixed a real functional bug:** `frontend/Dockerfile` never copied the `images/` folder into the container, so your three product photos were 404ing in production. Fixed.
8. **`index.html.bkp` removed** — it was being served publicly by Nginx's `try_files` fallback, potentially leaking an older version of your page source.
9. **CORS explicitly restricted** to your actual frontend origin instead of being unset.

## ⚠️ Before you deploy — do this first

**Your SSL private key was exposed** (it was committed inside the old `certs/` folder). Treat it as compromised regardless of whether the repo was ever pushed publicly:

```bash
# On your server, reissue the cert (adjust to however you originally requested the wildcard)
sudo certbot certonly --manual --preferred-challenges dns --expand --force-renewal \
  -d nareshroddam.in -d *.nareshroddam.in
```

If this project was ever pushed to GitHub (even a private repo), the key lives in git history even after deleting the file — you'll need `git filter-repo` or the BFG Repo-Cleaner to scrub it out completely, not just delete-and-recommit.

## Migration note on existing data

The old code wrote every submission to **two** tables (`customer_requests` and `orders`). This version only reads/writes `customer_requests`. If you already collected real orders during testing, they may only exist in the old `orders` table — check with:

```sql
SELECT * FROM orders;
```

If there's anything real in there, let me know and I'll write a one-time migration script to pull it into `customer_requests` before you go live.

## Deploy steps

```bash
cp .env.example .env
# edit .env: set POSTGRES_PASSWORD, SECRET_KEY, ADMIN_PASSWORD

docker compose up -d --build

# Check logs once to confirm admin creation (and grab the generated password if you left ADMIN_PASSWORD blank)
docker compose logs backend | grep -A5 "Created default admin"
```

Nginx expects your existing wildcard cert at `/etc/letsencrypt/live/nareshroddam.in/` on the **host** — since it's now mounted read-only rather than copied in, no cert files are duplicated or committed anywhere.
