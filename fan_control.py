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

    def __init__(self, logger, gpio_pin, debug=False):
        """
        Initialize the FanControl.

        Args:
            logger: Logger instance.
            gpio_pin: The BCM GPIO pin number the fan is connected to.
            debug (bool): If True, use mock GPIO and skip actual hardware interaction.
        """
        self.logger = logger
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

    def _check_humidity_and_control(self, current_avg_humidity: float):
        """
        Checks the average humidity and controls the fan accordingly.
        This method is intended to be called periodically by the main application loop.

        Args:
            current_avg_humidity (float): The current average humidity reading.
        """
        if not self._control_active:
            # self.logger.debug("Auto control inactive, skipping humidity check.") # Can be noisy
            return

        if current_avg_humidity is None:
            self.logger.warning("Cannot perform humidity check: current average humidity is None.")
            return

        try:
            error = self._target_humidity - float(current_avg_humidity)
            self.logger.debug(f"Humidity Check: Target={self._target_humidity}%, CurrentAvg={current_avg_humidity:.2f}%, Error={error:.2f}%")

            # Control Strategy: If humidity is more than 1% below target
            if error > 1.0:
                # Calculate run duration (proportional control)
                # For every 1% below target, run for 10 seconds. Max 30 seconds (5 mins).
                run_duration_seconds = min(int(error * 10), 30)
                self.logger.info(f"Humidity low (Error: {error:.2f}%). Running fan for {run_duration_seconds} seconds.")

                # Only start the fan and timer if it's not already running *under timer control*
                if not self._is_running or not (self._active_timer and self._active_timer.is_alive()):
                    # Cancel any existing timer just in case state is inconsistent
                    if self._active_timer and self._active_timer.is_alive():
                        self._active_timer.cancel()

                    self.turn_on() # Turn the fan on

                    # Schedule the fan to turn off after the calculated duration
                    self._active_timer = threading.Timer(run_duration_seconds, self.turn_off)
                    self._active_timer.daemon = True # Allow program to exit even if timer is pending
                    self._active_timer.start()
                    self.logger.debug(f"Scheduled fan turn_off in {run_duration_seconds} seconds.")
                else:
                    self.logger.debug("Fan is already running (possibly under timer control), check next cycle.")

            # Else: Humidity is within 1% of target or higher
            else:
                if self._is_running:
                    self.logger.info(f"Humidity sufficient (Error: {error:.2f}%). Turning fan off.")
                    # Cancel timer if it exists and turn off immediately
                    if self._active_timer and self._active_timer.is_alive():
                        self._active_timer.cancel()
                        self._active_timer = None
                    self.turn_off()
                else:
                    # self.logger.debug(f"Humidity sufficient (Error: {error:.2f}%). Fan already off.") # Can be noisy
                    pass

        except ValueError:
            self.logger.error(f"Invalid humidity value received: {current_avg_humidity}")
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
