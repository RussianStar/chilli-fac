class StaticLight:
    def __init__(self, pin: int = 23, debug: bool = False):
        """Initialize GPIO LED controller
        Args:
            pin (int): GPIO pin number (default 16) 
            debug (bool): Run in debug mode without GPIO (default False)
        """
        self._pin = pin
        self._is_on = False
        self._debug = debug
        
        if not debug:
            import RPi.GPIO as GPIO
            
            # Setup GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._pin, GPIO.OUT)
            GPIO.output(self._pin, GPIO.LOW) # Start with LED off

    def turn_on(self) -> None:
        """Turn LED on"""
        self._is_on = True
        print(f"Turning on light with gpio : {self._pin}")
        if not self._debug:
            import RPi.GPIO as GPIO
            GPIO.output(self._pin, GPIO.HIGH)
            
    def turn_off(self) -> None: 
        """Turn LED off"""
        self._is_on = False
        print(f"Turning off light with gpio : {self._pin}")
        if not self._debug:
            import RPi.GPIO as GPIO
            GPIO.output(self._pin, GPIO.LOW)

    def is_on(self) -> bool:
        """Get LED state
        Returns:
            bool: True if LED is on, False if off
        """
        return self._is_on

    def cleanup(self) -> None:
        """Cleanup GPIO resources"""
        if not self._debug:
            import RPi.GPIO as GPIO
            GPIO.cleanup(self._pin)
