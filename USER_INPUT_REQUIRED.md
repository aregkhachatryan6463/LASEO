# What I Need From You

## REQUIRED (the system will not send you alerts without these)

1. **A Telegram bot token**
   - What it is: a secret code that lets a program send messages as a Telegram bot.
   - Where to get it: open Telegram, search for the account called "BotFather" (blue
     checkmark), send it `/newbot`, follow its prompts (pick a name and a username ending in
     "bot"). It replies with a long token like `123456789:ABCdefGhIJKlmNoPQRstuVwxyz`.
   - Where it goes: **GitHub Secret** named `TELEGRAM_BOT_TOKEN` (see SETUP.md step 7). Never
     paste it into a README, a code file, or a normal chat message once you're done.
   - Sensitive? Yes — treat it like a password.

2. **Your Telegram chat ID**
   - What it is: the numeric ID of the chat where you want alerts sent (usually your own
     private chat with your new bot).
   - Where to get it: after creating your bot, send it any message, then visit
     `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser (replace
     `<YOUR_TOKEN>` with your real token) and look for a number next to `"chat":{"id":`.
     SETUP.md walks through this with screencast-style steps.
   - Where it goes: **GitHub Secret** named `TELEGRAM_CHAT_ID`.
   - Sensitive? Not really secret, but keep it as a Secret anyway for simplicity.

## OPTIONAL (the system works fine without these — defaults are already sensible)

- **An AI API key** (e.g. Google Gemini's free tier) — only if you want AI-written summaries
  instead of the built-in rule-based fallback. Skip this entirely if you're not sure; nothing
  breaks.
- **Preferred districts, price range, minimum area, minimum rooms** — defaults are already set
  (Yerevan, apartments + houses, $50k–$300k... actually defaults are in `.env.example`; you can
  change them any time by editing values in GitHub, no coding needed).
- **Whether to try requesting List.am access** — see `LISTAM_ACCESS_REQUEST.md`. Entirely your
  call, and not required for the system to work today (it runs on realistic demo data either
  way).

## NOT NEEDED (Claude already handled these)

- Server / hosting setup — GitHub Actions runs it for free.
- Database setup — SQLite file lives in the repo, no separate database account needed.
- Exchange rate API — uses a free public endpoint automatically, no signup.
- Any code, terminal commands, or programming — none required from you.
