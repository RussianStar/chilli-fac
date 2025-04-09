from gpio_device import gpio_device
import time
import threading
from datetime import datetime
from collections import defaultdict # Use defaultdict for easier state tracking

# Removed schedule import

class Hydro(gpio_device):

    # Removed DEFAULT_SCHEDULE

    def __init__(self, logger, gpio_config, state, debug=False): # Added state parameter
        self.gpio_config = gpio_config
        self.state = state # Store state object
        self.debug = debug
        self.logger = logger,
        self.num_valves = len(gpio_config["valve_pins"])
        # Removed time-based auto mode attributes
        # self._auto_mode = False
        # self._start_time = None
        # self._turn_on_job = None
        # self._scheduler_thread = None
        # self._scheduler_running = False

        # New state tracking for sensor-based watering
        self._watering_active = defaultdict(bool) # {stage: True if watering is active}
        self._waiting_for_readings = defaultdict(bool) # {stage: True if in cooldown waiting for readings}
        self._readings_since_watered = defaultdict(int) # {stage: count of readings since last watering}
        self._last_reading_timestamp = defaultdict(lambda: None) # {sensor_id: last processed timestamp}

        logger.info("Hydro Logger is initialized")

        if not debug:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            
            # Setup pump pin
            GPIO.setup(gpio_config["pump_pin"], GPIO.OUT)
            GPIO.output(gpio_config["pump_pin"], GPIO.HIGH)

            # Setup valve pins
            for pin in gpio_config["valve_pins"].values():
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.HIGH)

    def close_all_valves(self):
        """Closes all valves and stops the pump."""
        self.logger[0].info("Closing all valves and stopping pump.")
        for valve in range(1, self.num_valves + 1):
            self.set_valve(valve, False)
        self.set_pump(False)
        # Reset watering active flags if any were stuck
        for stage in list(self._watering_active.keys()):
             if self._watering_active[stage]:
                 self.logger[0].warning(f"Forcefully resetting active watering flag for stage {stage} during close_all_valves.")
                 self._watering_active[stage] = False


    def set_valve(self, valve_num: int, state: bool):
        """Set valve state (on/off)"""
        if valve_num not in range(1, self.num_valves + 1):
            raise ValueError(f"Invalid valve number[{valve_num}]. Must be 1-{self.num_valves}")
            
        if self.debug:
            return state

        pin = self.gpio_config["valve_pins"][str(valve_num)]
        import RPi.GPIO as GPIO
        GPIO.output(pin, GPIO.LOW if state else GPIO.HIGH)
        # Update state tracking in SystemState
        if hasattr(self, 'state') and self.state:
             self.state.valve_states[valve_num] = state
        self.logger[0].info(f"Setting valve {valve_num} to {state}")
        return state

    def set_pump(self, state: bool):
        """Set pump state (on/off)"""
        # Update state tracking in SystemState
        if hasattr(self, 'state') and self.state:
             self.state.pump_states[1] = state # Assuming pump ID 1
        self.logger[0].info(f"Setting pump to {state}")
        if self.debug:
            return state

        import RPi.GPIO as GPIO
        GPIO.output(self.gpio_config["pump_pin"], GPIO.LOW if state else GPIO.HIGH)
        return state

    def cleanup_gpio(self):
        """Cleanup GPIO on exit"""
        # Removed disable_auto_mode() call
        self.close_all_valves() # Ensure everything is off
        if not self.debug:
            import RPi.GPIO as GPIO
            GPIO.cleanup()

    # Removed is_auto_mode, get_auto_settings, set_auto_mode, disable_auto_mode,
    # auto_execute_watering, _start_scheduler, _run_scheduler

    def check_sensor_watering(self):
        """Checks sensor readings and triggers watering if necessary."""
        if not hasattr(self, 'state') or not self.state:
             self.logger[0].error("SystemState not available in Hydro controller.")
             return

        active_sensors_by_stage = defaultdict(list)
        for sensor_id, config in self.state.sensor_configs.items():
            if config.get('active', False):
                stage = config.get('stage')
                if stage is not None:
                    active_sensors_by_stage[stage].append(sensor_id)

        for stage, sensor_ids in active_sensors_by_stage.items():
            # --- Cooldown Logic: Check if waiting for readings ---
            if self._waiting_for_readings[stage]:
                readings_counted = 0
                new_reading_found_this_check = False
                for sensor_id in sensor_ids:
                    if sensor_id in self.state.sensor_readings and self.state.sensor_readings[sensor_id]:
                        latest_reading = self.state.sensor_readings[sensor_id][-1]
                        last_processed_ts = self._last_reading_timestamp[sensor_id]
                        current_ts = latest_reading.get('timestamp')

                        # Check if this is a new reading since the last check for this sensor
                        if current_ts and (last_processed_ts is None or current_ts > last_processed_ts):
                             self._readings_since_watered[stage] += 1
                             self._last_reading_timestamp[sensor_id] = current_ts # Update last processed timestamp
                             new_reading_found_this_check = True
                             self.logger[0].debug(f"Stage {stage}: Counted new reading from {sensor_id}. Total since watered: {self._readings_since_watered[stage]}")

                if self._readings_since_watered[stage] >= 4:
                    self.logger[0].info(f"Stage {stage}: Cooldown finished ({self._readings_since_watered[stage]} readings received). Enabling watering checks.")
                    self._waiting_for_readings[stage] = False
                    self._readings_since_watered[stage] = 0 # Reset counter
                # else:
                    # self.logger[0].debug(f"Stage {stage}: Still in cooldown ({self._readings_since_watered[stage]}/4 readings).")
                continue # Skip watering check if in cooldown

            # --- Watering Trigger Logic ---
            if self._watering_active[stage]:
                # self.logger[0].debug(f"Stage {stage}: Watering already active.")
                continue # Skip if watering is already running for this stage

            # Find the minimum moisture percentage among sensors for this stage
            min_moisture_in_stage = 100.0
            triggering_sensor = None
            threshold = 100.0 # Default high, find the actual threshold below

            # First find lowest moisture reading from all sensors in this stage
            moisture_readings = []
            for sensor_id in sensor_ids:
                if sensor_id in self.state.sensor_readings and self.state.sensor_readings[sensor_id]:
                    latest_reading = self.state.sensor_readings[sensor_id][-1]
                    moisture = latest_reading.get('moisture_percent')
                    if moisture is not None:
                        moisture_readings.append((sensor_id, moisture))
            
            if moisture_readings:
                # Get sensor with lowest moisture reading
                triggering_sensor, min_moisture_in_stage = min(moisture_readings, key=lambda x: x[1])
                threshold = self.state.sensor_configs[triggering_sensor].get('min_moisture', 50.0)

            # Check if the minimum moisture is below the threshold
            if triggering_sensor is not None and min_moisture_in_stage < threshold:
                self.logger[0].info(f"Stage {stage}: Triggering watering. Sensor {triggering_sensor} reading: {min_moisture_in_stage:.2f}% < Threshold: {threshold:.2f}%")
                self._watering_active[stage] = True
                self._waiting_for_readings[stage] = True # Start cooldown period immediately
                self._readings_since_watered[stage] = 0 # Reset reading count
                # Clear last reading timestamps for sensors in this stage to ensure fresh counting
                for s_id in sensor_ids:
                    self._last_reading_timestamp[s_id] = None

                # Start watering in a separate thread
                watering_thread = threading.Thread(target=self._execute_stage_watering_thread, args=(stage, 300), daemon=True)
                watering_thread.start()
            # else:
                # self.logger[0].debug(f"Stage {stage}: Moisture level OK (Min: {min_moisture_in_stage:.2f}%, Threshold: {threshold:.2f}%).")


    def _execute_stage_watering_thread(self, stage: int, duration: int):
        """Executes the watering sequence for a specific stage in a thread."""
        valve_id = stage # Assuming stage number corresponds directly to valve number
        self.logger[0].info(f"Starting watering thread for Stage {stage} (Valve {valve_id}) for {duration} seconds.")

        try:
            # Ensure other valves for other active stages are not affected?
            # For now, assume only one stage waters at a time controlled by _watering_active flag.
            # If concurrent watering is needed, pump logic needs refinement.

            # 1. Turn on Pump
            self.set_pump(True)
            time.sleep(1) # Small delay for pump pressure

            # 2. Open Valve
            self.set_valve(valve_id, True)

            # 3. Wait for duration
            time.sleep(duration)

            # 4. Close Valve
            self.set_valve(valve_id, False)
            time.sleep(1) # Small delay

            # 5. Turn off Pump (only if no other stages are actively watering - check _watering_active)
            # This check prevents turning off the pump if another stage started watering concurrently.
            # A more robust solution might involve reference counting for pump usage.
            if not any(self._watering_active.get(s, False) for s in self._watering_active if s != stage):
                 self.set_pump(False)
                 self.logger[0].info(f"Stage {stage}: Pump turned off as no other stages are active.")
            else:
                 self.logger[0].info(f"Stage {stage}: Pump left ON as other stages might be active.")


            self.logger[0].info(f"Watering thread for Stage {stage} completed successfully.")

        except Exception as e:
            self.logger[0].error(f"Error during watering thread for Stage {stage}: {str(e)}")
            # Ensure valve and potentially pump are turned off in case of error
            self.set_valve(valve_id, False)
            if not any(self._watering_active.get(s, False) for s in self._watering_active if s != stage):
                 self.set_pump(False)
                 self.logger[0].error(f"Stage {stage}: Pump turned off due to error.")


        finally:
            # Mark watering as inactive for this stage
            self._watering_active[stage] = False
            self.logger[0].debug(f"Stage {stage}: Watering marked as inactive.")


    # Removed create_custom_schedule - might be added back later if needed
