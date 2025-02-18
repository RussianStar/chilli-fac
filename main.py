from flask import Flask, render_template_string
import RPi.GPIO as GPIO

# Initialize Flask app
app = Flask(__name__)

PIN_NAMES=  {
    1: "Pumpe",
    2: "Ventil unten",
    3: "Ventil mitte", 
    4: "Ventil oben"
}

# Setup GPIO
GPIO.setmode(GPIO.BCM)
GPIO_PINS = {
    1: 26,
    2: 20,
    3: 19, 
    4: 12
}

# Initialize GPIO pins as outputs
for pin in GPIO_PINS.values():
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

# Updated HTML template with pin names
HTML = '''
<!DOCTYPE html>
<html>
<body>
    {% for id, pin in pins.items() %}
    <div style="margin: 10px">
        <span>{{ pin_names[id] }}</span>
        <button onclick="window.location.href='/toggle/{{ id }}'">
            Toggle
        </button>
        <span>State: {{ "ON" if states[id] else "OFF" }}</span>
    </div>
    {% endfor %}
</body>
</html>
'''

# Track states
pin_states = {1: False, 2: False, 3: False, 4: False}

@app.route('/')
def home():
    return render_template_string(HTML, pins=GPIO_PINS, states=pin_states, pin_names=PIN_NAMES)

@app.route('/toggle/<int:id>') 
def toggle(id):
    if id in GPIO_PINS:
        pin_states[id] = not pin_states[id]
        GPIO.output(GPIO_PINS[id], pin_states[id])
    return render_template_string(HTML, pins=GPIO_PINS, states=pin_states, pin_names=PIN_NAMES)

def main():
    try:
        app.run(host='0.0.0.0', port=5000)
    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    main()
