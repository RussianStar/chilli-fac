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
# Make sure all cameras are shown. I want them in rows with 2 cameras in each row. Do this for all camera endpoints. Also make the update button smaller and below the image
CAMERA_ENDPOINTS = [
    'http://192.168.178.155:8080',
    'http://192.168.178.157:8080',
    'http://192.168.178.152:8080',
    'http://192.168.178.158:8080',
    'http://192.168.178.197:8080',
    'http://192.168.178.198:8080'
]

# Initialize GPIO pins as outputs
for pin in GPIO_PINS.values():
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <style>
        .camera-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
            margin-top: 20px;
        }
        .camera-container {
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .update-btn, .take-picture-btn {
            margin-top: 10px;
            padding: 5px 10px;
            font-size: 12px;
        }
        .controls {
            margin: 10px;
        }
    </style>
</head>
<body>
    <div class="controls">
        {% for id, pin in pins.items() %}
        <div style="margin: 10px">
            <span>{{ pin_names[id] }}</span>
            <button onclick="window.location.href='/toggle/{{ id }}'">
                Toggle
            </button>
            <span>State: {{ "ON" if states[id] else "OFF" }}</span>
        </div>
        {% endfor %}
    </div>

    <div class="camera-grid">
        {% for i in range(camera_count) %}
        <div class="camera-container">
            <img id="camera{{i}}" src="/camera/{{i}}" style="width: 320px; height: 240px"/>
            <button class="update-btn" onclick="updateImage('camera{{i}}', {{i}})">
                Update Camera {{i+1}}
            </button>
            <button class="take-picture-btn" onclick="takePicture({{i}})">
                Take Picture 
            </button>
        </div>
        {% endfor %}
    </div>

    <script>
        function updateImage(imgId, cameraIndex) {
            const img = document.getElementById(imgId);
            img.src = '/camera/' + cameraIndex + '?t=' + new Date().getTime();
        }
        
        function takePicture(cameraIndex) {
            fetch('/camera/' + cameraIndex + '/take/picture', {
                method: 'POST'
            })
            .then(response => {
                if(response.ok) {
                    alert('Picture taken successfully!');
                } else {
                    alert('Failed to take picture');
                }
            })
            .catch(error => {
                alert('Error taking picture: ' + error);
            });
        }
    </script>
</body>
</html>
'''

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
    return render_template_string(HTML, 
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
    return render_template_string(HTML, 
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
