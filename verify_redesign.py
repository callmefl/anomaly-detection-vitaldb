#!/usr/bin/env python3
"""
E2E Verification Suite for Thesis Redesign (VitalDB Anomaly Detection)
Authoritative Specifications: ORIGINAL_REQUEST.md, PROJECT.md, regole_tesi.md

Validates editorial typography, TikZ architectural diagrams, AI-template artifact deprecation,
and document compilation across 4 progressive tiers (F1 through F8).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class TestResult:
    feature: str
    tier: int
    name: str
    passed: bool
    message: str
    details: List[str] = field(default_factory=list)
    severity: str = "ERROR"  # ERROR, WARNING, INFO


def strip_latex_comments(content: str) -> str:
    r"""Strip LaTeX comments (% ...) while preserving escaped \% and newlines."""
    lines = content.splitlines()
    cleaned_lines = []
    for line in lines:
        # Match unescaped %
        # A % is a comment if not preceded by an odd number of backslashes
        comment_idx = None
        for i, char in enumerate(line):
            if char == "%":
                # count backslashes immediately preceding
                bs_count = 0
                j = i - 1
                while j >= 0 and line[j] == "\\":
                    bs_count += 1
                    j -= 1
                if bs_count % 2 == 0:
                    comment_idx = i
                    break
        if comment_idx is not None:
            cleaned_lines.append(line[:comment_idx])
        else:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


class LaTeXRedesignVerifier:
    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            self.project_root = Path(__file__).resolve().parent
        else:
            self.project_root = Path(project_root).resolve()

        self.relazione_dir = self.project_root / "relazione"
        self.main_tex_path = self.relazione_dir / "main.tex"
        self.medallion_path = self.relazione_dir / "medallion_tikz.tex"
        self.pipeline_path = self.relazione_dir / "pipeline_execution_tikz.tex"

        self.all_tikz_files = sorted(list(self.relazione_dir.glob("*_tikz.tex")))

    def _read_file(self, path: Path) -> str:
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def _read_active_file(self, path: Path) -> str:
        raw = self._read_file(path)
        return strip_latex_comments(raw)

    # =========================================================================
    # F1: Minimalist Editorial Frontespizio
    # =========================================================================
    def check_f1_frontespizio(self) -> List[TestResult]:
        results = []
        raw_content = self._read_file(self.main_tex_path)
        active_content = self._read_active_file(self.main_tex_path)

        if not self.main_tex_path.exists():
            return [TestResult("F1", 1, "Frontespizio Exists", False, f"File not found: {self.main_tex_path}")]

        # Extract titlepage
        titlepage_match = re.search(r"\\begin\{titlepage\}(.*?)\\end\{titlepage\}", active_content, re.DOTALL)
        if not titlepage_match:
            results.append(TestResult(
                "F1", 1, "Titlepage Environment", False,
                "\\begin{titlepage} ... \\end{titlepage} block not found in main.tex"
            ))
            return results

        tp_text = titlepage_match.group(1)

        # 1. Absence of \branddot in titlepage
        branddot_in_tp = bool(re.search(r"\\branddot\b", tp_text))
        results.append(TestResult(
            "F1", 1, "Absence of \\branddot in Frontespizio",
            not branddot_in_tp,
            "\\branddot detected in frontespizio" if branddot_in_tp else "Zero \\branddot in frontespizio",
            ["Found \\branddot in titlepage"] if branddot_in_tp else []
        ))

        # 2. Absence of shaded hero spheres
        # Checks for \shade.*circle or sphere.xl-a/b style
        spheres_in_tp = bool(re.search(r"\\shade\[.*?circle\s*\([0-9.]+cm\)", tp_text, re.DOTALL))
        results.append(TestResult(
            "F1", 1, "Absence of Gradient Spheres in Frontespizio",
            not spheres_in_tp,
            "Faux-3D shaded spheres found in frontespizio canvas" if spheres_in_tp else "Zero decorative shaded spheres in frontespizio",
            ["Shaded circle coordinates found in titlepage"] if spheres_in_tp else []
        ))

        # 3. Absence of pill badges on Docente, Candidati, and Anno Accademico
        # Check for rounded corners >= 10pt with drop shadow on person blocks
        pill_badges = re.findall(r"rounded\s+corners\s*=\s*(?:1[0-9]|[2-9][0-9])pt.*?drop\s+shadow", tp_text, re.DOTALL)
        has_pills = len(pill_badges) > 0 or "rounded corners=13pt" in tp_text or "rounded corners=11pt" in tp_text
        results.append(TestResult(
            "F1", 1, "Absence of Pill Badges in Frontespizio",
            not has_pills,
            f"Found {len(pill_badges)} pill badge containers in frontespizio" if has_pills else "Zero pill badges in frontespizio",
            [f"Pill matches: {pill_badges}"] if has_pills else []
        ))

        # 4. Absence of drop shadow on UNIVPM seal avatar
        seal_shadow = bool(re.search(r"univpm_seal\.png.*?drop\s+shadow|drop\s+shadow.*?univpm_seal\.png", tp_text, re.DOTALL))
        results.append(TestResult(
            "F1", 1, "Absence of Drop Shadow on Seal Avatar",
            not seal_shadow,
            "Drop shadow on university seal card detected" if seal_shadow else "Zero drop shadow on university seal",
            ["Drop shadow attached to seal node"] if seal_shadow else []
        ))

        # 5. Presence of required institutional and academic metadata (Tier 2 Boundary)
        has_docente = "Claudia Diamantini" in tp_text
        has_altieri = "Andrea Altieri" in tp_text
        has_flaiani = "Andrea Flaiani" in tp_text
        has_anno = bool(re.search(r"anno\s+accademico|2026", tp_text, re.IGNORECASE))
        all_metadata = has_docente and has_altieri and has_flaiani and has_anno
        results.append(TestResult(
            "F1", 2, "Frontespizio Academic Metadata Integrity",
            all_metadata,
            "Complete metadata present" if all_metadata else "Missing one or more required academic metadata items",
            [f"Docente: {has_docente}, Altieri: {has_altieri}, Flaiani: {has_flaiani}, Anno: {has_anno}"]
        ))

        return results

    # =========================================================================
    # F2: Clean Editorial Chapter Headings
    # =========================================================================
    def check_f2_chapter_headings(self) -> List[TestResult]:
        results = []
        active_content = self._read_active_file(self.main_tex_path)

        # Match \titleformat{\chapter}
        tf_match = re.search(r"\\titleformat\{\\chapter\}(.*?)(?=\\titlespacing|\n\n\n|\\titleformat|$)", active_content, re.DOTALL)
        if not tf_match:
            results.append(TestResult("F2", 1, "Chapter Titleformat", False, "\\titleformat{\\chapter} not found in main.tex"))
            return results

        tf_text = tf_match.group(1)

        # 1. Absence of TikZ pill badge node with \branddot or drop shadow
        has_tikz_pill = bool(re.search(r"\\tikz.*?\\node\[.*?rounded\s+corners.*?drop\s+shadow", tf_text, re.DOTALL))
        has_branddot_in_heading = "\\branddot" in tf_text
        results.append(TestResult(
            "F2", 1, "Absence of TikZ Pill Badge in Chapter Headings",
            not (has_tikz_pill or has_branddot_in_heading),
            "TikZ pill badge / \\branddot detected in \\titleformat{\\chapter}" if (has_tikz_pill or has_branddot_in_heading) else "Clean chapter heading prefix without TikZ pill badge",
            ["TikZ pill node in \\titleformat{\\chapter}"] if (has_tikz_pill or has_branddot_in_heading) else []
        ))

        # 2. Absence of hardcoded "CAPITOLO 0\thechapter" prefix hack
        has_zero_hack = "CAPITOLO 0\\thechapter" in tf_text or "Capitolo 0\\thechapter" in tf_text
        results.append(TestResult(
            "F2", 2, "Absence of Hardcoded Zero Hack (0\\thechapter)",
            not has_zero_hack,
            "Hardcoded '0\\thechapter' hack found in chapter titleformat" if has_zero_hack else "Proper dynamic chapter numbering format",
            ["Found hardcoded '0\\thechapter'"] if has_zero_hack else []
        ))

        # 3. Absence of peach-blue gradient underline box
        has_gradient_underline = bool(re.search(r"\\shade\[.*?left\s+color\s*=\s*brandPeach.*?right\s+color\s*=\s*brandPrimary.*?rectangle", tf_text, re.DOTALL))
        results.append(TestResult(
            "F2", 1, "Absence of Peach-Blue Gradient Underline in Chapter Headings",
            not has_gradient_underline,
            "Peach-blue gradient underline bar found in \\titleformat{\\chapter}" if has_gradient_underline else "Clean solid hairline rule or ruleless editorial heading",
            ["Found \\shade[left color=brandPeach, right color=brandPrimary]"] if has_gradient_underline else []
        ))

        # 4. Spacing sanity check (Tier 2 Boundary)
        ts_match = re.search(r"\\titlespacing\*?\{\\chapter\}\{.*?\}\{(.*?)\}\{.*?\}", active_content)
        if ts_match:
            top_spacing = ts_match.group(1).strip()
            is_negative_hack = "-" in top_spacing and "22pt" in top_spacing
            results.append(TestResult(
                "F2", 2, "Chapter Top Spacing Natural Bounds",
                not is_negative_hack,
                f"Negative top spacing offset hack ({top_spacing}) detected" if is_negative_hack else f"Natural chapter title spacing ({top_spacing})",
                [f"Top spacing value: {top_spacing}"]
            ))

        return results

    # =========================================================================
    # F3: Typographic Page Numbering
    # =========================================================================
    def check_f3_page_numbering(self) -> List[TestResult]:
        results = []
        active_content = self._read_active_file(self.main_tex_path)

        # Match \fancyfoot and \fancypagestyle{plain}
        fancyfoot_matches = re.findall(r"\\fancyfoot\[R\]\{(.*?)\}", active_content, re.DOTALL)
        plain_style_match = re.search(r"\\fancypagestyle\{plain\}\{(.*?)\}", active_content, re.DOTALL)

        all_footer_code = " ".join(fancyfoot_matches)
        if plain_style_match:
            all_footer_code += " " + plain_style_match.group(1)

        # 1. Absence of TikZ node pill badge around \thepage
        has_tikz_pill_footer = bool(re.search(r"\\tikz.*?\\node\[.*?rounded\s+corners.*?drop\s+shadow.*?\\thepage", all_footer_code, re.DOTALL))
        has_rounded_footer_box = "rounded corners=8pt" in all_footer_code and "\\thepage" in all_footer_code
        is_pill_footer = has_tikz_pill_footer or has_rounded_footer_box

        results.append(TestResult(
            "F3", 1, "Absence of TikZ Pill Badge in Footers",
            not is_pill_footer,
            "TikZ pill badge enclosing page number detected in footer" if is_pill_footer else "Clean typographic page numbering without pill badges",
            ["Pill node wrapping \\thepage in footer"] if is_pill_footer else []
        ))

        # 2. Absence of heavy "Pag. " button prefix in folios
        has_pag_prefix = bool(re.search(r"Pag\.\s*\\textcolor|Pag\.\s*\\thepage", all_footer_code))
        results.append(TestResult(
            "F3", 2, "Clean Typographic Folio (No 'Pag.' Web Button)",
            not has_pag_prefix,
            "Heavy 'Pag. ' button prefix found in footer" if has_pag_prefix else "Unobtrusive pure page number folio",
            ["Found 'Pag.' prefix in footer"] if has_pag_prefix else []
        ))

        # 3. Clean \thepage output presence
        has_thepage = "\\thepage" in all_footer_code
        results.append(TestResult(
            "F3", 1, "Presence of Dynamic Page Numbering (\\thepage)",
            has_thepage,
            "\\thepage macro present in footers" if has_thepage else "Missing \\thepage in footers"
        ))

        return results

    # =========================================================================
    # F4: AI Artifact Deprecation
    # =========================================================================
    def check_f4_ai_artifact_deprecation(self) -> List[TestResult]:
        results = []
        active_main = self._read_active_file(self.main_tex_path)

        # 1. Scan ALL .tex files for active invocations of \branddot
        active_branddot_locations = []
        for tex_path in self.relazione_dir.rglob("*.tex"):
            content = self._read_active_file(tex_path)
            # Find \branddot not part of \newcommand{\branddot} or \renewcommand{\branddot}
            matches = [m.start() for m in re.finditer(r"\\branddot\b", content)]
            # Filter out macro definition itself
            def_matches = [m.start() for m in re.finditer(r"\\(?:re)?newcommand\{\\branddot\}", content)]
            # If a match is inside a definition, ignore it
            real_invocations = []
            for m in matches:
                if not any(d <= m <= d + 30 for d in def_matches):
                    real_invocations.append(m)
            if real_invocations:
                rel_path = tex_path.relative_to(self.project_root)
                active_branddot_locations.append(f"{rel_path} ({len(real_invocations)} invocations)")

        no_branddot_invocations = len(active_branddot_locations) == 0
        results.append(TestResult(
            "F4", 1, "Zero Active \\branddot Invocations in Project",
            no_branddot_invocations,
            f"Active \\branddot invocations found in: {', '.join(active_branddot_locations)}" if not no_branddot_invocations else "Zero active \\branddot invocations across all project files",
            active_branddot_locations
        ))

        # 2. Check definition of \branddot: must be safe/empty or completely removed
        branddot_def = re.search(r"\\newcommand\{\\branddot\}\{(.*?)\}", active_main, re.DOTALL)
        if branddot_def:
            def_body = branddot_def.group(1).strip()
            # If it still contains \shade or circle, it's not deprecated
            is_heavy_sphere = "circle" in def_body and "\\shade" in def_body
            results.append(TestResult(
                "F4", 2, "Safe Deprecation of \\branddot Macro",
                not is_heavy_sphere,
                "\\branddot still contains heavy TikZ shaded sphere definition" if is_heavy_sphere else "\\branddot safely deprecated to empty/no-op macro",
                [f"Definition body: {def_body[:60]}..."] if is_heavy_sphere else []
            ))
        else:
            results.append(TestResult(
                "F4", 2, "Safe Deprecation of \\branddot Macro",
                True,
                "\\branddot macro removed entirely from main.tex"
            ))

        # 3. Check htmlCard style: must not contain 3-layer drop shadows
        htmlcard_match = re.search(r"htmlCard/\.style\s*=\s*\{(.*?)\}", active_main, re.DOTALL)
        if htmlcard_match:
            card_body = htmlcard_match.group(1)
            drop_shadow_count = len(re.findall(r"drop\s+shadow", card_body))
            is_flat_card = drop_shadow_count == 0
            results.append(TestResult(
                "F4", 2, "htmlCard Flat Border (Zero Drop Shadows)",
                is_flat_card,
                f"htmlCard contains {drop_shadow_count} cascaded drop shadow preactions" if not is_flat_card else "htmlCard uses clean flat borders without drop shadows",
                ["Multi-layer drop shadows in htmlCard"] if not is_flat_card else []
            ))

        # 4. Check lstlisting tcolorbox: must not contain 5-layer cascaded shadow stack
        lst_match = re.search(r"\\tcolorboxenvironment\{lstlisting\}\{(.*?)\}", active_main, re.DOTALL)
        if lst_match:
            lst_body = lst_match.group(1)
            shadow_count = len(re.findall(r"shadow\s*=\s*\{", lst_body))
            is_flat_listing = shadow_count == 0
            results.append(TestResult(
                "F4", 2, "lstlisting Container (Zero Cascaded Shadows)",
                is_flat_listing,
                f"lstlisting container has {shadow_count} stacked shadow preactions" if not is_flat_listing else "lstlisting uses clean flat frame without shadow stack",
                ["Stacked shadows in lstlisting"] if not is_flat_listing else []
            ))

        return results

    # =========================================================================
    # F5: Medallion Architecture Restructuring (relazione/medallion_tikz.tex)
    # =========================================================================
    def check_f5_medallion_architecture(self) -> List[TestResult]:
        results = []
        if not self.medallion_path.exists():
            return [TestResult("F5", 1, "Medallion File Exists", False, f"File missing: {self.medallion_path}")]

        active_content = self._read_active_file(self.medallion_path)

        # 1. Absence of rounded pill badges on layers (rounded corners=9pt with inline circle)
        pill_badges = re.findall(r"rounded\s+corners\s*=\s*9pt.*?LAYER", active_content, re.DOTALL)
        has_layer_pills = len(pill_badges) > 0
        results.append(TestResult(
            "F5", 1, "Absence of Pill Badges on Medallion Layers",
            not has_layer_pills,
            f"Found {len(pill_badges)} rounded pill badges on Medallion layers" if has_layer_pills else "Zero rounded pill badges in Medallion diagram",
            pill_badges
        ))

        # 2. Absence of nested inline TikZ bullet circles (\tikz[baseline...]\fill circle)
        inline_circles = re.findall(r"\\tikz.*?\\fill.*?circle", active_content)
        has_inline_circles = len(inline_circles) > 0
        results.append(TestResult(
            "F5", 1, "Absence of Nested Inline TikZ Bullet Circles",
            not has_inline_circles,
            f"Found {len(inline_circles)} nested inline TikZ bullet circles in item rows" if has_inline_circles else "Zero nested inline bullet circles in Medallion diagram",
            [f"Count: {len(inline_circles)}"]
        ))

        # 3. Absence of transient metric foot pill badges (33,95 MB, 44,52 MB, etc.)
        transient_metrics = re.findall(r"(?:33,95|44,52|15,60)\s*MB", active_content)
        has_transient_metrics = len(transient_metrics) > 0
        results.append(TestResult(
            "F5", 1, "Elimination of Redundant Benchmark Telemetry Clutter",
            not has_transient_metrics,
            f"Found {len(transient_metrics)} transient byte count badges in architectural diagram" if has_transient_metrics else "Architectural schema clean of redundant benchmark clutter",
            transient_metrics
        ))

        # 4. Presence of 3-column architecture (Bronze, Silver, Gold) (Tier 2 Boundary)
        has_bronze = bool(re.search(r"bronze|livello\s*0?1", active_content, re.IGNORECASE))
        has_silver = bool(re.search(r"silver|livello\s*0?2", active_content, re.IGNORECASE))
        has_gold = bool(re.search(r"gold|livello\s*0?3", active_content, re.IGNORECASE))
        has_clean_script = "clean.py" in active_content
        has_load_script = "load_mongo.py" in active_content or "load\\_mongo.py" in active_content
        complete_architecture = has_bronze and has_silver and has_gold and has_clean_script and has_load_script
        results.append(TestResult(
            "F5", 2, "Medallion 3-Tier Layer Completeness & Transitions",
            complete_architecture,
            "Complete 3-tier structure with clean.py and load_mongo.py transitions" if complete_architecture else "Incomplete Medallion structure or missing pipeline transition scripts",
            [f"Bronze: {has_bronze}, Silver: {has_silver}, Gold: {has_gold}, clean.py: {has_clean_script}, load_mongo.py: {has_load_script}"]
        ))

        return results

    # =========================================================================
    # F6: Pipeline Execution Restructuring (relazione/pipeline_execution_tikz.tex)
    # =========================================================================
    def check_f6_pipeline_execution(self) -> List[TestResult]:
        results = []
        if not self.pipeline_path.exists():
            return [TestResult("F6", 1, "Pipeline File Exists", False, f"File missing: {self.pipeline_path}")]

        active_content = self._read_active_file(self.pipeline_path)

        # 1. Absence of reverse snake U-turn dataflow (Phase 04 -> Phase 05 Right-to-Left)
        # In baseline, arrow is: \draw[flowArrow] (p4.west) -- node... (p5.east); where p4 is on right (x=4.45) and p5 on left (x=-4.45)
        reverse_arrow_match = re.search(r"\(p4\.west\)\s*--.*?\(p5\.east\)", active_content)
        has_reverse_arrow = bool(reverse_arrow_match)
        results.append(TestResult(
            "F6", 1, "Absence of Reverse Snake U-Turn Flow (Right-to-Left)",
            not has_reverse_arrow,
            "Disorienting reverse Right-to-Left arrow detected ((p4.west) -- (p5.east))" if has_reverse_arrow else "Consistent Left-to-Right unidirectional dataflow",
            ["Found reverse arrow (p4.west) -- (p5.east)"] if has_reverse_arrow else []
        ))

        # 2. Absence of 1.45cm off-center vertical connector (p3.south |- p4.north)
        off_center_arrow = "(p3.south) -- (p3.south |- p4.north)" in active_content
        results.append(TestResult(
            "F6", 1, "Absence of 1.45cm Off-Center Connection Arrow",
            not off_center_arrow,
            "1.45cm off-center drop arrow detected ((p3.south) -- (p3.south |- p4.north))" if off_center_arrow else "Properly aligned vertical/cross-tier connection routing",
            ["Found off-center drop arrow"] if off_center_arrow else []
        ))

        # 3. Elimination of nested 7-pillbox stack (pillBox style)
        pillbox_count = len(re.findall(r"\\node\[pillBox", active_content))
        has_excessive_pillboxes = pillbox_count > 3
        results.append(TestResult(
            "F6", 1, "Elimination of Overcrowded Nested Pillbox Stacks",
            not has_excessive_pillboxes,
            f"Overcrowded nested pillboxes detected ({pillbox_count} pillBox nodes)" if has_excessive_pillboxes else f"Clean structured card layout ({pillbox_count} pillBox nodes)",
            [f"pillBox node count: {pillbox_count}"]
        ))

        # 4. Presence of all 5 functional phases in logical sequence (Tier 2 Boundary)
        has_p1 = bool(re.search(r"fase\s*0?1|ingestione", active_content, re.IGNORECASE))
        has_p2 = bool(re.search(r"fase\s*0?2|bonifica", active_content, re.IGNORECASE))
        has_p3 = bool(re.search(r"fase\s*0?3|gold|time\s*series", active_content, re.IGNORECASE))
        has_p4 = bool(re.search(r"fase\s*0?4|rilevamento|ibrido|detector", active_content, re.IGNORECASE))
        has_p5 = bool(re.search(r"fase\s*0?5|rest|dashboard|fastapi", active_content, re.IGNORECASE))
        all_phases = has_p1 and has_p2 and has_p3 and has_p4 and has_p5
        results.append(TestResult(
            "F6", 2, "Five-Phase Pipeline Completeness",
            all_phases,
            "All 5 execution phases present in diagram" if all_phases else "Missing one or more execution phases in pipeline diagram",
            [f"P1: {has_p1}, P2: {has_p2}, P3: {has_p3}, P4: {has_p4}, P5: {has_p5}"]
        ))

        return results

    # =========================================================================
    # F7: Cross-Diagram Style Harmonization
    # =========================================================================
    def check_f7_cross_diagram_harmonization(self) -> List[TestResult]:
        results = []

        if not self.all_tikz_files:
            return [TestResult("F7", 3, "TikZ Diagram Catalog", False, "No TikZ diagrams found in relazione/")]

        # 1. Zero background grids across all 9 diagrams
        grid_findings = []
        for tikz_file in self.all_tikz_files:
            content = self._read_active_file(tikz_file)
            has_grid = bool(re.search(r"\\draw.*?grid|help\s+lines|step\s*=", content))
            if has_grid:
                grid_findings.append(tikz_file.name)

        has_no_grids = len(grid_findings) == 0
        results.append(TestResult(
            "F7", 3, "Zero Background Grids Across All Diagrams",
            has_no_grids,
            f"Background grids found in: {', '.join(grid_findings)}" if not has_no_grids else f"Zero background grids confirmed across all {len(self.all_tikz_files)} diagrams",
            grid_findings
        ))

        # 2. Zero \branddot references across all diagrams
        branddot_findings = []
        for tikz_file in self.all_tikz_files:
            content = self._read_active_file(tikz_file)
            if "\\branddot" in content:
                branddot_findings.append(tikz_file.name)

        has_no_branddot_in_diagrams = len(branddot_findings) == 0
        results.append(TestResult(
            "F7", 3, "Zero \\branddot Invocations in Standalone Diagrams",
            has_no_branddot_in_diagrams,
            f"\\branddot invocations found in diagrams: {', '.join(branddot_findings)}" if not has_no_branddot_in_diagrams else "Zero \\branddot invocations across all standalone diagrams",
            branddot_findings
        ))

        # 3. TikZ Environment Scope Balancing (Tier 3 Combinations)
        unbalanced_files = []
        for tikz_file in self.all_tikz_files:
            content = self._read_active_file(tikz_file)
            begins = len(re.findall(r"\\begin\{tikzpicture\}", content))
            ends = len(re.findall(r"\\end\{tikzpicture\}", content))
            if begins != ends or begins == 0:
                unbalanced_files.append(f"{tikz_file.name} (begins={begins}, ends={ends})")

        has_balanced_scopes = len(unbalanced_files) == 0
        results.append(TestResult(
            "F7", 3, "TikZ Environment Scope Balancing",
            has_balanced_scopes,
            f"Unbalanced tikzpicture environments in: {', '.join(unbalanced_files)}" if not has_balanced_scopes else f"All {len(self.all_tikz_files)} diagrams properly balanced",
            unbalanced_files
        ))

        return results

    # =========================================================================
    # F8: End-to-End Build & Validation
    # =========================================================================
    def check_f8_compilation(self, attempt_compile: bool = False) -> List[TestResult]:
        results = []
        main_pdf = self.relazione_dir / "main.pdf"
        main_log = self.relazione_dir / "main.log"

        compiler_name = None
        for cmd in ["pdflatex", "latexmk"]:
            if shutil.which(cmd):
                compiler_name = cmd
                break

        # 1. Compiler Availability check
        has_compiler = compiler_name is not None
        results.append(TestResult(
            "F8", 4, "LaTeX Compiler Availability",
            has_compiler,
            f"Compiler available: {compiler_name}" if has_compiler else "No LaTeX compiler (latexmk/pdflatex) detected on PATH",
            [f"Compiler: {compiler_name}"] if has_compiler else []
        ))

        # 2. Compilation execution (if requested or compiler present)
        if attempt_compile and has_compiler:
            compile_cmd = [compiler_name, "-interaction=nonstopmode", "main.tex"]
            if compiler_name == "latexmk":
                compile_cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", "main.tex"]

            try:
                proc = subprocess.run(
                    compile_cmd,
                    cwd=str(self.relazione_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=180
                )
                compile_passed = proc.returncode == 0
                results.append(TestResult(
                    "F8", 4, f"Document Compilation ({compiler_name})",
                    compile_passed,
                    f"Compilation succeeded with exit code 0" if compile_passed else f"Compilation exited with non-zero code {proc.returncode}",
                    [proc.stdout[-500:] if proc.stdout else "No output"]
                ))
            except Exception as e:
                results.append(TestResult(
                    "F8", 4, f"Document Compilation Execution",
                    False,
                    f"Execution failed: {str(e)}",
                    [str(e)]
                ))
        else:
            # Fallback inspection of existing build logs
            if main_log.exists():
                log_content = main_log.read_text(encoding="utf-8", errors="replace")
                has_fatal_errors = bool(re.search(r"!\s+LaTeX\s+Error:|Fatal\s+error\s+occurred|Emergency\s+stop", log_content))
                results.append(TestResult(
                    "F8", 4, "Document Build Log Status (main.log)",
                    not has_fatal_errors,
                    "Fatal LaTeX errors detected in main.log" if has_fatal_errors else "main.log contains zero fatal errors",
                    ["Fatal error markers in main.log"] if has_fatal_errors else []
                ))

        # 3. Output PDF artifact presence and non-zero size
        pdf_exists = main_pdf.is_file() and main_pdf.stat().st_size > 50000
        size_kb = (main_pdf.stat().st_size // 1024) if (main_pdf.is_file()) else 0
        results.append(TestResult(
            "F8", 4, "Output PDF Generation (main.pdf)",
            pdf_exists,
            f"Valid output PDF verified: main.pdf ({size_kb} KB)" if pdf_exists else "main.pdf is missing or below minimum size threshold (<50 KB)",
            [f"Path: {main_pdf}, Size: {size_kb} KB"]
        ))

        return results

    # =========================================================================
    # Aggregation & Execution Runners
    # =========================================================================
    def run_all(self, attempt_compile: bool = False) -> List[TestResult]:
        all_results = []
        all_results.extend(self.check_f1_frontespizio())
        all_results.extend(self.check_f2_chapter_headings())
        all_results.extend(self.check_f3_page_numbering())
        all_results.extend(self.check_f4_ai_artifact_deprecation())
        all_results.extend(self.check_f5_medallion_architecture())
        all_results.extend(self.check_f6_pipeline_execution())
        all_results.extend(self.check_f7_cross_diagram_harmonization())
        all_results.extend(self.check_f8_compilation(attempt_compile=attempt_compile))
        return all_results

    def run_tier(self, tier: int, attempt_compile: bool = False) -> List[TestResult]:
        all_results = self.run_all(attempt_compile=attempt_compile)
        return [r for r in all_results if r.tier == tier]

    def run_feature(self, feature: str, attempt_compile: bool = False) -> List[TestResult]:
        feature_upper = feature.upper()
        if feature_upper == "F1":
            return self.check_f1_frontespizio()
        elif feature_upper == "F2":
            return self.check_f2_chapter_headings()
        elif feature_upper == "F3":
            return self.check_f3_page_numbering()
        elif feature_upper == "F4":
            return self.check_f4_ai_artifact_deprecation()
        elif feature_upper == "F5":
            return self.check_f5_medallion_architecture()
        elif feature_upper == "F6":
            return self.check_f6_pipeline_execution()
        elif feature_upper == "F7":
            return self.check_f7_cross_diagram_harmonization()
        elif feature_upper == "F8":
            return self.check_f8_compilation(attempt_compile=attempt_compile)
        else:
            raise ValueError(f"Unknown feature ID: {feature}. Expected F1..F8.")


def format_table(results: List[TestResult]) -> str:
    lines = []
    lines.append("=" * 86)
    lines.append(f"{'STATUS':<8} | {'FEAT':<5} | {'TIER':<4} | {'TEST NAME':<40} | {'MESSAGE'}")
    lines.append("-" * 86)
    for r in results:
        status_str = "[PASS]" if r.passed else "[FAIL]"
        lines.append(f"{status_str:<8} | {r.feature:<5} | T{r.tier:<3} | {r.name[:40]:<40} | {r.message}")
    lines.append("=" * 86)

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    pct = (passed / total * 100) if total > 0 else 0.0

    lines.append(f"SUMMARY: {total} tests ran | {passed} PASSED | {failed} FAILED | Pass Rate: {pct:.1f}%")
    lines.append("=" * 86)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="E2E Verification Suite for Thesis Redesign (VitalDB Anomaly Detection)"
    )
    parser.add_argument(
        "--tier", type=int, choices=[1, 2, 3, 4],
        help="Run tests for a specific coverage tier (1: Features, 2: Boundary, 3: Combinations, 4: Compilation)"
    )
    parser.add_argument(
        "--feature", type=str, choices=["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"],
        help="Run tests for a specific feature (F1 through F8)"
    )
    parser.add_argument(
        "--compile", action="store_true",
        help="Attempt live compilation of relazione/main.tex using pdflatex or latexmk"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output structured JSON report"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Output detailed diagnostics for failing tests"
    )

    args = parser.parse_args()
    verifier = LaTeXRedesignVerifier()

    if args.feature:
        results = verifier.run_feature(args.feature, attempt_compile=args.compile)
    elif args.tier:
        results = verifier.run_tier(args.tier, attempt_compile=args.compile)
    else:
        results = verifier.run_all(attempt_compile=args.compile)

    if args.json:
        report = {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "tests": [
                {
                    "feature": r.feature,
                    "tier": r.tier,
                    "name": r.name,
                    "passed": r.passed,
                    "message": r.message,
                    "details": r.details
                }
                for r in results
            ]
        }
        print(json.dumps(report, indent=2))
    else:
        print(format_table(results))
        if args.verbose:
            failures = [r for r in results if not r.passed]
            if failures:
                print("\nDETAILED FAILURE DIAGNOSTICS:")
                for f in failures:
                    print(f"\n[-] {f.feature} (Tier {f.tier}) - {f.name}:")
                    print(f"    Message: {f.message}")
                    for d in f.details:
                        print(f"    Detail:  {d}")

    # Return exit code: 0 if all passed, 1 if any failed
    all_passed = all(r.passed for r in results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
