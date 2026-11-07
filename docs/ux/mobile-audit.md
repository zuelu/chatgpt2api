# Mobile UX audit and fixes

Date: 2026-11-07. Target: https://aimg.ezzz.ru, baseline v1.12.1 (`2c72e913`), release v1.13.0.

Scope and assumptions: this is an image creation/editing tool with an administrator account pool. The primary task is to describe an image, generate it with defaults, preview/download it and continue editing. The user explicitly requested fixes and a release, so the initial audit was read-only, followed by an implementation pass. Existing authorization covered administrator sign-in and minimal live generation. No existing accounts, images, logs, keys or settings were deleted or changed during the audit.

The live version and the repository baseline matched on `/image/`, `/accounts/`, `/logs/` and the version display. The route inventory also covered `/`, `/login/`, `/image-manager/`, `/debug/` and `/settings/`; `/` redirects. Browser evidence used Chromium with mobile viewport and touch emulation, starting at 390 × 844. This is not a physical-device Safari test.

## Inventory

Reproduce baseline with `python3 docs/ux/inventory.py --ref 2c72e91393edc2af976e4facc1a3ded9bd52dc84`; reproduce current source with `python3 docs/ux/inventory.py`.

| Script field | Baseline | Release source | Interpretation |
| --- | ---: | ---: | --- |
| route_count | 8 | 8 | Next page routes, including root redirect |
| source_files | 84 | 85 | TS/TSX/CSS under web/src |
| component_declarations | 169 | 169 | Regex declaration candidates, not rendered instances |
| css_tokens_defined | 69 | 79 | Includes Tailwind theme aliases |
| literal_color_occurrences | 88 | 90 | Candidates, not defects; new colors belong to the installed motion recipe |
| tailwind_arbitrary_occurrences | 291 | 294 | Candidates, including viewport and safe-area constraints |
| inline_style_attributes | 18 | 15 | Removed manual popover coordinates and display-font overrides |

The same script reports component name references, CSS variable references, state-marker occurrences and motion-bearing files. These are screening aids, not proof that a component or token is unused. Next page/layout exports are referenced by the framework; Tailwind theme aliases can be consumed by utilities without a literal `var()` call. Settings state is delegated to child components. Those cases were not counted as missing states or dead code.

## Findings by flow

These are observations, not business verdicts. Severity is a guess on a 0–4 scale; the user's stated priority is making default image generation straightforward. Evidence names below refer to the saved browser audit artifacts. The implementation preserves the existing warm neutral visual identity.

| Flow / location | Observed evidence | Severity guess / basis | Resolution |
| --- | --- | --- | --- |
| First image / empty state | Chinese interface displayed an English title and technical language about stateless edits (`before/image-empty.png`). | 2 / observed | Localized title and short instructions for describe → generate / upload → edit. |
| Image settings | Escape did not close the manually positioned menu; its hit area intercepted the Edit control (`before/image-options-escape.png`, click trace). | 3 / observed and source-confirmed | Shared portal popover, bounded scroll area, explicit Done button, outside dismissal, Escape and focus return. |
| Prompt / input | Enter handler did not check composition state; mobile Enter triggered submission rather than a line break (composer source). | 3 / measured source | Composition guard, key-code fallback, touch-device newline behavior; arrow remains the explicit mobile submit control. |
| Format / small screen | Native format selection worked after v1.12.1, but small controls and an unlabeled quota number made the toolbar harder to scan (`before/image-empty.png`). | 2 / observed | Larger format/touch targets, quota label beside format, labeled image description and numeric fields. GIF/SVG routing remains automatic. |
| Editing / studio | Custom fullscreen surface lacked dialog focus management and global Escape dismissal (`before/continue-edit.png`, source). | 3 / observed and source-confirmed | Shared accessible dialog, title, focus containment, Escape, compact mobile header and wrapping tool controls. |
| Editing → New draft | End-to-end regression reproduced a new draft retaining Edit mode after its reference was cleared, leaving submission blocked (page resetComposer source and browser flow). | 3 / observed and source-confirmed | New draft resets to Create and dismisses the source picker. |
| Results / error | Error descriptions were truncated to two lines on mobile (results source). | 2 / measured source | Full-width, naturally sized error cards with wrapping text and alert semantics; existing per-image retry preserved. |
| Accounts / overview | Document width was 1196px at a 390px viewport; one-column metrics and the model inventory pushed the account list far below the fold (`before/accounts-clean.png`, recorded DOM geometry). | 3 / measured | Two-column metrics, model disclosure, mobile record layout, wrapping pagination and constrained containers. |
| Logs / table | Important status/details actions lived far to the right of the phone viewport; bulk toolbar squeezed Clear selection into vertical text (`before/logs.png`). | 3 / observed | Labeled vertical records and wrapping actions; desktop retains the data table. |
| Gallery / bulk actions | Clear selection also wrapped into a vertical word (`before/gallery.png`). | 2 / observed | Wrapping toolbar and nonshrinking action labels. |
| Logs / details and shared dialogs | Close buttons were 24px; large panels needed predictable viewport bounds (`before/log-detail.png`, DOM geometry). | 2 / measured | 44px close targets, viewport height cap and internal scrolling; detail header reserves close-button space. |

