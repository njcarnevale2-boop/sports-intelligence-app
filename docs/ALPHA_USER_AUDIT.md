# SIA Alpha User Audit
**Date:** 2026-08-12  
**Auditor:** GitHub Copilot — first-time user perspective  
**Scope:** Complete friends-and-family alpha journey, all viewports, error states, trust signals

---

## Severity Legend
| Priority | Meaning |
|---|---|
| **P0** | Blocks alpha — user cannot complete the flow |
| **P1** | Major usability or trust issue — misleads or confuses |
| **P2** | Polish — rough edge, minor confusion |
| **P3** | Future improvement — nice-to-have |

---

## Journey Evaluation

### Step 1 — Landing Page (`/`)
**Route:** `/` redirects to the `LayoutShell` which renders the home dashboard (not the marketing page at `/(marketing)`). The marketing page is only accessible if Next.js routing resolves the route group.

| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | Loads opportunities from `/api/opportunities?limit=100` |
| Loads quickly | ⚠️ | No loading skeleton — blank white flash before data |
| Next action obvious | ❌ | New user lands in a dense data dashboard with no onboarding text |
| Confusing | ❌ | "SI Score", "Edge", "EV/dollar", "Kelly 20%" are displayed with no tooltip or legend |
| Too technical | ❌ | Kelly criterion shown as raw numbers — no plain-English translation |
| Missing | ❌ | No "What is this?" call-to-action or introductory guidance for alpha users |
| Mock/live status | ⚠️ | Home page shows opportunities with no data freshness indicator |

**Issues:**
- **P1-001** No onboarding / empty-state guidance for new users
- **P1-002** Technical jargon (Kelly, EV, edge %) not explained anywhere on home
- **P2-003** No loading skeleton — content jumps in after fetch
- **P2-004** The marketing page at `/(marketing)` is never seen by logged-in users — they bypass it entirely

---

### Step 2 — Register (`/register`)
| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | Form submits to `/api/auth/register` |
| Next action obvious | ⚠️ | On success, redirects to `/settings` — unexpected; new users expect to be taken to the dashboard |
| Error messages | ❌ | On failure, shows "Unable to create account." with no detail — duplicate email? weak password? |
| Password requirements | ❌ | No password requirements shown (min length, special chars, etc.) |
| No email confirmation | ⚠️ | No confirmation step — alpha OK but worth noting |
| Missing | ❌ | No explanation of what bankroll/sportsbook settings are before asking user to set them |

**Issues:**
- **P1-004** Opaque error message on registration failure — user cannot self-diagnose
- **P1-005** Post-register redirect to `/settings` instead of home/dashboard
- **P2-006** No password strength requirements visible
- **P3-007** No email verification for alpha (acceptable now, needed pre-launch)

---

### Step 3 — Login (`/login`)
| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | JWT stored in localStorage |
| Error messages | ❌ | "Unable to sign in." — no distinction between wrong password and account not found |
| Redirect after login | ❌ | Redirects to `/settings` — should go to home or where user came from |
| Forgot password | ⚠️ | Link exists at `/forgot-password` but page content unknown |
| Session persistence | ✅ | `AuthProvider` re-hydrates from localStorage on load |
| Token not auto-refreshed | ⚠️ | `fetchJson` sends the token but there is no automatic refresh-token rotation on 401 |

**Issues:**
- **P0-001** **No token expiry handling** — when `access_token` expires, every authenticated request silently fails; user is not redirected to login (no 401 interceptor in `fetchJson`)
- **P1-006** Login redirects to `/settings` instead of dashboard
- **P1-007** Generic error message obscures root cause
- **P2-008** No "remember me" option

---

### Step 4 — Home / Dashboard (`/`)
| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | Loads top opportunities |
| Overloaded on first view | ❌ | 100 opportunities requested on home — wall of data |
| SI Score explained | ❌ | Score visible but no legend; no tooltip on hover |
| Stars visible | ✅ | Stars render correctly |
| Market intelligence | ⚠️ | Score/grade shown but "booksTracked" etc. not visible without drilling in |
| Empty state | ⚠️ | `"Unable to load live model data."` is shown if API fails — not friendly |
| Mobile navigation | ❌ | Sidebar is `hidden lg:flex` — on mobile there is NO navigation at all |
| No "what to do next" | ❌ | User has no clear first action — no CTA button to get started |

