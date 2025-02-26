from gpio_device import gpio_device
import schedule
import time
import threading
from datetime import datetime, timedelta

class StaticLight(gpio_device):
    def __init__(self, logger, pin: int = 23, debug: bool = False):
        """Initialize GPIO LED controller
        Args:
            pin (int): GPIO pin number (default 16) 
            debug (bool): Run in debug mode without GPIO (default False)
        """
        self._pin = pin
        self._is_on = False
        self._debug = debug
        self._logger = logger
        self._auto_mode = False
        self._start_time = None
        self._duration_hours = 0
        self._turn_off_job = None
        self._turn_on_job = None
        self._scheduler_thread = None
        self._scheduler_running = False
        
        if not debug:
            import RPi.GPIO as GPIO
            
            # Setup GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._pin, GPIO.OUT)
            GPIO.output(self._pin, GPIO.HIGH) # Start with LED off

    def turn_on(self) -> None:
        """Turn LED on"""
        self._is_on = True
        self._logger.debug(f"Turning on light with gpio : {self._pin}")
        if not self._debug:
            import RPi.GPIO as GPIO
            GPIO.output(self._pin, GPIO.LOW)
            
    def turn_off(self) -> None: 
        """Turn LED off"""
        self._is_on = False
        self._logger.debug(f"Turning off light with gpio : {self._pin}")
        if not self._debug:
            import RPi.GPIO as GPIO
            GPIO.output(self._pin, GPIO.HIGH)

    def is_on(self) -> bool:
        """Get LED state
        Returns:
            bool: True if LED is on, False if off
        """
        return self._is_on
        
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
            "duration_hours": self._duration_hours
        }

    def cleanup_gpio(self) -> None:
        """Cleanup GPIO resources"""
        self.disable_auto_mode()  # Stop scheduler if running
        if not self._debug:
            import RPi.GPIO as GPIO
            GPIO.cleanup(self._pin)

    def set_auto_mode(self, start_time: str, duration_hours: int):
        """Set auto mode with start time and duration in hours
        
        Args:
            start_time (str): Time to turn on the light in 24-hour format (HH:MM)
            duration_hours (int): Duration in hours to keep the light on
        """
        # Clear any existing schedules
        self.disable_auto_mode()
        
        # Set new auto mode parameters
        self._auto_mode = True
        self._start_time = start_time
        self._duration_hours = duration_hours
        
        # Schedule the turn on job
        self._turn_on_job = schedule.every().day.at(start_time).do(self.auto_turn_on)
        self._logger.info(f"Auto mode enabled for light {self._pin}. Start: {start_time}, Duration: {duration_hours}h")
        
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
                schedule.cancel_job(self._turn_on_job)
                self._turn_on_job = None
                
            if self._turn_off_job:
                schedule.cancel_job(self._turn_off_job)
                self._turn_off_job = None
                
            self._logger.info(f"Auto mode disabled for light {self._pin}")
            
            # Stop scheduler thread if no other lights are using it
            if self._scheduler_thread and self._scheduler_thread.is_alive():
                self._scheduler_running = False
                self._scheduler_thread.join(timeout=2)
                self._scheduler_thread = None

    def auto_turn_on(self):
        """Turn on light automatically based on schedule"""
        if self._auto_mode:
            self.turn_on()
            
            # Clear any existing turn-off job
            if self._turn_off_job:
                schedule.cancel_job(self._turn_off_job)
            
            # Schedule turn off after duration
            turn_off_time = datetime.now() + timedelta(hours=self._duration_hours)
            self._turn_off_job = schedule.every().day.at(turn_off_time.strftime("%H:%M")).do(self.auto_turn_off)
            
            self._logger.debug(f"Auto turning on light at {self._start_time} for {self._duration_hours} hours")
            return schedule.CancelJob  # Don't repeat this specific job instance

    def auto_turn_off(self):
        """Turn off light automatically after duration"""
        if self._auto_mode:
            self.turn_off()
            self._logger.debug(f"Auto turning off light after {self._duration_hours} hours")
            self._turn_off_job = None
            return schedule.CancelJob  # Don't repeat this specific job instance

    def _start_scheduler(self):
        """Start the scheduler thread if not already running"""
        if not self._scheduler_thread or not self._scheduler_thread.is_alive():
            self._scheduler_running = True
            self._scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
            self._scheduler_thread.start()
            self._logger.debug(f"Started scheduler thread for light {self._pin}")

    def _run_scheduler(self):
        """Run the scheduler in a separate thread"""
        while self._scheduler_running:
            schedule.run_pending()
            time.sleep(1)
        self._logger.debug(f"Scheduler thread stopped for light {self._pin}")
        
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
                    self.turn_on()
                    # Schedule turn off
                    if current_time <= end_time:
                        seconds_until_off = (end_time - current_time).total_seconds()
                        self._turn_off_job = schedule.every(seconds_until_off).seconds.do(self.auto_turn_off)
            else:
                # If current time is between start and end time, light should be on
                if start_time <= current_time <= end_time:
                    self.turn_on()
                    # Schedule turn off
                    seconds_until_off = (end_time - current_time).total_seconds()
                    self._turn_off_job = schedule.every(seconds_until_off).seconds.do(self.auto_turn_off)
        except Exception as e:
            self._logger.error(f"Error checking if light should be on: {str(e)}")
