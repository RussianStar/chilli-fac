import time
import threading
import schedule
import logging
from gpio_device import gpio_device

# Attempt to import RPi.GPIO and handle ImportErrors if not on a Raspberry Pi
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    # Mock GPIO class for debugging/testing off-target
    class MockGPIO:
        BCM = "BCM_MODE"
        OUT = "OUTPUT_MODE"
        HIGH = 1
        LOW = 0
        def setmode(self, mode): pass
        def setup(self, pin, mode): pass
        def output(self, pin, state): pass
        def cleanup(self, pin=None): pass
    GPIO = MockGPIO()
    logging.warning("RPi.GPIO not found. Using mock GPIO.")

class FanControl(gpio_device):
    """
    Controls a fan connected to a GPIO pin based on target humidity.
    """

    def __init__(self, logger, state, gpio_pin, debug=False):
        """
        Initialize the FanControl.

        Args:
            logger: Logger instance.
            state: The SystemState object containing sensor readings.
            gpio_pin: The BCM GPIO pin number the fan is connected to.
            debug (bool): If True, use mock GPIO and skip actual hardware interaction.
        """
        self.logger = logger
        self.state = state # Store the state object
        self.gpio_pin = gpio_pin
        self.debug = debug or not GPIO_AVAILABLE # Force debug if GPIO not available

        self.logger.info(f"Initializing FanControl on GPIO pin {self.gpio_pin} (Debug: {self.debug})")

        # Initialize state variables
        self._is_running = False  # Tracks if the fan is currently physically on
        self._target_humidity = 20.0  # Default target humidity percentage
        self._control_active = False  # Whether the automatic control loop is active
        self._check_job = None  # Holds the scheduled humidity check job
        self._scheduler_thread = None
        self._scheduler_running = False
        self._active_timer = None # Holds the threading.Timer instance if fan is running timed

        if not self.debug:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self.gpio_pin, GPIO.OUT)
                # Initialize fan to OFF state (assuming HIGH is OFF)
                GPIO.output(self.gpio_pin, GPIO.HIGH)
                self.logger.info(f"GPIO pin {self.gpio_pin} setup as OUTPUT, initial state HIGH (OFF).")
            except Exception as e:
                self.logger.error(f"Error setting up GPIO pin {self.gpio_pin}: {e}. Switching to debug mode.")
                self.debug = True # Fallback to debug mode on GPIO error

    def cleanup_gpio(self):
        """Cleans up GPIO resources."""
        self.logger.info("Cleaning up FanControl GPIO resources.")
        # Ensure automatic control is stopped first
        if self._control_active:
            self.deactivate_control() # This also turns off the fan

        # Turn off fan just in case it was left on manually
        self.turn_off()

        if not self.debug:
            try:
                GPIO.cleanup(self.gpio_pin)
                self.logger.info(f"GPIO pin {self.gpio_pin} cleaned up.")
            except Exception as e:
                self.logger.error(f"Error during GPIO cleanup for pin {self.gpio_pin}: {e}")

    def turn_on(self):
        """Turns the fan ON (sets GPIO LOW)."""
        if self._is_running:
            return # Already on

        self.logger.info(f"Turning fan ON (GPIO {self.gpio_pin} -> LOW)")
        if not self.debug:
            try:
                GPIO.output(self.gpio_pin, GPIO.LOW)
            except Exception as e:
                self.logger.error(f"Error setting GPIO pin {self.gpio_pin} LOW: {e}")
                return # Avoid changing state if GPIO fails

        self._is_running = True
        # Cancel any existing turn-off timer if manually turned on
        if self._active_timer and self._active_timer.is_alive():
            self._active_timer.cancel()
            self._active_timer = None
            self.logger.debug("Cancelled existing turn-off timer due to manual turn_on.")


    def turn_off(self):
        """Turns the fan OFF (sets GPIO HIGH)."""
        if not self._is_running:
            return # Already off

        self.logger.info(f"Turning fan OFF (GPIO {self.gpio_pin} -> HIGH)")
        if not self.debug:
            try:
                GPIO.output(self.gpio_pin, GPIO.HIGH)
            except Exception as e:
                self.logger.error(f"Error setting GPIO pin {self.gpio_pin} HIGH: {e}")
                return # Avoid changing state if GPIO fails

        self._is_running = False
        # Cancel any existing turn-off timer if manually turned off
        if self._active_timer and self._active_timer.is_alive():
            self._active_timer.cancel()
            self._active_timer = None
            self.logger.debug("Cancelled existing turn-off timer due to manual turn_off.")

    def is_on(self) -> bool:
        """Returns True if the fan is currently running, False otherwise."""
        return self._is_running

    # --- Control Loop Management ---

    def set_target_humidity(self, target: float):
        """Sets the target humidity percentage."""
        try:
            target = float(target)
            if 40.0 <= target <= 90.0: # Example valid range
                 self._target_humidity = target
                 self.logger.info(f"Target humidity set to {self._target_humidity}%")
            else:
                 self.logger.warning(f"Invalid target humidity: {target}. Must be between 40 and 90.")
        except ValueError:
            self.logger.error(f"Invalid target humidity value provided: {target}")


    def get_target_humidity(self) -> float:
        """Returns the current target humidity."""
        return self._target_humidity

    def activate_control(self):
        """Activates the automatic humidity control loop."""
        if self._control_active:
            self.logger.info("Automatic fan control is already active.")
            return

        self.logger.info("Activating automatic fan control.")
        self._control_active = True
        # Note: The actual scheduling of _check_humidity_and_control
        # will happen in the main application loop, which passes the current humidity.
        # We just set the flag here and start the scheduler for potential future use
        # or if we adapt this class later.
        # For now, starting the scheduler isn't strictly necessary based on the plan
        # but we include the methods for consistency with hydro.py.
        self._start_scheduler() # Start scheduler thread if needed

    def deactivate_control(self):
        """Deactivates the automatic humidity control loop."""
        if not self._control_active:
            # self.logger.info("Automatic fan control is already inactive.") # Can be noisy
            return

        self.logger.info("Deactivating automatic fan control.")
        self._control_active = False
        # No schedule job to cancel here as the check is triggered externally

        # Stop the scheduler thread if it was started
        self._stop_scheduler()

        # Ensure the fan is turned off when deactivating auto control
        self.turn_off()

    def is_control_active(self) -> bool:
        """Returns True if automatic control is active, False otherwise."""
        return self._control_active

    def get_status(self) -> dict:
        """Returns the current status of the fan control."""
        return {
            'is_on': self._is_running,
            'target_humidity': self._target_humidity,
            'control_active': self._control_active
        }

    # --- Core Control Logic ---

    def _check_humidity_and_control(self):
        """
        Checks the average humidity from sensor readings and controls the fan accordingly.
        This method is intended to be called periodically by the main application loop.
        It calculates the average humidity from the latest reading of all sensors.
        """
        if not self._control_active:
            # self.logger.debug("Auto control inactive, skipping humidity check.") # Can be noisy
            return

        # --- Start Inserted Code Block ---
        active_humidities = []
        if hasattr(self.state, 'sensor_configs') and self.state.sensor_configs:
            active_sensor_ids = {sensor_id for sensor_id, config in self.state.sensor_configs.items() if config.get('active', False)}
            self.logger.debug(f"Active sensors for humidity check: {active_sensor_ids}")

            if not active_sensor_ids:
                self.logger.warning("Cannot perform humidity check: No sensors are marked as active in sensor_configs.")
                return # Cannot proceed without active sensors

            if hasattr(self.state, 'sensor_readings') and self.state.sensor_readings:
                for sensor_id in active_sensor_ids:
                    if sensor_id in self.state.sensor_readings and self.state.sensor_readings[sensor_id]:
                        last_reading = self.state.sensor_readings[sensor_id][-1]
                        if 'humidity' in last_reading:
                            try:
                                humidity_value = float(last_reading['humidity'])
                                active_humidities.append(humidity_value)
                                self.logger.debug(f"Sensor {sensor_id}: Found active humidity reading: {humidity_value}")
                            except (ValueError, TypeError):
                                self.logger.warning(f"Invalid humidity value '{last_reading['humidity']}' for active sensor {sensor_id}. Skipping.")
                        else:
                            self.logger.warning(f"No 'humidity' key in last reading for active sensor {sensor_id}. Skipping.")
                    else:
                        self.logger.warning(f"No readings found for active sensor {sensor_id}. Skipping.")
            else:
                self.logger.warning("Cannot perform humidity check: 'sensor_readings' not found in state or is empty.")
                return # Cannot proceed without sensor data

        else:
            self.logger.warning("Cannot perform humidity check: 'sensor_configs' not found in state or is empty.")
            return # Cannot proceed without sensor configurations

        if not active_humidities:
            self.logger.warning("Cannot perform humidity check: No valid humidity readings available from active sensors.")
            # If no active sensors have readings, should the fan be off? Assuming yes.
            if self._is_running:
                 self.logger.info("Turning fan OFF due to lack of valid humidity data from active sensors.")
                 self.turn_off()
            return # Cannot proceed without valid humidity data

        current_avg_humidity = sum(active_humidities) / len(active_humidities)
        # --- End Inserted Code Block ---

        try:
            # --- Start Inserted Code Block ---
            target_humidity_float = float(self._target_humidity)
            self.logger.debug(f"Humidity Check: Target={target_humidity_float}%, CurrentAvgActive={current_avg_humidity:.2f}%")

            # Control Strategy: Turn fan ON if average humidity of active sensors is ABOVE target.
            if current_avg_humidity > target_humidity_float:
                if not self._is_running:
                    self.logger.info(f"Humidity high ({current_avg_humidity:.2f}% > {target_humidity_float}%). Turning fan ON.")
                    self.turn_on()
                else:
                    # self.logger.debug(f"Humidity high ({current_avg_humidity:.2f}% > {target_humidity_float}%). Fan already ON.") # Can be noisy
                    pass # Fan is already running, leave it on
            # Else: Humidity is at or below target.
            else:
                if self._is_running:
                    self.logger.info(f"Humidity OK ({current_avg_humidity:.2f}% <= {target_humidity_float}%). Turning fan OFF.")
                    self.turn_off()
                else:
                    # self.logger.debug(f"Humidity OK ({current_avg_humidity:.2f}% <= {target_humidity_float}%). Fan already OFF.") # Can be noisy
                    pass # Fan is already off, leave it off

            # Ensure any previously running turn-off timers are cancelled, as we now use direct on/off logic.
            if self._active_timer and self._active_timer.is_alive():
                self.logger.debug("Cancelling legacy turn-off timer.")
                self._active_timer.cancel()
                self._active_timer = None
            # --- End Inserted Code Block ---

        except ValueError as ve:
             self.logger.error(f"Error converting humidity values during check: {ve}")
        except Exception as e:
            self.logger.error(f"Error during humidity check and control: {e}", exc_info=True)


    # --- Scheduler Thread Methods (for consistency, may not be used directly by plan) ---

    def _start_scheduler(self):
        """Starts the scheduler thread if not already running."""
        if not self._scheduler_thread or not self._scheduler_thread.is_alive():
            self._scheduler_running = True
            self._scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
            self._scheduler_thread.start()
            self.logger.debug("Started scheduler thread for FanControl.")

    def _run_scheduler(self):
        """Runs the scheduler loop."""
        self.logger.debug("FanControl scheduler thread running.")
        while self._scheduler_running:
            try:
                schedule.run_pending()
            except Exception as e:
                self.logger.error(f"Error in FanControl scheduler loop: {e}", exc_info=True)
            time.sleep(1)
        self.logger.debug("FanControl scheduler thread stopped.")

    def _stop_scheduler(self):
        """Stops the scheduler thread."""
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self.logger.debug("Stopping FanControl scheduler thread.")
            self._scheduler_running = False
            try:
                self._scheduler_thread.join(timeout=2)
                self.logger.debug("FanControl scheduler thread joined.")
            except Exception as e:
                self.logger.error(f"Error joining FanControl scheduler thread: {e}")
            self._scheduler_thread = None
        else:
            self.logger.debug("FanControl scheduler thread already stopped or not started.")
