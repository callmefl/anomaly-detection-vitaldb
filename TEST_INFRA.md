# Test Infrastructure & E2E Verification Suite: Thesis Redesign

**Project**: VitalDB Anomaly Detection — Editorial Typography & TikZ Restructuring  
**Authoritative Specifications**: `ORIGINAL_REQUEST.md`, `PROJECT.md`, `regole_tesi.md`  
**Test Suite Engine**: `verify_redesign.py` / `tests/test_latex_redesign.py`  
**Version**: 1.0.0 (Production-Grade E2E Test Infrastructure)  

---

## 1. Test Philosophy: Opaque-Box & Requirement-Driven

The testing infrastructure adopts an **opaque-box, requirement-driven verification philosophy**. Rather than testing incidental internal LaTeX implementation choices, the test suite evaluates the codebase strictly against the observable external requirements established in `ORIGINAL_REQUEST.md`, `PROJECT.md`, and the editorial standards of `regole_tesi.md`.

### Core Testing Tenets:
1. **Opaque-Box Verification**: The verification engine examines the structural integrity of the LaTeX document, macro boundaries, geometric graph topologies, and compilation artifacts as observable contracts, rather than dictating private TeX register allocations.
2. **Deterministic Expected Outputs**: Every test derives its assertions from documented specifications:
   - Total absence of AI web-template artifacts (spherical gradient dots, pill badges, multi-layer drop shadows, reverse snake flows).
   - Strict adherence to academic typography (sentence-case titles, clean tabular/grid metadata, subtle hairline rules, unobtrusive folios).
   - Deterministic compiler exit code 0 under standard TeX engines (`pdflatex` / `latexmk`).
3. **Progressive Testability & Defect Escalation**: As a test writer, the verification suite modifies **test code only**. Implementation defects detected in baseline files (`relazione/main.tex`, `relazione/*_tikz.tex`) are codified as failing test assertions with actionable diagnostic reports to guide M1 (Typography & Layout) and M2 (TikZ Restructuring) workers.
4. **Adversarial & Boundary Verification**: The test suite exercises boundary conditions such as macro deprecation safety (invoking `\branddot` must not trigger undefined control sequence crashes), casing rules (no uppercase after colons), unclosed TikZ scopes, and document compilation with zero fatal errors.

---

## 2. Feature Inventory (F1 through F8)

The test suite provides 100% coverage across all eight features defined in `PROJECT.md`:

| Feature ID | Feature Name | Primary Target Files | Acceptance Criteria Source | Test Scope & Verification Focus |
|:---|:---|:---|:---|:---|
| **F1** | Minimalist Editorial Frontespizio | `relazione/main.tex` | `ORIGINAL_REQUEST.md` R1 | Eliminate 3D gradient spheres, floating seal card, 4 rounded pill badges, and drop shadows; replace with clean institutional typography and aligned Docente/Candidati blocks. |
| **F2** | Clean Editorial Chapter Headings | `relazione/main.tex` | `ORIGINAL_REQUEST.md` R1, `regole_tesi.md` | Eliminate TikZ rounded pill node, `\branddot`, drop shadow, hardcoded "0" prefix, and peach-blue gradient underline from `\titleformat{\chapter}`; adopt clean sentence-case headings with hairline rule. |
| **F3** | Typographic Page Numbering | `relazione/main.tex` | `ORIGINAL_REQUEST.md` R1 | Eliminate TikZ pill box and drop shadow enclosing `Pag. \thepage` in `\fancyfoot[R]` and `\fancypagestyle{plain}`; adopt pure, unobtrusive typographic folios. |
| **F4** | AI Artifact Deprecation | `relazione/main.tex`, `relazione/*` | `PROJECT.md` § Interface Contracts | Ensure zero active invocations of `\branddot` across the entire codebase; deprecate macro safely; eliminate multi-layer drop shadows from `htmlCard` and `lstlisting`. |
| **F5** | Medallion Architecture Restructuring | `relazione/medallion_tikz.tex` | `ORIGINAL_REQUEST.md` R2, Survey 3 | Eliminate pill badges, nested inline bullet circles, footer byte counts, and multi-layer drop shadows from Figure 2.1; establish 3 symmetric columns with clean header bands. |
| **F6** | Pipeline Execution Restructuring | `relazione/pipeline_execution_tikz.tex` | `ORIGINAL_REQUEST.md` R2, Survey 3 | Eliminate reverse snake U-turn dataflow (Phase 04 $\to$ Phase 05 must flow Left-to-Right); eliminate 1.45cm off-center drop arrow; eliminate nested 7-pillbox stack. |
| **F7** | Cross-Diagram Style Harmonization | `relazione/*_tikz.tex` (all 9 files) | `PROJECT.md` F7, Survey 3 | Harmonize all 9 TikZ figures: verify zero background grids, zero `\branddot` references, and consistent palette tokens (`brandPrimary`, `brandCoral`, `brandTeal`). |
| **F8** | End-to-End Build & Validation | `relazione/main.tex`, `main.pdf` | `ORIGINAL_REQUEST.md` § Acceptance Criteria | Compile full document (`pdflatex` / `latexmk`) returning exit code 0; verify PDF generation, zero blocking errors in `main.log`, and complete page structure. |