## Cross-cutting

- Zoom was disabled in viewport metadata. Removed the restriction and enabled safe-area fitting. Mobile editable controls use 16px text to avoid automatic zoom on focus.
- Essential icon buttons and touch controls were smaller than 44px. The shared coarse-pointer rules enlarge their hit areas, preserve desktop density, and retain checkbox visuals with larger hit regions.
- Focus styling now covers native buttons, links, selects and disclosure summaries. Navigation identifies the current page; icon-only history deletion is named.
- Motion audit found existing Radix and Sonner lifecycle handling. Kept those mechanisms, standardized open/close durations, added anchored popover fades/scaling and a transitions.dev generation-status shimmer. The selected recipe was installed with its reduced-motion guard. A global reduced-motion rule also covers pre-existing spinners and Tailwind animations.
- Removed redundant English section kickers from the affected administration screens. Important result metadata and prompt placeholder contrast were strengthened.

## Harness

- The local webpack development path hit an existing CommonJS/ESM dependency error in `magic-string`. Verification instead used the successful Turbopack production export behind a local preview proxy. This was not reported as a live product defect.
- An initial automated locator matched both the settings trigger and its closing dialog during the exit animation. Changed the test to target the button and await dialog removal; this was not a product failure.
- One audit step attempted history navigation while the fullscreen editor was still open. Closed the editor explicitly and completed the history flow. This is not evidence of a broken history button.
- The first scratch log counter read top-level status instead of `detail.status`. Corrected query: the latest 100 call records contained 75 historical failures and 25 successes at that point. The last animated-input rejection was at 03:12:44; later successful edits and the live default-generation check were verified. Old failures are retained as history, not erased to improve the count.

## Probably fine

- Existing warm backgrounds, rounded surfaces, dense desktop tables and separate success/error badge colors are coherent with the incumbent application.
- Native output-format selection is appropriate on phones and avoids a custom inaccessible picker.
- GIF and SVG remain explicitly routed to official API accounts. Original animated inputs are preserved while editing uses a prepared still frame. SVG editing remains intentionally unsupported.
- The existing server account rotation and error classification were already covered by v1.12.0/v1.12.1 regressions. This release does not broaden paid-provider routing or retry policy.
- The settings tab strip scrolls intentionally to retain all administration categories. Destructive actions still require their existing confirmation dialogs.

## Proposed priorities

Given the user's explicit direction, the implementation order was: unblock settings/edit interactions; prevent accidental prompt submissions; fix mobile overflow and action reachability; clarify initial/loading/error states; then standardize motion. This records the chosen scope, not a claim about commercial impact.

## How to re-run

Run the inventory commands above, `node web/scripts/check-locales.mjs`, `./web/node_modules/.bin/tsc --noEmit -p web/tsconfig.json`, and `npm --prefix web run build`. Serve the resulting static export with the application backend. Walk login, default PNG generation, preview/download, continue-edit, animated-reference preparation, GIF/SVG selection, history, gallery, account import, logs/details, settings tabs and debug tabs. Verify 320/360/390/430px phone widths and intermediate/desktop layouts, light/dark themes, keyboard dismissal/focus and reduced motion. Use test-only failures for error and recovery checks; do not delete production data.

Physical iPhone/Android behavior, Safari rendering and virtual-keyboard viewport movement remain device-verification gaps. Browser emulation validates layout and synthetic touch, not those hardware/browser details. No claim of universal zero generation failures is made: upstream availability, policy and exhausted pools remain genuine failure conditions.

> This is a findings list. It does not say what to fix first, what to leave alone, or which of these is costing you customers. Those are decisions, and they take someone who knows the product and its plans and is accountable for the answer. If you want them made, send this report to hello@product.inc. Alex Zapadenko turns findings into a build order as a fixed-scope audit: https://www.product.inc/hire