**Issues:**
- **P0-002** **Mobile navigation completely missing** — sidebar hidden below `lg` breakpoint, no hamburger menu, no bottom nav — mobile users are trapped
- **P1-008** 100 opportunities loaded on home with no filtering guidance
- **P1-009** SI Score visible but unexplained in context
- **P2-009** Error message "Unable to load live model data." sounds alarming; should be softer
- **P2-010** No active nav item highlight (no `pathname` comparison)

---

### Step 5 — Games Hub (`/games`)
| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | 272 games load correctly |
| Week navigation | ✅ | Weeks 1-18 appear after fix |
| Loading | ⚠️ | First load can be slow (272 games × enrichment) — loading state shown |
| Team logos | ✅ | ESPN CDN logos load |
| Game times | ✅ | Formatted with timezone |
| Lines shown | ✅ | Spread/total shown when available |
| No-edge state | ✅ | Games without edge show neutral state |
| Mock/live status | ✅ | `dataStatus` bar shown |
| SI Score | ✅ | Shown per game |
| Week nav confusing | ⚠️ | 18 week buttons in a row overflow on mobile |
| Date filter + week filter | ⚠️ | Both active at once can produce 0 results with no clear reset |
| No "view full analysis" from game card | ❌ | Game cards don't link to a per-game opportunity detail |

**Issues:**
- **P1-010** Week buttons overflow and wrap chaotically on mobile
- **P1-011** No path from Games Hub → Full Game Intelligence — no "Analyze" CTA on game card
- **P2-011** Date sub-filter combined with week filter creates confusing state
- **P3-008** No game search (team name or matchup)

---

### Step 6 — Select Week (within Games)
Already covered above. Week selector uses `availableWeeks` from backend (fixed). Navigation works.

**Issues:**
- **P2-012** No visual "active week" state differentiation when scrolled horizontally on mobile
- **P2-013** No back/forward arrow for week navigation — must scroll the pill row

---

### Step 7 & 8 — Full Game Intelligence (`/opportunities/[id]`)
| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | Loads opportunity + projection + schedule context |
| Recommendation visible | ✅ | Shown prominently |
| SI Score explainability | ✅ | Component breakdown shown with weights |
| Model projection | ✅ | Scores, margins shown |
| Market intelligence | ✅ | Grade, signal, books tracked |
| Injury context | ⚠️ | Present in data model but rendering depends on non-null values |
| Weather context | ⚠️ | Present in data model but rendering depends on non-null values |
| Decision timeline | ⚠️ | Shown if data exists; no clear "no changes yet" empty state |
| Best sportsbook | ✅ | Alternate books table shown |
| Information hierarchy | ⚠️ | Dense — recommendation competes with many data points |
| Back navigation | ✅ | "← Back" link present |
| "Add to My Card" | ✅ | Button present |
| dataStatus shown | ❌ | Full analysis page does not surface whether injury/weather data is LIVE/MOCK/UNAVAILABLE |

**Issues:**
- **P1-012** Full analysis page does not expose injury/weather `dataStatus` — user cannot tell if they're seeing real data or mock
- **P1-013** Injury/weather sections may silently show nothing when data is UNAVAILABLE with no label
- **P2-014** Decision Timeline shows "No changes detected" but doesn't explain what it tracks
- **P2-015** Model projection numbers (e.g. "4.2 point margin") need brief explanation for non-analysts
- **P3-009** No sharing / print view for full analysis

---

### Step 9 — Opportunities List (`/opportunities`)
| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | Ranked opportunity board loads |
| Filters | ✅ | Market, recommendation, sportsbook filters |
| SI Score visible | ✅ | On each card |
| Stars | ✅ | Rendered |
| Recommendation badges | ✅ | STRONG BET, LEAN, etc. |
| Empty state | ⚠️ | If filtered to 0 results, no "clear filters" prompt |
| Add to card from list | ✅ | Available via card |
| dataStatus not shown on list | ❌ | No data freshness indicator on the opportunity list |

**Issues:**
- **P1-014** No data freshness indicator on opportunity list — user can't tell if opportunities are hours or days old
- **P2-016** No "why is this ranked #1?" explanation
- **P2-017** 0-result state after filtering lacks a "clear filters" button

---

