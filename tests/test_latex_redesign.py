"""
Pytest integration for E2E Thesis Redesign Verification.
Wraps verify_redesign.py checks into granular pytest assertions.
"""

import sys
from pathlib import Path
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from verify_redesign import LaTeXRedesignVerifier, TestResult


@pytest.fixture(scope="module")
def verifier():
    return LaTeXRedesignVerifier(project_root=PROJECT_ROOT)


# =============================================================================
# TIER 1: FEATURE COVERAGE (ABSENCE OF AI ARTIFACTS & WEB BADGES)
# =============================================================================

def test_t1_f1_absence_of_branddot_in_frontespizio(verifier):
    results = [r for r in verifier.check_f1_frontespizio() if "branddot" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t1_f1_absence_of_gradient_spheres_in_frontespizio(verifier):
    results = [r for r in verifier.check_f1_frontespizio() if "gradient spheres" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t1_f1_absence_of_pill_badges_in_frontespizio(verifier):
    results = [r for r in verifier.check_f1_frontespizio() if "pill badges" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t1_f1_absence_of_seal_drop_shadow(verifier):
    results = [r for r in verifier.check_f1_frontespizio() if "seal" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t1_f2_absence_of_chapter_heading_pills(verifier):
    results = [r for r in verifier.check_f2_chapter_headings() if "pill badge" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t1_f2_absence_of_gradient_underline(verifier):
    results = [r for r in verifier.check_f2_chapter_headings() if "gradient underline" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t1_f3_absence_of_footer_pills(verifier):
    results = [r for r in verifier.check_f3_page_numbering() if "pill badge" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t1_f4_zero_active_branddot_invocations(verifier):
    results = [r for r in verifier.check_f4_ai_artifact_deprecation() if "zero active \\branddot" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t1_f5_medallion_absence_of_layer_pills(verifier):
    results = [r for r in verifier.check_f5_medallion_architecture() if "pill badges" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t1_f5_medallion_absence_of_nested_bullet_circles(verifier):
    results = [r for r in verifier.check_f5_medallion_architecture() if "nested inline tikz" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t1_f5_medallion_absence_of_transient_metrics(verifier):
    results = [r for r in verifier.check_f5_medallion_architecture() if "benchmark telemetry" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t1_f6_pipeline_absence_of_reverse_flow(verifier):
    results = [r for r in verifier.check_f6_pipeline_execution() if "reverse snake" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t1_f6_pipeline_absence_of_off_center_arrow(verifier):
    results = [r for r in verifier.check_f6_pipeline_execution() if "off-center" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t1_f6_pipeline_elimination_of_overcrowded_pillboxes(verifier):
    results = [r for r in verifier.check_f6_pipeline_execution() if "nested pillbox" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


# =============================================================================
# TIER 2: BOUNDARY & CORNER CASES (CASING, DEFINITIONS, SHADOWS)
# =============================================================================

def test_t2_f1_frontespizio_metadata_integrity(verifier):
    results = [r for r in verifier.check_f1_frontespizio() if r.tier == 2]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t2_f2_chapter_top_spacing_bounds(verifier):
    results = [r for r in verifier.check_f2_chapter_headings() if r.tier == 2 and "spacing" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t2_f3_clean_folio_prefix(verifier):
    results = [r for r in verifier.check_f3_page_numbering() if r.tier == 2]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t2_f4_branddot_macro_safe_deprecation(verifier):
    results = [r for r in verifier.check_f4_ai_artifact_deprecation() if "safe deprecation" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t2_f4_htmlcard_zero_drop_shadows(verifier):
    results = [r for r in verifier.check_f4_ai_artifact_deprecation() if "htmlcard" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t2_f4_lstlisting_zero_shadows(verifier):
    results = [r for r in verifier.check_f4_ai_artifact_deprecation() if "lstlisting" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t2_f5_medallion_3_tier_completeness(verifier):
    results = [r for r in verifier.check_f5_medallion_architecture() if r.tier == 2]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t2_f6_pipeline_5_phase_completeness(verifier):
    results = [r for r in verifier.check_f6_pipeline_execution() if r.tier == 2]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


# =============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS
# =============================================================================

def test_t3_f7_zero_background_grids_across_all_diagrams(verifier):
    results = [r for r in verifier.check_f7_cross_diagram_harmonization() if "zero background grids" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t3_f7_zero_branddot_in_standalone_diagrams(verifier):
    results = [r for r in verifier.check_f7_cross_diagram_harmonization() if "zero \\branddot" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


def test_t3_f7_all_tikz_diagrams_balanced(verifier):
    results = [r for r in verifier.check_f7_cross_diagram_harmonization() if "scope balancing" in r.name.lower()]
    assert len(results) > 0
    for r in results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"


# =============================================================================
# TIER 4: COMPILATION & PDF ARTIFACT INTEGRITY
# =============================================================================

def test_t4_f8_compilation_and_log_status(verifier):
    results = verifier.check_f8_compilation(attempt_compile=False)
    # Check that main.pdf is present and valid
    pdf_results = [r for r in results if "pdf" in r.name.lower()]
    for r in pdf_results:
        assert r.passed, f"{r.name} failed: {r.message} -> {r.details}"
