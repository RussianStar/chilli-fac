import asyncio
import asyncio
from state import SystemState
from db import DatabaseAdapter
import statistics # For calculating average humidity

class Controller:

    def __init__(self, db: DatabaseAdapter, config,logger,debug = False) -> None:
        self._logger = logger
        self._db = db
        self._debug = debug
        self._config = config

    async def _log_status_async(self, current_state):
        await self._db.log_status_without_images(current_state)

    def _log_status_fire_and_forget(self, current_state):
        asyncio.create_task(self._log_status_async(current_state))

    def set_brightness(self, current_state: SystemState, id, brightness):

        if id in current_state.zeus:
            led_controller = current_state.zeus[id]

            current_state.light_states[id] = brightness
            led_controller.set_level(brightness)

            self._log_status_fire_and_forget(current_state)
            self._logger.info(f"Setting light #{id} brightness to {brightness}%")

        return current_state

    def set_light(self, current_state, id):
        if id in current_state.static_lights:
            light_controller = current_state.static_lights[id]
            
            if light_controller.is_on():
                light_controller.turn_off()
                current_state.static_light_states[id] = False
            else:
                light_controller.turn_on()
                current_state.static_light_states[id] = True

            self._logger.info(f"Toggling static light #{id} to {current_state.static_light_states[id]}")


        self._log_status_fire_and_forget(current_state)
        return current_state
        
    def set_light_auto_mode(self, current_state, id, auto_mode, start_time=None, duration_hours=None, brightness=None):
        """
        Set auto mode for a light (static or Zeus)
        
        Args:
            current_state: The current system state
            id: The ID of the light to set auto mode for
            auto_mode: Boolean indicating whether to enable (True) or disable (False) auto mode
            start_time: Time to turn on the light in 24-hour format (HH:MM)
            duration_hours: Duration in hours to keep the light on
            brightness: Brightness level (0-100) for Zeus lights
        
        Returns:
            Updated system state
        """
        # Check if this is a static light
        if id in current_state.static_lights:
            light_controller = current_state.static_lights[id]
            
            if auto_mode:
                if start_time is None or duration_hours is None:
                    self._logger.error(f"Cannot enable auto mode for static light #{id}: missing start time or duration")
                    return current_state
                    
                light_controller.set_auto_mode(start_time, duration_hours)
                current_state.static_light_auto_states[id] = {
                    "enabled": True,
                    "start_time": start_time,
                    "duration_hours": duration_hours
                }
                self._logger.info(f"Enabled auto mode for static light #{id}: start at {start_time}, duration {duration_hours}h")
            else:
                light_controller.disable_auto_mode()
                current_state.static_light_auto_states[id] = {
                    "enabled": False,
                    "start_time": None,
                    "duration_hours": None
                }
                self._logger.info(f"Disabled auto mode for static light #{id}")
                
            self._log_status_fire_and_forget(current_state)
            
        # Check if this is a Zeus light
        elif id in current_state.zeus:
            light_controller = current_state.zeus[id]
            
            if auto_mode:
                if start_time is None or duration_hours is None:
                    self._logger.error(f"Cannot enable auto mode for Zeus light #{id}: missing start time or duration")
                    return current_state
                
                # Default brightness to 100% if not specified
                if brightness is None:
                    brightness = 100
                
                light_controller.set_auto_mode(start_time, duration_hours, brightness)
                current_state.zeus_auto_states[id] = {
                    "enabled": True,
                    "start_time": start_time,
                    "duration_hours": duration_hours,
                    "brightness": brightness
                }
                self._logger.info(f"Enabled auto mode for Zeus light #{id}: start at {start_time}, duration {duration_hours}h, brightness {brightness}%")
            else:
                light_controller.disable_auto_mode()
                current_state.zeus_auto_states[id] = {
                    "enabled": False,
                    "start_time": None,
                    "duration_hours": None,
                    "brightness": None
                }
                self._logger.info(f"Disabled auto mode for Zeus light #{id}")
                
            self._log_status_fire_and_forget(current_state)
            
        return current_state
        
    def get_light_auto_settings(self, current_state, id):
        """
        Get auto mode settings for a light (static or Zeus)
        
        Args:
            current_state: The current system state
            id: The ID of the light to get auto mode settings for
            
        Returns:
            Dictionary with auto mode settings
        """
        # Check if this is a static light
        if id in current_state.static_lights:
            light_controller = current_state.static_lights[id]
            return light_controller.get_auto_settings()
        
        # Check if this is a Zeus light
        elif id in current_state.zeus:
            light_controller = current_state.zeus[id]
            return light_controller.get_auto_settings()
            
        return None
        
    def set_watering_auto_mode(self, current_state, auto_mode, start_time=None):
        """
        Set auto mode for watering
        
        Args:
            current_state: The current system state
            auto_mode: Boolean indicating whether to enable (True) or disable (False) auto mode
            start_time: Time to execute watering in 24-hour format (HH:MM)
        
        Returns:
            Updated system state
        """
        watering_controller = current_state.wtrctrl
        
        if auto_mode:
            if start_time is None:
                self._logger.error("Cannot enable auto mode for watering: missing start time")
                return current_state
                
            watering_controller.set_auto_mode(start_time)
            current_state.watering_auto_state = {
                "enabled": True,
                "start_time": start_time
            }
            self._logger.info(f"Enabled auto mode for watering: start at {start_time}")
        else:
            watering_controller.disable_auto_mode()
            current_state.watering_auto_state = {
                "enabled": False,
                "start_time": None
            }
            self._logger.info("Disabled auto mode for watering")
            
        self._log_status_fire_and_forget(current_state)
        return current_state
        
    def get_watering_auto_settings(self, current_state):
        """
        Get auto mode settings for watering
        
        Args:
            current_state: The current system state
            
        Returns:
            Dictionary with auto mode settings
        """
        watering_controller = current_state.wtrctrl
        settings = watering_controller.get_auto_settings()
        settings['durations'] = current_state.watering_durations
        return settings
        
    def set_watering_durations(self, current_state, durations):
        """
        Set durations for each watering zone
        
        Args:
            current_state: The current system state
            durations: Dictionary mapping valve IDs to durations in seconds
        
        Returns:
            Updated system state
        """
        # Update the durations in the state
        for valve_id, duration in durations.items():
            if valve_id in current_state.watering_durations:
                current_state.watering_durations[valve_id] = duration
                
        self._logger.info(f"Updated watering durations: {current_state.watering_durations}")
        self._log_status_fire_and_forget(current_state)
        return current_state

    def calculate_total_watering_duration(self, current_state):
        schedule = current_state.wtrctrl.DEFAULT_SCHEDULE
        return sum(step for step in schedule if not isinstance(step, dict))

    # --- Fan Control Methods ---

    def set_fan_target_humidity(self, current_state: SystemState, target: float):
        """Sets the target humidity for the fan controller."""
        if hasattr(current_state, 'fanctrl') and current_state.fanctrl:
            current_state.fanctrl.set_target_humidity(target)
            current_state.fan_state = current_state.fanctrl.get_status() # Update state
            self._logger.info(f"Controller set fan target humidity to {target}%.")
            self._log_status_fire_and_forget(current_state) # Log state change
        else:
            self._logger.error("Fan controller not available in state.")
        return current_state

    def set_fan_control_active(self, current_state: SystemState, active: bool):
        """Activates or deactivates automatic fan control."""
        if hasattr(current_state, 'fanctrl') and current_state.fanctrl:
            if active:
                current_state.fanctrl.activate_control()
                self._logger.info("Controller activated automatic fan control.")
            else:
                current_state.fanctrl.deactivate_control()
                self._logger.info("Controller deactivated automatic fan control.")
            current_state.fan_state = current_state.fanctrl.get_status() # Update state
            self._log_status_fire_and_forget(current_state) # Log state change
        else:
            self._logger.error("Fan controller not available in state.")
        return current_state

    def set_fan_manual(self, current_state: SystemState, turn_on: bool):
        """Manually turns the fan on or off, disabling auto control."""
        if hasattr(current_state, 'fanctrl') and current_state.fanctrl:
            # Deactivate auto control when manual control is used
            if current_state.fanctrl.is_control_active():
                current_state.fanctrl.deactivate_control()
                self._logger.info("Deactivated auto control due to manual fan operation.")

            if turn_on:
                current_state.fanctrl.turn_on()
                self._logger.info("Controller manually turned fan ON.")
            else:
                current_state.fanctrl.turn_off()
                self._logger.info("Controller manually turned fan OFF.")
            current_state.fan_state = current_state.fanctrl.get_status() # Update state
            self._log_status_fire_and_forget(current_state) # Log state change
        else:
            self._logger.error("Fan controller not available in state.")
        return current_state

    def check_and_control_humidity(self, current_state: SystemState):
        """
        Calculates average humidity and triggers fan control check.
        Intended to be called periodically.
        """
        if not hasattr(current_state, 'fanctrl') or not current_state.fanctrl:
            # self._logger.debug("Fan controller not available, skipping humidity check.") # Can be noisy
            return current_state

        if not current_state.fanctrl.is_control_active():
             # self._logger.debug("Fan auto control not active, skipping humidity check.") # Can be noisy
             return current_state # No need to check if auto control is off

        # Calculate average humidity from the latest reading of each sensor
        latest_readings = []
        if hasattr(current_state, 'humidity_readings') and current_state.humidity_readings:
            for sensor_id, readings in current_state.humidity_readings.items():
                if readings: # Check if list is not empty
                    # Get the last reading's humidity value
                    latest_reading = readings[-1].get('humidity')
                    if latest_reading is not None:
                        try:
                            latest_readings.append(float(latest_reading))
                        except (ValueError, TypeError):
                             self._logger.warning(f"Invalid humidity value '{latest_reading}' for sensor {sensor_id}")

        average_humidity = None
        if latest_readings:
            try:
                average_humidity = statistics.mean(latest_readings)
                self._logger.debug(f"Calculated average humidity: {average_humidity:.2f}% from {len(latest_readings)} sensors.")
            except statistics.StatisticsError:
                 self._logger.error("Error calculating mean humidity.")
            except Exception as e:
                 self._logger.error(f"Unexpected error calculating average humidity: {e}")
        else:
            self._logger.warning("No recent humidity readings available to calculate average.")
            # Optionally: Decide on behavior - turn fan off? Maintain last state?
            # For now, we'll just not call the control check if no average is available.
            return current_state # Exit if no average could be calculated

        # Call the fan controller's internal check method with the calculated average
        current_state.fanctrl._check_humidity_and_control(average_humidity)

        # Update the state representation after the check
        current_state.fan_state = current_state.fanctrl.get_status()

        return current_state


    # --- Watering Methods ---

    def check_and_execute_watering(self, current_state: SystemState):
        """
        Check watering triggers and execute watering if needed
        
        Args:
            current_state: Current system state
            
        Returns:
            Updated system state
        """
        for stage, should_water in current_state.watering_triggers.items():
            if should_water:
                # Set custom 300s duration for this stage
                durations = {stage: 300}
                current_state = self.set_watering_durations(current_state, durations)
                
                # Execute watering sequence
                current_state = self.execute_watering_sequence(current_state)
                
                # Reset trigger
                current_state.watering_triggers[stage] = False
                self._logger.info(f"Executed watering for stage {stage} based on sensor trigger")
                
        return current_state

    async def execute_watering_sequence(self, current_state, progress_callback=None, schedule=None):
        """
        Execute the watering sequence with progress tracking through callback.
        
        Args:
            current_state: The state dictionary containing system state
            progress_callback: Async function to report progress updates
            schedule: Optional custom watering schedule, uses custom durations if None
        """
        self._logger.info("Starting watering sequence")
        
        if schedule is None:
            # Create a custom schedule based on the configured durations
            schedule = current_state.wtrctrl.create_custom_schedule(current_state.watering_durations)
            self._logger.info(f"Using custom schedule with durations: {current_state.watering_durations}")
        
        # Calculate total wait time for progress tracking
        total_wait_time = sum(step for step in schedule if not isinstance(step, dict))
        elapsed_wait_time = 0
        
        # Track active zone
        current_zone = None

        # Setting initial state
        for id in range(1, current_state.wtrctrl.num_valves + 1):
            current_state.wtrctrl.set_valve(id, False)
        await asyncio.sleep(1)
        
        try:
            # Update status to in_progress
            if progress_callback:
                await progress_callback(0, None, "in_progress")
            
            for step in schedule:
                if isinstance(step, dict):
                    # This is a control step (valve/pump operation)
                    for device, (id, state) in step.items():
                        if 'valve' in device:
                            # If turning on a valve, track as the current zone
                            if state:
                                current_zone = f"zone_{id}"
                                if progress_callback:
                                    await progress_callback(
                                        int(elapsed_wait_time * 100 / total_wait_time), 
                                        current_zone, 
                                        "zone_active"
                                    )
                            # If turning off a valve that was active, mark as complete
                            elif current_zone == f"zone_{id}" and not state:
                                if progress_callback:
                                    await progress_callback(
                                        int(elapsed_wait_time * 100 / total_wait_time), 
                                        current_zone, 
                                        "zone_completed"
                                    )
                                current_zone = None
                                
                            current_state.valve_states[id] = current_state.wtrctrl.set_valve(id, state)
                        elif device == 'pump':
                            current_state.pump_states[1] = current_state.wtrctrl.set_pump(state)
                            self._logger.info(f"Setting actor [{device}] to [{state}]")
                else:
                    # This is a wait step
                    self._logger.info(f"Waiting for {step}s. Progress: {elapsed_wait_time}/{total_wait_time}")
                    
                    # Update in smaller increments for smoother progress reporting
                    chunk_size = 1  # Update every second
                    for _ in range(step):
                        await asyncio.sleep(chunk_size)
                        elapsed_wait_time += chunk_size
                        
                        # Report progress
                        progress_percent = int(elapsed_wait_time * 100 / total_wait_time)
                        if progress_callback:
                            await progress_callback(
                                progress_percent,
                                current_zone,
                                "in_progress"
                            )
            
            # Mark sequence as completed
            if progress_callback:
                await progress_callback(100, None, "completed")
                
            return current_state

        except asyncio.CancelledError:
            self._logger.info("Watering sequence was cancelled")
            # Report cancellation through callback
            if progress_callback:
                await progress_callback(
                    int(elapsed_wait_time * 100 / total_wait_time), 
                    current_zone, 
                    "cancelled"
                )
            raise  # Re-raise to properly handle cancellation
            
        except Exception as e:
            self._logger.error(f"Error during watering sequence: {str(e)}", exc_info=True)
            # Report error through callback
            if progress_callback:
                await progress_callback(
                    int(elapsed_wait_time * 100 / total_wait_time), 
                    current_zone, 
                    "error"
                )
            raise

        finally:
            for id in range(1, current_state.wtrctrl.num_valves + 1):
                current_state.wtrctrl.set_valve(id, False)
            current_state.wtrctrl.set_pump(False)
            current_state.wtrctrl.logger[0].info("All valves and pump turned off")