### Step 10 — Add Opportunity to My Card
The add-to-card action is implemented via `localStorage`. The opportunity detail page has an "Add to Card" button.

| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | localStorage write confirmed |
| Snapshot stored in backend | ❌ | `POST /api/recommendation/snapshot` route exists but is **not wired** to the add-to-card button in the UI — the button only writes to localStorage |
| Confirmation | ⚠️ | Button changes to "Added ✓ View My Card" but no toast or visual confirmation on the main opportunity page |
| Persist across sessions | ✅ | localStorage persists across page loads |

**Issues:**
- **P0-003** **CLV tracking broken** — "Add to My Card" does NOT call `POST /api/recommendation/snapshot`. The immutable snapshot system built in the backend is never triggered by the UI. CLV will never be captured for any user-added bet.
- **P2-018** No toast notification on add

---

### Step 11 — My Card (`/my-card`)
| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | Loads from localStorage + portfolio API |
| CLV display | ⚠️ | CLV row renders correctly but will always show "CLV pending" because snapshots are never stored (see P0-003) |
| Sportsbook selector | ✅ | Dropdown present |
| Best line comparison | ✅ | Alternate books shown |
| Bankroll exposure | ✅ | Summary metrics shown |
| Portfolio warnings | ✅ | Risk warnings present |
| Remove bet | ❌ | **No way to remove a bet from My Card** — there is no "Remove" button on the card shell |
| Empty state | ✅ | "Add opportunities from the grid" message shown |
| Export | ✅ | JSON/CSV/PDF export works |

**Issues:**
- **P0-004** **Cannot remove a bet from My Card** — once added, it is stuck until localStorage is manually cleared
- **P1-015** CLV "pending" message is always shown — will confuse users who expect to see results

---

### Step 12 — Choose Sportsbook (within My Card)
| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | Dropdown with 7 sportsbook options |
| Options hardcoded | ⚠️ | `["DraftKings", "FanDuel", "BetMGM", "Caesars", "ESPN BET", "Fanatics", "bet365"]` — not pulled from live data |
| Link to sportsbook | ❌ | No affiliate/direct link to place the bet on the chosen sportsbook |
| Best price shown | ✅ | "Prepared for {sportsbook}" message visible |

**Issues:**
- **P2-019** Sportsbook list is hardcoded and may not match available books in current odds data
- **P3-010** No deep-link to place the bet on the sportsbook

---

### Step 13 — Review Bet (within My Card)
The "Hand-off prep" section exists but is largely placeholder text: _"No bet is placed. This view prepares a clean hand-off package for later execution."_

**Issues:**
- **P1-016** Review Bet section is a placeholder with dummy text — alpha users will not understand what to do with it
- **P1-017** No actionable output from the "hand-off" — no printable bet slip, no formatted text to copy

---

### Step 14 — Market / Line Movement (`/line-movement`)
| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | Loads from `line_movement_board.csv` |
| Steam flag visible | ✅ | Badge shown |
| dataStatus shown | ✅ | "FILE" / "LIVE" / etc. shown in header |
| Sort options | ✅ | Largest point move, price move, recent |
| Market filter | ✅ | All / Spread / Total / Moneyline |
| Sportsbook filter | ✅ | Dynamic from data |
| Explains what "steam" means | ❌ | "Steam" label appears but is never explained |
| Historic vs current | ⚠️ | "first seen" vs "last seen" timestamps shown but not labelled clearly |
| Zero state | ✅ | "No movements" message shown |

**Issues:**
- **P1-018** "Steam" terminology not explained — new users don't know what it means
- **P2-020** "FILE" as a dataStatus value is confusing — should map to "LIVE" or "CACHED" for display
- **P2-021** First/last seen timestamps lack timezone labels

---

### Step 15 — Briefing (`/briefing`)
| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | Loads top 10 opportunities |
| Readable | ✅ | Best written page in the app |
| Executive tone | ✅ | Clear headline recommendation |
| Lead recommendation prominent | ✅ | Featured card with key metrics |
| "Kelly 20%" shown | ⚠️ | Percentage shown but not explained |
| Navigation back to opportunities | ✅ | "Review Opportunities" CTA |
| Live/mock status | ❌ | Briefing pulls from `/api/opportunities` but shows no data freshness |

**Issues:**
- **P2-022** Briefing does not show data freshness / last updated timestamp
- **P3-011** Briefing is static — no "refresh" button

