from gpio_device import gpio_device
import schedule
import time
import threading

class Hydro(gpio_device):

    DEFAULT_SCHEDULE = [
            {f"valve{i}": (i, False) for i in range(1, 3 + 1)},
            {"valve3": (3, True)},
            {"pump": (1, True)},
            180,
            {"valve3": (3, False)},
            {"valve2": (2, True)},
            180,
            {"valve2": (2, False)},
            {"valve1": (1, True)},
            180,
            {"pump": (1, False)},
            {"valve1": (1, False)},
        ]

    def __init__(self,logger, gpio_config, debug = False):
        self.gpio_config = gpio_config
        self.debug = debug
        self.logger = logger,
        self.num_valves = len(gpio_config["valve_pins"])
        self._auto_mode = False
        self._start_time = None
        self._turn_on_job = None
        self._scheduler_thread = None
        self._scheduler_running = False
        logger.info("Logger is initialized")
        
        if not debug:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            
            # Setup pump pin
            GPIO.setup(gpio_config["pump_pin"], GPIO.OUT)
            GPIO.output(gpio_config["pump_pin"], GPIO.HIGH)
            
            # Setup valve pins
            for pin in gpio_config["valve_pins"].values():
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.HIGH)

    def close_all_valves(self):
        for valve in range(1, self.num_valves + 1):
            self.set_valve(valve,False)
        self.set_pump(False)

    def set_valve(self, valve_num: int, state: bool):
        """Set valve state (on/off)"""
        if valve_num not in range(1, self.num_valves + 1):
            raise ValueError(f"Invalid valve number[{valve_num}]. Must be 1-{self.num_valves}")
            
        self.logger[0].info(f"Setting valve {valve_num} to {state}")
        if self.debug:
            return state

        pin = self.gpio_config["valve_pins"][str(valve_num)]
        import RPi.GPIO as GPIO
        GPIO.output(pin, GPIO.LOW if state else GPIO.HIGH)
        return state
        
    def set_pump(self, state: bool):
        """Set pump state (on/off)"""

        self.logger[0].info(f"Setting pump to {state}")
        if self.debug:
            return state
            
        import RPi.GPIO as GPIO  
        GPIO.output(self.gpio_config["pump_pin"], GPIO.LOW if state else GPIO.HIGH)
        return state

    def cleanup_gpio(self):
        """Cleanup GPIO on exit"""
        self.disable_auto_mode()  # Stop scheduler if running
        if not self.debug:
            import RPi.GPIO as GPIO
            GPIO.cleanup()
            
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
            "start_time": self._start_time
        }
        
    def set_auto_mode(self, start_time: str):
        """Set auto mode with start time
        
        Args:
            start_time (str): Time to execute watering in 24-hour format (HH:MM)
        """
        # Clear any existing schedules
        self.disable_auto_mode()
        
        # Set new auto mode parameters
        self._auto_mode = True
        self._start_time = start_time
        
        # Schedule the turn on job
        self._turn_on_job = schedule.every().day.at(start_time).do(self.auto_execute_watering)
        self.logger[0].info(f"Auto mode enabled for watering. Start: {start_time}")
        
        # Start the scheduler thread if not already running
        self._start_scheduler()

    def disable_auto_mode(self):
        """Disable auto mode and clear all schedules"""
        if self._auto_mode:
            self._auto_mode = False
            
            # Clear scheduled jobs
            if self._turn_on_job:
                schedule.cancel_job(self._turn_on_job)
                self._turn_on_job = None
                
            self.logger[0].info(f"Auto mode disabled for watering")
            
            # Stop scheduler thread if no other devices are using it
            if self._scheduler_thread and self._scheduler_thread.is_alive():
                self._scheduler_running = False
                self._scheduler_thread.join(timeout=2)
                self._scheduler_thread = None
                
    def auto_execute_watering(self):
        """Execute watering automatically based on schedule"""
        if self._auto_mode:
            self.logger[0].info(f"Auto executing watering at {self._start_time}")
            
            # Execute the default watering schedule
            # This is a simplified version - in a real implementation, 
            # you would need to handle this asynchronously
            try:
                # Close all valves first
                self.close_all_valves()
                
                # Execute each step in the schedule
                for step in self.DEFAULT_SCHEDULE:
                    if isinstance(step, dict):
                        # This is a control step (valve/pump operation)
                        for device, (id, state) in step.items():
                            if 'valve' in device:
                                self.set_valve(id, state)
                            elif device == 'pump':
                                self.set_pump(state)
                    else:
                        # This is a wait step
                        time.sleep(step)
                
                # Make sure all valves are closed at the end
                self.close_all_valves()
                self.logger[0].info("Auto watering completed successfully")
            except Exception as e:
                self.logger[0].error(f"Error during auto watering: {str(e)}")
                # Make sure all valves are closed in case of error
                self.close_all_valves()
            
            return schedule.CancelJob  # Don't repeat this specific job instance
            
    def _start_scheduler(self):
        """Start the scheduler thread if not already running"""
        if not self._scheduler_thread or not self._scheduler_thread.is_alive():
            self._scheduler_running = True
            self._scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
            self._scheduler_thread.start()
            self.logger[0].debug(f"Started scheduler thread for watering")

    def _run_scheduler(self):
        """Run the scheduler in a separate thread"""
        while self._scheduler_running:
            schedule.run_pending()
            time.sleep(1)
        self.logger[0].debug(f"Scheduler thread stopped for watering")
        
    def create_custom_schedule(self, durations):
        """Create a custom watering schedule based on provided durations
        
        Args:
            durations: Dictionary mapping valve IDs to durations in seconds
            
        Returns:
            List representing the watering schedule
        """
        # Start with closing all valves
        schedule = [{f"valve{i}": (i, False) for i in range(1, self.num_valves + 1)}]
        
        # For each valve, add the steps to open it, wait, and close it
        for valve_id in sorted(durations.keys()):
            duration = durations[valve_id]
            
            # Skip valves with zero duration
            if duration <= 0:
                continue
                
            # If this is the first valve, turn on the pump
            if len(schedule) == 1:
                schedule.append({"pump": (1, True)})
                
            # Open the valve
            schedule.append({f"valve{valve_id}": (valve_id, True)})
            
            # Wait for the specified duration
            schedule.append(duration)
            
            # Close the valve
            schedule.append({f"valve{valve_id}": (valve_id, False)})
        
        # Turn off the pump at the end if any valves were watered
        if len(schedule) > 1:
            schedule.append({"pump": (1, False)})
            
        return schedule
