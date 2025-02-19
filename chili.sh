#!/bin/bash

# Script to run on startup for chili project

# Navigate to chili directory
cd /home/serveradmin/chili-fac

# Pull latest changes and ensure we're on master branch
git pull && git checkout main

# Run uv package installer to update dependencies
uv pip install -r requirements.txt

# Run the main Python script
python main.py