---

### Step 16 — Performance (`/performance`)
| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | Loads without error |
| Empty state handled | ✅ | "Not enough historical performance has been tracked yet" shown |
| No fabricated data | ✅ | Dashboard is honest and empty |
| hasHistory check | ✅ | Correctly gates charts |
| CLV field | ⚠️ | `closingLineValue` is in the type but will always show "—" because no snapshots exist (P0-003) |
| What triggers history? | ❌ | Page gives no instruction on HOW to start tracking (add bets to card) |

**Issues:**
- **P1-019** No instruction on how to populate performance history — user reads "not enough history" and has no idea what to do
- **P2-023** `closingLineValue` field label says "Closing line value" — not meaningful without context

---

### Step 17 — Settings (`/settings`)
| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | Profile loads from `/api/auth/me` |
| Bankroll editable | ❌ | Bankroll is displayed but **not editable** on this page |
| Sportsbook preferences | ❌ | Settings page shows email/username/bankroll only — no sportsbook preference setting |
| Password change | ❌ | No password change option |
| Notification settings | ❌ | None |
| Logout | ✅ | Logout button works |
| Redirect if not authenticated | ✅ | Redirects to `/login` |

**Issues:**
- **P1-020** Settings page is display-only — no edit capability for bankroll (core feature of the platform)
- **P1-021** No sportsbook preference setting (mentioned in register flow as a feature)
- **P2-024** No password change
- **P3-012** No notification/alert preferences

---

### Step 18 — Logout
| Criterion | Status | Notes |
|---|---|---|
| Works | ✅ | `localStorage` cleared, user state cleared |
| Redirects to login | ✅ | Router pushes `/login` |
| Token truly invalidated | ⚠️ | Client-side only — no server-side token revocation call |

**Issues:**
- **P2-025** No server-side token revocation on logout (acceptable for alpha)

---

### Step 19 — Login Again + Saved State
| Criterion | Status | Notes |
|---|---|---|
| Auth restores | ✅ | `AuthProvider` reads localStorage on mount |
| My Card persists | ✅ | localStorage-backed |
| Opportunities load fresh | ✅ | API call on page load |
| Week selection lost | ⚠️ | Games page defaults to week 1 on every load |

**Issues:**
- **P2-026** Games page week selection not persisted across sessions

---

## Data Trust Audit

| Surface | LIVE | CACHED | MOCK | UNAVAILABLE | Notes |
|---|---|---|---|---|---|
| Opportunities list | ❌ | ❌ | ❌ | ❌ | No data status shown |
| Home dashboard | ❌ | ❌ | ❌ | ❌ | No data status shown |
| Games Hub | ✅ | ✅ | ✅ | ✅ | dataStatus bar shown |
| Line Movement | ✅ | ✅ | ⚠️ | ✅ | "FILE" label needs mapping |
| Full Analysis | ❌ | ❌ | ❌ | ❌ | Injury/weather status not shown |
| Briefing | ❌ | ❌ | ❌ | ❌ | No data status shown |
| Performance | ✅ | — | — | ✅ | Honest empty state |
| Admin (internal) | ✅ | ✅ | ✅ | ✅ | Complete |

**Issues:**
- **P1-022** Opportunities page never shows data freshness — user cannot tell if edge data is current
- **P1-023** Full Analysis (most important trust surface) shows no injury/weather data status

---

## Mobile Audit

| Viewport | Page | Status | Notes |
|---|---|---|---|
| 375px | Home | ❌ | No navigation — sidebar hidden, no mobile nav |
| 375px | Games | ❌ | Week buttons overflow uncontrollably |
| 375px | Opportunities | ❌ | No navigation |
| 375px | My Card | ❌ | No navigation |
| 430px | All pages | ❌ | Same — sidebar hidden, no mobile menu |
| 768px | All pages | ❌ | Still below `lg` breakpoint — no sidebar |
| 768px | Games | ⚠️ | Week row marginally better at tablet width |
| Desktop | All | ✅ | Sidebar renders, content fills well |

**Critical finding:** The entire navigation is invisible below 1024px. There is no hamburger menu, drawer, or bottom navigation. Mobile users arriving from a link cannot navigate anywhere.

