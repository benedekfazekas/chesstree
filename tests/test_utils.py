"""Tests for chesstree.utils"""
import pytest
from chesstree.utils import has_real_comment


class TestHasRealComment:
    def test_empty_string(self):
        assert has_real_comment("") is False

    def test_whitespace_only(self):
        assert has_real_comment("   ") is False

    def test_real_comment(self):
        assert has_real_comment("Good move!") is True

    def test_clk_only(self):
        assert has_real_comment("[%clk 0:05:00]") is False

    def test_clk_with_space(self):
        assert has_real_comment(" [%clk 1:23:45] ") is False

    def test_emt_only(self):
        assert has_real_comment("[%emt 0:00:03]") is False

    def test_eval_only(self):
        assert has_real_comment("[%eval 0.5]") is False

    def test_csl_only(self):
        assert has_real_comment("[%csl Gd4,Re5]") is False

    def test_cal_only(self):
        assert has_real_comment("[%cal Ge2e4]") is False

    def test_clk_with_real_comment(self):
        assert has_real_comment("[%clk 0:05:00] This is a good move") is True

    def test_real_comment_with_clk(self):
        assert has_real_comment("Interesting idea. [%clk 0:02:30]") is True

    def test_multiple_annotations(self):
        assert has_real_comment("[%clk 0:05:00] [%eval 0.3]") is False

    def test_multiple_annotations_with_text(self):
        assert has_real_comment("[%clk 0:05:00] Critical position! [%eval 0.3]") is True

    def test_clk_with_decimal_seconds(self):
        assert has_real_comment("[%clk 0:00:03.5]") is False
