"""Tests for ticker_utils.t212_to_yf conversion."""

import pytest

from src.utils.ticker_utils import t212_to_yf


def test_basic_us_eq():
    assert t212_to_yf("AAPL_US_EQ") == "AAPL"
    assert t212_to_yf("MSFT_US_EQ") == "MSFT"


def test_uk_eq():
    assert t212_to_yf("BP._UK_EQ") == "BP."
    assert t212_to_yf("HSBC_UK_EQ") == "HSBC"


def test_class_a_slash_to_hyphen():
    assert t212_to_yf("TAP/A_US_EQ") == "TAP-A"


def test_class_b_underscore_to_dot():
    assert t212_to_yf("BRK_B_US_EQ") == "BRK.B"
    assert t212_to_yf("BF_B_US_EQ") == "BF.B"


def test_non_standard_eq_suffix():
    assert t212_to_yf("VPNUS_EQ") == "VPNUS"  # strip _EQ


def test_whitespace_handling():
    assert t212_to_yf("  AAPL_US_EQ  ") == "AAPL"