---

## 3. Test Architecture

The verification harness combines **Static Structural Validation** and **Document Compilation Testing** within a unified runner architecture:

```
                                 [Test Suite Engine]
                             verify_redesign.py / pytest
                                          |
        +---------------------------------+---------------------------------+
        |                                                                   |
  [Static Validation Engine]                                      [Compilation Engine]
  - Regex & AST Tokenizer                                         - pdflatex / latexmk Runner
  - TeX Macro & Scope Parser                                      - Multi-pass execution (x2)
  - TikZ Geometry & Flow Auditor                                  - Log Parser & Exit Code Verifier
        |                                                                   |
        +-----------------+-------------------------------+-----------------+
                          |                               |
                   [Tier 1: Features]              [Tier 4: Build]
                   - Zero \branddot                - Exit Code 0
                   - Zero Pill Badges              - Zero Fatal Errors
                   - Zero Drop Shadows             - Valid main.pdf Size
                          |
                   [Tier 2: Boundary]
                   - Capitalization Rules
                   - Macro Safety / Fallback
                   - Flat Border Styles
                          |
                   [Tier 3: Combinations]
                   - Cross-Diagram Palette
                   - Zero Background Grids
                   - TikZ Textwidth Bounding
```

### 3.1 Static Structural Validation Engine
- **TeX Source Tokenizer**: Strips LaTeX comments (`% ...`) to prevent false positives in commented-out legacy code, then analyzes active TeX macros, environments, and TikZ styles.
- **Pattern Matchers**:
  - `ArtifactDetector`: Scans for forbidden AI template patterns (`\branddot`, `rounded corners=13pt`, `drop shadow`, `\shade.*circle`).
  - `GeometryAuditor`: Evaluates TikZ coordinate paths and arrow directions to mathematically detect reverse flows (e.g. verifying that $x_{\text{dest}} > x_{\text{source}}$ for forward horizontal flows).
  - `TypographyAuditor`: Inspects casing rules, colons, and titles against `regole_tesi.md` (no uppercase after colons, standard sentence casing).

### 3.2 Compilation & Log Inspection Engine
- **TeX Compiler Interface**: Invokes `latexmk -pdf -interaction=nonstopmode main.tex` or `pdflatex -interaction=nonstopmode main.tex` within `relazione/`.
- **Diagnostic Log Parser**: Analyzes `main.log` for fatal error flags (`! LaTeX Error:`, `Fatal error occurred`, `Emergency stop`), missing package warnings, and undefined references (`LaTeX Warning: Reference ... undefined`).
- **Artifact Verifier**: Asserts that `main.pdf` exists, has size $> 100\text{ KB}$, and renders all sections.

---

## 4. Coverage Thresholds: The 4 Tiers of Tests

The testing suite enforces four progressive quality tiers:

```
+-----------------------------------------------------------------------------------+
| TIER 1: Feature Coverage (Absence of AI Artifacts & Web Badges)                   |
| Required Pass Rate: 100% of defined forbidden patterns eliminated                |
+-----------------------------------------------------------------------------------+
| TIER 2: Boundary & Corner Cases (Typography, Macros & Deprecation Safety)         |
| Required Pass Rate: 100% compliance with regole_tesi.md and TeX safety            |
+-----------------------------------------------------------------------------------+
| TIER 3: Cross-Feature Combinations (Diagrams, Margins & Color Tokens)             |
| Required Pass Rate: 100% consistency across all 9 TikZ files and main.tex         |
+-----------------------------------------------------------------------------------+
| TIER 4: Document Compilation Scenario (Clean Multi-Pass PDF Generation)           |
| Required Pass Rate: Exit code 0, 0 fatal errors, valid main.pdf generated         |
+-----------------------------------------------------------------------------------+
```

### Detailed Tier Breakdown

