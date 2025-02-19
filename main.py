import RPi.GPIO as GPIO
import requests
import json
from  flask  import Flask, render_template

# Initialize Flask app
app = Flask(__name__)

with open('config.json') as f:
    config = json.load(f)

PIN_NAMES = config['pin_names']
GPIO_PINS = {int(k): v for k,v in config['gpio_pins'].items()} 
CAMERA_ENDPOINTS = config['camera_endpoints']

# Setup GPIO
GPIO.setmode(GPIO.BCM)

# Initialize GPIO pins as outputs
for pin in GPIO_PINS.values():
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)


# Add new route for taking pictures
@app.route('/camera/<int:camera_id>/take/picture', methods=['POST'])
def take_picture(camera_id):
    if camera_id < len(CAMERA_ENDPOINTS):
        try:
            # POST to camera endpoint
            response = requests.post(f"{CAMERA_ENDPOINTS[camera_id]}/take/picture")
            
            if response.status_code == 200:
                return "Picture taken successfully", 200
            else:
                return "Failed to take picture", 500
            
        except Exception as e:
            return f"Error taking picture: {str(e)}", 500
            
 
@app.route('/')
def home():
    return render_template("index.html", 
                                pins=GPIO_PINS, 
                                states=pin_states, 
                                pin_names=PIN_NAMES,
                                camera_count=len(CAMERA_ENDPOINTS))


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
                # Get base64 data directly from src attribute
                img_data = img['src']
                
                # Check if it's a base64 encoded image
                if img_data.startswith('data:image/jpeg;base64,'):
                    # Extract just the base64 content
                    base64_data = img_data.split(',')[1]
                    
                    # Decode base64 to bytes
                    import base64
                    image_bytes = base64.b64decode(base64_data)
                    
                    return image_bytes

            return "No image found in response", 500
            
        except Exception as e:
            return f"Error loading camera image: {str(e)}", 500
            
    return "Camera not found", 404

@app.route('/toggle/<int:id>')
def toggle(id):
    if id in GPIO_PINS:
        pin_states[id] = not pin_states[id]
        GPIO.output(GPIO_PINS[id], pin_states[id])
    return render_template("index.html", 
                                pins=GPIO_PINS, 
                                states=pin_states, 
                                pin_names=PIN_NAMES,
                                camera_count=len(CAMERA_ENDPOINTS))

def main():
    try:
        app.run(host='0.0.0.0', port=5000)
    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    main()
