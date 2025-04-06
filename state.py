from dataclasses import dataclass, field
from typing import Dict, List 

from hydro import Hydro
from lux import Lux
from static_light import StaticLight
from fan_control import FanControl # Import the new FanControl class
import itertools

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
    sensor_configs: Dict[str, Dict] = field(default_factory=dict)  # {sensor_id: {stage: int, min_moisture: float, active: bool}}
    humidity_readings: Dict[str, List[Dict]] = field(default_factory=dict) # {sensor_id: [{timestamp, humidity}]} # Add humidity readings storage
    sensor_readings: Dict[str, List[Dict]] = field(default_factory=dict)  # {sensor_id: [{timestamp, moisture, temp}]}
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
    watering_auto_state: Dict = field(init=False, default_factory=dict)
    watering_durations: Dict[int, int] = field(init=False, default_factory=dict)
    camera_endpoints: Dict = field(init=False)
    
    watering_progress: Dict = field(default_factory=dict)
    watering_task: Dict = field(default_factory=dict)
    fan_state: Dict = field(init=False, default_factory=dict) # Add fan state storage

    def __post_init__(self):
        """Initialize components after dataclass initialization"""
        self.pumps = self.config['database_timeout']
        self.wtrctrl = Hydro(logger=self.logger, gpio_config=self.config,debug= self.debug)
        
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
        self.static_light_auto_states = {
            int(k): {
                "enabled": False,
                "start_time": None,
                "duration_hours": None
            } for k in self.config['static_light_pins']
        }
        self.zeus_auto_states = {
            int(k): {
                "enabled": False,
                "start_time": None,
                "duration_hours": None,
                "brightness": None
            } for k in self.config['light_pins']
        }
        self.valve_states = {
            int(k): False for k in self.config['valve_pins']
        }
        self.watering_auto_state = {
            "enabled": False,
            "start_time": None
        }
        
        # Initialize watering durations (default 3 minutes per valve)
        self.watering_durations = {
            int(k): 180 for k in self.config['valve_pins']
        }

        # Initialize Fan Controller
        if 'PIN_FAN' in self.config:
            self.fanctrl = FanControl(logger=self.logger, gpio_pin=self.config['PIN_FAN'], debug=self.debug)
            self.fan_state = self.fanctrl.get_status() # Initialize fan state
        else:
            self.logger.error("PIN_FAN not found in config.json. Fan control will be unavailable.")
            # Create a dummy FanControl or handle appropriately if needed elsewhere
            # For now, accessing self.fanctrl will raise an AttributeError if PIN_FAN is missing
            pass # Or initialize self.fanctrl to None and check elsewhere

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
