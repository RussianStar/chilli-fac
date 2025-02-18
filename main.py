import RPi.GPIO as GPIO
import requests
from  flask  import Flask, render_template_string

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

# Camera endpoints
CAMERA_ENDPOINTS = [
    'http://192.168.178.155:8080',
    'http://192.168.178.157:8080',
    'http://192.168.178.152:8080',
    'http://192.168.178.158:8080'
]

# Initialize GPIO pins as outputs
for pin in GPIO_PINS.values():
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

# Updated HTML template with pin names and cameras
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

    <div style="display: flex; margin-top: 20px">
        <div style="margin-right: 20px">
            <img id="camera1" src="/camera/0" style="width: 320px; height: 240px"/>
            <button onclick="updateImage('camera1', 0)">Update Camera 1</button>
        </div>
        <div>
            <img id="camera2" src="/camera/1" style="width: 320px; height: 240px"/>
            <button onclick="updateImage('camera2', 1)">Update Camera 2</button>
        </div>
    </div>

    <script>
        function updateImage(imgId, cameraIndex) {
            const img = document.getElementById(imgId);
            img.src = '/camera/' + cameraIndex + '?t=' + new Date().getTime();
        }
    </script>
</body>
</html>
'''

# Track states
pin_states = {1: False, 2: False, 3: False, 4: False}

@app.route('/camera/<int:camera_id>')
def get_camera_image(camera_id):
    if camera_id < len(CAMERA_ENDPOINTS):
        try:
            # Get response from camera endpoint
            response = requests.get(CAMERA_ENDPOINTS[camera_id])
            
            # Parse HTML content
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find first image in body
            img = soup.body.find('img')
            if img and img.get('src'):
                # Get image data from src attribute
                img_response = requests.get(img['src'])
                return img_response.content
            
            return "No image found in response", 500
            
        except Exception as e:
            return f"Error loading camera image: {str(e)}", 500
            
    return "Camera not found", 404

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
