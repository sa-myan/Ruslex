# Ruslex frontend developer guide

The Svelte frontend is deliberately a small client-rendered application. It does not need
SvelteKit, a frontend API server, or a custom state-management framework. Most views
use Svelte 5's **supported legacy component syntax** (`export let`, `$:` and `on:`).
Do not mix runes and legacy syntax within a component just to make it appear newer.
A separate, tested migration to runes may be considered later.

## Source layout

| Location | Responsibility |
| --- | --- |
| `src/lib/http.ts` | HTTP requests, CSRF token, typed errors |
| `src/lib/session.ts` | Current user, Edit Mode and Review Mode |
| `src/lib/navigation.ts` | Browser history and route store |
| `src/lib/errors.ts` | Safe error messages and abort detection |
| `src/lib/searchFilters.ts` | Prevent hidden entries outside Review Mode |
| `src/lib/types.ts` | Django API response/request types |
| `src/lib/externalLinks.ts` | Built-in external dictionary URLs |
| `src/components/layout/Sidebar.svelte` | Desktop/portrait navigation, account controls |
| `src/pages/Entry.svelte` | Entry loading, save confirmation, page composition |
| `src/components/entry/*` | Identity, external links, expression components |
| `src/components/SenseCard.svelte` | Sense editing and composition |
| `src/components/TagPicker.svelte` | Existing/new tag selection |
| `src/components/RecordList.svelte` | Patterns and examples |
| `src/components/RelationList.svelte` | Whole-entry/sense-level relationships |

`src/lib/api.ts` reexports older imports for compatibility. New code should import from
`http`, `session` or `navigation` directly, not add new responsibilities to `api.ts`.

## Editing rules

- Writes go through Django; the browser never writes SQLite directly.
- `Entry.saveChange()` clears stale notifications before submitting a mutation.
- A save is only acknowledged after both the API request **and** a fresh entry fetch succeed.
- A failed mutation must leave its editor open and show the error.
- Child editors get a refresh/save callback rather than duplicating global notification state.
- Hidden entries stay excluded from normal search, regardless of the last Review Mode filter.
- Sense-specific relationships must stay attached to their individual senses.
- Avoid fake `Summary` values cast with `as Summary`; use the `EntryReference` type.

## Async requests

- Search/entry pickers use `AbortController` and a request version number to avoid stale results.
- Errors can be arbitrary JavaScript values. Use `errorMessage()` rather than `as Error`.
- A canceled search is not displayed as a server error.
- Disable submission buttons for longer operations where duplicate submission would be harmful.

## Development

Inside `frontend/`:

```bash
npm install           # initial setup, or npm ci once package-lock.json is committed
npm run check         # Svelte and TypeScript diagnostics
npm test              # Vitest unit tests
npm run build         # production frontend build
npm run format        # consistently format Svelte/TS/CSS files with Prettier
npm run format:check  # report files that need formatting
```

This change includes package.json updates but **not a generated package-lock.json**,
because npm dependencies are unavailable in the authoring environment. Generate and
commit the lockfile from a machine with npm access (`npm install --package-lock-only`),
then prefer `npm ci` for deterministic builds. A lockfile created with one npm version
should be verified against your Docker Node version.

A full browser regression check is still needed: portrait drawer/keyboard navigation,
search/review status, sense and relation editing, tag selection, successful/failed saves,
external links, and all-reference pagination. Backend routes and database schema were not
changed in this refactor.

## Design decisions

- Keep the DOM and visible workflow stable, and make internal responsibilities clearer.
- Prefer explicit functions over one-line callbacks and unchecked type assertions.
- Avoid introducing extra libraries without a demonstrated need.
- Keep API transport separate from writable UI stores.
- Refactor one behavior at a time; ensure a test covers regressions before changing it again.
