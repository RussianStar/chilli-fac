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
            # Subscribe to all soil moisture sensor topics
            client.subscribe(f"{self.broker}/bodenfeuchte/devices/#")
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
            sensor_id = msg.topic.split('/')[-1]
            data = json.loads(msg.payload)
            
            # Validate required fields
            if not all(k in data for k in ['ADC', 'temperature']):
                print(f"Invalid sensor data format from {sensor_id}")
                return
                
            self.process_sensor_data(sensor_id, data)
            
        except Exception as e:
            print(f"Error processing MQTT message: {str(e)}")
    
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
    
    def disconnect(self):
        """Disconnect from MQTT broker"""
        self.client.loop_stop()
        self.client.disconnect()