**Issues:**
- **P0-002** (repeated) **Mobile navigation completely absent** — 375px/430px/768px all have no navigation

---

## Accessibility Audit

| Issue | Severity | Notes |
|---|---|---|
| Contrast: `text-zinc-600`/`text-zinc-700` on dark | P1 | Labels like "SI Score", "Edge" fail WCAG AA at these zinc shades |
| Contrast: `text-[10px]` section labels | P1 | 10px text is unreadable on mobile regardless of color |
| `<button>` without labels | P1 | Logout button in sidebar has only icon context — no `aria-label` |
| Input fields lack visible `focus` ring | P2 | Login/register inputs use `outline-none` — no focus indicator |
| `alt` text on team logos | P2 | `<img>` for ESPN logos may lack alt text |
| Color-only status indicators | P2 | Emerald/amber/red dots used without text labels in sidebar |
| No skip-to-content link | P3 | Keyboard users must tab through entire sidebar |

**Issues:**
- **P1-024** 10px and zinc-600/700 labels fail WCAG AA contrast
- **P1-025** `outline-none` on inputs removes keyboard focus visibility
- **P2-027** Missing `aria-label` on icon-only sidebar buttons
- **P2-028** Team logo `<img>` elements need `alt` text

---

## Error State Audit

| Scenario | Handled | Notes |
|---|---|---|
| Backend unavailable | ✅ | Generic error message shown on most pages |
| No opportunities | ✅ | Empty state handled |
| Weather unavailable | ❌ | Full analysis page — no visible indicator |
| Injury feed unavailable | ❌ | Full analysis page — no visible indicator |
| No sportsbook line | ✅ | Shows "—" |
| Expired authentication | ❌ | API calls silently fail; no redirect to login |
| Slow API response | ⚠️ | 10s timeout in `fetchJson` — "Request timed out" shown on games |
| 500 from backend | ⚠️ | "Request failed (500)" thrown but error messages generic |

**Issues:**
- **P0-001** (repeated) Expired token — no 401 interceptor
- **P1-026** Weather/injury UNAVAILABLE not surfaced on Full Analysis
- **P2-029** All API errors produce the same generic user-facing message regardless of cause

---

## Summary Counts

| Priority | Count |
|---|---|
| P0 | 4 |
| P1 | 26 |
| P2 | 29 |
| P3 | 12 |

---

## P0 Issues (Alpha Blockers)

| ID | Issue |
|---|---|
| **P0-001** | Expired JWT causes silent API failures system-wide — no 401 interceptor in `fetchJson`, no redirect to login |
| **P0-002** | Mobile navigation completely absent — no hamburger menu, drawer, or bottom nav below 1024px |
| **P0-003** | "Add to My Card" does NOT call `POST /api/recommendation/snapshot` — CLV tracking is never triggered from the UI |
| **P0-004** | No "Remove" button on My Card — bets cannot be removed once added |

---

## P1 Issues (Major Usability / Trust)

| ID | Issue |
|---|---|
| P1-001 | No onboarding for new users — no explanation of what to do first |
| P1-002 | Technical jargon (Kelly, EV, edge %) shown without explanation |
| P1-004 | Registration errors are opaque — "Unable to create account." |
| P1-005 | Post-register/login redirect to `/settings` instead of home |
| P1-006 | Login redirects to `/settings` instead of dashboard |
| P1-007 | Generic login error hides root cause |
| P1-008 | 100 opportunities loaded on home with no filter/pagination guidance |
| P1-009 | SI Score visible but unexplained in home context |
| P1-010 | Week buttons overflow on mobile |
| P1-011 | No path from Games Hub → Full Game Intelligence |
| P1-012 | Full analysis does not show injury/weather dataStatus |
| P1-013 | Injury/weather sections may silently show nothing when UNAVAILABLE |
| P1-014 | No data freshness indicator on opportunities list |
| P1-015 | CLV "pending" always shown — misleads users expecting results |
| P1-016 | Review Bet section is a placeholder with dummy text |
| P1-017 | No actionable output from hand-off prep |
| P1-018 | "Steam" terminology not explained |
| P1-019 | Performance page gives no instruction on how to populate history |
| P1-020 | Settings page is display-only — bankroll not editable |
| P1-021 | No sportsbook preference setting in settings |
| P1-022 | Opportunities page shows no data freshness |
| P1-023 | Full analysis shows no injury/weather data status |
| P1-024 | 10px labels and zinc-600/700 text fail WCAG AA contrast |
| P1-025 | `outline-none` on inputs removes keyboard focus visibility |
| P1-026 | Weather/injury UNAVAILABLE not surfaced on Full Analysis |

