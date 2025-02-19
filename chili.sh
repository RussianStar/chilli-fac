# how can I run a shell script after startup ?
#There are several ways to run a shell script after system startup. Here are the most common methods, ordered by complexity:

1. Using crontab with `@reboot`:
```
# Open crontab editor
crontab -e

# Add this line
@reboot /path/to/your/script.sh
```

2. Using systemd service (modern Linux systems):
```
# Create service file
sudo nano /etc/systemd/system/myscript.service

# Add these contents
[Unit]
Description=My Startup Script
After=network.target

[Service]
ExecStart=/path/to/your/script.sh
User=your_username

[Install]
WantedBy=multi-user.target

# Enable and start the service
sudo systemctl enable myscript.service
sudo systemctl start myscript.service
```

3. Using rc.local (traditional method):
```
# Edit rc.local
sudo nano /etc/rc.local

# Add before 'exit 0':
/path/to/your/script.sh &
```

4. Using startup applications (Desktop environment):
```
# Create .desktop file
nano ~/.config/autostart/myscript.desktop

# Add these contents
[Desktop Entry]
Type=Application
Name=My Startup Script
Exec=/path/to/your/script.sh
```

Best practices:
- Make sure your script has execute permissions (`chmod +x script.sh`)
- Use absolute paths in your script
- Add logging to debug startup issues
- Consider adding delay if your script needs network/other services

Choose the method based on:
- If you need root privileges (systemd/rc.local)
- If you need GUI (startup applications)
- If you need precise timing (crontab)
- Your Linux distribution (some might not have all options)

#!/bin/bash

# Script to run on startup for chili project

# Navigate to chili directory
cd ~/chili-fac

# Pull latest changes and ensure we're on master branch
git pull && git checkout master

# Run uv package installer to update dependencies
uv pip install -r requirements.txt

# Run the main Python script
python main.py