#### Tier 1: Feature Coverage (Absence of AI-Template Artifacts)
- **T1.1 (F1 Frontespizio Pills & Spheres)**: `relazione/main.tex` must contain zero TikZ pill badge nodes (`rounded corners=13pt`, `rounded corners=11pt`), zero shaded hero spheres (`\shade.*circle`), zero circular avatar borders around `univpm_seal.png`, and zero drop shadows in the frontispiece.
- **T1.2 (F2 Chapter Heading Pills)**: `\titleformat{\chapter}` in `relazione/main.tex` must contain zero TikZ pill badge nodes (`rounded corners=9pt`), zero `\branddot` invocations, zero drop shadows, and zero gradient underline boxes (`\shade[left color=brandPeach, right color=brandPrimary...`).
- **T1.3 (F3 Footer Page Number Pills)**: `\fancyfoot[R]` and `\fancypagestyle{plain}` in `relazione/main.tex` must contain zero TikZ pill nodes (`rounded corners=8pt`, `drop shadow`, `draw=brandBorder`, `Pag. \thepage`).
- **T1.4 (F4 Branddot Macro Absence)**: Zero active occurrences of `\branddot` across all `.tex` files in `relazione/` (including all chapters and diagrams).
- **T1.5 (F5 Medallion Clutter Absence)**: `relazione/medallion_tikz.tex` must contain zero pill badge headers (`rounded corners=9pt`), zero inline bullet circles (`\tikz.*circle`), zero transient metric foot pills (`33,95 MB`, etc.), and zero drop shadows.
- **T1.6 (F6 Pipeline Reverse Flow Absence)**: `relazione/pipeline_execution_tikz.tex` must contain zero right-to-left reverse arrows (`(p4.west) -- ... (p5.east)`), zero 1.45cm off-center drop connectors, and zero nested 7-pillbox stacks.

#### Tier 2: Boundary & Corner Cases (Typography, Casing & Macro Safety)
- **T2.1 (Capitalization & Colon Rules)**: Compliance with `regole_tesi.md`: verify that labels followed by colons ("Docente:", "Candidati:") do not introduce illicit capital letters, and titles/headings use standard sentence capitalization (no ALL-CAPS or Title Case for every word).
- **T2.2 (Chapter Numbering & Spacing Bounds)**: `\titleformat{\chapter}` must not hardcode leading zero ("CAPITOLO 0\thechapter"); `\titlespacing*{\chapter}` must use clean positive top spacing rather than negative hack offsets (`-22pt`).
- **T2.3 (Macro Deprecation Safety)**: If `\branddot` is defined, it must resolve to a safe no-op (`\newcommand{\branddot}{}`) so that legacy references compile safely without syntax errors.
- **T2.4 (Card Border Flattening)**: `htmlCard` and `editorialCard` styles must feature clean flat borders (`draw=brandBorderStrong` or `brandBorder`, `line width=0.8pt`) with zero cascaded `preaction={drop shadow=...}` preactions.
- **T2.5 (Listing Container Shadows)**: `\tcolorboxenvironment{lstlisting}` must not include the 5-layer cascaded `shadow={...}` stack, using a crisp flat frame with soft arc (`arc=4pt`, `boxrule=0.6pt`).

#### Tier 3: Cross-Feature Combinations (Harmonization Across All Files)
- **T3.1 (Color Token Contract)**: All 9 TikZ diagrams must strictly use declared project palette tokens (`brandPrimary`, `brandDark`, `brandInkSoft`, `brandCoral`, `brandTeal`, `brandBorderStrong`, `brandSurface`), with zero undeclared colors.
- **T3.2 (Zero Background Grids)**: Exhaustive check across all 9 TikZ diagrams confirming zero background grids (`\draw.*grid`, `step=`, `help lines`), honoring thesis standards.
- **T3.3 (Self-Contained TikZ Bounding)**: All standalone TikZ diagrams must reside inside `tikzpicture` environments without unclosed groups or missing coordinates, scaling cleanly under `\resizebox{\textwidth}{!}{\input{...}}`.
- **T3.4 (Flow Direction Consistency)**: Both Tier 1 (Lakehouse) and Tier 2 (Analytics & Serving) in `pipeline_execution_tikz.tex` must flow in unidirectional Left-to-Right orientation.

#### Tier 4: Document Compilation Scenario (End-to-End Build)
- **T4.1 (Compiler Execution)**: Invocation of `pdflatex` / `latexmk` on `relazione/main.tex` executes to completion with exit code `0`.
- **T4.2 (Zero Fatal Errors)**: Verification that `relazione/main.log` contains zero fatal error signatures (`! LaTeX Error:`, `Fatal error occurred`).
- **T4.3 (Complete Document Artifact)**: Verification that `relazione/main.pdf` is generated, has non-zero size (> 100 KB), and contains the complete document structure (frontispiece, table of contents, chapters 1 through 5, and bibliography).

