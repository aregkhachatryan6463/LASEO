# Data Access Findings

This document records what was investigated for getting REAL Armenian real-estate
listing data into this system, and why each option was or wasn't used.

## 1. List.am — investigated directly

Checked (as of August 2026):

| What was checked | Found |
|---|---|
| Terms of Use (`list.am/help/14`) | Explicitly states users agree **not to "use automated programs to gain access"** to the site, and that site content **"may not be copied, reproduced, distributed, published... stored electronically, transmitted, or used for commercial or other purposes"** without permission. |
| About / Help pages (`/help/1`, `/help/13`) | General company info and a contact **form** only (no public email address, no developer/API section). |
| robots.txt | Could not be fetched in this environment (tool restriction on this session), but is not relevant here anyway — the Terms of Use already explicitly prohibit automation regardless of what robots.txt allows. |
| Developer / API documentation | None found anywhere on the site. |
| RSS / structured feed | None found. |
| Saved-search / email alert feature | Not found in the site's help/FAQ pages. The site has a "favorites" (heart icon) feature for logged-in users, but nothing describing email or push notifications for saved searches. |
| Business/partner contact info | Only the generic contact form; no listed business-development or API-partnership contact. |

**Conclusion: automated access to List.am is explicitly prohibited by their own Terms of Use.** This isn't a gray area — it's an unambiguous "you agree not to." No official API, feed, or notification mechanism exists to work around that. This project therefore does not access List.am programmatically in any form.

## 2. Other Armenian real-estate sites — investigated

Checked MyRealty.am's Terms & Conditions as a representative second major site.

**Same restriction**: MyRealty.am's terms also state users agree not to "use automatic programs to access the site" ("Չ՛օգտագործել ավտոմատ ծրագրեր կայք մուտք գործելու համար"), word-for-word the same restriction pattern as List.am. This appears to be a standard clause across Armenian classifieds sites, not a List.am-specific quirk. Other sites found in searches (estate.am, real-estate.am, realtors.am) were not individually checked in depth, but given the consistent pattern, none should be assumed to permit automation without checking their own terms first — and per your instructions, this project doesn't act on an assumption either way.

**This project intentionally does not swap in a different Armenian listings site as a silent replacement for List.am** — per your instruction, if List.am can't be integrated, you're told clearly rather than the source being quietly swapped.

## 3. Armenian government / public data — investigated

| Source | What it offers | Usable for this project? |
|---|---|---|
| `e-cadastre.am` (State Committee of the Real Estate Cadastre) | Public lookup of **cadastral value and property tax** for a *specific* parcel, given its cadastral code or ownership certificate number. | Not directly — it's a one-property-at-a-time lookup tool, not a bulk/searchable dataset of current listings or market prices. There's no bulk API. It could theoretically enrich a listing's data *if* you already had its cadastral code (which listings don't publish), so not practical here. |
| `maparmenia.am` (Geomatics Center) | Public map layers: parcels, buildings, orthophotos, hydrography/transport network. | Not relevant to pricing/listings. |
| Armenia's Open Government Partnership commitments | Note that Armenia's land cadastre database has historically **not** been fully publicly accessible in bulk, consistent with what was found above. | N/A |

**Conclusion:** No usable free bulk government real-estate pricing/listing dataset was found. This remains a documented possibility for the future (e.g. if the Cadastre Committee opens a bulk data feed), but is not implemented.

## 4. Third-party Armenian real-estate APIs/datasets — investigated

No dedicated third-party API or dataset specifically for Armenian/Yerevan real-estate listings was found in general-purpose API directories or search. If one exists, it was not surfaced by this research; it's worth a targeted follow-up search focused specifically on real-estate data vendors (e.g. commercial data providers that resell classifieds data under license) if you want to pursue this further — but none should be integrated without confirming licensing terms explicitly permit the intended use.

## 5. Saved search / email alert workflow — investigated

No evidence was found that List.am (or MyRealty.am) offers a saved-search email/push notification feature that a user could legitimately subscribe to and then have this system parse. Without that feature existing, the "email → parser → pipeline" design (Option E in your message) has nothing to connect to. This isn't ruled out for the future — if List.am adds this feature, or if you're aware of one already existing that this research didn't find (e.g. hidden behind a logged-in account), it's the most promising legitimate near-real-time channel, since it would be List.am themselves pushing data to a channel they control, not this project pulling it.

## 6. Summary table

| Method | Technically possible | Official | Allowed by terms | Requires permission | Recommended |
|---|---|---|---|---|---|
| Scrape List.am HTML directly | Yes | No | **No — explicitly prohibited** | Yes (would need to ask) | **No** |
| Use a "hidden"/internal List.am API found via reverse-engineering | Yes | No | **No** | Yes | **No** |
| List.am official public API | N/A (doesn't exist) | — | — | — | N/A |
| List.am RSS/feed | N/A (doesn't exist) | — | — | — | N/A |
| Request licensed data access from List.am directly | Unknown (depends on their response) | Would become official if granted | Yes, if granted | **Yes** | **Yes — best path, see `LISTAM_ACCESS_REQUEST.md`** |
| Scrape another Armenian real-estate site instead | Yes | No | Same prohibition found on MyRealty.am; assume similarly on others unless checked | Yes | No, without checking that specific site's terms and getting permission |
| Armenia Cadastre Committee public lookup | Yes, per-parcel only | Yes (official gov. site) | Yes, for the lookup tool as designed | No (public tool) | Not usable at scale for this project's purpose (no bulk listings/pricing) |
| Mock/demo data | Yes | — | Yes (it's synthetic) | No | **Yes — what this project uses today** |

## 7. Source priority scoring (per your requested framework)

| Source | Legality | Reliability | Completeness | Freshness | Cost | Historical coverage | Ease of integration | **Score /100** |
|---|---|---|---|---|---|---|---|---|
| List.am with authorized access (hypothetical, pending their response) | 10/10 if granted | High | High | High | Unknown, possibly free or paid | None initially | Medium (need their format) | **~90/100** *if granted* |
| Cadastre Committee public lookup | 10/10 | High | Low (per-parcel only, no listings) | N/A | Free | N/A | Low (not bulk) | **~35/100** for this project's purpose |
| Mock/demo data | 10/10 | Perfect (synthetic, deterministic) | You control it | N/A | Free | N/A | Trivial | **~70/100** *for development/testing*, 0/100 for real-world deal-finding |
| Scraping List.am or any AM real-estate site without permission | 0/10 (prohibited) | — | — | — | — | — | — | **Not scored — excluded on legality grounds alone** |

Nothing scores as a ready-to-use real-data source today except "request access," which is a real step but takes time and isn't guaranteed.
