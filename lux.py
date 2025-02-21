
class Lux:
    def __init__(self, pin: int = 16, freq: int = 1000, debug: bool = False):
        """Initialize PWM LED controller
        Args:
            pin (int): GPIO pin number (default 16)
            freq (int): PWM frequency in Hz (default 1000Hz)
            debug (bool): Run in debug mode without GPIO (default False)
        """
        self._pin = pin
        self._freq = freq
        self._pwm = None
        self._current_level = 0
        self._debug = debug
        
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
        
    def turn_on(self) -> None:
        """Turn LED to full brightness"""
        self.set_level(100)
        
    def cleanup(self) -> None:
        """Cleanup GPIO resources"""
        if not self._debug:
            if self._pwm:
                self._pwm.stop()
            import RPi.GPIO as GPIO
            GPIO.cleanup(self._pin)
