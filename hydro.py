class Hydro:
    def __init__(self, gpio_config, debug = False):
        self.gpio_config = gpio_config
        self.debug = debug
        self.num_valves = len(gpio_config["valve_pins"])
        
        if not debug:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            
            # Setup pump pin
            GPIO.setup(gpio_config["pump_pin"], GPIO.OUT)
            GPIO.output(gpio_config["pump_pin"], GPIO.LOW)
            
            # Setup valve pins
            for pin in gpio_config["valve_pins"].values():
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)

    def water_level(self, level: int, duration: int = 300):
        """
        Water a specific level for given duration
        Args:
            level: Level number (1-num_valves) to water
            duration: Watering duration in seconds (default 5min = 300s)
        """
        # Validate level
        if level not in range(1, self.num_valves + 1):
            raise ValueError(f"Invalid level number. Must be 1-{self.num_valves}")

        try:
            # Close all valves first
            for valve in range(1, self.num_valves + 1):
                self.set_valve(valve, False)
                
            # Open valve for specified level
            self.set_valve(level, True)
            
            # Start pump
            self.set_pump(True)
            
            # Wait for duration
            from time import sleep
            sleep(duration)
            
        finally:
            # Cleanup - close valve and stop pump
            self.set_valve(level, False)
            self.set_pump(False)
            
    def set_valve(self, valve_num: int, state: bool):
        """Set valve state (on/off)"""
        if valve_num not in range(1, self.num_valves + 1):
            raise ValueError(f"Invalid valve number. Must be 1-{self.num_valves}")
            
        if self.debug:
            print(f"Setting valve {valve_num} to {state}")
            return

        pin = self.gpio_config["valve_pins"][str(valve_num)]
        import RPi.GPIO as GPIO
        GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)
        
    def set_pump(self, state: bool):
        """Set pump state (on/off)"""
        if self.debug:
            print(f"Setting pump to {state}")
            return
            
        import RPi.GPIO as GPIO  
        GPIO.output(self.gpio_config["pump_pin"], GPIO.HIGH if state else GPIO.LOW)

    def cleanup(self):
        """Cleanup GPIO on exit"""
        import RPi.GPIO as GPIO
        GPIO.cleanup()
