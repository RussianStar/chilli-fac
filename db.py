import asyncio 
from datetime import datetime
import aiosqlite

from camera import capture_image_data
from state import SystemState

class DatabaseAdapter:
    """Database adapter for async SQLite operations"""
    
    def __init__(self, logger, config):
        self.logger = logger
        self.config = config
        self.conn_string = config['database_connection']
        self.timeout = config['database_timeout']
        self._connection = None

    async def init_tables(self):
        """Initialize database tables if they don't exist"""
        if self._connection is None:
            self._connection = await self._get_connection()
            
        async with self._connection.cursor() as cursor:
            # Create status table
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS status (
                    timestamp TEXT NOT NULL,
                    valve_states TEXT,
                    light_states TEXT,
                    pump_states TEXT,
                    static_light_states TEXT
                )
            ''')
            
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS camera_images (
                    camera_id INTEGER,
                    timestamp TEXT NOT NULL,
                    image_data TEXT
                )
            ''')
            await self._connection.commit()

    async def _get_connection(self):
        """Get database connection with proper configuration"""
        if not self._connection:
            if 'http' in self.conn_string.lower():
                self._connection = await aiosqlite.connect(
                    f'http:{self.conn_string}',
                    timeout=self.timeout
                )
            else:
                self._connection = await aiosqlite.connect(
                    self.conn_string,
                    timeout=self.timeout
                )
            await self._connection.execute('PRAGMA journal_mode=WAL')
        return self._connection

    async def close(self):
        """Close database connection if open"""
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def log_status(self, current: SystemState):
        """Log full system state including camera images"""
        try:
            conn = await self._get_connection()
            async with conn.cursor() as cursor:
                now = datetime.now().isoformat()
                
                # Insert system state
                await cursor.execute('''
                    INSERT INTO status VALUES (:timestamp, :valve_states, 
                    :light_states, :pump_states, :static_light_states)
                ''', {
                    'timestamp': now,
                    'valve_states': str(current.valve_states),
                    'light_states': str(current.light_states),
                    'pump_states': str(current.pump_states), 
                    'static_light_states': str(current.static_light_states)
                })

                # Capture images concurrently
                image_tasks = [
                    asyncio.create_task(
                        capture_image_data(
                            self.logger,
                            camera_id, 
                            current.camera_endpoints[camera_id]
                        )
                    )
                    for camera_id in range(len(current.camera_endpoints))
                ]
                
                images = await asyncio.gather(*image_tasks)
                if images and not isinstance(images, (list, tuple)):
                    images = [images]

                self.logger.info(f"Captured {len(images) if images else 0} images")

                for data in images:
                    if data is None:
                        continue
                    if isinstance(data, tuple):
                        camera_id, image_data = data  # Unpack single tuple
                        self.logger.info(f"Storing image for camera {camera_id}")
                        await cursor.execute('''
                            INSERT INTO camera_images VALUES (?, ?, ?)
                        ''', (camera_id, now, image_data))
                await conn.commit()
                self.logger.debug('Status and images logged successfully')

        except aiosqlite.Error as e:
            self.logger.error(f"Database error in log_status: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in log_status: {e}")

    async def log_status_without_images(self, current: SystemState):
        """Log system state without camera images"""
        try:
            conn = await self._get_connection()
            async with conn.cursor() as cursor:
                now = datetime.now().isoformat()
                
                await cursor.execute('''
                    INSERT INTO status VALUES (:timestamp, :valve_states,
                    :light_states, :pump_states, :static_light_states)
                ''', {
                    'timestamp': now,
                    'valve_states': str(current.valve_states),
                    'light_states': str(current.light_states),
                    'pump_states': str(current.pump_states),
                    'static_light_states': str(current.static_light_states)
                })

                await conn.commit()
                self.logger.debug('Status logged successfully')

        except aiosqlite.Error as e:
            self.logger.error(f"Database error in log_status_without_images: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in log_status_without_images: {e}")
