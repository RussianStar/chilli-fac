import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logging():
    # Create logger
    logger = logging.getLogger('hydro')
    logger.setLevel(logging.DEBUG)

    # Ensure log directory exists
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Create log file path
    log_file = os.path.join(log_dir, 'hydro.log')

    # Initialize rotating file handler with modern parameters
    file_handler = RotatingFileHandler(
        filename=log_file,
        mode='a',
        maxBytes=1024*1024,  # 1MB per file
        backupCount=5,
        encoding='utf-8',
        delay=False
    )
    file_handler.setLevel(logging.DEBUG)
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Create formatters
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')

    # Add formatters to handlers
    file_handler.setFormatter(file_formatter)
    console_handler.setFormatter(console_formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
