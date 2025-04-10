import asyncio
import json
import os
import signal
from datetime import datetime, timedelta
import sys
from typing import Any, Dict, Optional 

import aiohttp
import aiohttp_cors
import aiohttp_jinja2
import jinja2
from aiohttp import web

from camera import get_camera_bytes
from controller import Controller
from db import DatabaseAdapter
from helper import is_raspberry_pi, render
from logger import setup_logging
from state import SystemState

class HydroControlApp:
    """Main application for the Hydro Control System."""
    
    CONFIG_FILE = 'config.json'
    TEMPLATE_DIR = 'templates'
    SERVER_PORT = 5000
    
    def __init__(self):
        """Initialize the Hydro Control application."""
        self.config = self._load_config()
        self.logger = setup_logging()
        self.db = DatabaseAdapter(self.logger, self.config)
        self.debug = not is_raspberry_pi()
        self.current_state = SystemState(self.logger, self.config, self.debug)
        self.controller = Controller(
            db=self.db,
            logger=self.logger,
            config=self.config,
            debug=self.debug,
            status_update_callback=self._trigger_mqtt_status_update # Pass the trigger method
        )
        self.app = self._create_web_app()
        self.status_task = None
        self.humidity_check_task = None # Add task for humidity check
        self.mqtt_status_task = None # Add task for periodic MQTT status
        
        # Initialize MQTT client if configured
        # Initialize MQTT client if configured
        self.mqtt_client = None # Initialize as None
        if 'mqtt' in self.config:
            try:
                from mqtt_client import MQTTClient
                self.mqtt_client = MQTTClient(self.current_state, self.config)
                if not self.mqtt_client.connect():
                    self.logger.error("MQTT Client failed to connect during initialization.")
                    self.mqtt_client = None # Set back to None if connection failed
                else:
                    self.logger.info("MQTT Client connected successfully.")
            except ImportError:
                self.logger.error("mqtt_client.py not found or paho-mqtt not installed. MQTT features disabled.")
            except Exception as e:
                self.logger.error(f"Failed to initialize MQTT client: {e}", exc_info=True)

    def _trigger_mqtt_status_update(self):
        """Safely triggers the MQTT status update if the client is available."""
        if self.mqtt_client:
            try:
                # Run in a separate task to avoid blocking the caller
                asyncio.create_task(self._publish_mqtt_status_async())
            except Exception as e:
                self.logger.error(f"Error scheduling MQTT status update: {e}", exc_info=True)
        else:
            self.logger.debug("MQTT client not available, skipping status update trigger.")

    async def _publish_mqtt_status_async(self):
        """Asynchronously publish status to prevent blocking."""
        if self.mqtt_client:
            # Add a small delay to allow state changes to settle if needed
            # await asyncio.sleep(0.1)
            self.mqtt_client.publish_status()

    @classmethod
    def _load_config(cls) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        with open(cls.CONFIG_FILE) as f:
            return json.load(f)

    def _create_web_app(self) -> web.Application:
        """Set up and configure the web application."""
        app = web.Application()
        
        # Configure templating engine
        aiohttp_jinja2.setup(
            app,
            loader=jinja2.FileSystemLoader(os.path.join(os.getcwd(), self.TEMPLATE_DIR))
        )

        # Add routes and CORS
        self._setup_routes(app)
        self._setup_cors(app)
        
        return app


    def _setup_cors(self, app: web.Application) -> None:
        """Configure Cross-Origin Resource Sharing for the application."""
        cors = aiohttp_cors.setup(app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
            )
        })
        
        # Apply CORS to all routes
        for route in list(app.router.routes()):
            cors.add(route)

    def _setup_routes(self, app: web.Application) -> None:
        """Set up route handlers for the application."""
        routes = [
            ('GET', '/', self.home),
            ('GET', '/camera/{camera_id}', self.get_camera_image),
            ('POST', '/camera/{camera_id}/take/picture', self.take_picture),
            ('POST', '/water/sequence', self.watering_sequence),
            ('GET', '/water/status', self.get_watering_status),  # Added missing route for status
            ('POST', '/water/cancel', self.cancel_watering),     # Added missing route for cancellation
            ('POST', '/water/auto', self.set_watering_auto_mode),  # New route for watering auto mode
            ('GET', '/water/auto', self.get_watering_auto_settings),  # New route for watering auto settings
            ('POST', '/water/durations', self.set_watering_durations),  # New route for watering durations
            ('POST', '/light/{light_id}/toggle', self.toggle_static_light),
            ('POST', '/light/{light_id}/brightness', self.set_light_brightness),
            ('POST', '/light/{light_id}/auto', self.set_light_auto_mode),
            ('GET', '/light/{light_id}/auto', self.get_light_auto_settings),
            ('POST', '/sensor/config', self.set_sensor_config),
            ('POST', '/sensor/toggle', self.toggle_sensor_active),
            # --- Fan Control Routes ---
            ('GET', '/api/fan/status', self.get_fan_status),
            ('POST', '/api/fan/target', self.set_fan_target),
            ('POST', '/api/fan/control', self.set_fan_control),
            ('POST', '/api/fan/manual', self.set_fan_manual),
        ]
        
        for method, path, handler in routes:
            if method == 'GET':
                app.router.add_get(path, handler)
            elif method == 'POST':
                app.router.add_post(path, handler)

    async def watering_sequence(self, request: web.Request) -> web.Response:
        """Endpoint to trigger the watering sequence with progress tracking."""
        try:
            # Check if a watering sequence is already running
            if hasattr(self.current_state, 'watering_task') and not hasattr(self.current_state.watering_task, 'done' ):
                return web.json_response({
                    'status': 'error',
                    'message': 'A watering sequence is already in progress'
                }, status=409)  # Conflict
                
            # Initialize watering state with progress tracking
            self.current_state.watering_state = {
                'status': 'starting',
                'progress_percent': 0,
                'current_zone': None,
                'zones_completed': 0,
                'total_zones': self.current_state.wtrctrl.num_valves,
                'started_at': datetime.now().isoformat(),
                'estimated_completion': None
            }
            
            # Create a progress tracking callback that updates the watering_state
            async def progress_tracker(progress: int, zone: int = None, status: str = None):
                if not hasattr(self.current_state, 'watering_state'):
                    return
                    
                self.current_state.watering_state['progress_percent'] = progress
                
                if zone is not None:
                    self.current_state.watering_state['current_zone'] = f"Zone {zone}"
                
                if status is not None:
                    self.current_state.watering_state['status'] = status
                    
                    if status == 'zone_completed' and 'zones_completed' in self.current_state.watering_state:
                        self.current_state.watering_state['zones_completed'] += 1
                    
                    if status == 'in_progress' and progress == 0:
                        # Calculate and set estimated completion time
                        total_duration = self.controller.calculate_total_watering_duration(self.current_state)
                        completion_time = datetime.now() + timedelta(seconds=total_duration)
                        self.current_state.watering_state['estimated_completion'] = completion_time.isoformat()
                        
                    if status == 'completed':
                        self.current_state.watering_state['completed_at'] = datetime.now().isoformat()
                        
                    if status == 'error':
                        self.current_state.watering_state['error_at'] = datetime.now().isoformat()
            
            # Execute watering sequence asynchronously to not block the response
            task = asyncio.create_task(self.controller.execute_watering_sequence(
                self.current_state,
                progress_callback=progress_tracker
            ))
            
            # Set up task completion callback to update status when done
            def on_task_done(task):
                try:
                    task.result()  # This will raise exception if task failed
                    if hasattr(self.current_state, 'watering_state'):
                        self.current_state.watering_state['status'] = 'completed'
                        self.current_state.watering_state['completed_at'] = datetime.now().isoformat()
                except asyncio.CancelledError:
                    if hasattr(self.current_state, 'watering_state'):
                        self.current_state.watering_state['status'] = 'cancelled'
                except Exception as e:
                    self.logger.error(f"Watering sequence failed: {str(e)}", exc_info=True)
                    if hasattr(self.current_state, 'watering_state'):
                        self.current_state.watering_state['status'] = 'error'
                        self.current_state.watering_state['error_message'] = str(e)
                        self.current_state.watering_state['error_at'] = datetime.now().isoformat()
            
            task.add_done_callback(on_task_done)  # Add completion callback
            
            # Store the task for status checks or cancellation
            self.current_state.watering_task = task
            
            return web.json_response({
                'status': 'watering_sequence_started',
                'message': 'Watering sequence has been initiated',
                'watering_state': self.current_state.watering_state
            })
        
        except Exception as e:
            # Update state to reflect error
            self.current_state.watering_state = {
                'status': 'error',
                'error_message': str(e),
                'timestamp': datetime.now().isoformat()
            }
            
            self.logger.error(f"Error initiating watering sequence: {str(e)}", exc_info=True)
            return web.json_response({
                'status': 'error',
                'message': f"Failed to start watering sequence: {str(e)}"
            }, status=500)

    async def get_watering_status(self, request: web.Request) -> web.Response:
        """Endpoint to check the current status of an ongoing watering sequence."""
        if not hasattr(self.current_state, 'watering_state'):
            return web.json_response({
                'status': 'no_watering',
                'message': 'No watering sequence is currently active'
            })
        
        # Check if the task has completed but status wasn't updated
        if hasattr(self.current_state, 'watering_task'):
            if self.current_state.watering_task.done():
                try:
                    self.current_state.watering_task.result()  # Will raise if there was an exception
                    if self.current_state.watering_state['status'] not in ['completed', 'cancelled', 'error']:
                        self.current_state.watering_state['status'] = 'completed'
                        self.current_state.watering_state['completed_at'] = datetime.now().isoformat()
                except asyncio.CancelledError:
                    self.current_state.watering_state['status'] = 'cancelled'
                except Exception as e:
                    self.current_state.watering_state['status'] = 'error'
                    self.current_state.watering_state['error_message'] = str(e)
        
        # Return the current watering state with real-time progress
        return web.json_response({
            'watering_state': self.current_state.watering_state
        })

    async def cancel_watering(self, request: web.Request) -> web.Response:
        """Endpoint to cancel an ongoing watering sequence."""
        if not hasattr(self.current_state, 'watering_task') or self.current_state.watering_task.done():
            return web.json_response({
                'status': 'no_watering',
                'message': 'No watering sequence is currently active'
            })
        
        try:
            # Cancel the watering task
            self.current_state.watering_task.cancel()
            
            # Update watering state
            if hasattr(self.current_state, 'watering_state'):
                self.current_state.watering_state['status'] = 'cancelled'
                self.current_state.watering_state['cancelled_at'] = datetime.now().isoformat()
            
            # Ensure all valves are closed
            self.current_state.wtrctrl.close_all_valves()
            
            return web.json_response({
                'status': 'cancelled',
                'message': 'Watering sequence has been cancelled',
                'watering_state': self.current_state.watering_state if hasattr(self.current_state, 'watering_state') else None
            })
        
        except Exception as e:
            self.logger.error(f"Error cancelling watering sequence: {str(e)}", exc_info=True)
            return web.json_response({
                'status': 'error',
                'message': f"Failed to cancel watering sequence: {str(e)}"
            }, status=500)

    async def toggle_static_light(self, request: web.Request) -> web.Response:
        """Endpoint to toggle a static light on/off."""
        light_id = self._parse_light_id(request)
        if light_id is None:
            return web.Response(text="Invalid light ID", status=400)
            
        try:
            self.current_state = self.controller.set_light(self.current_state, light_id)
            return render(request, self.current_state)
        except Exception as e:
            self.logger.error(f"Error toggling light {light_id}: {str(e)}", exc_info=True)
            return web.Response(text=f"Error toggling light: {str(e)}", status=500)

    async def set_light_brightness(self, request: web.Request) -> web.Response:
        """Endpoint to set the brightness of a light."""
        light_id = self._parse_light_id(request)
        if light_id is None:
            return web.Response(text="Invalid light ID", status=400)
            
        brightness = await self._parse_brightness(request)
        if brightness is None:
            return web.Response(text="Invalid brightness value", status=400)
                
        try:
            self.current_state = self.controller.set_brightness(
                self.current_state, light_id, brightness
            )
            return render(request, self.current_state)
        except Exception as e:
            self.logger.error(f"Error setting brightness for light {light_id}: {str(e)}", exc_info=True)
            return web.Response(text=f"Error setting brightness: {str(e)}", status=500)
            
    async def set_light_auto_mode(self, request: web.Request) -> web.Response:
        """Endpoint to set auto mode for a light (static or Zeus)."""
        light_id = self._parse_light_id(request)
        if light_id is None:
            return web.Response(text="Invalid light ID", status=400)
            
        try:
            form = await request.post()
            auto_mode = form.get('auto_mode', 'false').lower() == 'true'
            
            if auto_mode:
                start_time = form.get('start_time')
                if not start_time or not self._is_valid_time_format(start_time):
                    return web.Response(text="Invalid start time format. Use HH:MM in 24-hour format.", status=400)
                    
                try:
                    duration_hours = int(form.get('duration_hours', '0'))
                    if duration_hours <= 0 or duration_hours > 24:
                        return web.Response(text="Duration must be between 1 and 24 hours.", status=400)
                except (ValueError, TypeError):
                    return web.Response(text="Invalid duration format. Must be a number between 1 and 24.", status=400)
                
                # Check if this is a Zeus light (has brightness parameter)
                brightness = None
                if light_id in self.current_state.zeus:
                    try:
                        brightness_str = form.get('brightness')
                        if brightness_str:
                            brightness = int(brightness_str)
                            if brightness < 0 or brightness > 100:
                                return web.Response(text="Brightness must be between 0 and 100.", status=400)
                    except (ValueError, TypeError):
                        return web.Response(text="Invalid brightness format. Must be a number between 0 and 100.", status=400)
                    
                print(light_id)
                self.current_state = self.controller.set_light_auto_mode(
                    self.current_state, light_id, True, start_time, duration_hours, brightness
                )
            else:
                # Disable auto mode
                self.current_state = self.controller.set_light_auto_mode(
                    self.current_state, light_id, False
                )
                
            # Return the rendered HTML page
            return render(request, self.current_state)
                
        except Exception as e:
            self.logger.error(f"Error setting auto mode for light {light_id}: {str(e)}", exc_info=True)
            return web.Response(text=f"Error setting auto mode: {str(e)}", status=500)
            
    async def get_light_auto_settings(self, request: web.Request) -> web.Response:
        """Endpoint to get auto mode settings for a static light."""
        light_id = self._parse_light_id(request)
        if light_id is None:
            return web.Response(text="Invalid light ID", status=400)
            
        try:
            settings = self.controller.get_light_auto_settings(self.current_state, light_id)
            
            if settings is None:
                return web.json_response({
                    'status': 'error',
                    'message': f'Light #{light_id} not found'
                }, status=404)
                
            return web.json_response({
                'status': 'success',
                'settings': settings
            })
            
        except Exception as e:
            self.logger.error(f"Error getting auto settings for light {light_id}: {str(e)}", exc_info=True)
            return web.json_response({
                'status': 'error',
                'message': f"Error getting auto settings: {str(e)}"
            }, status=500)
            
    async def set_watering_auto_mode(self, request: web.Request) -> web.Response:
        """Endpoint to set auto mode for watering."""
        try:
            form = await request.post()
            auto_mode = form.get('auto_mode', 'false').lower() == 'true'
            
            if auto_mode:
                start_time = form.get('start_time')
                if not start_time or not self._is_valid_time_format(start_time):
                    return web.Response(text="Invalid start time format. Use HH:MM in 24-hour format.", status=400)
                
                self.current_state = self.controller.set_watering_auto_mode(
                    self.current_state, True, start_time
                )
            else:
                # Disable auto mode
                self.current_state = self.controller.set_watering_auto_mode(
                    self.current_state, False
                )
                
            # Return the rendered HTML page
            return render(request, self.current_state)
                
        except Exception as e:
            self.logger.error(f"Error setting auto mode for watering: {str(e)}", exc_info=True)
            return web.Response(text=f"Error setting auto mode: {str(e)}", status=500)
            
    async def get_watering_auto_settings(self, request: web.Request) -> web.Response:
        """Endpoint to get auto mode settings for watering."""
        try:
            settings = self.controller.get_watering_auto_settings(self.current_state)
            
            return web.json_response({
                'status': 'success',
                'settings': settings
            })
            
        except Exception as e:
            self.logger.error(f"Error getting auto settings for watering: {str(e)}", exc_info=True)
            return web.json_response({
                'status': 'error',
                'message': f"Error getting auto settings: {str(e)}"
            }, status=500)
            
    async def get_camera_image(self, request: web.Request) -> web.Response:
        """Endpoint to get an image from a specific camera."""
        camera_id = self._parse_camera_id(request)
        if camera_id is None:
            return web.Response(text="Invalid camera ID", status=400)
            
        if camera_id >= len(self.current_state.camera_endpoints):
            return web.Response(text="Camera not found", status=404)
        
        try:
            print(f"Getting image for {self.current_state.camera_endpoints[camera_id]}");
            result = await get_camera_bytes(self.current_state.camera_endpoints[camera_id])
            
            if result is None:
                return web.Response(text="Error loading camera image", status=500)
                
            image_bytes = result[0] if isinstance(result, tuple) else result
            
            if image_bytes is None:
                return web.Response(text="Error loading camera image", status=500)
                
            return web.Response(body=image_bytes, content_type='image/jpeg')
        except Exception as e:
            self.logger.error(f"Error getting camera image: {str(e)}", exc_info=True)
            return web.Response(text=f"Error loading camera image: {str(e)}", status=500)

    async def home(self, request: web.Request) -> web.Response:
        """Render the home page with current system state."""
        return render(request, self.current_state)

    async def take_picture(self, request: web.Request) -> web.Response:
        """Endpoint to trigger taking a picture from a specific camera."""
        camera_id = self._parse_camera_id(request)
        if camera_id is None:
            return web.Response(text="Invalid camera ID", status=400)
            
        if camera_id >= len(self.current_state.camera_endpoints):
            return web.Response(text="Camera not found", status=404)
            
        try:
            async with aiohttp.ClientSession() as session:
                camera_url = f"{self.current_state.camera_endpoints[camera_id]}/take/picture"
                async with session.get(camera_url) as response:
                    if response.status == 200:
                        return web.Response(text="Picture taken successfully")
                    return web.Response(text=f"Failed to take picture: {response.status}", status=500)
        except Exception as e:
            self.logger.error(f"Error taking picture: {str(e)}", exc_info=True)
            return web.Response(text=f"Error taking picture: {str(e)}", status=500)

    async def set_sensor_config(self, request: web.Request) -> web.Response:
        """Endpoint to configure sensor parameters."""
        try:
            form = await request.post()
            form = await request.post()
            sensor_id = form.get('sensor_id')
            if not sensor_id:
                return web.Response(text="Sensor ID is required", status=400)

            try:
                stage = int(form.get('stage'))
                min_moisture = float(form.get('min_moisture'))
                # Get calibration values, providing defaults if missing or invalid
                min_adc_str = form.get('min_adc', '0')
                max_adc_str = form.get('max_adc', '4095')
                min_adc = int(min_adc_str) if min_adc_str.isdigit() else 0
                max_adc = int(max_adc_str) if max_adc_str.isdigit() else 4095

                if stage not in [1, 2, 3] or min_moisture < 0 or min_adc < 0 or max_adc <= min_adc:
                    raise ValueError("Invalid sensor configuration values.")

            except (ValueError, TypeError) as e:
                 self.logger.warning(f"Invalid sensor configuration data received: {e}")
                 return web.Response(text=f"Invalid sensor configuration data: {e}", status=400)

            # Update sensor config in state, preserving existing 'active' state if updating
            existing_config = self.current_state.sensor_configs.get(sensor_id, {})
            self.current_state.sensor_configs[sensor_id] = {
                'stage': stage,
                'min_moisture': min_moisture,
                'min_adc': min_adc,
                'max_adc': max_adc,
                'active': existing_config.get('active', True) # Keep existing active state or default to True
            }
            self.logger.info(f"Updated sensor config for {sensor_id}: {self.current_state.sensor_configs[sensor_id]}")

            # Return to main page
            return render(request, self.current_state)
            
        except Exception as e:
            self.logger.error(f"Error setting sensor config: {str(e)}", exc_info=True)
            return web.Response(text=f"Error setting sensor config: {str(e)}", status=500)
            
    async def toggle_sensor_active(self, request: web.Request) -> web.Response:
        """Endpoint to toggle sensor active state."""
        try:
            form = await request.post()
            sensor_id = form.get('sensor_id')
            
            if not sensor_id or sensor_id not in self.current_state.sensor_configs:
                return web.Response(text="Invalid sensor ID", status=400)
                
            # Toggle active state
            current_active = self.current_state.sensor_configs[sensor_id].get('active', True)
            self.current_state.sensor_configs[sensor_id]['active'] = not current_active
            
            # Return to main page
            return render(request, self.current_state)
            
        except Exception as e:
            self.logger.error(f"Error toggling sensor active state: {str(e)}", exc_info=True)
            return web.Response(text=f"Error toggling sensor active state: {str(e)}", status=500)

    # Helper methods for parameter parsing
    def _parse_camera_id(self, request: web.Request) -> Optional[int]:
        """Extract and validate camera ID from request."""
        try:
            return int(request.match_info['camera_id'])
        except (ValueError, KeyError):
            return None

    def _parse_light_id(self, request: web.Request) -> Optional[int]:
        """Extract and validate light ID from request."""
        try:
            return int(request.match_info['light_id'])
        except (ValueError, KeyError):
            return None

    async def _parse_brightness(self, request: web.Request) -> Optional[int]:
        """Extract and validate brightness value from request."""
        if not request.can_read_body:
            return 0
            
        try:
            form = await request.post()
            return min(max(int(form.get('brightness', 0)), 0), 100)
        except (TypeError, ValueError):
            return None
            
    def _is_valid_time_format(self, time_str: str) -> bool:
        """Validate time string format (HH:MM in 24-hour format)."""
        try:
            # Check format
            if len(time_str) != 5 or time_str[2] != ':':
                return False
                
            # Parse hours and minutes
            hours, minutes = map(int, time_str.split(':'))
            
            # Validate ranges
            if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
                return False
                
            return True
        except (ValueError, IndexError):
            return False

    # --- Fan Control Handlers ---

    async def get_fan_status(self, request: web.Request) -> web.Response:
        """Endpoint to get the current status of the fan."""
        if hasattr(self.current_state, 'fan_state'):
            # Ensure the state is up-to-date before returning
            if hasattr(self.current_state, 'fanctrl') and self.current_state.fanctrl:
                 self.current_state.fan_state = self.current_state.fanctrl.get_status()
            return web.json_response({'status': 'success', 'fan_state': self.current_state.fan_state})
        else:
            return web.json_response({'status': 'error', 'message': 'Fan state not available'}, status=500)

    async def set_fan_target(self, request: web.Request) -> web.Response:
        """Endpoint to set the target humidity for the fan."""
        try:
            data = await request.json()
            target = float(data.get('target'))
            if not (40.0 <= target <= 90.0): # Validate range
                 return web.json_response({'status': 'error', 'message': 'Target humidity must be between 40 and 90'}, status=400)

            self.current_state = self.controller.set_fan_target_humidity(self.current_state, target)
            return web.json_response({'status': 'success', 'fan_state': self.current_state.fan_state})
        except (ValueError, TypeError, KeyError):
            return web.json_response({'status': 'error', 'message': 'Invalid target value provided. Expecting JSON: {"target": float}'}, status=400)
        except Exception as e:
            self.logger.error(f"Error setting fan target: {e}", exc_info=True)
            return web.json_response({'status': 'error', 'message': f'Internal server error: {e}'}, status=500)

    async def set_fan_control(self, request: web.Request) -> web.Response:
        """Endpoint to activate or deactivate automatic fan control."""
        try:
            data = await request.json()
            active = bool(data.get('active')) # bool(None) is False, bool(True) is True
            self.current_state = self.controller.set_fan_control_active(self.current_state, active)
            return web.json_response({'status': 'success', 'fan_state': self.current_state.fan_state})
        except (ValueError, TypeError, KeyError):
             return web.json_response({'status': 'error', 'message': 'Invalid active value provided. Expecting JSON: {"active": boolean}'}, status=400)
        except Exception as e:
            self.logger.error(f"Error setting fan control active state: {e}", exc_info=True)
            return web.json_response({'status': 'error', 'message': f'Internal server error: {e}'}, status=500)

    async def set_fan_manual(self, request: web.Request) -> web.Response:
        """Endpoint to manually turn the fan on or off."""
        try:
            data = await request.json()
            turn_on = bool(data.get('on'))
            self.current_state = self.controller.set_fan_manual(self.current_state, turn_on)
            return web.json_response({'status': 'success', 'fan_state': self.current_state.fan_state})
        except (ValueError, TypeError, KeyError):
             return web.json_response({'status': 'error', 'message': 'Invalid manual value provided. Expecting JSON: {"on": boolean}'}, status=400)
        except Exception as e:
            self.logger.error(f"Error setting fan manual state: {e}", exc_info=True)
            return web.json_response({'status': 'error', 'message': f'Internal server error: {e}'}, status=500)


    # Application lifecycle methods

    async def start(self) -> None:
        """Start the Hydro Control application."""
        try:
            self.logger.info('Starting Hydro Control System')
            self.logger.debug('Initializing database')
            await self.db.init_tables()

            # Start background tasks
            self.status_task = asyncio.create_task(self._log_status())
            self.humidity_check_task = asyncio.create_task(self._periodic_humidity_check()) # Start humidity check task
            # Start MQTT status task only if client initialized successfully
            if self.mqtt_client:
                self.mqtt_status_task = asyncio.create_task(self._periodic_mqtt_status())

            # Start web server
            runner = web.AppRunner(self.app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', self.SERVER_PORT)
            await site.start()
            
            self.logger.info(f'Web server running at http://0.0.0.0:{self.SERVER_PORT}')
            
            # Keep application running
            await asyncio.Event().wait()
            
        except Exception as e:
            self.logger.error(f'Fatal error: {str(e)}', exc_info=True)
        finally:
            await self._shutdown()

    async def _log_status(self) -> None:
        """Periodically log system status to the database."""
        STATUS_LOG_INTERVAL = self.config['LOGGING_INTERVAL']  # seconds (6.25 minutes)
        
        while True:
            try:
                # Log immediately then wait
                await self.db.log_status(self.current_state)
                await asyncio.sleep(STATUS_LOG_INTERVAL)
            except asyncio.CancelledError:
                self.logger.debug("Status logging task cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in status logging: {str(e)}", exc_info=True)
                await asyncio.sleep(10)  # Wait a bit before retrying

    async def _shutdown(self) -> None:
        """Clean up resources on application shutdown."""
        self.logger.info('Shutting down Hydro Control System')
        
        # Cancel status logging task
        if self.status_task:
            self.status_task.cancel()
            try:
                await self.status_task
            except asyncio.CancelledError:
                self.logger.debug("Status logging task already cancelled.")

        # Cancel humidity check task
        if self.humidity_check_task:
            self.humidity_check_task.cancel()
            try:
                await self.humidity_check_task
            except asyncio.CancelledError:
                self.logger.debug("Humidity check task already cancelled.")

        # Cancel MQTT status task
        if self.mqtt_status_task:
            self.mqtt_status_task.cancel()
            try:
                await self.mqtt_status_task
            except asyncio.CancelledError:
                self.logger.debug("MQTT status task already cancelled.")

        # Perform state cleanup (includes GPIO cleanup for all devices)
        if hasattr(self, 'current_state') and self.current_state:
             self.current_state.cleanup()
             self.logger.info("System state cleanup performed.")

        # Disconnect MQTT client if it exists
        if hasattr(self, 'mqtt_client') and self.mqtt_client:
            self.mqtt_client.disconnect()
            self.logger.info("MQTT client disconnected.")

        # Close database connection
        await self.db.close()
        self.logger.info('Shutdown complete')

    async def _periodic_humidity_check(self) -> None:
        """Periodically check humidity and trigger fan control."""
        HUMIDITY_CHECK_INTERVAL = 10 # seconds (5 minutes)
        self.logger.info(f"Starting periodic humidity check every {HUMIDITY_CHECK_INTERVAL} seconds.")
        while True:
            try:
                # Wait first, then check
                await asyncio.sleep(HUMIDITY_CHECK_INTERVAL)
                self.logger.debug("Running periodic humidity check...")
                self.current_state = self.controller.check_and_control_humidity(self.current_state)
            except asyncio.CancelledError:
                self.logger.info("Periodic humidity check task cancelled.")
                break
            except Exception as e:
                self.logger.error(f"Error in periodic humidity check: {str(e)}", exc_info=True)
                # Wait a bit longer before retrying after an error
                await asyncio.sleep(60)

    async def _periodic_mqtt_status(self) -> None:
        """Periodically publish system status via MQTT."""
        MQTT_STATUS_INTERVAL = 300 # seconds (5 minutes)
        self.logger.info(f"Starting periodic MQTT status publishing every {MQTT_STATUS_INTERVAL} seconds.")
        while True:
            try:
                # Wait first, then publish
                await asyncio.sleep(MQTT_STATUS_INTERVAL)
                if self.mqtt_client: # Ensure client still exists
                    self.logger.debug("Publishing periodic MQTT status...")
                    self.mqtt_client.publish_status()
                else:
                    self.logger.warning("MQTT client not available, skipping periodic status publish.")
                    # Optionally break the loop or wait longer if the client might reconnect
                    # break
            except asyncio.CancelledError:
                self.logger.info("Periodic MQTT status task cancelled.")
                break
            except Exception as e:
                self.logger.error(f"Error in periodic MQTT status publishing: {str(e)}", exc_info=True)
                # Wait a bit longer before retrying after an error
                await asyncio.sleep(60)


def main() -> None:
    """Application entry point."""
    app = HydroControlApp()
    
    # Set up signal handlers
    def handle_shutdown(signum, frame):
        app.logger.info(f"Received signal {signal.Signals(signum).name}")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    try:
        asyncio.run(app.start())
    except KeyboardInterrupt:
        app.logger.info('Received keyboard interrupt, shutting down...')

if __name__ == "__main__":
    main()
