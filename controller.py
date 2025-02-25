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

    async def water_level(self, current_state, level, schedule =None ):
        wtrctrl = current_state.wtrctrl
        self._log_status_fire_and_forget(current_state)

        self._logger.info("Starting watering")
        if level not in range(1, wtrctrl.num_valves + 1):
            raise ValueError(f"Invalid level number. Must be 1-{wtrctrl.num_valves}")

        if schedule is None:
            schedule = wtrctrl.DEFAULT_SCHEDULE
            self._logger.info("Using default schedule(top to bottom, 3min)")
            pass

        try:
            for step in schedule:
                if isinstance(step, dict):
                    for device, (id, state) in step.items():
                        if 'valve' in device:
                            wtrctrl.set_valve(id, state)
                        elif device == 'pump':
                            wtrctrl.set_pump(state)
                        self._logger.info(f"Setting actor [{device}] to [{state}]")
                    wtrctrl._log_status_fire_and_forget(current_state)
                else:
                    self._logger.info(f"Waiting for {step}s.")
                    await asyncio.sleep(step)

            return current_state

        finally:
            wtrctrl.set_valve(level, False)
            wtrctrl.set_pump(False)
