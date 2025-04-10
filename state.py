from dataclasses import dataclass, field
from typing import Dict, List 

from hydro import Hydro
from lux import Lux
from static_light import StaticLight
from fan_control import FanControl # Import the new FanControl class
import itertools
import json
from datetime import datetime

@dataclass
class SystemState:
    """
    Class to manage system state including lights, valves and pumps
    Uses dataclass for cleaner initialization and better structure
    """
    logger: object
    config: Dict
    debug: bool = False
    
    # Initialize component controllers
    wtrctrl: Hydro = field(init=False)
    zeus: Dict[int, Lux] = field(init=False, default_factory=dict)
    static_lights: Dict[int, StaticLight] = field(init=False, default_factory=dict)
    fanctrl: FanControl = field(init=False) # Add FanControl instance

    # Sensor state tracking
    # Updated sensor_configs structure: {sensor_id: {stage: int, min_moisture: float, active: bool, min_adc: int, max_adc: int}}
    sensor_configs: Dict[str, Dict] = field(default_factory=dict)
    humidity_readings: Dict[str, List[Dict]] = field(default_factory=dict) # {sensor_id: [{timestamp, humidity}]} # Add humidity readings storage
    # Updated sensor_readings structure: {sensor_id: [{timestamp, raw_adc, moisture_percent, temp}]}
    sensor_readings: Dict[str, List[Dict]] = field(default_factory=dict)
    watering_triggers: Dict[int, bool] = field(default_factory=dict)  # {stage: should_water}
    
    # Initialize state tracking
    valves: list = field(default_factory=list)
    pumps: int = field(init=False)
    pump_states: Dict[int, bool] = field(default_factory=lambda: {1: False})
    light_states: Dict[int, bool] = field(init=False, default_factory=dict) 
    static_light_states: Dict[int, bool] = field(init=False, default_factory=dict)
    static_light_auto_states: Dict[int, Dict] = field(init=False, default_factory=dict)
    zeus_auto_states: Dict[int, Dict] = field(init=False, default_factory=dict)
    valve_states: Dict[int, bool] = field(init=False, default_factory=dict)
    camera_endpoints: Dict = field(init=False)

    watering_progress: Dict = field(default_factory=dict) # Keep for potential manual/future use
    watering_task: Dict = field(default_factory=dict)
    fan_state: Dict = field(init=False, default_factory=dict) # Add fan state storage

    def __post_init__(self):
        """Initialize components after dataclass initialization"""
        # Get initial state from config, default to empty dict if not found
        initial_state = self.config.get('initial_state', {})

        self.pumps = self.config['database_timeout']
        # Pass self (the state instance) to Hydro constructor
        self.wtrctrl = Hydro(logger=self.logger, gpio_config=self.config, state=self, debug=self.debug)

        # Initialize light controllers and states
        self.zeus = {
            int(k): Lux(self.logger, pin=v, freq=1000, debug=self.debug) 
            for k,v in self.config['light_pins'].items()
        }
        self.static_lights = {
            int(k): StaticLight(self.logger, v, debug=self.debug)
            for k,v in self.config['static_light_pins'].items()
        }
        
        # Initialize state dictionaries
        self.light_states = {
            int(k): False for k in self.config['light_pins']
        }
        self.static_light_states = {
            int(k): False for k in self.config['static_light_pins']
        }

        # Initialize auto states from config or defaults
        initial_static_auto = initial_state.get('static_lights_auto', {})
        self.static_light_auto_states = {
            int(k): initial_static_auto.get(str(k), {
                "enabled": False, "start_time": None, "duration_hours": None
            }) for k in self.config['static_light_pins']
        }
        # Apply initial static light auto modes
        for light_id, auto_config in self.static_light_auto_states.items():
            if auto_config.get("enabled"):
                self.logger.info(f"Applying initial auto mode for static light {light_id}: {auto_config}")
                self.static_lights[light_id].set_auto_mode(
                    auto_config["start_time"], auto_config["duration_hours"]
                )

        initial_zeus_auto = initial_state.get('zeus_lights_auto', {})
        self.zeus_auto_states = {
            int(k): initial_zeus_auto.get(str(k), {
                "enabled": False, "start_time": None, "duration_hours": None, "brightness": None
            }) for k in self.config['light_pins']
        }
        # Apply initial Zeus light auto modes
        for light_id, auto_config in self.zeus_auto_states.items():
            if auto_config.get("enabled"):
                 self.logger.info(f"Applying initial auto mode for Zeus light {light_id}: {auto_config}")
                 self.zeus[light_id].set_auto_mode(
                     auto_config["start_time"], auto_config["duration_hours"], auto_config.get("brightness", 100) # Use configured brightness or default 100
                 )

        self.valve_states = {
            int(k): False for k in self.config['valve_pins'] # Keep default off state
        }

        # Removed initialization for watering_auto_state and watering_durations
        # # Initialize watering auto state from config or defaults
        # initial_watering_auto = initial_state.get('watering', {}).get('auto_mode', {})
        # self.watering_auto_state = {
        #     "enabled": initial_watering_auto.get('enabled', False),
        #     "start_time": initial_watering_auto.get('start_time', None)
        # }
        #
        # # Initialize watering durations from config or defaults (default 180 seconds)
        # initial_watering_durations = initial_state.get('watering', {}).get('durations', {})
        # self.watering_durations = {
        #     int(k): initial_watering_durations.get(str(k), 180) for k in self.config['valve_pins']
        # }

        # Initialize sensor configurations from config or defaults, ensuring calibration values are present
        initial_sensors = self.config.get('sensors', {}) # Get from main config directly
        self.sensor_configs = {}
        for sensor_id, config_data in initial_sensors.items():
            self.sensor_configs[sensor_id] = {
                'stage': config_data.get('stage', 1), # Default stage 1
                'min_moisture': config_data.get('min_moisture', 50.0), # Default threshold 50%
                'active': config_data.get('active', True), # Default active
                'min_adc': config_data.get('min_adc', 0), # Default min ADC 0 (needs calibration)
                'max_adc': config_data.get('max_adc', 4095) # Default max ADC (needs calibration)
            }


        # Initialize Fan Controller and its state from config or defaults
        if 'PIN_FAN' in self.config:
            self.fanctrl = FanControl(logger=self.logger, state=self, gpio_pin=self.config['PIN_FAN'], debug=self.debug) # Pass self (state)
            # Get initial hardware status first
            current_fan_status = self.fanctrl.get_status()
            # Get fan config from initial_state
            initial_fan_config = initial_state.get('fan', {})
            # Merge config over hardware status (config takes precedence)
            self.fan_state = {
                "target_humidity": initial_fan_config.get('target_humidity', current_fan_status.get('target_humidity', 65.0)),
                "control_active": initial_fan_config.get('control_active', current_fan_status.get('control_active', False)),
                "manual_on": initial_fan_config.get('manual_on', current_fan_status.get('manual_on', False)),
                "current_humidity": current_fan_status.get('current_humidity', None), # Keep current reading
                "is_on": current_fan_status.get('is_on', False) # Keep current on/off status
            }
            # Apply initial config settings to the controller based on the loaded fan_state
            self.logger.info(f"Applying initial fan state: {self.fan_state}")
            self.fanctrl.set_target_humidity(self.fan_state['target_humidity'])
            if self.fan_state['control_active']:
                self.fanctrl.activate_control()
                self.logger.info("Initial fan state: Activating automatic control.")
            else:
                # If auto control is not active, apply manual state if specified
                self.fanctrl.deactivate_control() # Ensure auto is off
                if self.fan_state['manual_on']:
                    self.fanctrl.turn_on()
                    self.logger.info("Initial fan state: Turning fan ON manually.")
                else:
                    self.fanctrl.turn_off() # Ensure fan is off if not manually on
                    self.logger.info("Initial fan state: Turning fan OFF (manual/auto inactive).")

        else:
            self.logger.error("PIN_FAN not found in config.json. Fan control will be unavailable.")
            self.fanctrl = None # Explicitly set to None
            self.fan_state = {} # Empty state if no fan controller

        self.camera_endpoints = self.config['camera_endpoints']

    def cleanup(self):
        try:
            # Cleanup Fan Control if initialized
            if hasattr(self, 'fanctrl') and self.fanctrl:
                try:
                    self.fanctrl.cleanup_gpio()
                except Exception as e:
                    self.logger.error(f"Error cleaning up FanControl GPIO: {e}")

            all_gpio_based = [
                self.pump_states.values(),
                self.valve_states.values(), 
                self.light_states.values(),
                self.static_light_states.values()
            ]

            for gpio_obj in list(itertools.chain.from_iterable(all_gpio_based)):
                try:
                    gpio_obj.cleanup_gpio()
                except Exception as e:
                    self.logger.error(f"Error cleaning up GPIO object: {e}")
                    
        except Exception as e:
            self.logger.error(f"Error during GPIO cleanup: {e}")

    def get_status_payload(self) -> dict:
        """
        Gathers the current system state into a dictionary suitable for JSON serialization.
        """
        # Get latest sensor readings (moisture, temp, humidity)
        latest_sensor_readings = {}
        for sensor_id, readings in self.sensor_readings.items():
            if readings:
                latest = readings[-1].copy() # Get the last reading
                # Ensure timestamp is serializable (ISO format string)
                if isinstance(latest.get('timestamp'), datetime):
                    latest['timestamp'] = latest['timestamp'].isoformat()
                latest_sensor_readings[sensor_id] = latest
            else:
                latest_sensor_readings[sensor_id] = None # Indicate no readings yet

        # Get latest humidity readings (if stored separately)
        latest_humidity_readings = {}
        for sensor_id, readings in self.humidity_readings.items():
             if readings:
                 latest = readings[-1].copy()
                 if isinstance(latest.get('timestamp'), datetime):
                     latest['timestamp'] = latest['timestamp'].isoformat()
                 latest_humidity_readings[sensor_id] = latest
             else:
                 latest_humidity_readings[sensor_id] = None

        # Consolidate fan state, ensuring it exists
        fan_status = self.fan_state.copy() if hasattr(self, 'fanctrl') and self.fanctrl else {}
        # Update with live status if controller exists
        if hasattr(self, 'fanctrl') and self.fanctrl:
            live_fan_status = self.fanctrl.get_status()
            fan_status.update(live_fan_status) # Merge live status (is_on, target, active)

        payload = {
            "timestamp": datetime.now().isoformat(),
            "lights": {
                "zeus": self.light_states,
                "static": self.static_light_states,
                "auto_zeus": self.zeus_auto_states,
                "auto_static": self.static_light_auto_states,
            },
            "watering": {
                "valves": self.valve_states,
                "pump": self.pump_states.get(1, False), # Assuming pump ID 1
                # Removed old auto_mode and durations from status
                # "auto_mode": self.watering_auto_state,
                # "durations": self.watering_durations,
                "progress": self.watering_progress, # Keep for potential manual/future use
                "active_task": bool(self.watering_task), # Keep for potential manual/future use
                # Optionally add new hydro internal states if needed for UI:
                # "sensor_watering_active": dict(self.wtrctrl._watering_active),
                # "sensor_watering_cooldown": dict(self.wtrctrl._waiting_for_readings),
            },
            "fan": fan_status,
            "sensors": {
                "configs": self.sensor_configs,
                "latest_readings": latest_sensor_readings,
                # "latest_humidity": latest_humidity_readings, # Redundant if included in sensor_readings
            },
            # Add other relevant states if needed
        }
        return payload
