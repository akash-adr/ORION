# Profit Pilot design contract

Every later page follows this file. If a rule here and a page disagree, the page is wrong.

**Concept: a neuro-lab for your P&L.** Precise, calm, clinical. Neural activity is the one vivid element on screen. Machine numbers are set in a clean sans; the engine's human-language reasoning is set in a serif, like an analyst's note beside the data.

## 1. Colour tokens

Defined as CSS variables in `app/globals.css`. Dark is the default; light is `html[data-theme="light"]`. Use the Tailwind names (`bg-ink`, `bg-slate`, `bg-slate-2`, `border-line`, `text-bone`, `text-fog`, `text-synapse`, `text-gain`, `text-loss`, `text-risk`).

| Token | Dark | Light | Use |
|---|---|---|---|
| `--ink` | #0F1724 | #F5F7FB | page background |
| `--slate` | #18233A | #FFFFFF | panels |
| `--slate-2` | #1F2B45 | #EEF2F8 | raised surfaces, inputs, hover |
| `--line` | #26324D | #E1E6F0 | 1px borders, dividers |
| `--bone` | #E8ECF4 | #121A2B | text |
| `--fog` | #8B97B0 | #5A6580 | muted text |
| `--synapse` | #3FC7E0 | #0E8FA8 | engine activity, primary actions, focus |
| `--gain` | #5BD68A | #14955A | gain |
| `--loss` | #FB7185 | #D43F5C | loss |
| `--risk` | #F2A93B | #B4761A | risk, warning |

**Text-safe variants.** In the light theme the four accent colours are below 4.5:1 as small text on white. Text uses `--gain-fg`, `--loss-fg`, `--risk-fg`, `--synapse-fg` (identical to the base token in dark; darker in light). Fills, bars, lines and icons use the base token. This is how the contract stays AA in both themes without changing the specified palette.

**Semantic colours only mean gain / loss / risk, and always come with an icon (↑ ↓ ⚠ 🔒 or the lucide equivalent) or a word.** Never decorative. Colour is never the only signal.

**Factor colours (fixed M4 contract).** One colour per root-cause factor, used by the waterfall and anywhere a factor is named. Light values are darkened so bars stay readable on white.

| Factor | Dark | Light | Token |
|---|---|---|---|
| Budget change | #7C8DB5 | #5A6B96 | `--factor-budget` |
| Auction cost (CPM/CPC) | #E0A34A | #B77A1F | `--factor-auction` |
| Click-through / creative | #9F8CF0 | #7A66D6 | `--factor-creative` |
| Conversion rate | #5B9CF5 | #2F76D6 | `--factor-conversion` |
| Price / unit margin | #34B3A0 | #1E8F7E | `--factor-price` |
| Traffic (sessions) | #6C7BE0 | #4A59C9 | `--factor-traffic` |
| Site conversion rate | #5B9CF5 | #2F76D6 | `--factor-site` |

**Brain colours.** Node health: good = gain, weak = risk, losing = loss. Region tints appear only while that region is active: Ingest #5B9CF5, Diagnose #9F8CF0, Decide #5BD68A, Learn #F2A93B (`--region-*`).

## 2. Typography

- **Manrope** (`next/font`) for all UI and every number. `font-variant-numeric: tabular-nums lining-nums` is set on `body`, so numbers align everywhere.
- **Newsreader** (serif, `next/font`) **only** for the engine's narratives: decision causes, diagnosis narratives, Ask answers, outcome notes. Use the `.narrative` class: 15px / 1.6, max 70ch.
- **Scale:** 12 / 14 / 16 / 20 / 28 / 40. Body is 14 minimum (12 is for chart axes, captions and chips only). KPI values are 28 (the P&L strip). Hero numbers are 40 and appear in exactly two places: the expected ₹ on the open decision and the simulator's profit delta.
- **Sentence case everywhere.** No all-caps labels. No monospace labels (monospace appears only inside the API-call log). No "→" appended to buttons. No middle-dot meta strings in the UI chrome (use separate items).

## 3. Shape and structure

