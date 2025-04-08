import paho.mqtt.client as mqtt
from datetime import datetime
import json
from typing import Dict, List

# Import the calibration function
from helper import calculate_moisture_percentage

class MQTTClient:
    def __init__(self, state, config, client=None):
        """
        Initialize MQTT client with system state and configuration
        
        Args:
            state: SystemState instance
            config: Configuration dictionary with MQTT settings
            client: Optional pre-configured MQTT client (for testing)
        """
        self.state = state
        self.client = client if client else mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        
        # Configure from config.json
        self.broker = config['mqtt']['broker']
        self.port = config['mqtt'].get('port', 1883)
        self.keepalive = config['mqtt'].get('keepalive', 60)
        # self.humidity_topics = "/bodenfeuchte/+/humidity" # REMOVED
        self.sensor_data_topic_prefix = f"bodenfeuchte/devices/" # Topic prefix for combined sensor data

        # Set up authentication if user and password are provided in config
        if 'user' in config['mqtt'] and 'password' in config['mqtt']:
            self.username = config['mqtt']['user']
            self.password = config['mqtt']['password']
            self.client.username_pw_set(self.username, self.password)
            print(f"MQTT authentication configured for user: {self.username}")

    def connect(self):
        """Connect to MQTT broker and start network loop"""
        try:
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)
                
            # Add some error checking for broker address
            if not self.broker:
                raise ValueError("MQTT broker address cannot be empty")
                
            # Try to resolve the hostname before connecting
            import socket
            try:
                socket.gethostbyname(self.broker)
            except socket.gaierror:
                print(f"Warning: Could not resolve hostname '{self.broker}'")
                # You might want to use a fallback address or IP directly
                # self.broker = "fallback.mqtt.broker" or "192.168.1.100"
            
            # Add connection timeout
            self.client.connect(self.broker, self.port, self.keepalive, bind_address="0.0.0.0")
            self.client.loop_start()
            return True
        except Exception as e:
            print(f"MQTT connection failed: {str(e)}")
            # Add more detailed error information
            import traceback
            traceback.print_exc()
            return False
    
    def on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker"""
        if rc == 0:
            print("Connected to MQTT broker")
            # Subscribe to the main sensor data topic
            sensor_topic_wildcard = f"{self.sensor_data_topic_prefix}#"
            client.subscribe(sensor_topic_wildcard)
            print(f"Subscribed to sensor data topic: {sensor_topic_wildcard}")
            # Publish initial status upon successful connection
            self.publish_status()
        else:
            connection_errors = {
                1: "Connection refused - incorrect protocol version",
                2: "Connection refused - invalid client identifier",
                3: "Connection refused - server unavailable",
                4: "Connection refused - bad username or password",
                5: "Connection refused - not authorized"
            }
            error_msg = connection_errors.get(rc, f"Unknown error code {rc}")
            print(f"Connection failed: {error_msg}")
    
    def on_message(self, client, userdata, msg):
        """Callback for incoming messages"""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8') # Decode payload
            data = json.loads(payload)


            # Check if the topic matches the expected sensor data prefix
            if topic.startswith(self.sensor_data_topic_prefix):
                sensor_id = topic.split('/')[-1]
                # Validate required fields based on payload content
                required_keys = ['ADC', 'Temperature', 'Humidity']
                if all(k in data for k in required_keys):
                    # Process the combined sensor data
                    self.process_sensor_data(sensor_id, data)
                else:
                    missing_keys = [k for k in required_keys if k not in data]
                    print(f"Invalid sensor data format from {sensor_id} on topic {topic}. Missing keys: {missing_keys}")
            else:
                # Optional: Log messages from other topics if needed
                print(f"Received message on unhandled topic: {topic}")
                pass

        except json.JSONDecodeError:
            print(f"Error decoding JSON from topic {msg.topic}: {msg.payload}")
        except ValueError as ve:
             print(f"Error converting value from topic {msg.topic}: {ve}")
        except Exception as e:
            print(f"Error processing MQTT message from topic {msg.topic}: {str(e)}")
    
    def process_sensor_data(self, sensor_id: str, data: Dict):
        """
        Process and store sensor data, check watering triggers
        
        Args:
            sensor_id: Unique sensor identifier
            data: Dictionary containing sensor readings
        """
        if sensor_id not in self.state.sensor_readings:
            self.state.sensor_readings[sensor_id] = []
            
        # Extract all relevant values
        timestamp = datetime.now().isoformat()
        raw_adc = int(data['ADC']) # Keep as int for calculation
        temperature = float(data['Temperature'])
        humidity = float(data.get('Humidity', 0.0)) # Use .get with default if Humidity might be missing

        # Get calibration values from state
        sensor_config = self.state.sensor_configs.get(sensor_id)
        moisture_percent = None
        if sensor_config:
            min_adc = sensor_config.get('min_adc', 0)
            max_adc = sensor_config.get('max_adc', 4095) # Use defaults if not set
            moisture_percent = calculate_moisture_percentage(raw_adc, min_adc, max_adc)
        else:
            # Handle case where sensor data arrives before config is set (e.g., during startup)
            # Or log a warning
            print(f"Warning: Received data for unconfigured sensor {sensor_id}. Cannot calculate percentage.")
            # Optionally calculate with defaults anyway, or store raw only
            moisture_percent = calculate_moisture_percentage(raw_adc, 0, 4095) # Example: Calculate with defaults


        self.state.sensor_readings[sensor_id].append({
            'timestamp': timestamp,
            'raw_adc': raw_adc, # Store raw value
            'moisture_percent': moisture_percent, # Store calculated percentage
            'temperature': temperature,
            'humidity': humidity # Store humidity here
        })
        
        # Keep only last 24 readings (as per existing code)
        self.state.sensor_readings[sensor_id] = self.state.sensor_readings[sensor_id][-24:]
        
        # Check watering triggers if this sensor is configured and we have a percentage
        if sensor_config and moisture_percent is not None:
            self.check_watering_trigger(sensor_id, moisture_percent) # Pass the calculated percentage
    
    def check_watering_trigger(self, sensor_id: str, current_moisture_percent: float):
        """
        Check if watering should be triggered based on sensor data
        
        Args:
            sensor_id: Sensor to check triggers for
        """
        config = self.state.sensor_configs.get(sensor_id)
        if not config: # Should not happen if called correctly, but safety check
             return

        # Use the configured threshold (which is already a percentage)
        min_moisture_threshold = config['min_moisture'] 
        
        # Trigger if the current reading is below the threshold
        # Note: The original logic checked the last 4 readings. 
        # We'll keep that logic but use the percentage.
        readings = self.state.sensor_readings.get(sensor_id, [])
        if len(readings) < 4:
             return # Not enough data yet

        # Get last 4 moisture percentages (handle None if calculation failed previously)
        last_four_percent = [r.get('moisture_percent') for r in readings[-4:]]

        # Check if all last 4 readings are valid (not None) and below threshold
        if all(p is not None and p < min_moisture_threshold for p in last_four_percent):
            stage = config.get('stage')
            if stage: # Ensure stage is configured
                self.state.watering_triggers[stage] = True
                print(f"Watering triggered for stage {stage} (sensor {sensor_id}) based on moisture percentage.")
        # Optional: Add logic to reset the trigger if moisture goes above threshold?
        # else:
        #     stage = config.get('stage')
        #     if stage and stage in self.state.watering_triggers:
        #         self.state.watering_triggers[stage] = False
        #         print(f"Watering trigger reset for stage {stage} (sensor {sensor_id}).")


    # Removed process_humidity_data function as it's no longer needed

    def disconnect(self):
        """Disconnect from MQTT broker"""
        self.client.loop_stop()
        self.client.disconnect()

    def publish_status(self):
        """
        Gathers the current system status and publishes it to the MQTT status topic.
        """
        try:
            status_payload = self.state.get_status_payload()
            status_json = json.dumps(status_payload, indent=2) # Use indent for readability if needed
            topic = "chili-fac/status"
            result, mid = self.client.publish(topic, status_json, qos=1) # Use QoS 1 for reliability

            if result == mqtt.MQTT_ERR_SUCCESS:
                print(f"Successfully published status to {topic}") # Use print or logger
            else:
                print(f"Failed to publish status to {topic}. Error code: {result}") # Use print or logger

        except TypeError as te:
            # Handle potential issues with non-serializable data in the payload
            print(f"Error serializing status payload to JSON: {te}") # Use print or logger
            # Optionally log the problematic payload for debugging
            # print(f"Problematic payload: {status_payload}")
        except Exception as e:
            print(f"An error occurred while publishing status: {e}") # Use print or logger
