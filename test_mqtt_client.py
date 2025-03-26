import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from mqtt_client import MQTTClient

@pytest.fixture
def mock_state():
    state = MagicMock()
    state.sensor_configs = {}
    state.sensor_readings = {}
    state.watering_triggers = {}
    return state

@pytest.fixture
def config():
    return {
        'mqtt': {
            'broker': 'test.mosquitto.org',
            'port': 1883,
            'keepalive': 60,
            'username': 'dummy_user',  # Added dummy credentials
            'password': 'dummy_password'  # Added dummy credentials
        }
    }

@pytest.fixture
def mqtt_client(mock_state, config):
    with patch('paho.mqtt.client.Client') as mock_mqtt:
        mock_client = mock_mqtt.return_value
        client = MQTTClient(mock_state, config)
        yield client, mock_client

def test_connect_success(mqtt_client):
    client, mock_client = mqtt_client
    client.connect()
    # Should set credentials before connecting
    mock_client.username_pw_set.assert_called_with('dummy_user', 'dummy_password')
    mock_client.connect.assert_called_with(
        'test.mosquitto.org',
        1883,
        60
    )
    mock_client.loop_start.assert_called_once()

def test_on_connect_success(mqtt_client):
    client, mock_client = mqtt_client
    client.on_connect(mock_client, None, None, 0)
    mock_client.subscribe.assert_called_with('test.mosquitto.org/bodenfeuchte/#')

def test_on_connect_failure(mqtt_client):
    client, mock_client = mqtt_client
    with patch('builtins.print') as mock_print:
        client.on_connect(mock_client, None, None, 1)
        mock_print.assert_called_with('Connection failed with code 1')

def test_process_sensor_data(mock_state, config):
    client = MQTTClient(mock_state, config)
    test_data = {
        'soil_moisture': 45.2,
        'temperature': 22.1
    }
    
    client.process_sensor_data('sensor1', test_data)
    
    assert len(mock_state.sensor_readings['sensor1']) == 1
    reading = mock_state.sensor_readings['sensor1'][0]
    assert reading['moisture'] == 45.2
    assert reading['temperature'] == 22.1

def test_check_watering_trigger(mock_state, config):
    client = MQTTClient(mock_state, config)
    sensor_id = 'sensor1'
    mock_state.sensor_configs[sensor_id] = {
        'stage': 1,
        'min_moisture': 50.0
    }
    
    mock_state.sensor_readings[sensor_id] = [
        {'moisture': 49.0, 'temperature': 22.0, 'timestamp': datetime.now().isoformat()},
        {'moisture': 48.5, 'temperature': 22.1, 'timestamp': datetime.now().isoformat()},
        {'moisture': 47.8, 'temperature': 22.0, 'timestamp': datetime.now().isoformat()},
        {'moisture': 46.2, 'temperature': 21.9, 'timestamp': datetime.now().isoformat()}
    ]
    
    with patch('builtins.print') as mock_print:
        client.check_watering_trigger(sensor_id)
        mock_print.assert_called_with('Watering triggered for stage 1 (sensor sensor1)')
        assert mock_state.watering_triggers[1] is True

def test_check_watering_no_trigger(mock_state, config):
    client = MQTTClient(mock_state, config)
    sensor_id = 'sensor1'
    mock_state.sensor_configs[sensor_id] = {
        'stage': 1,
        'min_moisture': 50.0
    }
    
    mock_state.sensor_readings[sensor_id] = [
        {'moisture': 51.0, 'temperature': 22.0, 'timestamp': datetime.now().isoformat()},
        {'moisture': 52.5, 'temperature': 22.1, 'timestamp': datetime.now().isoformat()},
        {'moisture': 50.8, 'temperature': 22.0, 'timestamp': datetime.now().isoformat()},
        {'moisture': 51.2, 'temperature': 21.9, 'timestamp': datetime.now().isoformat()}
    ]
    
    client.check_watering_trigger(sensor_id)
    assert 1 not in mock_state.watering_triggers

def test_check_watering_insufficient_readings(mock_state, config):
    """Test that watering is not triggered with only 3 readings below threshold"""
    client = MQTTClient(mock_state, config)
    sensor_id = 'sensor1'
    mock_state.sensor_configs[sensor_id] = {
        'stage': 1,
        'min_moisture': 50.0
    }
    
    mock_state.sensor_readings[sensor_id] = [
        {'moisture': 49.0, 'temperature': 22.0, 'timestamp': datetime.now().isoformat()},
        {'moisture': 48.5, 'temperature': 22.1, 'timestamp': datetime.now().isoformat()},
        {'moisture': 47.8, 'temperature': 22.0, 'timestamp': datetime.now().isoformat()}
    ]
    
    with patch('builtins.print') as mock_print:
        client.check_watering_trigger(sensor_id)
        mock_print.assert_not_called()
        assert 1 not in mock_state.watering_triggers
