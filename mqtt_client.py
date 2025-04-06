import paho.mqtt.client as mqtt
from datetime import datetime
import json
from typing import Dict, List

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
        self.humidity_topics = "/bodenfeuchte/+/humidity" # Topic for humidity sensors
        self.soil_moisture_topics = f"{self.broker}/bodenfeuchte/devices/#" # Original topic for soil moisture

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
            # Subscribe to topics
            client.subscribe(self.soil_moisture_topics)
            print(f"Subscribed to soil moisture topic: {self.soil_moisture_topics}")
            client.subscribe(self.humidity_topics)
            print(f"Subscribed to humidity topic: {self.humidity_topics}")
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

            # Check if it's a humidity message
            # Simple check: does the topic end with /humidity?
            if topic.endswith("/humidity"):
                # Extract sensor_id (assuming format /bodenfeuchte/<id>/humidity)
                parts = topic.split('/')
                if len(parts) >= 3 and parts[-1] == 'humidity':
                    sensor_id = parts[-2]
                    if 'humidity' in data:
                        humidity_value = float(data['humidity'])
                        self.process_humidity_data(sensor_id, humidity_value)
                    else:
                        print(f"Missing 'humidity' key in payload from {topic}")
                else:
                     print(f"Could not parse sensor_id from humidity topic: {topic}")

            # Check if it's a soil moisture message (using original logic structure)
            # Note: This assumes soil moisture topics DON'T end with /humidity
            elif topic.startswith(self.broker + "/bodenfeuchte/devices/"): # More specific check
                sensor_id = topic.split('/')[-1]
                # Validate required fields for soil moisture
                if all(k in data for k in ['ADC', 'temperature']):
                    self.process_sensor_data(sensor_id, data)
                else:
                    print(f"Invalid soil moisture sensor data format from {sensor_id} on topic {topic}")
            else:
                # Optional: Log messages from other topics if needed
                # print(f"Received message on unhandled topic: {topic}")
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
            
        self.state.sensor_readings[sensor_id].append({
            'timestamp': datetime.now().isoformat(),
            'moisture': float(data['ADC']),
            'temperature': float(data['temperature'])
        })
        
        # Keep only last 10 readings
        self.state.sensor_readings[sensor_id] = self.state.sensor_readings[sensor_id][-24:]
        
        # Check watering triggers if this sensor is configured
        if sensor_id in self.state.sensor_configs:
            self.check_watering_trigger(sensor_id)
    
    def check_watering_trigger(self, sensor_id: str):
        """
        Check if watering should be triggered based on sensor data
        
        Args:
            sensor_id: Sensor to check triggers for
        """
        config = self.state.sensor_configs[sensor_id]
        readings = self.state.sensor_readings.get(sensor_id, [])
        
        # Need at least 4 readings to trigger
        if len(readings) < 4:
            return
            
        # Get last 4 moisture readings
        last_four = [r['moisture'] for r in readings[-4:]]
        min_moisture = config['min_moisture']
        
        # Trigger if all last 4 readings are below threshold
        if all(m < min_moisture for m in last_four):
            self.state.watering_triggers[config['stage']] = True
            print(f"Watering triggered for stage {config['stage']} (sensor {sensor_id})")

    def process_humidity_data(self, sensor_id: str, humidity: float):
        """
        Process and store humidity sensor data.

        Args:
            sensor_id: Unique sensor identifier from the topic.
            humidity: The humidity value from the payload.
        """
        try:
            # Ensure the state object has the humidity_readings dictionary
            if not hasattr(self.state, 'humidity_readings'):
                 self.state.humidity_readings = {} # Initialize if missing

            if sensor_id not in self.state.humidity_readings:
                self.state.humidity_readings[sensor_id] = []

            timestamp = datetime.now().isoformat()
            self.state.humidity_readings[sensor_id].append({
                'timestamp': timestamp,
                'humidity': humidity
            })

            # Keep only the last N readings (e.g., 5)
            max_readings = 5
            self.state.humidity_readings[sensor_id] = self.state.humidity_readings[sensor_id][-max_readings:]

            print(f"Processed humidity from {sensor_id}: {humidity}% at {timestamp}")

        except Exception as e:
            print(f"Error processing humidity data for sensor {sensor_id}: {e}")


    def disconnect(self):
        """Disconnect from MQTT broker"""
        self.client.loop_stop()
        self.client.disconnect()
