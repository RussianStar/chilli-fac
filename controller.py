import asyncio
from state import SystemState
from db import DatabaseAdapter

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

        if id <= len(current_state.zeus):
            led_controller = current_state.zeus[id]

            current_state.light_states[id] = brightness
            led_controller.set_level(brightness)

            self._log_status_fire_and_forget(current_state)
            self._logger.info(f"Setting light #{id} brightness to {brightness}%")

        return current_state

    def set_light(self, current_state, id):
        if id <= len(current_state.static_lights):
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

    def calculate_total_watering_duration(self, current_state):
        schedule = current_state.wtrctrl.DEFAULT_SCHEDULE
        return sum(step for step in schedule if not isinstance(step, dict))

    async def execute_watering_sequence(self, current_state, progress_callback=None, schedule=None):
        """
        Execute the watering sequence with progress tracking through callback.
        
        Args:
            current_state: The state dictionary containing system state
            progress_callback: Async function to report progress updates
            schedule: Optional custom watering schedule, uses DEFAULT_SCHEDULE if None
        """
        self._logger.info("Starting watering sequence")
        
        if schedule is None:
            schedule = current_state.wtrctrl.DEFAULT_SCHEDULE
            self._logger.info("Using default schedule (top to bottom, 3min)")
        
        # Calculate total wait time for progress tracking
        total_wait_time = sum(step for step in schedule if not isinstance(step, dict))
        elapsed_wait_time = 0
        
        # Track active zone
        current_zone = None
        
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
