# List.am Data Access Request

This file is prepared so **you** can decide whether to send it. Claude has not sent anything.

## What we already found (see DATA_ACCESS_FINDINGS.md for full detail)

List.am's Terms of Use (list.am/help/14) explicitly say users agree not to use automated
programs to access the site, and that site content may not be copied/stored/reused without
permission. No public API, feed, RSS, or saved-search email notification was found anywhere
on the site. So the only legitimate path to real List.am data is to **ask them directly** for
permission/access.

There is no public developer contact — only a general "Contact Us" form at
**https://www.list.am/en/help/13**. That form is where this request would need to go
(or an email if you find one through a business contact separately).

## What to ask for

- Read-only, low-volume access to new residential listing data for Yerevan (apartments and
  houses), refreshed roughly every 5 minutes.
- Fields needed: listing ID/URL, title, description, property type, location (city/district),
  price + currency, area (m²), rooms, floor/total floors, building year/type, renovation
  status, seller type, published date.
- Personal, non-commercial use: a private hobby project that alerts one person (you) via a
  private Telegram bot when a listing looks priced meaningfully below comparable local
  listings. Not resold, not republished, not shown to other users.
- Expected volume: one fetch roughly every 5 minutes, for one city initially (Yerevan).

## Ready-to-send message (English)

> Subject: Request for permission / API access — personal, non-commercial real estate monitoring project
>
> Hello,
>
> I'm building a small personal, non-commercial project that monitors new residential
> listings (apartments and houses) in Yerevan and privately alerts me via Telegram when a
> listing looks priced notably below comparable recent listings in the same area. It's for my
> own use only — not resold, not republished, and not shown to other users.
>
> I noticed List.am's Terms of Service don't currently permit automated access, and I want to
> respect that rather than work around it. I'm writing to ask whether List.am would be willing
> to grant limited, read-only access to new listing data (for example: an API key, a data
> feed, or another mechanism you'd recommend) for this kind of personal use.
>
> If useful, here's what I'd need:
> - Read access to new apartment/house listings for Yerevan, refreshed roughly every 5 minutes
> - Fields: listing ID/URL, title, description, property type, location, price + currency,
>   area, rooms, floor, building info, renovation status, seller type, published date
> - Expected volume: about one request every 5 minutes, for one city to start
>
> I'm glad to agree to any usage terms, rate limits, or attribution you'd want, and to pay a
> reasonable fee if that's how you handle this kind of access. Please let me know if this is
> possible and what the next step would be.
>
> Thank you for your time,
> [Your name]
> [Your email]

## What happens after you send it (if you choose to)

- If they grant access in any form, tell Claude what they gave you (API docs, a key, a feed
  URL, an export format — whatever it is) and Claude will build `src/sources/listam.py`
  against it, using the same `ListingSource` interface already in place. Nothing else in the
  app needs to change.
- If they decline or don't respond, the mock pipeline keeps working as-is, and
  `DATA_ACCESS_FINDINGS.md` documents the alternatives that were investigated.
