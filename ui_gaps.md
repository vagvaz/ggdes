# UI Gap Analysis

## Overview

This document captures functional and experiential gaps observed across GGDes’s two primary user interfaces:

- **Terminal UI (Textual-based TUI)** – located under `ggdes/tui/`
- **Web UI (FastAPI + vanilla HTML/CSS/JS)** – single-file app in `ggdes/web/__init__.py`

The goal is to highlight strengths, identify friction points, and note actionable improvements that would bring parity and polish to both experiences.

## Terminal UI (Textual)

**Key implementation files:** `ggdes/tui/app.py`, `ggdes/tui/feedback_view.py`, `ggdes/tui/debug_view.py`

### Strengths

- Rich, multi-tab layout covering analyses, worktrees, git log, section feedback, and contextual help.
- Interactive review flow (`ReviewScreen`) captures stage-level feedback and persists it for regeneration.
- Feedback tab delivers section-level guidance plus a live output viewer, keeping CLI/TUI users in a single interface.
- Keyboard shortcuts exist for primary actions (refresh, new analysis, feedback tab, git log controls).

### Gaps & Pain Points

1. **Debug tooling is hidden** – `debug_view.py` is not wired into the main tab set, so live conversations/outputs are unavailable from the primary TUI.
2. **Stage previews are minimal** – `ReviewScreen` shows status and accepts feedback, but it does not surface the rich preview tables that the CLI reviewer offers (e.g., key facts, files, plans).
3. **Limited discoverability for new features** – No contextual tips or onboarding to explain when to use Review vs Feedback tabs; help tab is static text.
4. **Polling-only architecture** – Section feedback and live outputs rely on fixed 3s intervals; there is no event-driven refresh or throttling when idle.
5. **Analysis list scalability** – Single column list lacks search/filter, sorting, or grouping, which can become unwieldy for large repositories.
6. **Error handling UX** – KB access failures (missing plan, unreadable feedback files) fall back to generic dim labels; no notifications beyond console logs.
7. **Accessibility gaps** – No screen-reader labels, limited focus management between panes, and keyboard shortcuts do not cover all actions (e.g., resume/delete).

### Opportunities

- Integrate DebugView as an optional tab for parity with Web UI’s real-time monitoring.
- Reuse CLI `StagePreview` tables in `ReviewScreen` for richer context before feedback.
- Introduce filtering and multi-select bulk actions for the analyses list.
- Replace fixed polling with event hooks (e.g., file watchers, notifications) or allow user-configurable intervals.
- Add toast/notification widget for success/failure feedback when saving feedback or resuming analyses.
- Layer in context-sensitive help, onboarding, or command palette for discoverability.

## Web UI (FastAPI + Vanilla JS)

**Implementation file:** `ggdes/web/__init__.py` (single file containing API routes, HTML, CSS, JS)

### Strengths

- Modern landing dashboard with stats, live WebSocket updates, and core actions (create, resume, delete, cleanup).
- Dedicated feedback page (`/feedback/{analysis_id}`) mirrors the TUI feedback tab with section textareas and live output viewer.
- Minimal build pipeline: all assets embedded; easy to deploy.

### Gaps & Pain Points

1. **Single-page limitation** – The main dashboard provides only top-level stats; there is no detailed analysis view (stage statuses, review history, document plan) without downloading raw files.
2. **No stage-level review UI** – Web users cannot perform the interactive review/regenerate flow that exists in CLI/TUI.
3. **Conversation/debug visibility missing** – No equivalent to the TUI DebugView; agent conversations and intermediate previews are inaccessible from the browser.
4. **Feedback navigation siloed** – Feedback page is separate and only reachable via button; lacks breadcrumb navigation back to specific analysis details or stage context.
5. **Minimal feedback acknowledgement** – Saving feedback shows inline text but no persistent history, timestamps, or user identification (multi-user scenarios).
6. **Limited live updates beyond dashboard** – Feedback page relies on polling (5s interval) for outputs; no WebSocket-driven updates or notifications for new files.
7. **No authentication / multi-user support** – Entire app is anonymous; there is no permission model or audit trail for who provided feedback.
8. **Device responsiveness gaps** – While layout is generally responsive, wide tables and dual-panel feedback layout degrade on smaller screens (no collapse or stacking behaviour).

### Opportunities

- Introduce an analysis detail page showing stage timeline, review history, document previews, and download shortcuts.
- Build a Web-based review modal that mirrors CLI/TUI feedback, including stage previews and regenerate controls.
- Surface agent conversations/output logs through a dedicated “Debug” section using existing API data.
- Share UI components (e.g., plan rendering, output file trees) between web and TUI via reusable API endpoints.
- Add notification system (toasts, banners) for long-running actions such as resume, cleanup, export.
- Consider modularizing assets (external CSS/JS files) for maintainability and easier testing.
- Evaluate authentication (even basic token-based) for shared environments.

## Cross-Cutting Recommendations

1. **Unify Feedback Data Flows** – Provide a central API and shared components so both UIs display identical stage/section feedback states, timestamps, and authorship.
2. **Richer Previews Everywhere** – Reuse `StagePreview` data (files, facts, plans) to give context in both Web and TUI interfaces before users leave feedback.
3. **Event-Driven Updates** – Extend WebSocket broadcasts (already used on dashboard) to notify Feedback and Review views of new outputs or stage completions instead of polling.
4. **Shared Design System** – Establish common styles/components (buttons, cards, status badges) to align look-and-feel across Textual and Web (color tokens, iconography).
5. **Onboarding & Guidance** – Add contextual help, tooltips, or walkthroughs explaining when to use interactive review, how feedback influences regeneration, and where outputs live.

## Appendix

- **TUI Files**: `ggdes/tui/app.py`, `ggdes/tui/feedback_view.py`, `ggdes/tui/debug_view.py`
- **Web UI File**: `ggdes/web/__init__.py`
- **Feedback Persistence**: `ggdes/kb/manager.py`
