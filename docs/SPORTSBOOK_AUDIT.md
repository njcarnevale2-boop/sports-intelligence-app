# Sportsbook Deep Linking + Bet Slip Audit Report

**Date:** 2026-08-13  
**Sprint:** Sportsbook Deep Linking + Bet Slip Action Flow

---

## 1. SPORTSBOOKS DISCOVERED

### In Backend Data (ranked_bet_board.csv)
| Sportsbook | Row Count | Status |
|-----------|-----------|--------|
| DraftKings | 53 | ✅ Most represented |
| BetUS | 30 | ✅ Second most |
| FanDuel | 7 | ✅ Present |
| BetOnline.ag | 2 | ✅ Present |
| BetRivers | 2 | ✅ Present |
| LowVig.ag | 2 | ✅ Present |
| MyBookie.ag | 2 | ✅ Present |
| Bovada | 2 | ✅ Present |
| **Total** | **100 rows** | 8 unique books |

### In Frontend (Hardcoded)
`components/my-card-shell.tsx` line 11:
```javascript
["DraftKings", "FanDuel", "BetMGM", "Caesars", "ESPN BET", "Fanatics", "bet365"]
```

### Data/Frontend Mismatch ⚠️
**Frontend books NOT in data:**
- BetMGM
- Caesars
- ESPN BET
- Fanatics
- bet365

**Backend books NOT in frontend:**
- BetOnline.ag
- BetRivers
- BetUS
- Bovada
- LowVig.ag
- MyBookie.ag

---

## 2. SCHEMA ANALYSIS

### SavedBet (lib/my-card-helpers.ts)
```typescript
type SavedBet = {
  book: string;                    // Sportsbook name (e.g., "DraftKings")
  point?: number;                  // Spread/total value
  price?: number;                  // Odds (e.g., -105)
  alternateBooks?: Array<{         // Other sportsbooks' prices
    book: string;
    point: number;
    price: number;
    edge: number;
    evPerDollar: number;
  }>;
  // ... other fields
}
```

### Opportunity (app/opportunities/page.tsx)
```typescript
type Opportunity = {
  book: string;                    // SIA recommended sportsbook
  point: number;
  price: number;
  alternateBooks?: AlternateBook[];
}

type AlternateBook = {
  book: string;
  point: number;
  price: number;
  edge: number;
  evPerDollar: number;
}
```

### Market Data Available
- Opportunity.marketIntelligence includes: booksTracked, booksMoving, consensus
- Each opportunity has: sportsIntelligenceScore, edge, evPerDollar

---

## 3. CURRENT BET SLIP IMPLEMENTATION

**Location:** `components/my-card-shell.tsx` (lines 214-296)

### What Works
✅ Displays selection, matchup, pick  
✅ Shows "Better line available" info box (if alternateBooks has better line)  
✅ Copy button with formatted text  
✅ Sportsbook selector dropdown  
✅ Shows Line/Odds, SI Score, EV, Kelly %  

### What Doesn't Work
❌ Sportsbook selector doesn't hydrate line/odds from alternateBooks  
❌ Line/odds remain static when sportsbook changes  
❌ Hardcoded sportsbook list doesn't match actual data  
❌ No deep linking / "Open in [Sportsbook]" action  
❌ No warning when selected book has **worse** line than SIA recommended  
❌ Doesn't show which sportsbook SIA actually recommended  

---

## 4. DATA FLOW FOR SPORTSBOOK SWITCHING

**Current State:**
```
reviewBet (SavedBet)
  ├── book: "DraftKings"
  ├── point: -7
  ├── price: -105
  └── alternateBooks: [
        { book: "FanDuel", point: -6.5, price: -110, ... },
        { book: "BetUS", point: -6.5, price: -108, ... }
      ]

selectedSportsbook = "DraftKings" (state)
```

**Problem:** When user selects "FanDuel", displayed line stays "-7 at -105" (from reviewBet.point/price).

**Solution Needed:** When sportsbook changes, look up alternateBooks to find matching sportsbook entry and display its line/odds.

---

## 5. SPORTSBOOK WEBSITE CONFIGURATION

### Verified Base URLs
| Sportsbook | Homepage | Notes |
|-----------|----------|-------|
| DraftKings | https://sportsbook.draftkings.com | ✅ Mobile app available |
| FanDuel | https://sportsbook.fanduel.com | ✅ Mobile app available |
| BetMGM | https://sports.betmgm.com | ❌ Not in data |
| Caesars | https://www.caesarssportsbook.com | ❌ Not in data |
| BetRivers | https://betrivers.com | ✅ In data, ~2 rows |
| BetUS | https://www.betusbet.com | ✅ In data, ~30 rows |
| BetOnline.ag | https://www.betonline.ag | ✅ In data, ~2 rows |
| MyBookie.ag | https://www.mybookie.ag | ✅ In data, ~2 rows |
| Bovada | https://www.bovada.lv | ✅ In data, ~2 rows |
| LowVig.ag | https://www.lowvig.ag | ✅ In data, ~2 rows |

### Deep Linking Capability
**Standard OAuth/Bet Placement Deep Links:**
- No major sportsbook publishes documented affiliate bet-placement deep links
- Mobile apps support URL schemes (e.g., `draftkings://odds/...`) but are undocumented
- App deeplinking is fragile and liable to change per app update

