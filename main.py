import requests
import json
from  flask  import Flask, render_template
from hydro import Hydro

# Initialize Flask app
app = Flask(__name__)

with open('config.json') as f:
    config = json.load(f)

wtrctrl = Hydro(config['gpio_pins'],True)
PIN_NAMES = config['pin_names']
GPIO_PINS = {int(k): v for k,v in config['gpio_pins'].items()} 
LIGHT_PINS = {1:12, 2:23} 
PUMP_PINS = {1:26} 
CAMERA_ENDPOINTS = config['camera_endpoints']

# Add new route for taking pictures
@app.route('/camera/<int:camera_id>/take/picture', methods=['POST'])
def take_picture(camera_id):
    if camera_id < len(CAMERA_ENDPOINTS):
        try:
            # POST to camera endpoint
            response = requests.get(f"{CAMERA_ENDPOINTS[camera_id]}/take/picture")
            
            if response.status_code == 200:
                return "Picture taken successfully", 200
            else:
                return "Failed to take picture", 500
            
        except Exception as e:
            return f"Error taking picture: {str(e)}", 500
            
 
@app.route('/')
def home():
    return render_template("index.html", 
                                 valves=valve_states,
                                 lights=light_states,
                                 pumps=pump_states,
                                pin_names=PIN_NAMES,
                                camera_count=len(CAMERA_ENDPOINTS))

pump_states = {1: False}
light_states = {1: False, 2: False }
valve_states = {1: False, 2: False , 3: False }

# Endpoint for toggling pump
@app.route('/pump/toggle')
def toggle_pump():
    pump_states[1] = not pump_states[1]
    wtrctrl.set_pump(pump_states[1])
    return render_template("index.html",
                         valves=valve_states,
                         lights=light_states,
                         pumps=pump_states,
                         pin_names=PIN_NAMES,
                         camera_count=len(CAMERA_ENDPOINTS))

# Endpoint for toggling valves
@app.route('/valve/<int:valve_id>/toggle')
def toggle_valve(valve_id):
    if valve_id in GPIO_PINS:
        valve_states[valve_id] = not valve_states[valve_id]
        wtrctrl.set_valve(valve_id, valve_states[valve_id])
    return render_template("index.html",
                         valves=valve_states,
                         lights=light_states,
                         pumps=pump_states,
                         pin_names=PIN_NAMES,
                         camera_count=len(CAMERA_ENDPOINTS))

# Endpoint for toggling lights
@app.route('/light/<int:light_id>/toggle')
def toggle_light(light_id):

    light_states[light_id] = not light_states[light_id]
    print(f"Setting light #{light_id} to {light_states[light_id]}")
    return render_template("index.html",
                         valves=valve_states,
                         lights=light_states,
                         pumps=pump_states,
                         pin_names=PIN_NAMES,
                         camera_count=len(CAMERA_ENDPOINTS))
# Track states

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


def main():
    try:
        app.run(host='0.0.0.0', port=5000)
    finally:
        wtrctrl.cleanup()

if __name__ == "__main__":
    main()
