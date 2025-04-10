import platform
import asyncio
from aiohttp import web
import aiohttp_jinja2
import importlib.util

def is_raspberry_pi():
    """
    Checks if the RPi.GPIO library is installed.

    Returns:
        bool: True if RPi.GPIO is installed, False otherwise.
    """
    return importlib.util.find_spec('RPi.GPIO') is not None

def render(request, context):
    """Render the main template with the given context."""
    # If context is a SystemState object, convert it to a dictionary
    if hasattr(context, '__class__') and context.__class__.__name__ == 'SystemState':
        # Create a dictionary with all the attributes we need for the template
        template_context = {
            'lights': context.light_states,
            'static_lights': context.static_light_states,
            'static_light_auto_states': context.static_light_auto_states,
            'zeus_auto_states': context.zeus_auto_states,
            'watering_durations': context.watering_durations,
            'sensor_configs': context.sensor_configs,
            'sensor_readings': context.sensor_readings,
            'camera_count': len(context.camera_endpoints) if hasattr(context, 'camera_endpoints') else 0,
            'fan_state': context.fan_state if hasattr(context, 'fan_state') else {}
        }
        return aiohttp_jinja2.render_template('index.html', request, template_context)
    else:
        # If it's already a dictionary, use it directly
        return aiohttp_jinja2.render_template('index.html', request, context)

def calculate_moisture_percentage(raw_adc: int, min_adc: int, max_adc: int) -> float:
    """
    Calculates the soil moisture percentage based on raw ADC value and calibration.

    Args:
        raw_adc: The raw ADC reading from the sensor.
        min_adc: The ADC reading when the sensor is dry (0% moisture).
        max_adc: The ADC reading when the sensor is fully submerged (100% moisture).

    Returns:
        The calculated moisture percentage (0.0 to 100.0).
        Returns 0.0 if min_adc >= max_adc to prevent division by zero or invalid range.
    """
    if min_adc >= max_adc:
        # Invalid calibration range
        return 0.0

    # Clamp the raw_adc value within the calibration range
    clamped_adc = max(min_adc, min(raw_adc, max_adc))

    # Calculate percentage
    percentage = ((clamped_adc - min_adc) / (max_adc - min_adc)) * 100.0

    # Ensure the percentage is within 0-100 range (due to potential float inaccuracies)
    return max(0.0, min(percentage, 100.0))

async def run_async_task(task_func, *args):
    """Run an async task in the background."""
    loop = asyncio.get_event_loop()
    loop.create_task(task_func(*args))
