import pigpio
import time

pi = pigpio.pi()

# Set pin 6 as output
PIN = 6
FREQ = 1000 # 1000Hz frequency

try:
    while True:
        # Increase duty cycle from 0 to 100%
        for duty in range(0, 255, 3): # pigpio uses range 0-255
            pi.set_PWM_frequency(PIN, FREQ)
            pi.set_PWM_dutycycle(PIN, duty)
            print(f"Duty cycle: {int(duty/255*100)}%")
            time.sleep(0.1)
            
        # Decrease duty cycle from 100% to 0
        for duty in range(255, -1, -3):
            pi.set_PWM_frequency(PIN, FREQ) 
            pi.set_PWM_dutycycle(PIN, duty)
            print(f"Duty cycle: {int(duty/255*100)}%")
            time.sleep(0.1)
            
except KeyboardInterrupt:
    print("\nProgram stopped by user")
    pi.set_PWM_dutycycle(PIN, 0) # Turn off PWM
    pi.stop() # Release resources
except:
    print("\nOther error occurred")
    pi.set_PWM_dutycycle(PIN, 0)
    pi.stop()
