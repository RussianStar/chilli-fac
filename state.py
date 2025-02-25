from dataclasses import dataclass, field
from typing import Dict 

from hydro import Hydro
from lux import Lux
from static_light import StaticLight
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
    
    # Initialize state tracking
    valves: list = field(default_factory=list)
    pumps: int = field(init=False)
    pump_states: Dict[int, bool] = field(default_factory=lambda: {1: False})
    light_states: Dict[int, bool] = field(init=False, default_factory=dict) 
    static_light_states: Dict[int, bool] = field(init=False, default_factory=dict)
    valve_states: Dict[int, bool] = field(init=False, default_factory=dict)
    camera_endpoints: Dict = field(init=False)
    
    watering_progress: Dict = field(init=False)
    watering_task: Dict = field(init=False)

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
        self.valve_states = {
            int(k): False for k in self.config['valve_pins']
        }
        
        self.camera_endpoints = self.config['camera_endpoints']
        
    def cleanup(self):
        try:
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
