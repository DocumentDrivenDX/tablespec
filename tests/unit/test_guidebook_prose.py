"""Tests for the guidebook prose-to-HTML formatter."""

from tablespec.guidebook.prose import format_prose


def test_empty_input_returns_empty_string():
    assert format_prose("") == ""
    assert format_prose(None) == ""
    assert format_prose("   \n  ") == ""


def test_plain_paragraph_wrapped_in_prose_block():
    out = format_prose("Just a sentence.")
    assert out.startswith('<div class="prose-block">')
    assert "<p>Just a sentence.</p>" in out


def test_html_is_escaped():
    out = format_prose("Beware <script>alert(1)</script>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_blank_lines_split_blocks():
    out = format_prose("First paragraph.\n\nSecond paragraph.")
    assert out.count("<p>") == 2
    assert "First paragraph." in out
    assert "Second paragraph." in out


def test_label_paragraph_bolds_label():
    out = format_prose("Source: enterprise gold table.")
    assert "<strong>Source:</strong>" in out
    assert "enterprise gold table." in out


def test_numbered_list_renders_as_ol():
    text = "1. First step.\n2. Second step.\n3. Third step."
    out = format_prose(text)
    assert "<ol>" in out
    assert out.count("<li>") == 3
    assert "First step." in out


def test_bulleted_list_renders_as_ul():
    text = "- alpha\n- beta\n- gamma"
    out = format_prose(text)
    assert "<ul>" in out
    assert out.count("<li>") == 3


def test_fenced_code_block_preserved():
    text = "```\nSELECT *\nFROM members\n```"
    out = format_prose(text)
    assert "<pre><code>" in out
    assert "SELECT *\nFROM members" in out


def test_indented_code_block_preserved():
    text = "    SELECT id\n    FROM members"
    out = format_prose(text)
    assert "<pre><code>" in out
    assert "SELECT id" in out


def test_inline_case_expression_wrapped_in_code():
    out = format_prose("Use CASE WHEN x IS NULL THEN 'a' ELSE 'b' END to compute.")
    assert (
        "<code>CASE WHEN x IS NULL THEN &#x27;a&#x27; ELSE &#x27;b&#x27; END</code>"
        in out
    )


def test_inline_function_call_wrapped_in_code():
    out = format_prose("Aggregate with MIN(completed_date_time) across the join.")
    assert "<code>MIN(completed_date_time)</code>" in out


def test_label_block_with_continuation_line():
    text = "Logic: pick the most recent record\nthen tiebreak on priority"
    out = format_prose(text)
    assert "<strong>Logic:</strong>" in out
    assert "<br>" in out
    assert "tiebreak on priority" in out


def test_mixed_blocks_render_in_order():
    text = (
        "Source: outreach_list.\n"
        "\n"
        "Logic applied:\n"
        "1. Pick the first call\n"
        "2. Fallback to inbound\n"
        "\n"
        "Beware nulls when both sources are missing."
    )
    out = format_prose(text)
    # Sequence: label, ol, plain paragraph.
    label_pos = out.index("<strong>Source:")
    ol_pos = out.index("<ol>")
    last_pos = out.index("Beware nulls")
    assert label_pos < ol_pos < last_pos


def test_label_followed_by_blank_line_does_not_capture_next_block():
    text = "Source: outreach_list.\n\nUnrelated paragraph."
    out = format_prose(text)
    assert "<strong>Source:</strong>" in out
    # Second paragraph stays its own <p>.
    assert "<p>Unrelated paragraph.</p>" in out


def test_unrecognized_label_capitalization_is_not_treated_as_label():
    """`HEDIS:` would be valid, but `but:` (lowercase) must not match."""
    out = format_prose("but: this should not be a label")
    assert "<strong>" not in out


def test_horizontal_rule_dashes_render_as_hr():
    text = "Intro paragraph.\n\n---\n\nDetail paragraph."
    out = format_prose(text)
    assert "<hr>" in out
    # `---` must not leak through as literal text.
    assert "<p>---</p>" not in out
    assert "Intro paragraph." in out
    assert "Detail paragraph." in out


def test_horizontal_rule_stars_render_as_hr():
    out = format_prose("---***\n\nstuff")
    # `---***` is not a pure rule, so it stays a paragraph; verify rule
    # detection is strict.
    assert "<hr>" not in out


def test_horizontal_rule_pure_stars_render_as_hr():
    out = format_prose("Before\n\n***\n\nAfter")
    assert "<hr>" in out


def test_multi_label_block_splits_into_separate_paragraphs():
    """Each label gets its own paragraph in a multi-label run-on."""
    text = (
        "Strategy: pick the best source.\n"
        "Selected source: outreach_list_gaps.quality_gap_group.\n"
        "Rejected candidates: outreach_list lacks gap detail.\n"
        "Business rules and fallback: leave null if no CARE row exists."
    )
    out = format_prose(text)
    assert out.count("<strong>Strategy:</strong>") == 1
    assert out.count("<strong>Selected source:</strong>") == 1
    assert out.count("<strong>Rejected candidates:</strong>") == 1
    assert out.count("<strong>Business rules and fallback:</strong>") == 1
    assert "<br>" not in out


def test_inline_known_label_splits_paragraph():
    """A long paragraph with inline `Fallback behavior:` should split there."""
    text = (
        "Strategy: pick the best authoritative source for the field. "
        "Fallback behavior: leave the value null when no source is present."
    )
    out = format_prose(text)
    assert "<strong>Strategy:</strong>" in out
    assert "<strong>Fallback behavior:</strong>" in out
    assert out.count("<p>") == 2


def test_inline_split_does_not_break_phrase_like_source_priority_rules():
    """Phrases that look like labels but aren't must not split."""
    text = (
        "This mapping aligns with Source Priority Rules: use outreach_list as primary, "
        "supplemental tables to fill gaps."
    )
    out = format_prose(text)
    assert out.count("<p>") == 1
    assert "<strong>Source:</strong>" not in out


def test_inline_split_does_not_affect_domain_acronyms():
    """Domain acronyms must stay plain text."""
    text = "Use the PCP record if present; otherwise treat CARE gaps as authoritative."
    out = format_prose(text)
    assert "<strong>" not in out
    assert out.count("<p>") == 1


def test_inline_split_preserves_intro_text_before_first_label():
    """Leading non-label prose becomes its own paragraph."""
    text = "This field comes from the outreach package. Fallback behavior: null when missing."
    out = format_prose(text)
    assert out.count("<p>") == 2
    assert "<strong>Fallback behavior:</strong>" in out


def test_inline_split_skips_inside_fenced_code():
    """Fenced code blocks pass through unchanged."""
    text = "```\n-- Strategy: keep this in code\nSELECT 1\n```"
    out = format_prose(text)
    assert "<pre><code>" in out
    assert "<strong>Strategy:</strong>" not in out


def test_single_label_with_continuation_still_uses_br():
    """Single label + continuation prose stays as one paragraph with <br>."""
    text = "Logic: do this thing\nand then do another thing"
    out = format_prose(text)
    assert "<br>" in out
    assert out.count("<strong>") == 1
