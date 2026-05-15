# Deploy LeadMap to Render + Google login

You still create the **Google OAuth client** yourself (Render and Google do not allow the repo to do that). This file is the exact checklist.

## 1. Push the repo to GitHub

Ensure `app.py`, `requirements.txt`, and `render.yaml` are on the branch you deploy.

## 2. Create the Render service

- **New** → **Blueprint** → connect the repo **or** **Web Service** from the repo.
- If you use **Blueprint**, Render reads `render.yaml` (build + start + env placeholders).
- If you use **Web Service** manually:
  - **Build:** `pip install -r requirements.txt`
  - **Start:** `gunicorn app:app --bind 0.0.0.0:$PORT`

Wait until the service is **Live** and note the URL, e.g. `https://leadmap-xxxx.onrender.com`.

## 3. Environment variables on Render

Set these on the **Web Service** (Dashboard → Environment):

| Key | Value |
|-----|--------|
| `GOOGLE_OAUTH_CLIENT_ID` | From Google (step 4) |
| `GOOGLE_OAUTH_CLIENT_SECRET` | From Google (step 4) |
| `FLASK_SECRET_KEY` | Long random string (Render can generate one) |
| `LEADMAP_BOOTSTRAP_OWNER_EMAIL` | Your Google account email (first login becomes **owner**) |

**Optional**

| Key | When |
|-----|------|
| `LEADMAP_PUBLIC_URL` | Custom domain only, e.g. `https://app.example.com` (no trailing slash). If omitted on Render, the app uses **`RENDER_EXTERNAL_URL`** automatically. |

**Do not** set `LEADMAP_AUTH_DISABLED=1` in production if you want real login.

Redeploy after saving.

## 4. Google Cloud — OAuth client

1. [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → **OAuth consent screen** (External or Internal) → add **Test users** with the emails that may sign in while the app is in Testing.
2. **Credentials** → **Create credentials** → **OAuth client ID** → **Web application**.

**Authorized JavaScript origins** (one line):

`https://YOUR-SERVICE.onrender.com`

(no path, no trailing slash)

**Authorized redirect URIs** — you may need **two different** URIs (Google’s form sometimes requires more than one row). Use:

| URI | Purpose |
|-----|--------|
| `https://YOUR-SERVICE.onrender.com/api/auth/google/callback` | Production on Render |
| `http://127.0.0.1:5050/api/auth/google/callback` | Local `python app.py` |

Replace `YOUR-SERVICE` with your real hostname. **Do not** duplicate the same URL twice. **Do not** leave an empty second row.

3. Copy **Client ID** and **Client secret** into Render env vars and redeploy.

## 5. First login

Open your Render URL → **Continue with Google** → sign in with the same email as `LEADMAP_BOOTSTRAP_OWNER_EMAIL`. With an empty user database, that account becomes **owner** (full access, including **Users** / invites).

## Troubleshooting

| Symptom | Fix |
|--------|-----|
| `redirect_uri_mismatch` | Redirect URI in Google must match **exactly** `https://…/api/auth/google/callback` (https, host, path). |
| `Duplicate redirect URIs` | Remove duplicate rows; use prod + `127.0.0.1` if you need two different URIs. |
| `Invalid Redirect: URI must not be empty` | Remove blank URI rows and remove placeholder `https://www.example.com`. |
| Users disappear after redeploy | `data/app_users.sqlite` is on ephemeral disk unless you add a **Persistent Disk** and mount it on `data/`. |
