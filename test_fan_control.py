import unittest
from unittest.mock import patch, MagicMock, ANY
import time
import logging

# Mock the RPi.GPIO module before importing FanControl
# This prevents the real GPIO module from being loaded during tests
import sys
mock_gpio = MagicMock()
sys.modules['RPi'] = MagicMock()
sys.modules['RPi.GPIO'] = mock_gpio

# Now import the class under test
from fan_control import FanControl

# Configure a dummy logger for tests
logging.basicConfig(level=logging.DEBUG)
test_logger = logging.getLogger("TestFanControl")

class TestFanControl(unittest.TestCase):

    def setUp(self):
        """Set up for test methods."""
        # Reset mock before each test
        mock_gpio.reset_mock()
        # Use a distinct pin number for testing
        self.test_pin = 25
        # Instantiate FanControl in debug mode (forces mock GPIO usage)
        self.fan_control = FanControl(logger=test_logger, gpio_pin=self.test_pin, debug=True)
        # Ensure debug mode is active
        self.assertTrue(self.fan_control.debug)

    def test_initialization_debug(self):
        """Test initial state in debug mode."""
        self.assertEqual(self.fan_control.gpio_pin, self.test_pin)
        self.assertFalse(self.fan_control.is_on())
        self.assertEqual(self.fan_control.get_target_humidity(), 70.0)
        self.assertFalse(self.fan_control.is_control_active())
        # Check that GPIO setup was NOT called in debug mode
        mock_gpio.setmode.assert_not_called()
        mock_gpio.setup.assert_not_called()
        mock_gpio.output.assert_not_called()

    def test_turn_on_off_debug(self):
        """Test turning the fan on and off in debug mode."""
        self.assertFalse(self.fan_control.is_on())
        self.fan_control.turn_on()
        self.assertTrue(self.fan_control.is_on())
        # GPIO output should not be called in debug mode
        mock_gpio.output.assert_not_called()

        self.fan_control.turn_off()
        self.assertFalse(self.fan_control.is_on())
        mock_gpio.output.assert_not_called()

    def test_set_get_target_humidity(self):
        """Test setting and getting target humidity."""
        self.fan_control.set_target_humidity(65.5)
        self.assertEqual(self.fan_control.get_target_humidity(), 65.5)

        # Test invalid values (should log warning/error but might keep old value or default)
        initial_target = self.fan_control.get_target_humidity()
        self.fan_control.set_target_humidity(30) # Below range
        self.assertEqual(self.fan_control.get_target_humidity(), initial_target) # Assuming it rejects invalid
        self.fan_control.set_target_humidity(95) # Above range
        self.assertEqual(self.fan_control.get_target_humidity(), initial_target)
        self.fan_control.set_target_humidity("invalid") # Invalid type
        self.assertEqual(self.fan_control.get_target_humidity(), initial_target)


    def test_activate_deactivate_control(self):
        """Test activating and deactivating automatic control."""
        self.assertFalse(self.fan_control.is_control_active())
        self.fan_control.activate_control()
        self.assertTrue(self.fan_control.is_control_active())
        # Check if scheduler thread was started (mocked if needed, basic check here)
        self.assertTrue(self.fan_control._scheduler_running)
        self.assertIsNotNone(self.fan_control._scheduler_thread)

        self.fan_control.deactivate_control()
        self.assertFalse(self.fan_control.is_control_active())
        # Check if scheduler thread was stopped
        # Note: _stop_scheduler might take time, direct check might be tricky without sleep/mocks
        # self.assertFalse(self.fan_control._scheduler_running) # Check after join potentially
        self.assertFalse(self.fan_control.is_on()) # Ensure fan turned off

    def test_get_status(self):
        """Test the get_status method."""
        status = self.fan_control.get_status()
        self.assertIsInstance(status, dict)
        self.assertIn('is_on', status)
        self.assertIn('target_humidity', status)
        self.assertIn('control_active', status)
        self.assertEqual(status['is_on'], False)
        self.assertEqual(status['target_humidity'], 70.0)
        self.assertEqual(status['control_active'], False)

        self.fan_control.turn_on()
        self.fan_control.activate_control()
        self.fan_control.set_target_humidity(68.0)
        status = self.fan_control.get_status()
        self.assertEqual(status['is_on'], True)
        self.assertEqual(status['target_humidity'], 68.0)
        self.assertEqual(status['control_active'], True)

    @patch('threading.Timer')
    def test_check_humidity_control_fan_on(self, mock_timer_class):
        """Test humidity check triggers fan ON when humidity is low."""
        mock_timer_instance = MagicMock()
        mock_timer_class.return_value = mock_timer_instance

        self.fan_control.set_target_humidity(70.0)
        self.fan_control.activate_control()
        self.assertFalse(self.fan_control.is_on())

        # Simulate low humidity
        self.fan_control._check_humidity_and_control(60.0) # 10% below target

        # Assert fan turned on
        self.assertTrue(self.fan_control.is_on())
        # Assert Timer was called to schedule turn_off
        expected_duration = 10.0 * 10 # error * 10 seconds
        mock_timer_class.assert_called_once_with(expected_duration, self.fan_control.turn_off)
        mock_timer_instance.start.assert_called_once()

    @patch('threading.Timer')
    def test_check_humidity_control_fan_on_max_duration(self, mock_timer_class):
        """Test humidity check triggers fan ON with max duration."""
        mock_timer_instance = MagicMock()
        mock_timer_class.return_value = mock_timer_instance

        self.fan_control.set_target_humidity(70.0)
        self.fan_control.activate_control()

        # Simulate very low humidity (should hit max duration)
        self.fan_control._check_humidity_and_control(35.0) # 35% below target

        self.assertTrue(self.fan_control.is_on())
        max_duration = 300 # As defined in the implementation
        mock_timer_class.assert_called_once_with(max_duration, self.fan_control.turn_off)
        mock_timer_instance.start.assert_called_once()

    @patch('threading.Timer')
    def test_check_humidity_control_fan_off(self, mock_timer_class):
        """Test humidity check turns fan OFF when humidity is sufficient."""
        mock_timer_instance = MagicMock()
        mock_timer_class.return_value = mock_timer_instance

        self.fan_control.set_target_humidity(70.0)
        self.fan_control.activate_control()

        # Manually turn fan on to test turn-off logic
        self.fan_control.turn_on()
        self.assertTrue(self.fan_control.is_on())
        # Simulate a running timer
        self.fan_control._active_timer = mock_timer_instance
        mock_timer_instance.is_alive.return_value = True


        # Simulate sufficient humidity
        self.fan_control._check_humidity_and_control(70.5) # Slightly above target

        # Assert fan turned off
        self.assertFalse(self.fan_control.is_on())
        # Assert timer was cancelled
        mock_timer_instance.cancel.assert_called_once()

    @patch('threading.Timer')
    def test_check_humidity_control_inactive(self, mock_timer_class):
        """Test humidity check does nothing if control is inactive."""
        self.fan_control.set_target_humidity(70.0)
        # Ensure control is inactive (default)
        self.assertFalse(self.fan_control.is_control_active())

        # Simulate low humidity
        self.fan_control._check_humidity_and_control(60.0)

        # Assert fan remains off and timer not called
        self.assertFalse(self.fan_control.is_on())
        mock_timer_class.assert_not_called()

    def test_cleanup(self):
        """Test the cleanup method."""
        # Activate control and turn on fan to ensure cleanup handles active state
        self.fan_control.activate_control()
        self.fan_control.turn_on()
        self.assertTrue(self.fan_control.is_control_active())
        self.assertTrue(self.fan_control.is_on())

        self.fan_control.cleanup_gpio()

        # Assert control is deactivated and fan is off
        self.assertFalse(self.fan_control.is_control_active())
        self.assertFalse(self.fan_control.is_on())
        # GPIO cleanup should not be called in debug mode
        mock_gpio.cleanup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
