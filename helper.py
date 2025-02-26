import aiohttp_jinja2

def is_raspberry_pi():
    try:
        with open('/proc/device-tree/model') as f:
            return 'raspberry' in f.read().lower()
    except:
        return False

def render(request,current_state):
    return aiohttp_jinja2.render_template('index.html', request, 
                                          {'valves': current_state.valve_states,
                                            'lights': current_state.light_states, 
                                            'static_lights': current_state.static_light_states,
                                            'static_light_auto_states': current_state.static_light_auto_states,
                                            'zeus_auto_states': current_state.zeus_auto_states,
                                            'pumps': current_state.pump_states,
                                            'camera_count': len(current_state.camera_endpoints)})
