import asyncio
import aiohttp
import io
from PIL import Image
import base64

async def capture_image_data(logger, camera_id, endpoint, rotation=0):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{endpoint}/take/picture") as response:
                if response.status == 200:
                    logger.info(f"Successfully requested new image for : {camera_id}")
                    await asyncio.sleep(120)
                else:
                    # no picture, no camera.
                    return

            logger.info(f"Getting image for {camera_id}")
            
            image_bytes = await get_camera_bytes(endpoint)
            
            if isinstance(image_bytes, bytes):
                logger.info(f"Successfully received image from: {camera_id}")
                
                # Apply rotation if needed
                if rotation != 0:
                    try:
                        # Convert bytes to PIL Image
                        img = Image.open(io.BytesIO(image_bytes))
                        # Rotate image (rotation should be a multiple of 90)
                        rotated_img = img.rotate(-rotation, expand=True)  # negative for clockwise rotation
                        # Convert back to bytes
                        img_byte_arr = io.BytesIO()
                        rotated_img.save(img_byte_arr, format='JPEG')
                        image_bytes = img_byte_arr.getvalue()
                    except Exception as e:
                        logger.error(f"Error rotating image for camera {camera_id}: {str(e)}")
                
                base64_data = base64.b64encode(image_bytes).decode('utf-8')
                return camera_id, base64_data

        logger.info("Done.")
        return None
    
    except Exception as e:
        logger.error(f"Error logging camera {camera_id}: {str(e)}")
        return

async def get_camera_bytes(endpoint):
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(endpoint) as response:
                    content = await response.text()
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # Find first image in body
                    img = soup.body.find('img')
                    if img and img.get('src'):
                        # Get base64 data directly from src attribute
                        img_data = img['src']
                        
                        # Check if it's a base64 encoded image
                        if img_data.startswith('data:image/jpeg;base64,'):
                            # Extract just the base64 content
                            base64_data = img_data.split(',')[1]
                            
                            # Decode base64 to bytes
                            import base64
                            image_bytes = base64.b64decode(base64_data)
                            
                            return image_bytes

            return "No image found in response", 500
            
        except Exception:
            return "Error getting the image", 500
