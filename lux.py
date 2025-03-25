from gpio_device import gpio_device
import schedule
import time
import threading
from datetime import datetime, timedelta

class Lux(gpio_device):
    def __init__(self, logger, pin: int = 16, freq: int = 1000, debug: bool = False, scheduler=None):
        """Initialize PWM LED controller
        Args:
            logger: Logger instance
            pin (int): GPIO pin number (default 16)
            freq (int): PWM frequency in Hz (default 1000Hz)
            debug (bool): Run in debug mode without GPIO (default False)
            scheduler: Optional scheduler instance (for testing)
        """
        self._pin = pin
        self._freq = freq
        self._pwm = None
        self._current_level = 0
        self._debug = debug
        self._logger = logger
        
        # Auto mode attributes
        self._auto_mode = False
        self._start_time = None
        self._duration_hours = 0
        self._auto_brightness = 100
        self._turn_off_job = None
        self._turn_on_job = None
        self._scheduler_thread = None
        self._scheduler_running = False
        self._scheduler = scheduler if scheduler is not None else schedule
        
        self._logger.info(f'led controller on {self._pin} with frequency of {self._freq}Hz')
        if not debug:
            import RPi.GPIO as GPIO
            
            # Setup GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._pin, GPIO.OUT)
            
            # Initialize PWM
            self._pwm = GPIO.PWM(self._pin, self._freq)
            self._pwm.start(0) # Start with LED off

    def set_level(self, level: float) -> None:
        """Set LED brightness level
        Args:
            level (float): Brightness level 0-100
        """
        # Validate and clamp input 
        self._current_level = max(0, min(100, level))
        print(f"Setting current level to : {self._current_level}")
        if not self._debug:
            self._pwm.ChangeDutyCycle(self._current_level)
            
    def get_level(self) -> float:
        """Get current brightness level
        Returns:
            float: Current brightness level 0-100
        """
        return self._current_level

    def turn_off(self) -> None:
        """Turn LED completely off"""
        self.set_level(0)
        
    def turn_on(self, brightness: float = 100) -> None:
        """Turn LED on with specified brightness
        
        Args:
            brightness (float): Brightness level 0-100 (default 100)
        """
        self.set_level(brightness)
        
    def is_on(self) -> bool:
        """Check if LED is on
        
        Returns:
            bool: True if LED is on (brightness > 0), False otherwise
        """
        return self._current_level > 0
        
    def is_auto_mode(self) -> bool:
        """Get auto mode state
        
        Returns:
            bool: True if auto mode is enabled, False if disabled
        """
        return self._auto_mode
        
    def get_auto_settings(self) -> dict:
        """Get auto mode settings
        
        Returns:
            dict: Dictionary with auto mode settings
        """
        return {
            "auto_mode": self._auto_mode,
            "start_time": self._start_time,
            "duration_hours": self._duration_hours,
            "brightness": self._auto_brightness
        }
        
    def cleanup_gpio(self) -> None:
        """Cleanup GPIO resources"""
        self.disable_auto_mode()  # Stop scheduler if running
        if not self._debug:
            if self._pwm:
                self._pwm.stop()
            import RPi.GPIO as GPIO
            GPIO.cleanup(self._pin)
            
    def set_auto_mode(self, start_time: str, duration_hours: int, brightness: float = 100):
        """Set auto mode with start time, duration, and brightness
        
        Args:
            start_time (str): Time to turn on the light in 24-hour format (HH:MM)
            duration_hours (int): Duration in hours to keep the light on
            brightness (float): Brightness level 0-100 (default 100)
        """
        # Clear any existing schedules
        self.disable_auto_mode()
        
        # Set new auto mode parameters
        self._auto_mode = True
        self._start_time = start_time
        self._duration_hours = duration_hours
        self._auto_brightness = max(0, min(100, brightness))
        
        # Schedule the turn on job
        self._turn_on_job = self._scheduler.every().day.at(start_time).do(self.auto_turn_on)
        self._logger.info(f"Auto mode enabled for light {self._pin}. Start: {start_time}, Duration: {duration_hours}h, Brightness: {brightness}%")
        
        # Start the scheduler thread if not already running
        self._start_scheduler()
        
        # Check if we should turn on immediately (if current time is between start time and end time)
        self._check_if_should_be_on()

    def disable_auto_mode(self):
        """Disable auto mode and clear all schedules"""
        if self._auto_mode:
            self._auto_mode = False
            
            # Clear scheduled jobs
            if self._turn_on_job:
                self._scheduler.cancel_job(self._turn_on_job)
                self._turn_on_job = None
                
            if self._turn_off_job:
                self._scheduler.cancel_job(self._turn_off_job)
                self._turn_off_job = None
                
            self._logger.info(f"Auto mode disabled for light {self._pin}")
            
            # Stop scheduler thread if no other lights are using it
            if self._scheduler_thread and self._scheduler_thread.is_alive():
                self._scheduler_running = False
                self._scheduler_thread.join(timeout=2)
                self._scheduler_thread = None

    def auto_turn_on(self, current_time=None):
        """Turn on light automatically based on schedule with specified brightness
        
        Args:
            current_time: Optional datetime to use instead of datetime.now() (for testing)
        """
        if self._auto_mode:
            self.turn_on(self._auto_brightness)
            
            # Clear any existing turn-off job
            if self._turn_off_job:
                schedule.cancel_job(self._turn_off_job)
            
            # Schedule turn off after duration
            now = current_time if current_time is not None else datetime.now()
            turn_off_time = now + timedelta(hours=self._duration_hours)
            self._turn_off_job = self._scheduler.every().day.at(turn_off_time.strftime("%H:%M")).do(self.auto_turn_off)
            
            log_time = self._start_time if current_time is None else current_time.strftime("%H:%M")
            self._logger.info(f"Auto turning on light at {log_time} for {self._duration_hours} hours with brightness {self._auto_brightness}%")

    def auto_turn_off(self):
        """Turn off light automatically after duration"""
        if self._auto_mode:
            self.turn_off()
            self._logger.info(f"Auto turning off light after {self._duration_hours} hours")
            self._turn_off_job = None

    def _start_scheduler(self):
        """Start the scheduler thread if not already running"""
        if not self._scheduler_thread or not self._scheduler_thread.is_alive():
            self._scheduler_running = True
            self._scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
            self._scheduler_thread.start()
            self._logger.info(f"Started scheduler thread for light {self._pin}")

    def _run_scheduler(self):
        """Run the scheduler in a separate thread"""
        while self._scheduler_running:
            schedule.run_pending()
            time.sleep(1)
        self._logger.info(f"Scheduler thread stopped for light {self._pin}")
        
    def _check_if_should_be_on(self):
        """Check if the light should be on based on current time and auto settings"""
        if not self._auto_mode or not self._start_time:
            return
            
        try:
            # Parse start time
            current_time = datetime.now()
            start_hour, start_minute = map(int, self._start_time.split(':'))
            start_time = current_time.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
            
            # Calculate end time
            end_time = start_time + timedelta(hours=self._duration_hours)
            
            # Handle case where end time is on the next day
            if end_time < start_time:
                # If current time is after start time or before end time, light should be on
                if current_time >= start_time or current_time <= end_time:
                    self.turn_on(self._auto_brightness)
                    # Schedule turn off
                    if current_time <= end_time:
                        seconds_until_off = (end_time - current_time).total_seconds()
                        self._turn_off_job = self._scheduler.every(seconds_until_off).seconds.do(self.auto_turn_off)
            else:
                # If current time is between start and end time, light should be on
                if start_time <= current_time <= end_time:
                    self.turn_on(self._auto_brightness)
                    # Schedule turn off
                    seconds_until_off = (end_time - current_time).total_seconds()
                    self._turn_off_job = self._scheduler.every(seconds_until_off).seconds.do(self.auto_turn_off)
        except Exception as e:
            self._logger.error(f"Error checking if light should be on: {str(e)}")