---

## 5. Execution Protocol & Verification Harness

### 5.1 Standalone Test Runner: `verify_redesign.py`
The project includes a standalone executable Python test runner located at the repository root:
`c:\Users\andre\Documents\GitHub\NGDB\anomaly-detection-vitaldb\verify_redesign.py`

#### Commands:
```bash
# Run full 4-tier test suite with detailed diagnostics
python verify_redesign.py

# Run specific tier (Tier 1: Feature Coverage, Tier 2: Boundary, Tier 3: Cross-Feature, Tier 4: Compilation)
python verify_redesign.py --tier 1
python verify_redesign.py --tier 2
python verify_redesign.py --tier 3
python verify_redesign.py --tier 4

# Run specific feature verification (F1 through F8)
python verify_redesign.py --feature F1
python verify_redesign.py --feature F5
python verify_redesign.py --feature F6

# Run with LaTeX compilation attempt (Tier 4)
python verify_redesign.py --compile

# Output structured JSON for automated tooling / CI
python verify_redesign.py --json
```

### 5.2 Pytest Integration: `tests/test_latex_redesign.py`
For unified testing alongside the existing project test suite (`pytest tests/`), a pytest module is co-located in `tests/`:
```bash
# Run LaTeX redesign tests via pytest
pytest tests/test_latex_redesign.py -v

# Run alongside existing test suite
pytest tests/ -v
```

### 5.3 Exit Code Standards:
- `Exit Code 0`: All targeted tests PASSED. The codebase fully satisfies acceptance criteria for the selected tier/feature.
- `Exit Code 1`: One or more tests FAILED. The test runner outputs exact file paths, offending lines, and remediation guidance.
- `Exit Code 2`: Configuration or environment error (e.g. missing target directory or syntax failure in test runner).

---

## 6. Baseline Quality Audit & Expected Defect Triage

Running the test suite against the initial baseline state (before M1 and M2 implementation) yields expected failures that systematically map to the work scopes of downstream implementation agents:

| Feature / Tier | Current Baseline Status | Offending Lines / Root Cause | Target Worker |
|:---|:---|:---|:---|
| **F1 (Frontespizio)** | **FAIL** (Tier 1 & 2) | `main.tex:336-344` (gradient spheres), `main.tex:361` (avatar seal shadow), `main.tex:382-438` (4 pill badges with shadows, 3 `\branddot` instances) | `teamwork_worker_m1` |
| **F2 (Chapter Headings)** | **FAIL** (Tier 1 & 2) | `main.tex:116-127` (TikZ pill badge, drop shadow, `\branddot`, "CAPITOLO 0\thechapter", peach-blue gradient underline) | `teamwork_worker_m1` |
| **F3 (Footers & Folios)** | **FAIL** (Tier 1 & 2) | `main.tex:156-166, 174-184` (TikZ pill badge with drop shadow enclosing `Pag. \thepage`) | `teamwork_worker_m1` |
| **F4 (Artifact Deprecation)**| **FAIL** (Tier 1 & 2) | `main.tex:99` (active `\branddot`), `main.tex:84-86` (3-layer shadow in `htmlCard`), `main.tex:319-323` (5-layer shadow in `lstlisting`) | `teamwork_worker_m1` |
| **F5 (Medallion Diagram)** | **FAIL** (Tier 1 & 2) | `medallion_tikz.tex:23-33, 42-50, 55-67` (3 layer pill badges, 9 inline dot circles, 3 foot metric pills) | `teamwork_worker_m2` |
| **F6 (Pipeline Execution)** | **FAIL** (Tier 1 & 2) | `pipeline_execution_tikz.tex:175-176` (reverse snake arrow Right-to-Left, 1.45cm off-center drop arrow, 9 nested `pillBox` nodes) | `teamwork_worker_m2` |
| **F7 (Diagram Consistency)** | **PASS** (Zero grids) / **FAIL** (Style) | All 9 diagrams have zero grids (PASS), but inherit `htmlCard` shadows and pill styles | `teamwork_worker_m2` |
| **F8 (End-to-End Build)** | **PASS** (Compiles baseline) | Baseline compiles with warnings; must maintain clean compilation with redesigned assets | `teamwork_worker_m3` |

This test infrastructure provides the orchestrator and all milestone workers with unambiguous, objective pass/fail criteria to track progress through milestone completion.
