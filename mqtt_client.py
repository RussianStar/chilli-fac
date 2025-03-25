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
        
    def connect(self):
        """Connect to MQTT broker and start network loop"""
        try:
            self.client.connect(self.broker, self.port, self.keepalive)
            self.client.loop_start()
            return True
        except Exception as e:
            print(f"MQTT connection failed: {str(e)}")
            return False
    
    def on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker"""
        if rc == 0:
            print("Connected to MQTT broker")
            # Subscribe to all soil moisture sensor topics
            client.subscribe(f"{self.broker}/bodenfeuchte/devices/#")
        else:
            print(f"Connection failed with code {rc}")
    
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
        # Store reading (limit to last 10 readings)
        if sensor_id not in self.state.sensor_readings:
            self.state.sensor_readings[sensor_id] = []
            
        self.state.sensor_readings[sensor_id].append({
            'timestamp': datetime.now().isoformat(),
            'moisture': float(data['ADC']),
            'temperature': float(data['temperature'])
        })
        
        # Keep only last 10 readings
        self.state.sensor_readings[sensor_id] = self.state.sensor_readings[sensor_id][-10:]
        
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
