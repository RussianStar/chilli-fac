import requests
import json
from  flask  import Flask, render_template, request
from hydro import Hydro
from lux import Lux
from static_light import StaticLight

def is_raspberry_pi():
    try:
        with open('/proc/device-tree/model') as f:
            return 'raspberry' in f.read().lower()
    except:
        return False

# Initialize Flask app
app = Flask(__name__)
debug = not is_raspberry_pi();

with open('config.json') as f:
    config = json.load(f)

wtrctrl = Hydro(config,debug)
# set the debug parameter on whether this code is run on an raspberry pi or not
zeus = {int(k):Lux(v, debug=debug) for k,v in config['light_pins'].items()}
static_lights = {int(k):StaticLight(v, debug=debug) for k,v in config['static_light_pins'].items()}

pump_states = { 1:False}
light_states = {int(k): False for k,_ in config['light_pins'].items()}
static_light_states = {int(k): False for k,_ in config['static_light_pins'].items()}
valve_states ={int(k): False for k,_ in config['valve_pins'].items()}  

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
                                 static_lights=static_light_states, 
                                camera_count=len(CAMERA_ENDPOINTS))


@app.route('/level/<int:level>/water', methods=['POST'])
def water_level(level):
    # Get duration from request, default to 300 seconds (5 minutes)
    duration = request.form.get('duration', type=int, default=300)
    
    try:
        # Start watering the level using hydro controller
        wtrctrl.water_level(level, duration)
        
        return render_template("index.html",
                         valves=valve_states,
                         lights=light_states,
                         static_lights=static_light_states, 
                         pumps=pump_states,
                         camera_count=len(CAMERA_ENDPOINTS))
                         
    except ValueError as e:
        return str(e), 400
    except Exception as e:
        return f"Error watering level: {str(e)}", 500

@app.route('/static_light/<int:light_id>/toggle', methods=['POST'])
def toggle_static_light(light_id):
    # Get corresponding static light controller
    if light_id <= len(static_lights):
        light_controller = static_lights[light_id]
        
        if light_controller.is_on():
            light_controller.turn_off()
            static_light_states[light_id] = False
        else:
            light_controller.turn_on()
            static_light_states[light_id] = True

        print(f"Toggling static light #{light_id} to {static_light_states[light_id]}")
    
    return render_template("index.html",
                         valves=valve_states,
                         lights=light_states,
                         static_lights=static_light_states,
                         pumps=pump_states,
                         camera_count=len(CAMERA_ENDPOINTS))

@app.route('/light/<int:light_id>/brightness', methods=['POST'])
def set_light_brightness(light_id):
    # Get brightness value from request (0-100)
    brightness = request.form.get('brightness', type=int, default=0)
    
    # Validate brightness is between 0-100
    brightness = max(0, min(100, brightness))

    # Get corresponding LED controller
    if light_id <= len(zeus):
        led_controller = zeus[light_id]

        # Update light state based on brightness 
        light_states[light_id] = brightness
        
        # Set brightness level (0-100%)
        led_controller.set_level(brightness)

        print(f"Setting light #{light_id} brightness to {brightness}%")
    
    return render_template("index.html",
                         valves=valve_states,
                         lights=light_states, 
                         static_lights=static_light_states, 
                         pumps=pump_states,
                         camera_count=len(CAMERA_ENDPOINTS))

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
