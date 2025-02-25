import asyncio
import json
import os
import signal
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
            debug=self.debug
        )
        self.app = self._create_web_app()
        self.status_task = None

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

    def _setup_routes(self, app: web.Application) -> None:
        """Set up route handlers for the application."""
        routes = [
            ('GET', '/', self.home),
            ('POST', '/camera/{camera_id}/take/picture', self.take_picture),
            ('POST', '/water/sequence', self.watering_sequence),
            ('POST', '/static_light/{light_id}/toggle', self.toggle_static_light),
            ('POST', '/light/{light_id}/brightness', self.set_light_brightness),
            ('GET', '/camera/{camera_id}', self.get_camera_image),
        ]
        
        for method, path, handler in routes:
            if method == 'GET':
                app.router.add_get(path, handler)
            elif method == 'POST':
                app.router.add_post(path, handler)

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

    # Route handlers

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

    async def watering_sequence(self, request: web.Request) -> web.Response:
        """Endpoint to trigger the watering sequence."""
        try:
            self.current_state = await self.controller.execute_watering_sequence(self.current_state)
            return render(request, self.current_state)
        except Exception as e:
            self.logger.error(f"Error in watering sequence: {str(e)}", exc_info=True)
            return web.Response(text=f"Error in watering sequence: {str(e)}", status=500)

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

    async def get_camera_image(self, request: web.Request) -> web.Response:
        """Endpoint to get an image from a specific camera."""
        camera_id = self._parse_camera_id(request)
        if camera_id is None:
            return web.Response(text="Invalid camera ID", status=400)
            
        if camera_id >= len(self.current_state.camera_endpoints):
            return web.Response(text="Camera not found", status=404)
        
        try:
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

    # Application lifecycle methods

    async def start(self) -> None:
        """Start the Hydro Control application."""
        try:
            self.logger.info('Starting Hydro Control System')
            self.logger.debug('Initializing database')
            await self.db.init_tables()
            
            # Start background status logging
            self.status_task = asyncio.create_task(self._log_status())
            
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
        STATUS_LOG_INTERVAL = 375  # seconds (6.25 minutes)
        
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
                pass
                
        # Close database connection
        await self.db.close()
        self.logger.info('Shutdown complete')


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
