import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import schedule
import time
from static_light import StaticLight
from lux import Lux

class TestStaticLight:
    @pytest.fixture
    def mock_logger(self):
        return Mock()

    @pytest.fixture
    def mock_scheduler(self):
        return Mock(spec=schedule)

    @pytest.fixture
    def static_light(self, mock_logger, mock_scheduler):
        light = StaticLight(mock_logger, pin=23, debug=True)
        light._scheduler = mock_scheduler
        return light

    def test_set_auto_mode_schedules_jobs(self, static_light, mock_scheduler):
        with patch.object(static_light, '_check_if_should_be_on'):
            static_light.set_auto_mode("08:00", 12)
            
            # Should be called at least once for the main schedule
            mock_scheduler.every.assert_called()
            mock_scheduler.every().day.at.assert_any_call("08:00")
        assert static_light._auto_mode is True
        assert static_light._start_time == "08:00"
        assert static_light._duration_hours == 12

    def test_auto_turn_on_schedules_turn_off(self, static_light, mock_scheduler):
        static_light._auto_mode = True
        static_light._duration_hours = 5
        
        with patch('datetime.datetime') as mock_datetime:
            mock_now = datetime(2025, 3, 25, 8, 0)
            mock_datetime.now.return_value = mock_now
            static_light.auto_turn_on(current_time=mock_now)
            
            # Verify turn off is scheduled for start_time + duration
            expected_time = (mock_datetime.now() + timedelta(hours=5)).strftime("%H:%M")
            mock_scheduler.every().day.at.assert_any_call(expected_time)
            static_light._logger.info.assert_called_with(
                "Auto turning on light at 08:00 for 5 hours"
            )

    def test_auto_turn_off_turns_off_light(self, static_light):
        static_light._auto_mode = True
        static_light.auto_turn_off()
        
        static_light._logger.info.assert_called_with(
            "Auto turning off light after 0 hours"
        )
        assert static_light._turn_off_job is None

class TestLux:
    @pytest.fixture
    def mock_logger(self):
        return Mock()

    @pytest.fixture
    def mock_scheduler(self):
        return Mock(spec=schedule)

    @pytest.fixture
    def lux(self, mock_logger, mock_scheduler):
        light = Lux(mock_logger, pin=16, debug=True)
        light._scheduler = mock_scheduler
        return light

    def test_set_auto_mode_schedules_jobs(self, lux, mock_scheduler):
        with patch.object(lux, '_check_if_should_be_on'):
            lux.set_auto_mode("08:00", 12, 80)
            
            # Should be called at least once for the main schedule
            mock_scheduler.every.assert_called()
            mock_scheduler.every().day.at.assert_any_call("08:00")
        assert lux._auto_mode is True
        assert lux._start_time == "08:00"
        assert lux._duration_hours == 12
        assert lux._auto_brightness == 80

    def test_auto_turn_on_sets_brightness(self, lux, mock_scheduler):
        lux._auto_mode = True
        lux._auto_brightness = 75
        lux._duration_hours = 5
        
        with patch('datetime.datetime') as mock_datetime:
            mock_now = datetime(2025, 3, 25, 8, 0)
            mock_datetime.now.return_value = mock_now
            lux.auto_turn_on(current_time=mock_now)
            
            # Verify turn off is scheduled for start_time + duration
            expected_time = (mock_datetime.now() + timedelta(hours=5)).strftime("%H:%M")
            mock_scheduler.every().day.at.assert_any_call(expected_time)
            lux._logger.info.assert_called_with(
                "Auto turning on light at 08:00 for 5 hours with brightness 75%"
            )
            assert lux._current_level == 75

    def test_auto_turn_off_turns_off_light(self, lux):
        lux._auto_mode = True
        lux._current_level = 50
        lux.auto_turn_off()
        
        lux._logger.info.assert_called_with(
            "Auto turning off light after 0 hours"
        )
        assert lux._turn_off_job is None
        assert lux._current_level == 0
