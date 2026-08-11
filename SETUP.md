# SETUP GUIDE (for someone who has never coded before)

Follow these steps in order. Every step tells you exactly what to tap. This assumes you're
using an iPhone with Safari, but every step also works on a computer.

---

## Step 1 — Get the project files onto your phone

1. Download the `real_estate_deal_finder.zip` file Claude gave you (tap it, then the share/
   download icon).
2. Open the **Files** app on your iPhone.
3. Find the zip file (usually in "Downloads").
4. Tap it once — iPhone will automatically unzip it into a folder called
   `real_estate_deal_finder`.

## Step 2 — Create a free GitHub account (skip if you already have one)

1. Open Safari, go to **github.com**.
2. Tap "Sign up" and follow the prompts (email, password, username).

## Step 3 — Create a new repository (this is just a project folder on GitHub)

1. In Safari, go to **github.com/new**.
2. Repository name: type `real-estate-deal-finder` (or anything you like).
3. Leave it **Private** if you'd rather only you can see it (recommended, though nothing
   secret ever gets stored in the code itself).
4. Tap **Create repository**.

## Step 4 — Upload the project files

1. On your new (empty) repository page, tap **"uploading an existing file"**.
2. Tap the upload area to open the file picker.
3. In the picker, browse to the `real_estate_deal_finder` folder you unzipped in Step 1.
4. Select the folder itself (or select everything inside it) and upload.
5. Scroll down, type a short message like "Initial upload", and tap **Commit changes**.

If the picker won't let you select a whole folder at once on your phone, upload it in a few
batches (e.g. all files in `src/sources/`, then all files in `src/analysis/`, etc.) — GitHub
will keep the folder structure as long as you don't rename anything.

## Step 5 — Create your Telegram bot

1. Open Telegram, search for **BotFather** (has a blue checkmark).
2. Send it: `/newbot`
3. Give your bot a name (anything), then a username ending in `bot` (must be unique).
4. BotFather replies with a **token** — a long string like `123456789:ABCdefGhIJKlmNoPQRstuVwxyz`.
5. Copy that token somewhere temporarily (Notes app) — you'll paste it into GitHub in Step 7.
6. Send your new bot any message (e.g. "hi") so it knows about your chat.

## Step 6 — Get your Telegram chat ID

1. In Safari, go to this address, replacing `<TOKEN>` with your real bot token:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
2. You'll see some text on the page. Look for `"chat":{"id":` followed by a number
   (e.g. `123456789`). That number is your chat ID.
3. Copy it to Notes as well.

## Step 7 — Add your secrets to GitHub (this keeps them private)

1. Go to your repository on github.com.
2. Tap **Settings** (top of the repo page).
3. Tap **Secrets and variables** → **Actions**.
4. Tap **New repository secret**.
5. Name: `TELEGRAM_BOT_TOKEN`, Value: paste your token from Step 5. Tap **Add secret**.
6. Repeat: Name `TELEGRAM_CHAT_ID`, Value: paste your chat ID from Step 6.

That's it for required secrets — the system works with just these two.

## Step 8 — Run it for the first time (manually, to test)

1. Go to your repository → **Actions** tab.
2. Tap **"Real Estate Deal Monitor"** in the left list (or "I understand my workflows, enable
   them" if GitHub asks first).
3. Tap **Run workflow** → **Run workflow** (green button).
4. Wait about 30–60 seconds, then refresh — you'll see a run appear with a green checkmark
   (success) or red X (something failed — tap into it to read the error).

## Step 9 — Check Telegram

Open your chat with your bot in Telegram. If any demo listing qualified as a "deal" during
that test run, you'll see a message there.

## Step 10 — Turn on automatic monitoring

Nothing else to do — the workflow file already runs on a schedule (`.github/workflows/
monitor.yml`) roughly every 5 minutes, automatically, as long as the repository exists and
GitHub Actions isn't disabled. You don't need to keep your phone or any app open.

---

## Important notes

- **The system currently runs on realistic demo (mock) data, not real List.am listings.** See
  `DATA_ACCESS_FINDINGS.md` for exactly why, and `LISTAM_ACCESS_REQUEST.md` if you'd like to
  ask List.am for permission to connect real data later.
- **GitHub Actions may occasionally run a bit late or skip a slot** under heavy load — this is
  a GitHub limitation, not a bug. The system is built so this never causes duplicate alerts or
  lost listings.
- To change settings (max price, min area, etc.) later, edit the **Variables** or **Secrets**
  under the same Settings → Secrets and variables → Actions page, or edit `.env.example`
  values directly in the repo (tap the file → pencil icon → edit → commit).
