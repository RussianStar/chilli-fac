from gpio_device import gpio_device

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
        import RPi.GPIO as GPIO
        GPIO.cleanup()