**Recommended Approach:**
- ✅ Link to sportsbook homepage (always safe, always available)
- ✅ Display the bet details in the slip so user can search/find it at the book
- ❌ Do NOT attempt bet placement deep linking (unsafe, fabricated, fragile)

---

## 6. IMPLEMENTATION PLAN

### Phase 1: Central Sportsbook Config
Create `lib/sportsbook-config.ts`:
```typescript
type SportsbookConfig = {
  key: string;                      // e.g., "draftkings"
  displayName: string;              // e.g., "DraftKings"
  baseUrl: string;                  // e.g., "https://sportsbook.draftkings.com"
  hasAppDeeplink?: boolean;         // false for all for now
}

const SPORTSBOOKS = {
  draftkings: { displayName: "DraftKings", baseUrl: "https://sportsbook.draftkings.com" },
  fanduel: { displayName: "FanDuel", baseUrl: "https://sportsbook.fanduel.com" },
  betrivers: { displayName: "BetRivers", baseUrl: "https://betrivers.com" },
  betUS: { displayName: "BetUS", baseUrl: "https://www.betusbet.com" },
  betonline: { displayName: "BetOnline.ag", baseUrl: "https://www.betonline.ag" },
  mybookie: { displayName: "MyBookie.ag", baseUrl: "https://www.mybookie.ag" },
  bovada: { displayName: "Bovada", baseUrl: "https://www.bovada.lv" },
  lowvig: { displayName: "LowVig.ag", baseUrl: "https://www.lowvig.ag" },
}
```

### Phase 2: Fix Sportsbook Selector
- Pull sportsbookOptions from alternateBooks + reviewBet.book (dynamic)
- Only show sportsbooks that have price data for this bet
- Display SIA recommendation clearly ("Recommended" badge on reviewBet.book)

### Phase 3: Hydrate Line/Odds on Sportsbook Change
- When selectedSportsbook changes, find matching entry in alternateBooks
- Update displayed point/price to show that sportsbook's actual line
- Show "—" if sportsbook has no data for this bet

### Phase 4: Line Difference Warning
- If selectedSportsbook.point !== reviewBet.point OR selectedSportsbook.price !== reviewBet.price:
  - Show comparison box with SIA line vs Selected book line
  - Highlight worse odds in red/amber

### Phase 5: Open Sportsbook Action
- Add button: "Open [Sportsbook] →" (opens homepage, not bet-placement link)
- Use `target="_blank"` to open sportsbook website
- Add disclaimer: "Verify current line and odds at the sportsbook"

### Phase 6: Improve Copy Bet Details
Concise format:
```
SIA BET
New Orleans Saints +7
vs Detroit Lions
LowVig.ag • -105
SI Score: 81.9 | Confidence: 86%
Edge: 7.4% | EV: +$0.074/$ | Kelly 20%: 2.8%
```

---

## 7. VALIDATION CHECKLIST

### Sportsbooks
- [ ] Sportsbook list matches actual ranked_bet_board.csv data
- [ ] Frontend dropdown populated dynamically from opportunity data
- [ ] No hardcoded sportsbook list in components

### Bet Slip Hydration
- [ ] Selecting sportsbook updates displayed line/odds
- [ ] Shows "—" if no alternate price exists
- [ ] Preserves original SIA line when sportsbook has no data

### Line Difference Warning
- [ ] Shows when selected book has different line than SIA recommended
- [ ] Displays side-by-side comparison
- [ ] Highlights worse odds

### Copy Bet Details
- [ ] Concise format (no full analysis)
- [ ] Includes: pick, matchup, sportsbook, line, odds, SI score, confidence
- [ ] Copies to clipboard without errors

### Deep Linking
- [ ] "Open [Sportsbook] →" button opens homepage
- [ ] Opens in new tab (`target="_blank"`)
- [ ] Disclaimer visible (user must verify line at book)

### Data Integrity
- [ ] Never shows fake sportsbook information
- [ ] Never silently reuses another book's line
- [ ] Shows "—" or "unavailable" for missing data
- [ ] No fabricated deep link URLs

### Testing
- [ ] Opportunity with multiple alternate books (e.g., DraftKings with FanDuel/BetUS alternates)
- [ ] Opportunity with single sportsbook
- [ ] Opportunity with missing sportsbook price
- [ ] Page reload preserves selected sportsbook
- [ ] Multiple saved bets with different sportsbooks
- [ ] Switching between bets updates bet slip correctly
- [ ] No console errors

---

## 8. WHAT NOT TO MODIFY

✅ DO NOT CHANGE:
- SI Score calculation
- Model probability
- Edge calculations
- EV per dollar
- Kelly calculations
- Opportunity ranking
- Week filtering
- CLV
- Market intelligence scoring
- Games page
- Opportunity Analysis page

---

## Recommendation

**Proceed with implementation of:**
1. ✅ Central sportsbook config
2. ✅ Dynamic sportsbook selector (pull from opportunity data)
3. ✅ Hydrated line/odds switching
4. ✅ Line difference warning
5. ✅ Open sportsbook homepage (safe, documented behavior)
6. ✅ Improved copy bet details

**DO NOT ATTEMPT:**
- ❌ Bet placement deep linking (no documented API)
- ❌ Automatic bet execution (unsafe, out of scope)
- ❌ Sportsbook account integration (security risk)
- ❌ Fabricated affiliate URLs

**Status:** Ready to implement Phase 1.
