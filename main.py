from aiohttp import web
import aiohttp_cors
import jinja2
import os
from aiohttp import web
import asyncio
import json
from  helper  import is_raspberry_pi, render
from controller import Controller
from logger import setup_logging
from db import DatabaseAdapter
from state import SystemState
from camera import get_camera_bytes
import asyncio
import aiohttp
from aiohttp import web
import aiohttp_jinja2
import jinja2
import os

# Global state
global current_state, db

# Load config
with open('config.json') as f:
    config = json.load(f)

# Setup
app = web.Application() 
logger = setup_logging()
db = DatabaseAdapter(logger, config)

debug = not is_raspberry_pi()
current_state = SystemState(logger, config, debug)
ctrl = Controller(db=db, logger=logger, config=config, debug=debug)

# Configure templating
aiohttp_jinja2.setup(app,
    loader=jinja2.FileSystemLoader(os.path.join(os.getcwd(), 'templates')))

# Route handlers
async def take_picture(request):
    camera_id = int(request.match_info['camera_id'])
    if camera_id < len(current_state.camera_endpoints):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{current_state.camera_endpoints[camera_id]}/take/picture") as response:
                    if response.status == 200:
                        return web.Response(text="Picture taken successfully")
                    else:
                        return web.Response(text="Failed to take picture", status=500)
        except Exception as e:
            return web.Response(text=f"Error taking picture: {str(e)}", status=500)
    return web.Response(text="Camera not found", status=404)

async def home(request):
    return render(request,current_state)

async def watering_sequence(request):
    global current_state
    current_state = await ctrl.execute_watering_sequence(current_state)
    return render(request, current_state)

async def toggle_static_light(request):
    global current_state
    light_id = int(request.match_info['light_id'])
    current_state = ctrl.set_light(current_state, light_id)
    return render(request,current_state)

async def set_light_brightness(request):
    global current_state
    light_id = int(request.match_info['light_id'])
    
    if not request.can_read_body:
        brightness = 0
    else:
        try:
            form = await request.post()
            brightness = min(max(int(form.get('brightness', 0)), 0), 100)
        except (TypeError, ValueError):
            return web.Response(text="Invalid brightness value", status=400)
            
    current_state = ctrl.set_brightness(current_state, light_id, brightness)
    return render(request, current_state)

async def get_camera_image(request):
    global current_state
    camera_id = int(request.match_info['camera_id'])
    if camera_id < len(current_state.camera_endpoints):
        result = await get_camera_bytes(current_state.camera_endpoints[camera_id])
        if result is None:
            return web.Response(text="Error loading camera image", status=500)
        return web.Response(body=result, content_type='image/jpeg')
    return web.Response(text="Camera not found", status=404)

app.router.add_get('/', home)
app.router.add_post('/camera/{camera_id}/take/picture', take_picture)
app.router.add_post('/water/sequence', watering_sequence)
app.router.add_post('/static_light/{light_id}/toggle', toggle_static_light)
app.router.add_post('/light/{light_id}/brightness', set_light_brightness)
app.router.add_get('/camera/{camera_id}', get_camera_image)

# Setup CORS after routes are added
cors = aiohttp_cors.setup(app, defaults={
    "*": aiohttp_cors.ResourceOptions(
        allow_credentials=True,
        expose_headers="*",
        allow_headers="*",
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    )
})

for route in list(app.router.routes()):
    cors.add(route)

async def main():
    global db
    try:
        logger.info('Starting Hydro Control System')
        logger.debug('Initializing database')
        await db.init_tables()
        
        logger.debug('Starting status logging task')
            
        async def log_status():
            while True:
                await asyncio.sleep(5)
                await db.log_status(current_state)
                await asyncio.sleep(370)
        
        status_task = asyncio.create_task(log_status())
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 5000)
        await site.start()
        logger.info('Starting web server on port 5000')
        
        # Keep the server running until interrupted
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info('Shutting down server...')
        finally:
            await runner.cleanup()
            status_task.cancel()
            
    except Exception as e:
        logger.error(f'Fatal error: {str(e)}', exc_info=True)
        raise
    finally:
        logger.info('Cleaning up resources')
        await current_state.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
