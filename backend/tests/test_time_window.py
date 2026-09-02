import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from models import is_in_time_window


class TestSameDayWindow:
    @pytest.mark.parametrize("now", ["07:00", "07:30", "09:00"])
    def test_inside_window_inclusive_of_bounds(self, now):
        assert is_in_time_window(now, "07:00", "09:00") is True

    @pytest.mark.parametrize("now", ["06:59", "09:01", "23:59", "00:00"])
    def test_outside_window(self, now):
        assert is_in_time_window(now, "07:00", "09:00") is False


class TestCrossMidnightWindow:
    @pytest.mark.parametrize("now", ["22:00", "23:59", "00:00", "05:59", "06:00"])
    def test_inside_wrapping_window(self, now):
        assert is_in_time_window(now, "22:00", "06:00") is True

    @pytest.mark.parametrize("now", ["06:01", "12:00", "21:59"])
    def test_outside_wrapping_window(self, now):
        assert is_in_time_window(now, "22:00", "06:00") is False