- **Radius:** panels 14px (`rounded-panel`), controls 8px (`rounded-lg`), chips fully rounded.
- **Borders:** 1px `--line`. **No glow, no gradients on data surfaces.** At most one soft shadow, only on floating layers (drawers, popovers, menus).
- **Hierarchy through structure, not identical cards.** The KPIs are ONE P&L strip with dividers. Decisions are LEDGER ROWS that expand. Tables are real `<table>`s. The Engine map is the single bold element on the home page.
- **Campaign names** from the API ("Meta · Summer Sneakers · broad") are rendered as parts with `<CampaignName>`: channel badge (display name) + product + audience in muted text. The raw dotted string is never printed. Anomaly labels are stripped of their kind prefix with `anomalyEntity()` first.
- **Numbers** are formatted by `lib/format.ts` (`inr` matches the backend `format_inr`). Every value carries its period: `/day`, "last 7 days", "vs previous 7 days". `/kpis` spend, revenue and profit are daily averages (see the comment in `lib/types.ts`).

## 4. Motion

- **One orchestrated moment:** the intro → dashboard assembly. Data surfaces do not fade or slide in on load.
- Motion answers actions (expand, approve, open a drawer) and lasts at most 250 ms. Brain pulses map to real events only.
- `prefers-reduced-motion` removes the intro animation, transitions and brain sway.

## 5. Copy voice

Plain, active, specific. Buttons say what happens: "Approve", "Roll back", "Run the loop now", "Replay the last 7 days". The toast repeats the verb: "Approved · 3 budget changes sent". Errors say what happened and how to fix it. Empty states invite an action ("No decisions waiting. Run the loop now to check again.").

## 6. Accessibility

WCAG AA contrast in both themes (use the `-fg` text variants). A visible 2px `--synapse` focus ring on every interactive element (global `:focus-visible`). Every control is keyboard reachable. Every chart is a labelled `role="img"` with a written summary of what it shows.

## 7. Responsive

- ≥ 1200px: full layout (left rail with labels, wide content).
- 1000–1199px: compact (narrower rail and gutters, secondary columns drop below).
- < 1000px: the rail becomes a top bar and columns stack.

## 8. Components and where they live

- `lib/format.ts`, `lib/names.ts`: all formatting and naming. Never format inline.
- `components/charts/`: pure SVG (no chart library). Read `--token` colours through CSS variables so both themes work.
- `components/shell/`: rail, top bar, Ask bar, toasts, offline banner.
- `components/ui/`: shadcn primitives, themed through the tokens above.
- `lib/api.ts` + `lib/queries.ts`: the only way pages talk to the engine. After any action call `invalidateAfterAction`.

## 9. Known deviations

Rules that could not be followed exactly, and why. Keep this list honest; remove an entry when it is fixed.

1. **The theme toggle does not persist.** The only allowed browser storage is the "intro shown" flag, so the theme is held in memory and returns to dark on a full reload. (There was no toggle in the project before M10; this part built one.)
2. **Engine-authored text keeps its own punctuation.** Decision titles, issues and anomaly labels come from the API with middle dots ("Protect stock · cut ads on Running Pro by 60%"), and the Ask answer prose can contain a dotted campaign name. These are shown as the engine wrote them, in the serif where they are narrative. Changing them needs a backend edit, which M10 does not allow. Campaign names in tables, badges and lists are always structured parts.
3. **The waterfall is horizontal, not vertical.** Factor names are long ("Auction cost (CPM/CPC)"), so each factor is a row with its bar floating from the previous running total. The contract is kept: factor order as given, factor colours, ↑/↓, ₹ labels, and a net bar that ends exactly where the last factor ends.
4. **Text-safe colour variants (`--gain-fg` and friends) are an addition to the token list**, needed to keep small text at AA in the light theme (see section 1).
5. **The Engine map is a data panel for now.** It carries the `data-engine-map` anchor the intro lands on; the live brain replaces its content in part 5. The old brain labels and dev panel (`BrainTooltip`, `DevPanel`) still use uppercase and monospace; they are not mounted on any page and get restyled when the brain is built into the dashboard.
6. **Pages other than Command are first versions** built to exercise the charts against real data. Decision approve / reject / roll back, the what-if controls and the live brain arrive in later parts.