---

## TOP 10 ALPHA FIXES
*Ranked by impact on alpha user trust and usability.*

### #1 — Mobile Navigation (P0-002)
**Impact:** All mobile users (likely majority of alpha testers) have zero navigation.  
**Fix:** Add a bottom navigation bar (Home, Opportunities, My Card, Games, Settings) visible below `lg` breakpoint. Can be done in `layout-shell.tsx` in ~50 lines.

### #2 — Expired Token / 401 Handling (P0-001)
**Impact:** Silent failures make the app appear broken. A user who last logged in yesterday will see empty screens.  
**Fix:** Add a 401 interceptor in `fetchJson` that clears tokens and redirects to `/login`.

### #3 — Wire Add-to-Card to Snapshot API (P0-003)
**Impact:** CLV system built in backend is completely dead — no snapshot is ever stored.  
**Fix:** After writing to localStorage in the add-to-card action, fire `POST /api/recommendation/snapshot` with the opportunity payload. ~10 lines.

### #4 — Remove Bet from My Card (P0-004)
**Impact:** Card is permanently additive — users cannot curate their card.  
**Fix:** Add a remove button to each bet card in `MyCardShell`. Update localStorage.

### #5 — Data Freshness on Opportunities (P1-014 / P1-022)
**Impact:** Users cannot tell if they are seeing stale data — a core trust issue.  
**Fix:** Add a "Last updated: X min ago" badge to the opportunities list header and home dashboard, reading from the same `dataStatus`/`lastUpdated` fields already present in the API.

### #6 — Injury/Weather Status on Full Analysis (P1-012 / P1-023 / P1-026)
**Impact:** The most important page for trust shows no indication of whether context data is real or unavailable.  
**Fix:** Add small LIVE/MOCK/UNAVAILABLE badges next to the Injury and Weather sections in the Full Analysis page, mirroring the pattern already working in the Games Hub.

### #7 — Post-Auth Redirect (P1-005 / P1-006)
**Impact:** After register/login, users land on Settings instead of the value-first experience.  
**Fix:** Change both redirect targets from `/settings` to `/` (or `/opportunities` for new users).

### #8 — Glossary / Term Tooltips for SI Score, Edge, Kelly (P1-002 / P1-009 / P1-018)
**Impact:** Alpha users are sports fans, not quants — raw numbers without labels are off-putting.  
**Fix:** Add a collapsed "What does this mean?" tooltip or footer glossary: SI Score, Edge %, EV/dollar, Kelly 20%, Steam. Does not require redesign.

### #9 — No-Instruction Performance Empty State (P1-019)
**Impact:** User reads "not enough history" and bounces — no path forward.  
**Fix:** Add one sentence: "Add opportunities to My Card to start tracking your picks and CLV." with a link to `/opportunities`.

### #10 — "Review Bet" Placeholder Text (P1-016 / P1-017)
**Impact:** The My Card "Hand-off Prep" section says "no bet is placed" — this is confusing for alpha users who may think the app is supposed to place bets.  
**Fix:** Replace placeholder with a clear formatted summary: chosen sportsbook, bet details, recommended units, and a "Copy to clipboard" button for the bet slip text.

---

## Alpha Readiness Verdict

**ALPHA READY TODAY: NO**

**Biggest Blocker:** Mobile navigation is completely absent — the majority of alpha testers will be on phones and will see a beautiful app with no way to navigate between pages.

### Before First Alpha Invite:
1. Mobile navigation (P0-002) — 1–2 hours
2. JWT expiry handling (P0-001) — 1 hour
3. Remove from My Card (P0-004) — 30 minutes
4. Post-auth redirect fix (P1-005/006) — 5 minutes
5. Data freshness badge on opportunities (P1-014) — 30 minutes

### First Week of Alpha:
- Wire Add-to-Card to snapshot API (P0-003)
- Injury/weather status on Full Analysis (P1-012)
- Glossary tooltips (P1-002)
- Performance empty state CTA (P1-019)

---

*End of Alpha User Audit — 2026-08-12*
