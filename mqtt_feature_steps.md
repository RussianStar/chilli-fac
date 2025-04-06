# MQTT Sensor Integration Implementation Guide

## Phase 1: Core System Modifications

### 1. State Management (state.py)
```python
# Add to SystemState class:
sensor_configs: Dict[str, Dict] = field(default_factory=dict)  # {sensor_id: {stage: int, min_moisture: float}}
sensor_readings: Dict[str, List[Dict]] = field(default_factory=dict)  # {sensor_id: [{timestamp, moisture, temp}]}
watering_triggers: Dict[int, bool] = field(default_factory=dict)  # {stage: should_water}
```

### 2. MQTT Client (new file: mqtt_client.py)
```python
import paho.mqtt.client as mqtt
from datetime import datetime
import json

class MQTTClient:
    def __init__(self, state, config):
        self.state = state
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.broker = config['mqtt']['broker']
        
    def connect(self):
        self.client.connect(self.broker)
        self.client.loop_start()
    
    def on_connect(self, client, userdata, flags, rc):
        client.subscribe(f"{self.broker}/bodenfeuchte/#")
    
    def on_message(self, client, userdata, msg):
        sensor_id = msg.topic.split('/')[-1]
        data = json.loads(msg.payload)
        self.process_sensor_data(sensor_id, data)
```

## Phase 2: Control Logic

### 3. Controller Updates (controller.py)
```python
def check_and_execute_watering(self, current_state):
    for stage, should_water in current_state.watering_triggers.items():
        if should_water:
            durations = {stage: 300}  # 300s watering duration
            current_state = self.set_watering_durations(current_state, durations)
            current_state = self.execute_watering_sequence(current_state)
            current_state.watering_triggers[stage] = False
    return current_state
```

## Phase 3: Web Interface

### 4. Frontend (templates/index.html)
```html
<div class="sensor-config">
  <form id="sensor-form">
    <input type="text" name="sensor_id" placeholder="Sensor ID" required>
    <select name="stage" required>
      <option value="1">Stage 1</option>
      <option value="2">Stage 2</option>
      <option value="3">Stage 3</option>
    </select>
    <input type="number" step="0.1" name="min_moisture" placeholder="Min Moisture %" required>
    <button type="submit">Add Sensor</button>
  </form>
</div>
```

## Implementation Checklist
- [ ] Create mqtt_client.py with basic connectivity
- [ ] Update state.py with sensor fields
- [ ] Add controller watering check method
- [ ] Implement frontend form
- [ ] Add API endpoints in main.py
- [ ] Integrate MQTT client initialization
- [ ] Test sensor data flow
- [ ] Verify watering triggers
