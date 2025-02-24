
import time
import requests

def capture_image_data(logger,camera_id,endpoint, images):
    try:
        response = requests.get(f"{endpoint}/take/picture")
        if response.status_code == 200:
            logger.info(f"Successfully requested new image for : {camera_id}")
            time.sleep(40)
        else:
            # no picture, no camera.
            return

        response = requests.get(endpoint)
        logger.info(f"Getting image for {camera_id}")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')
        img = soup.body.find('img')

        if img and img.get('src'):
            logger.info(f"Successfully received image from: {camera_id}")
            img_data = img['src']
            if img_data.startswith('data:image/jpeg;base64,'):
                base64_data = img_data.split(',')[1]
                
                images.append((camera_id, base64_data))
                return
                

        logger.info(f"Done.")
        return
    
    except Exception as e:
        logger.error(f"Error logging camera {camera_id}: {str(e)}")
        return


def get_camera_bytes(endpoint):
        try:
            response = requests.get(endpoint)
            
            # Parse HTML content
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
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
