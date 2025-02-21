
class Hydro:
    def __init__(self, gpio_config, debug = False):
        self.gpio_config = gpio_config
        self.debug = debug
        
        if not debug:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            
            for pin in self.gpio_config.values():
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW) 
            pass
    
    def set_valve(self, valve_num: int, state: bool):
        """Set valve state (on/off)"""
        if valve_num not in [1,2,3]:
            raise ValueError("Invalid valve number")
            
        if self.debug:
            print(f"Setting valve {valve_num} to {state}")
            return

        pin = self.gpio_config[str(valve_num)]
        import RPi.GPIO as GPIO
        GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)
        
    def set_pump(self, state: bool):
        """Set pump state (on/off)"""
        if self.debug:
            print(f"Setting pump to {state}")
            return
        pump_pin = self.gpio_config["4"]  # Pump is on pin 4
        import RPi.GPIO as GPIO  
        GPIO.output(pump_pin, GPIO.HIGH if state else GPIO.LOW)

    def cleanup(self):
        """Cleanup GPIO on exit"""
        import RPi.GPIO as GPIO
        GPIO.cleanup()
