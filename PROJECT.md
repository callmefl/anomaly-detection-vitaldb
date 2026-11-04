# Project: VitalDB Anomaly Detection — Editorial Typography & TikZ Restructuring

## Architecture
- **Document Type**: Academic Thesis / Master's Project Report (`report` class, 11pt, A4).
- **Styling Architecture**: LaTeX + TikZ + titlesec + fancyhdr + tcolorbox + listings.
- **Visual Design Standard**: Minimalist, sober, professional editorial design complying with `regole_tesi.md` and project color tokens, strictly devoid of AI-template artifacts (pill badges, shaded spheres, multi-layer drop shadows, reverse flow lines).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Minimalist Editorial Frontespizio | Replace full-page TikZ canvas pill badges, shaded spheres (`\branddot`), and drop shadows with an elegant, aligned typographic layout for Docente ("Prof.ssa Claudia Diamantini"), Candidati ("Andrea Altieri", "Andrea Flaiani"), and Anno Accademico | M1 | Survey 1 & 2 |
| F2 | Clean Editorial Chapter Headings | Refactor `\titleformat{\chapter}` to eliminate TikZ rounded pill badges, `\branddot`, drop shadows, and peach-blue gradient underline in favor of clean sentence-case numbered headings and a solid hairline rule | M1 | Survey 1 & 2 |
| F3 | Typographic Page Numbering | Refactor `\fancyfoot[R]` and `\fancypagestyle{plain}` to eliminate TikZ pill badges and drop shadows, adopting clean typographic page numbers | M1 | Survey 1 & 2 |
| F4 | AI Artifact Deprecation | Remove `\branddot` definition, simplify multi-layer drop shadow preactions in `htmlCard` and `lstlisting` | M1 | Survey 1 & 2 |
| F5 | Medallion Architecture Restructuring | Restructure Figura 2.1 (`medallion_tikz.tex`): eliminate pill badges, nested inline dot circles, duplicate metric clutter, and multi-layer drop shadows; establish clean geometric alignment and typography | M2 | Survey 1 & 3 |
| F6 | Pipeline Execution Restructuring | Restructure Figura 2.2 (`pipeline_execution_tikz.tex`): eliminate reverse snake U-turn flow in favor of unidirectional Left-to-Right dataflow; fix 1.45cm off-center arrow alignment; eliminate nested pill boxes | M2 | Survey 1 & 3 |
| F7 | Cross-Diagram Style Harmonization | Harmonize remaining TikZ diagrams (`relazione/*_tikz.tex`) to adhere to flat borders and zero background grids | M2 | Survey 1 & 3 |
| F8 | End-to-End Build & Validation | Compile LaTeX report (`pdflatex` / `latexmk`) with zero blocking errors; verify PDF output and compliance with all acceptance criteria | M3 | Survey 1, 2, 3 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Editorial Typography & Layout | `relazione/main.tex` (frontespizio, chapter titles, footers, style definitions) | none | DONE |
| M2 | TikZ Diagrams Restructuring | `relazione/*_tikz.tex` (all 9 diagrams restructured & harmonized) | M1 | DONE |
| M3 | End-to-End Compilation & Hardening | Full document compilation (`pdflatex`/`latexmk`), PDF validation, audit verification | M1, M2 | IN_PROGRESS |

## Interface Contracts
### `relazione/main.tex` ↔ `relazione/*_tikz.tex`
- Color tokens (`brandPrimary`, `brandDark`, `brandInkSoft`, `brandCoral`, `brandTeal`, `brandBorder`, `brandSurface`) must remain defined and consistent in `main.tex`.
- Diagram files are included via `\resizebox{\textwidth}{!}{\input{...}}`; they must produce self-contained `tikzpicture` environments without undefined external commands.
- Macro `\branddot` is deprecated and removed; diagrams must NOT invoke `\branddot`.
- Card style `htmlCard` must provide clean flat borders (`draw=brandBorder`, `fill=white`, `line width=0.8pt`) without requiring drop shadows.

## Code Layout
- `relazione/main.tex`: Master document, packages, color definitions, chapter styling, headers/footers, frontespizio.
- `relazione/medallion_tikz.tex`: Figure 2.1 Medallion 3-tier architecture.
- `relazione/pipeline_execution_tikz.tex`: Figure 2.2 End-to-end execution pipeline.
- `relazione/capitolo*/`: Thesis chapters (read-only references).
- `regole_tesi.md`: Authoritative thesis editorial guidelines.
