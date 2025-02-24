from logging.handlers import RotatingFileHandler
import os
import time
import logging
from datetime import datetime
import sqlite3
import threading
import requests
import json
from  flask  import Flask, render_template, request
from hydro import Hydro
from lux import Lux
from static_light import StaticLight
from camera import get_camera_bytes,capture_image_data

with open('config.json') as f:
    config = json.load(f)
# logging interval to database in seconds
LOGGING_INTERVAL = config['logging_interval']

def setup_logging():
    # Create logger
    logger = logging.getLogger('hydro')
    logger.setLevel(logging.DEBUG)

    # Ensure log directory exists
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Create log file path
    log_file = os.path.join(log_dir, 'hydro.log')

    # Initialize rotating file handler with modern parameters
    file_handler = RotatingFileHandler(
        filename=log_file,
        mode='a',
        maxBytes=1024*1024,  # 1MB per file
        backupCount=5,
        encoding='utf-8',
        delay=False
    )
    file_handler.setLevel(logging.DEBUG)
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Create formatters
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')

    # Add formatters to handlers
    file_handler.setFormatter(file_formatter)
    console_handler.setFormatter(console_formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

def is_raspberry_pi():
    try:
        with open('/proc/device-tree/model') as f:
            return 'raspberry' in f.read().lower()
    except:
        return False

# Initialize Flask app
app = Flask(__name__)
logger = setup_logging()
debug = not is_raspberry_pi();


wtrctrl = Hydro(logger,config,debug)
zeus = {int(k):Lux(logger,pin=v, freq=1000, debug=debug) for k,v in config['light_pins'].items()}
static_lights = {int(k):StaticLight(logger,v, debug=debug) for k,v in config['static_light_pins'].items()}

pump_states = { 1:False}
light_states = {int(k): False for k,_ in config['light_pins'].items()}
static_light_states = {int(k): False for k,_ in config['static_light_pins'].items()}
valve_states ={int(k): False for k,_ in config['valve_pins'].items()}  

CAMERA_ENDPOINTS = config['camera_endpoints']

@app.route('/camera/<int:camera_id>/take/picture', methods=['POST'])
def take_picture(camera_id):
    if camera_id < len(CAMERA_ENDPOINTS):
        try:
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
    duration = request.form.get('duration', type=int, default=45)
    
    try:
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
    if light_id <= len(static_lights):
        light_controller = static_lights[light_id]
        
        if light_controller.is_on():
            light_controller.turn_off()
            static_light_states[light_id] = False
        else:
            light_controller.turn_on()
            static_light_states[light_id] = True

        logger.info(f"Toggling static light #{light_id} to {static_light_states[light_id]}")
    
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

        logger.info(f"Setting light #{light_id} brightness to {brightness}%")
    
    return render_template("index.html",
                         valves=valve_states,
                         lights=light_states, 
                         static_lights=static_light_states, 
                         pumps=pump_states,
                         camera_count=len(CAMERA_ENDPOINTS))

@app.route('/camera/<int:camera_id>')
def get_camera_image(camera_id):
    if camera_id < len(CAMERA_ENDPOINTS):
        result = get_camera_bytes(CAMERA_ENDPOINTS[camera_id])
        if result is None:
            return f"Error loading camera image.", 500

        return result
            
    return "Camera not found", 404



def init_db():
    conn = sqlite3.connect('hydro_status.db')
    c = conn.cursor()
    
    # Create status table
    c.execute('''CREATE TABLE IF NOT EXISTS status
                 (timestamp TEXT,
                  valve_states TEXT,
                  light_states TEXT, 
                  pump_states TEXT,
                  static_light_states TEXT)''')
    
    # Create camera images table
    c.execute('''CREATE TABLE IF NOT EXISTS camera_images
                 (camera_id INTEGER,
                  timestamp TEXT,
                  image_data TEXT)''')
                  
    conn.commit()
    conn.close()

def log_status():
    while True:
        conn = None
        try:
            # Increased timeout and isolation level for better concurrency
            with sqlite3.connect('hydro_status.db', timeout=30.0, 
                               isolation_level='EXCLUSIVE') as conn:
                c = conn.cursor()
                
                now = datetime.now().isoformat()
                
                # Log system status in a single transaction
                status = {
                    'timestamp': now,
                    'valve_states': str(valve_states),
                    'light_states': str(light_states), 
                    'pump_states': str(pump_states),
                    'static_light_states': str(static_light_states)
                }
                
                c.execute('''INSERT INTO status VALUES 
                            (:timestamp, :valve_states, :light_states,
                             :pump_states, :static_light_states)''',
                         status)

                images = []
                threads = []
                for camera_id in range(len(CAMERA_ENDPOINTS)):
                    t = threading.Thread(target=capture_image_data,
                                      args=(logger,camera_id, CAMERA_ENDPOINTS[camera_id], images))
                    threads.append(t)
                    t.start()

                for t in threads:
                    t.join()
                
                logger.info(f"all threads finished.")
                logger.info(f"Got {len(images)} items.")

                for camera_id, image_data in images:
                    logger.info(f"Writing image for camera {camera_id}")
                    c.execute('''INSERT INTO camera_images 
                               VALUES (?, ?, ?)''', 
                               (camera_id, now, image_data))
                
                conn.commit()
                logger.debug('Database write completed successfully')

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
        except Exception as e:
            logger.error(f"Error in log_status: {e}")
        finally:
            # Ensure connection is closed even if error occurs
            if conn:
                try:
                    conn.close()
                except Exception as e:
                    logger.error(f"Error closing connection: {e}")

        # Wait before next logging interval
        time.sleep(LOGGING_INTERVAL)

def main():
    try:
        # Setup logging
        logger.info('Starting Hydro Control System')

        # Initialize database
        logger.debug('Initializing database')
        init_db()
        
        logger.debug('Starting status logging thread')
        status_thread = threading.Thread(target=log_status, daemon=True)
        status_thread.start()
        
        logger.info('Starting web server on port 5000')
        app.run(host='0.0.0.0', port=5000)
        
    except Exception as e:
        logger.error(f'Fatal error: {str(e)}', exc_info=True)
        raise
    finally:
        logger.info('Cleaning up resources')
        wtrctrl.cleanup()

if __name__ == "__main__":
    main()

